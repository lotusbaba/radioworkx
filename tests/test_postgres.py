import json
import sqlite3
import threading
from pathlib import Path
import pytest
from psycopg import DataError, errors
from app import db
from app.testing import database
from scripts.migrate_postgres import migrate


@pytest.fixture
def legacy(tmp_path, metadata):
    path = tmp_path/'radio.db'
    with sqlite3.connect(path) as c:
        c.executescript(Path('tests/fixtures/legacy_schema.sql').read_text())
        c.execute('ALTER TABLE tracks ADD COLUMN intro_id TEXT REFERENCES announcements(id)')
        c.execute('ALTER TABLE tracks ADD COLUMN requested_intro_id TEXT REFERENCES announcements(id)')
        c.execute('INSERT INTO announcements VALUES(?,?,?,?,?,?,?,?)', ('intro','track-a','Hello 🌍','{}','/data/intro.mp3',7.18,1720000000.123456,'onyx'))
        c.execute('INSERT INTO tracks(id,metadata,status,intro_id) VALUES(?,?,?,?)', ('track-a',json.dumps(metadata),'ready','intro'))
        c.execute('INSERT INTO users VALUES(?,?,?,?)', ('user','test@example.invalid','preserved-hash',1720000000.123456))
        c.execute('INSERT INTO user_sessions VALUES(?,?,?)', ('digest','user',1900000000.123456))
        c.execute('INSERT INTO user_likes VALUES(?,?,?)', ('user','track-a',1720000000.123456))
        c.execute('INSERT INTO user_playlists VALUES(?,?,?,?)', ('list','user','Evening',1720000000.123456))
        c.execute('INSERT INTO user_playlist_tracks VALUES(?,?,?)', ('list','track-a',3))
        c.execute('INSERT INTO playlist(position,track_id) VALUES(41,?)', ('track-a',))
        c.execute('DELETE FROM playlist')
        c.execute('INSERT INTO plays VALUES(?,?,?,?,?,?)', ('play','track-a',json.dumps(metadata),1000,1300,None))
        c.execute('INSERT INTO reactions VALUES(?,?,?,?,?,?,?)', ('old','play','listener','🔥',1000,'{}',1))
        c.executemany('INSERT INTO account_attempts VALUES(?,?)', [('same',1720000000.123456)]*2)
    observer = tmp_path/'observer.sqlite'
    with sqlite3.connect(observer) as c:
        c.executescript('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE seen(id TEXT PRIMARY KEY,created REAL);')
        c.execute("INSERT INTO settings VALUES('start','123')")
        c.execute("INSERT INTO seen VALUES('broadcast:play',123)")
    return path, observer


def test_migration_rehearsal_commit_and_sequences(legacy):
    with database():
        counts = migrate(*legacy)
        assert counts['account_attempts'] == 2
        with db.connect() as c:
            assert c.execute("SELECT to_regclass('tracks')").fetchone()[0] is None
        assert migrate(*legacy, apply=True) == counts
        with db.connect() as c:
            assert c.execute('SELECT intro_id FROM tracks').fetchone()[0] == 'intro'
            assert c.execute('SELECT password_hash FROM users').fetchone()[0] == 'preserved-hash'
            assert c.execute('SELECT created FROM users').fetchone()[0] == 1720000000.123456
            assert c.execute('SELECT position FROM user_playlist_tracks').fetchone()[0] == 3
            assert c.execute('SELECT COUNT(*) FROM observer_seen').fetchone()[0] == 1
            assert c.execute("INSERT INTO playlist(track_id) VALUES('track-a') RETURNING position").fetchone()[0] == 42
        from app.service import accept_reaction
        accept_reaction('play','listener','🔥',now=1005)
        db.init()
        db.init()
        with db.connect() as c:
            assert c.execute('SELECT COUNT(*) FROM reactions').fetchone()[0] == 2
        with pytest.raises(ValueError, match='empty'):
            migrate(*legacy, apply=True)
        with db.connect() as c:
            assert c.execute('SELECT COUNT(*) FROM reactions').fetchone()[0] == 2


def test_failed_migration_rolls_back_all_tables(legacy):
    # Deliberately invalid FK in the source is rejected before any destination writes.
    with sqlite3.connect(legacy[0]) as c:
        c.execute("UPDATE tracks SET intro_id='missing'")
    with database():
        with pytest.raises(ValueError, match='foreign-key'):
            migrate(*legacy, apply=True)
        with db.connect() as c:
            assert c.execute("SELECT to_regclass('tracks')").fetchone()[0] is None


def test_transactions_serialize_and_release_after_rollback():
    outcomes = []
    def contend():
        with db.connect() as c:
            c.execute("SET LOCAL lock_timeout='100ms'")
            try:
                db.lock_writes(c)
            except errors.LockNotAvailable:
                outcomes.append('locked')
                c.rollback()
    with pytest.raises(RuntimeError, match='rollback'):
        with db.transaction() as c:
            db.set_setting(c,'uncommitted','value')
            thread=threading.Thread(target=contend)
            thread.start();thread.join(timeout=5)
            assert not thread.is_alive()
            assert outcomes == ['locked']
            raise RuntimeError('rollback')
    with db.transaction() as c:
        assert db.setting(c,'uncommitted') is None
        db.set_setting(c,'committed','value')
    with db.connect() as c:
        assert db.setting(c,'committed') == 'value'


def test_destination_error_rolls_back_previously_copied_rows(legacy):
    # PostgreSQL rejects NUL text after earlier tables have already been copied.
    with sqlite3.connect(legacy[0]) as c:
        c.execute("UPDATE tracks SET metadata=?", ('bad\x00text',))
    with database():
        with pytest.raises(DataError):
            migrate(*legacy, apply=True)
        with db.connect() as c:
            assert c.execute("SELECT to_regclass('announcements')").fetchone()[0] is None


def test_wrong_source_database_is_rejected(tmp_path):
    path = tmp_path/'empty.db'
    sqlite3.connect(path).close()
    with pytest.raises(ValueError, match='not a RadioWorkx'):
        migrate(path, apply=True)


def test_repeated_init_does_not_request_exclusive_table_locks():
    # An API request may retain read locks across several queries. Startup DDL
    # against those same tables must be skipped when the schema is unchanged.
    original_connect = db.connect
    def bounded_connect():
        c = original_connect()
        c.execute("SET lock_timeout='200ms'")
        c.commit()
        return c
    from unittest.mock import patch
    with original_connect() as reader:
        reader.execute('SELECT * FROM tracks')
        with patch.object(db, 'connect', bounded_connect):
            db.init()

import json
import sqlite3
import time
from contextlib import contextmanager
from app.config import DATA

SCHEMA = """
CREATE TABLE IF NOT EXISTS failed_downloads (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL, track_id TEXT NOT NULL,
 kind TEXT NOT NULL, source_url TEXT, page_url TEXT, error_type TEXT NOT NULL,
 error_detail TEXT NOT NULL, created REAL NOT NULL, replacement_id TEXT,
 UNIQUE(job_id,track_id)
);
CREATE TABLE IF NOT EXISTS app_tokens (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
 created REAL NOT NULL, last_used REAL, revoked REAL
);
CREATE TABLE IF NOT EXISTS tracks (
 id TEXT PRIMARY KEY, metadata TEXT NOT NULL, source TEXT, rights TEXT,
 status TEXT NOT NULL DEFAULT 'available', duration REAL, path TEXT, error TEXT,
 downloaded_at REAL
);
CREATE TABLE IF NOT EXISTS playlist (
 position INTEGER PRIMARY KEY AUTOINCREMENT, track_id TEXT UNIQUE REFERENCES tracks(id), priority INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plays (
 id TEXT PRIMARY KEY, track_id TEXT NOT NULL, metadata TEXT NOT NULL,
 starts REAL NOT NULL, ends REAL NOT NULL, actual_end REAL
);
CREATE TABLE IF NOT EXISTS outbox (
 id TEXT PRIMARY KEY, queue TEXT NOT NULL, body TEXT NOT NULL,
 created REAL NOT NULL, sent REAL, done REAL, failed TEXT
);
CREATE TABLE IF NOT EXISTS reactions (
 id TEXT PRIMARY KEY, play_id TEXT NOT NULL, listener TEXT NOT NULL, emoji TEXT NOT NULL,
 accepted REAL NOT NULL, metadata TEXT NOT NULL, processed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS requests (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, listener TEXT NOT NULL,
 query TEXT NOT NULL, mode TEXT NOT NULL, response TEXT NOT NULL, track_id TEXT REFERENCES tracks(id),
 status TEXT NOT NULL, created REAL NOT NULL, play_id TEXT
);
CREATE INDEX IF NOT EXISTS request_pending ON requests(status,sequence);
CREATE TABLE IF NOT EXISTS conversations (listener TEXT PRIMARY KEY, genres TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rag_embeddings (track_id TEXT PRIMARY KEY, model TEXT NOT NULL, digest TEXT NOT NULL, vector TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rag_pending (listener TEXT PRIMARY KEY, genres TEXT NOT NULL, track_ids TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rag_turns (id TEXT PRIMARY KEY, listener TEXT NOT NULL, created REAL NOT NULL, busy INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS announcements (id TEXT PRIMARY KEY, track_id TEXT NOT NULL, script TEXT NOT NULL, details TEXT NOT NULL, path TEXT NOT NULL, duration REAL NOT NULL, created REAL NOT NULL, voice TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_hosts (hostname TEXT PRIMARY KEY, provider TEXT NOT NULL, role TEXT NOT NULL, status TEXT NOT NULL, discovered_from TEXT, notes TEXT NOT NULL DEFAULT '', first_seen REAL NOT NULL, last_seen REAL NOT NULL, tracks_downloaded INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS host_downloads (track_id TEXT PRIMARY KEY, source_host TEXT NOT NULL, media_host TEXT, completed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS crawl_frontier (url TEXT PRIMARY KEY, provider TEXT NOT NULL, genre TEXT, depth INTEGER NOT NULL DEFAULT 0, discovered_from TEXT, next_attempt REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', error TEXT);
CREATE TABLE IF NOT EXISTS crawl_runs (id TEXT PRIMARY KEY, started REAL NOT NULL, finished REAL, pages INTEGER NOT NULL DEFAULT 0, tracks INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS media_objects (object_key TEXT PRIMARY KEY, track_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, mime TEXT NOT NULL, checked REAL);
CREATE TABLE IF NOT EXISTS track_visuals (track_id TEXT PRIMARY KEY, status TEXT NOT NULL, created REAL NOT NULL, submitted REAL, completed REAL, provider_id TEXT, artwork_source TEXT, artwork_key TEXT, video_key TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS reaction_play ON reactions(play_id,processed);
CREATE INDEX IF NOT EXISTS play_time ON plays(ends);
"""

class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DATA / "radio.db", timeout=30, factory=Connection)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init():
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
    with transaction() as c:
        for column in ('intro_id','requested_intro_id'):
            if column not in {row['name'] for row in c.execute('PRAGMA table_info(tracks)')}:
                c.execute(f'ALTER TABLE tracks ADD COLUMN {column} TEXT REFERENCES announcements(id)')
        if 'suggestions' not in {row['name'] for row in c.execute('PRAGMA table_info(requests)')}:
            c.execute("ALTER TABLE requests ADD COLUMN suggestions TEXT NOT NULL DEFAULT '[]'")
        for name, default in [('sources', '[]'), ('engine', 'basic'), ('requested_genre', '')]:
            if name not in {row['name'] for row in c.execute('PRAGMA table_info(requests)')}:
                c.execute(f"ALTER TABLE requests ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
        schema=c.execute("SELECT sql FROM sqlite_master WHERE name='reactions'").fetchone()[0]
        if 'UNIQUE(play_id,listener,emoji)' in schema.replace(' ', ''):
            c.execute('ALTER TABLE reactions RENAME TO reactions_legacy')
            c.execute("CREATE TABLE reactions (id TEXT PRIMARY KEY, play_id TEXT NOT NULL, listener TEXT NOT NULL, emoji TEXT NOT NULL, accepted REAL NOT NULL, metadata TEXT NOT NULL, processed INTEGER DEFAULT 0)")
            c.execute('INSERT INTO reactions SELECT * FROM reactions_legacy')
            c.execute('DROP TABLE reactions_legacy')
        c.execute('CREATE INDEX IF NOT EXISTS reaction_play ON reactions(play_id,processed)')
        c.execute('CREATE INDEX IF NOT EXISTS reaction_listener ON reactions(listener,accepted)')
        from app.hosts import bootstrap
        bootstrap(c)

@contextmanager
def transaction():
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()

def emit(c, id, queue, body):
    c.execute("INSERT OR IGNORE INTO outbox(id,queue,body,created) VALUES(?,?,?,?)",
              (id, queue, json.dumps(body), time.time()))

def setting(c, key, default=None):
    row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def set_setting(c, key, value):
    c.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,str(value)))

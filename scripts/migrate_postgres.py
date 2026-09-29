"""Copy quiesced SQLite snapshots into an empty PostgreSQL database.

Defaults to a full rehearsal with rollback. --apply commits only after row verification.
DATABASE_URL is read from the environment, never printed or accepted on the CLI.
"""
import argparse
from collections import Counter
from contextlib import ExitStack
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from psycopg import sql
from app import db

SCHEMA = Path(db.__file__).with_name('schema.sql').read_text()
TABLES = re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', SCHEMA)


def fingerprint(row):
    def canonical(value):
        if isinstance(value, (int, float)):
            return ['number', format(Decimal(str(value)).normalize(), 'f')]
        return ['value', value]
    return hashlib.sha256(json.dumps([canonical(v) for v in row], ensure_ascii=False).encode()).digest()


def readonly(path):
    c = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    c.execute('BEGIN')
    if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        c.close()
        raise ValueError('SQLite integrity check failed')
    if c.execute('PRAGMA foreign_key_check').fetchone():
        c.close()
        raise ValueError('SQLite contains invalid foreign-key references')
    return c


def migrate(source, observer=None, *, apply=False):
    with ExitStack() as stack:
        origin = readonly(source)
        stack.callback(origin.close)
        sources = {r[0]: (origin, r[0]) for r in origin.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not {'tracks', 'plays', 'outbox', 'settings'}.issubset(sources):
            raise ValueError('Source is not a RadioWorkx application database')
        if set(sources) - set(TABLES):
            raise ValueError('Unexpected source tables; update migration before copying')
        if observer:
            checkpoints = readonly(observer)
            stack.callback(checkpoints.close)
            names = {r[0] for r in checkpoints.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if names != {'settings', 'seen'}:
                raise ValueError('Unexpected observer schema')
            sources.update({f'observer_{name}': (checkpoints, name) for name in names})
        # All DDL, imported rows, and sequence changes share this transaction.
        with db.transaction() as target:
            existing = {r[0] for r in target.execute(
                'SELECT tablename FROM pg_tables WHERE schemaname=current_schema()')}
            if existing - set(TABLES):
                raise ValueError('Target schema contains unrelated tables; use a dedicated empty database')
            target.execute(SCHEMA)
            for table in TABLES:
                if target.execute(sql.SQL('SELECT 1 FROM {} LIMIT 1').format(sql.Identifier(table))).fetchone():
                    raise ValueError('Target must be empty; no existing PostgreSQL data was overwritten')
            counts = {}
            # Dependency order: announcements precede tracks' cached-intro references.
            ordered = ['announcements', 'users', 'tracks', 'user_playlists']
            ordered += [t for t in TABLES if t not in ordered]
            for table in ordered:
                if table not in sources:
                    continue
                source_db, source_table = sources[table]
                columns = [r[1] for r in source_db.execute(f'PRAGMA table_info("{source_table}")')]
                target_columns = {r[0] for r in target.execute(
                    'SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s', (table,))}
                if set(columns) - target_columns:
                    raise ValueError(f'Unexpected columns in {table}')
                names = sql.SQL(',').join(map(sql.Identifier, columns))
                expected = Counter()
                with target.cursor().copy(sql.SQL('COPY {} ({}) FROM STDIN').format(sql.Identifier(table), names)) as copy:
                    for row in source_db.execute(f'SELECT * FROM "{source_table}"'):
                        copy.write_row(row)
                        expected[fingerprint(row)] += 1
                actual = Counter(fingerprint(tuple(row.values())) for row in target.execute(
                    sql.SQL('SELECT {} FROM {}').format(names, sql.Identifier(table))))
                if actual != expected:
                    raise ValueError(f'Row verification failed for {table}')
                counts[table] = sum(expected.values())
            for table, column in [('playlist', 'position'), ('requests', 'sequence')]:
                maximum = target.execute(sql.SQL('SELECT COALESCE(MAX({}),0) FROM {}').format(
                    sql.Identifier(column), sql.Identifier(table))).fetchone()[0]
                if origin.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
                    previous = origin.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone()
                    maximum = max(maximum, previous[0] if previous else 0)
                sequence = target.execute('SELECT pg_get_serial_sequence(%s,%s)', (table,column)).fetchone()[0]
                # Unlike setval(), ALTER SEQUENCE RESTART is rolled back in rehearsal mode.
                target.execute(sql.SQL('ALTER SEQUENCE {} RESTART WITH {}').format(
                    sql.Identifier(*sequence.split('.')), sql.Literal(maximum+1)))
            # Record the schema already installed here; ordinary starts must not repeat DDL.
            db.set_setting(target, 'database_schema_digest', hashlib.sha256(SCHEMA.encode()).hexdigest())
            if not apply:
                target.rollback()
            return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Quiesced radio.db snapshot')
    parser.add_argument('--observer', type=Path, help='Quiesced observer.sqlite snapshot')
    parser.add_argument('--apply', action='store_true', help='Commit verified import into an empty target')
    args = parser.parse_args()
    try:
        counts = migrate(args.source, args.observer, apply=args.apply)
    except Exception as error:
        # Database exceptions may include row contents or connection details.
        print(f'Migration failed ({type(error).__name__}); transaction rolled back. No source writes.', file=sys.stderr)
        return 1
    print(json.dumps({'committed': args.apply, 'verified_rows': counts}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

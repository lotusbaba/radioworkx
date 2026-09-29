"""PostgreSQL connections and explicitly serialized business transactions."""
import json
import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
import psycopg
from psycopg import IntegrityError
from app.config import DATA

# Preserve name/index row access used by the domain layer without rewriting SQL.
class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, (int, slice)) else super().__getitem__(key)


def row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))


def connect():
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise RuntimeError('DATABASE_URL is required; RadioWorkx uses PostgreSQL.')
    return psycopg.connect(url, row_factory=row_factory, connect_timeout=10)


def lock_writes(c):
    # Replaces BEGIN IMMEDIATE: serialize read/decide/write operations across workers.
    # READ COMMITTED gives each query fresh state after the advisory lock is acquired.
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(current_database() || ':' || current_schema() || ':radioworkx-write', 0))")


@contextmanager
def transaction():
    with connect() as c:
        lock_writes(c)
        yield c


def init():
    DATA.mkdir(parents=True, exist_ok=True)
    with transaction() as c:
        schema = Path(__file__).with_name('schema.sql').read_text()
        digest = hashlib.sha256(schema.encode()).hexdigest()
        exists = c.execute("SELECT to_regclass('settings')").fetchone()[0]
        if not exists or setting(c, 'database_schema_digest') != digest:
            c.execute(schema)
            set_setting(c, 'database_schema_digest', digest)
        from app.hosts import bootstrap
        bootstrap(c)


def emit(c, id, queue, body):
    c.execute("INSERT INTO outbox(id,queue,body,created) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
              (id, queue, json.dumps(body), time.time()))


def setting(c, key, default=None):
    row = c.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
    return row[0] if row else default


def set_setting(c, key, value):
    c.execute("INSERT INTO settings VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,str(value)))

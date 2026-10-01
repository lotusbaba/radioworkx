"""Apply only the additive social tables before a rolling API deployment.

Set DATABASE_URL to the application's PostgreSQL database. No existing records are
changed. A bounded lock timeout aborts safely if the tables cannot be added now.
"""
import hashlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db


def migrate():
    schema = (Path(__file__).resolve().parents[1] / 'app/schema.sql').read_text()
    previous, additions = schema.split('-- Opt-in sharing:', 1)
    expected = hashlib.sha256(previous.encode()).hexdigest()
    updated = hashlib.sha256(schema.encode()).hexdigest()
    with db.connect() as c:
        c.execute("SET LOCAL lock_timeout = '3s'")
        c.execute("SET LOCAL statement_timeout = '15s'")
        db.lock_writes(c)
        current = db.setting(c, 'database_schema_digest')
        if current == updated:
            return
        if current != expected:
            raise RuntimeError('Unexpected schema version; inspect before migrating.')
        c.execute('-- Opt-in sharing:' + additions)
        db.set_setting(c, 'database_schema_digest', updated)


if __name__ == '__main__':
    migrate()
    print('Social schema is ready; existing records preserved.')

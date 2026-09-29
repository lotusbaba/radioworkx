"""Disposable PostgreSQL schemas for tests and isolated browser smoke checks."""
import os
import uuid
from contextlib import contextmanager
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


@contextmanager
def database():
    # Never fall back to DATABASE_URL: tests must explicitly select their test server.
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        raise RuntimeError('Set TEST_DATABASE_URL to a disposable PostgreSQL database (see compose.test.yaml).')
    schema = 'rwx_test_' + uuid.uuid4().hex
    previous = os.environ.get('DATABASE_URL')
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        os.environ['DATABASE_URL'] = make_conninfo(url, options=f'-csearch_path={schema}')
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop('DATABASE_URL', None)
            else:
                os.environ['DATABASE_URL'] = previous
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

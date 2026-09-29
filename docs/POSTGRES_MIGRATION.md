# PostgreSQL storage and migration

RadioWorkx now requires `DATABASE_URL`. Application code uses Psycopg 3 and native
PostgreSQL SQL; SQLite is used only by the one-time import tool and legacy test
fixtures. The existing installation was cut over on 2026-09-29; other SQLite installations must follow the cutover procedure below.

All 28 application tables and both observer checkpoint tables live in one dedicated
PostgreSQL database. Observer tables are named `observer_settings` and `observer_seen`
to avoid colliding with station settings. Redis audio/events, SQS queues, S3 objects,
and the audio/artwork files on `radio-data` keep their existing roles.

`app/schema.sql` is the schema source. Its digest is stored in station settings;
normal starts skip unchanged DDL to avoid startup table-lock deadlocks. JSON payloads remain text to preserve existing
serialization and API behavior; queries use PostgreSQL JSON operators. Unix timestamps
use `DOUBLE PRECISION` to preserve SQLite's 64-bit precision. Playlist positions and
request sequence numbers use identity sequences. Upserts use `ON CONFLICT`.

`db.transaction()` takes a transaction-scoped PostgreSQL advisory lock before any
business reads. This preserves the former serialized read/decide/write behavior for
capacity reservations, scheduling, cooldowns, and idempotency. The lock is scoped to
database and schema, and releases on commit, rollback, or disconnection. Ordinary
reads can proceed concurrently. This deliberately preserves existing concurrency
semantics; finer-grained locks are a separate future optimization.

## Connection configuration

Use a dedicated database and role owned by RadioWorkx, with permission to create its
tables and indexes. Keep the connection URL in ignored `.env` or another ignored local
credential file; do not put passwords in chat, commands, commit messages, or docs.

For containers on this Mac, the database host is `host.docker.internal`. For local
Python commands it is `127.0.0.1`. The discovered existing container publishes port
5432. These two hostnames must point to the same approved database. URL-encode any
special characters in credentials. The production target is Homebrew PostgreSQL 14.15 on the Mac. The unrelated Docker
PostgreSQL 13 container was initially misidentified as the target. Tests also pass
against a disposable PostgreSQL 13 server.

Compose passes `DATABASE_URL` to both API slots and every worker. `DATA_DIR` now
locates media and worker lock files, not the active relational database. Credentials
must be set before using the updated Compose file, including build/status commands.

## Migration and cutover

The import tool requires an empty target schema and rejects unrelated tables,
unknown source tables/columns, invalid source foreign keys, and nonempty targets.
It never deletes or overwrites PostgreSQL records. It checks SQLite integrity, copies
all source columns, and compares row fingerprints including duplicate multiplicities
before committing. Identity sequences preserve both existing values and SQLite's
historical high-water marks, including deleted positions.

Run the following only with `DATABASE_URL` already loaded securely into the process
environment. Paths below are examples of private, quiesced snapshots:

```sh
# Full rehearsal: import, verify, then roll back.
.venv/bin/python scripts/migrate_postgres.py --source /private/path/radio.db --observer /private/path/observer.sqlite
# Commit the verified import into an empty dedicated target.
.venv/bin/python scripts/migrate_postgres.py --source /private/path/radio.db --observer /private/path/observer.sqlite --apply
```

A safe production cutover requires a brief coordinated maintenance window:

1. Record running service names, image IDs, active API slot, and deployment state.
   Preserve the currently stopped downloads worker and paused video generation.
   Build and verify the PostgreSQL application image before stopping services.
2. Stop both API writers and all running application workers, including station,
   crawler, dispatcher, reactions, visuals, and telemetry observer. Keep Redis,
   LocalStack, proxy, and analytics volumes. Live audio pauses during this window.
   Do not use the normal overlapping API rollout across different databases: it
   would allow writes to diverge between SQLite and PostgreSQL.
3. Use SQLite's backup API to snapshot `RADIO_DATA_DIR/radio.db` and
   `/telemetry/observer.sqlite`. Keep snapshots private and retain original volumes.
   Do not copy only a `.db` file while its writers/WAL are active. A live backup is
   suitable for a rehearsal, but the final import must use fresh stopped-writer data.
4. Run the verified import with `--apply` against the approved empty target. Import
   before starting any new service: startup bootstraps host records, making the
   target nonempty. Retain the counts-only migration report.
5. Set the container connection URL in ignored configuration and recreate only the
   previously running application services with the tested image. Keep the proxy's
   recorded API slot consistent. Never run old SQLite and new PostgreSQL writers
   together. Never start downloads merely as a side effect of migration.
6. Verify health, current status, live audio/announcement transitions, private account
   access, likes/playlists, admin history, and observer operation. Confirm that new
   plays and checkpoints are reaching PostgreSQL. Begin PostgreSQL backups alongside
   media, Redis, and other existing volume backups.

Before new PostgreSQL writes are accepted, rollback means stopping the new services
and restoring the recorded SQLite images/configuration with the untouched original
volumes. After new PostgreSQL writes occur, blindly switching back loses those writes;
keep maintenance mode and reconcile/export them first. The import tool intentionally
provides no destructive reverse migration or automatic overwrite option.

## Isolated verification

```sh
docker compose -f compose.test.yaml up -d --wait
export TEST_DATABASE_URL=postgresql://radioworkx_test:local-test-only@127.0.0.1:55432/radioworkx_test
.venv/bin/python -m pytest -q
.venv/bin/python scripts/accounts_smoke.py
.venv/bin/python scripts/transition_smoke.py
docker compose -f compose.test.yaml down
```

The test server uses a separate Compose project and memory-backed data directory.
Every test/smoke uses a random schema that is removed afterward. Tests require an
explicit `TEST_DATABASE_URL` and never fall back to the live `DATABASE_URL`.
The password above belongs only to the disposable test service.

Migration tests cover lossless timestamps, Unicode, password/session persistence,
likes/playlists, observer checkpoints, duplicate rows, sequence high-water marks,
rehearsal rollback, invalid foreign keys, nonempty-target refusal, and serialized
transactions releasing their locks after rollback.

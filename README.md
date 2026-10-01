# RadioWorkx — AI Radio

RadioWorkx is a shared live-radio website built with FastAPI, PostgreSQL, Redis, LocalStack SQS/S3, FFmpeg, and a vanilla browser frontend. It broadcasts licensed independent music, accepts conversational catalog requests, responds to listener reactions, and exposes operational activity through Elasticsearch/Kibana and OpenSearch Dashboards.

The live station is currently available at [radioworkx.tail060b33.ts.net](https://radioworkx.tail060b33.ts.net/).

## What it does

- Streams one shared live MP3 broadcast with SSE-powered status updates.
- Schedules tracks within artist, album, compilation, and consecutive-play limits.
- Accepts emoji reactions and catalog-grounded song, artist, album, genre, and mood requests.
- Acquires only allowlisted, explicitly authorized recordings and stops permanently at 10,000 downloaded tracks.
- Provides searchable artist and album pages with separate personal playback.
- Home-page Search opens a modal with artist, album, and track filters, live
  PostgreSQL fuzzy results, and no initial results until text is entered.
- Supports email/password accounts, private liked tracks, and personal playlists with sequential playback at `/my-music`.
- Uses a durable PostgreSQL outbox and LocalStack SQS workers for reactions, downloads, crawling, and artwork processing.
- Records privacy-limited activity in both Elasticsearch/Kibana and OpenSearch Dashboards.
- Supports proxy-based API deployments with connection draining and rollback.

## Run locally

Requirements: Docker Desktop or Docker Engine with Compose v2, and a dedicated PostgreSQL database. Existing installations must follow [the PostgreSQL migration guide](docs/POSTGRES_MIGRATION.md) before deploying this version.

```sh
cp .env.example .env
# Set SESSION_SECRET and DATABASE_URL in .env (see the migration guide).
docker compose up -d --build
```

Open [http://localhost:8000](http://localhost:8000). FastAPI documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

For a safe generated-audio demonstration, set `DEMO_MODE=1` in `.env` before starting the services. For real audio, keep `DEMO_MODE=0` and import an authorized catalog as described in the [system design reference](docs/SYSTEM_DESIGN.md#bandcamp-catalog-and-audio-sources).

```sh
docker compose ps
docker compose logs -f station reactions downloads dispatcher
docker compose down  # Stops services but retains named-volume data.
```

The active local installation uses `RADIO_DATA_DIR=/data/live`, Redis database 1, and the `radio-live` queue prefix. Preserve its Docker volumes; do not reset playback history or delete downloaded media as a troubleshooting shortcut.

## Architecture at a glance

```text
Listener → Tailscale Funnel → Nginx → FastAPI
                                      ├→ PostgreSQL + media volume
                                      ├→ durable outbox → LocalStack SQS → workers
                                      └→ Redis → SSE and live MP3

Application telemetry → rotating ECS JSONL
                         ├→ Logstash → Elasticsearch → Kibana
                         └→ OpenSearch ingest → OpenSearch → Dashboards
```

The complete architecture, requirements, data flows, endpoint behavior, scheduling rules, deployment design, and operational limits are documented in [System design and operations](docs/SYSTEM_DESIGN.md).

## Common operations

### Tests

Use the project virtual environment:

```sh
docker compose -f compose.test.yaml up -d --wait
export TEST_DATABASE_URL=postgresql://radioworkx_test:local-test-only@127.0.0.1:55432/radioworkx_test
.venv/bin/python -m pytest -q
.venv/bin/python scripts/browser_smoke.py --url http://127.0.0.1:8001 --read-only --audio-check --allow-autoplay
```

Some integration smoke tests intentionally create activity or exercise a deployment. Read their corresponding documentation before running them against the live installation.

### Agent-driven browser exploration

The [dual-engine test framework](docs/adversary-framework.md) supports a custom agent
using local Laya, and native Browser Use using the existing OpenAI key, with isolated synthetic app sessions,
saved reports and model-free replay. See that guide for installation and commands.

### Managed API deployment

Once the Nginx deployment proxy has been initialized, use the deployment controller instead of an unqualified API rebuild:

```sh
.venv/bin/python scripts/deploy.py status
.venv/bin/python scripts/deploy.py deploy
.venv/bin/python scripts/deploy.py rollback
```

The stable proxy address is `http://127.0.0.1:8001`. See [API deployments with temporary container overlap](docs/SYSTEM_DESIGN.md#api-deployments-with-temporary-container-overlap) before operating the live service.

### Local observability

| Interface | Address |
| --- | --- |
| Kibana | [http://localhost:5601](http://localhost:5601) |
| Elasticsearch API | `http://localhost:9200` |
| OpenSearch Dashboards | [Activity overview](http://localhost:5602/app/dashboards#/view/rwx-activity-overview) |
| OpenSearch API | `http://localhost:9201` |

These endpoints are bound to loopback and are not public station URLs.

## Documentation

- [PostgreSQL migration](docs/POSTGRES_MIGRATION.md) — configuration, verified data import, coordinated cutover, rollback, and isolated tests.

- [Station audio architecture](docs/STATION_AUDIO_ARCHITECTURE.md) — Python processes and threads, FFmpeg subprocesses and stdout pipes, Redis audio chunks, API delivery, and announcement state.
- [System design and operations](docs/SYSTEM_DESIGN.md) — full behavioral specification, architecture, APIs, deployment procedures, and observability setup.
- [RAG chat architecture](docs/RAG_CHAT_ARCHITECTURE.md) — embeddings, hybrid retrieval, pending confirmations, structured output, validation, rate limits, and fallback behavior.
- [Telemetry architecture explained](docs/telemetry-architecture-explained.md) — component-by-component explanation of the telemetry pipeline.
- [Architecture sequence source](docs/current-architecture.sequence.txt) and [rendered SVG](docs/current-architecture.svg) — editable SequenceDiagram.org model and generated diagram.
- [Session handoff](docs/SESSION_HANDOFF.md) — current operational context, recent production fixes, and live verification notes.

## Listener accounts

Use **Sign in** or **Create account** to open an in-page modal with an email address and a 12–128 character password. Authentication also opens in a modal when a signed-out listener saves a track, preserving their current page and audio. **My music** is embedded on the home page and remains available separately at `/my-music`. Like tracks or add them to playlists on the station and artist/album pages. My music supports creating, renaming, and deleting playlists, removing tracks, and Play all with automatic advance and a Next track control. Unavailable recordings are skipped when building the playback queue; preparation failures show a message and allow manually advancing. On the home page, starting a personal track disconnects live radio for that listener; Tune in stops personal playback and returns to live audio. Pending preparation and live reconnect timers cannot restart the other player. Playback stops when navigating to another page.

Accounts use salted PBKDF2-SHA256 password hashes (600,000 iterations), random revocable server-side sessions with a 30-day expiry, HTTP-only same-site cookies, same-origin mutation protection, and database-backed sign-in throttling. Liked tracks and new playlists are private. Owners can explicitly publish playlists using Share playlist. Account likes are separate from broadcast emoji reactions. Email verification and password-reset emails are not configured; registration currently uses an email address as the sign-in identifier.

Select a playlist in **My music** and choose **Share playlist** to publish it and copy its `/playlists/{id}` link. Shared playlists are also visible at the owner's `/people/{id}` profile. Choose a public name under **Your public profile**; email addresses never appear on these pages. Visitors can listen without registering, then sign in to **Follow playlist** or **Follow listener**. Followed playlists appear in My music and use the owner's current tracks when the collection loads; an already playing queue is a snapshot. Following a listener adds a link to their profile so you can find their public playlists. It does not automatically follow all of their playlists or send notifications.

**Make private** disables the public link and removes playlist follows. Sharing again does not restore old follows. People follows remain until unfollowed. Followers cannot edit the owner's playlists. Previously loaded tracks may remain in an active playback queue; sharing controls playlist visibility, not access to the station's public catalog. Limits: 100 followed playlists and 100 followed listeners per account.

For an existing PostgreSQL installation, run `DATABASE_URL=… .venv/bin/python scripts/migrate_social.py` before rolling out this version. This adds four tables with a short lock timeout, checks the prior schema digest, and marks the schema current without replaying unrelated DDL against live playback. Fresh installs initialize all tables normally.

The additive schema is initialized by the API on startup and preserves station history and media. Run `.venv/bin/python scripts/accounts_smoke.py` for an isolated Chrome test using temporary accounts, a temporary catalog, and synthetic audio.

## Safety and data

- Keep `.env`, `.admin-credentials`, runtime databases, and downloaded media out of Git.
- Do not expose Redis, LocalStack, Elasticsearch, OpenSearch, Kibana, or OpenSearch Dashboards publicly.
- Back up PostgreSQL, `radio-data`, and `redis-data` together, and preserve the analytics volumes when their history matters.
- Browser autoplay may require a user gesture; the application cannot bypass browser policy.
- Licensing, reporting, and public-operation obligations require review beyond the scheduling controls implemented here.

# RadioWorkx — AI Radio

RadioWorkx is a shared live-radio website built with FastAPI, SQLite, Redis, LocalStack SQS/S3, FFmpeg, and a vanilla browser frontend. It broadcasts licensed independent music, accepts conversational catalog requests, responds to listener reactions, and exposes operational activity through Elasticsearch/Kibana and OpenSearch Dashboards.

The live station is currently available at [radioworkx.tail060b33.ts.net](https://radioworkx.tail060b33.ts.net/).

## What it does

- Streams one shared live MP3 broadcast with SSE-powered status updates.
- Schedules tracks within artist, album, compilation, and consecutive-play limits.
- Accepts emoji reactions and catalog-grounded song, artist, album, genre, and mood requests.
- Acquires only allowlisted, explicitly authorized recordings and stops permanently at 10,000 downloaded tracks.
- Provides searchable artist and album pages with separate personal playback.
- Supports email/password accounts, private liked tracks, and personal playlists with sequential playback at `/my-music`.
- Uses a durable SQLite outbox and LocalStack SQS workers for reactions, downloads, crawling, and artwork processing.
- Records privacy-limited activity in both Elasticsearch/Kibana and OpenSearch Dashboards.
- Supports proxy-based API deployments with connection draining and rollback.

## Run locally

Requirements: Docker Desktop or Docker Engine with Compose v2.

```sh
cp .env.example .env
# Set SESSION_SECRET in .env to a long random value.
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
                                      ├→ SQLite / audio library
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
.venv/bin/python -m pytest -q
.venv/bin/python scripts/browser_smoke.py --url http://127.0.0.1:8001 --read-only --audio-check --allow-autoplay
```

Some integration smoke tests intentionally create activity or exercise a deployment. Read their corresponding documentation before running them against the live installation.

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

- [Station audio architecture](docs/STATION_AUDIO_ARCHITECTURE.md) — Python processes and threads, FFmpeg subprocesses and stdout pipes, Redis audio chunks, API delivery, and announcement state.
- [System design and operations](docs/SYSTEM_DESIGN.md) — full behavioral specification, architecture, APIs, deployment procedures, and observability setup.
- [RAG chat architecture](docs/RAG_CHAT_ARCHITECTURE.md) — embeddings, hybrid retrieval, pending confirmations, structured output, validation, rate limits, and fallback behavior.
- [Telemetry architecture explained](docs/telemetry-architecture-explained.md) — component-by-component explanation of the telemetry pipeline.
- [Architecture sequence source](docs/current-architecture.sequence.txt) and [rendered SVG](docs/current-architecture.svg) — editable SequenceDiagram.org model and generated diagram.
- [Session handoff](docs/SESSION_HANDOFF.md) — current operational context, recent production fixes, and live verification notes.

## Listener accounts

Open **My music** from the station or library navigation to register with an email address and a 12–128 character password. Like tracks or add them to playlists on the station and artist/album pages. My music supports creating, renaming, and deleting playlists, removing tracks, and Play all with automatic advance and a Next track control. Unavailable recordings are skipped when building the playback queue; preparation failures show a message and allow manually advancing. Playback stops when navigating to another page.

Accounts use salted PBKDF2-SHA256 password hashes (600,000 iterations), random revocable server-side sessions with a 30-day expiry, HTTP-only same-site cookies, same-origin mutation protection, and database-backed sign-in throttling. Saved music is private to its owner. Account likes are separate from broadcast emoji reactions. Email verification and password-reset emails are not configured; registration currently uses an email address as the sign-in identifier.

The additive schema is initialized by the API on startup and preserves station history and media. Run `.venv/bin/python scripts/accounts_smoke.py` for an isolated Chrome test using temporary accounts, a temporary catalog, and synthetic audio.

## Safety and data

- Keep `.env`, `.admin-credentials`, runtime databases, and downloaded media out of Git.
- Do not expose Redis, LocalStack, Elasticsearch, OpenSearch, Kibana, or OpenSearch Dashboards publicly.
- Back up `radio-data` and `redis-data` together, and preserve the analytics volumes when their history matters.
- Browser autoplay may require a user gesture; the application cannot bypass browser policy.
- Licensing, reporting, and public-operation obligations require review beyond the scheduling controls implemented here.

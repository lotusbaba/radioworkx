# RadioWorkx architecture checks with Polish

These specifications were created from the repository source on 2026-10-01. They
are not an inspection of running containers or a benchmark of the live station.
They require Polish 0.11.0 or newer (currently in the adjacent `spec-lang` workspace).
No application configuration, running services, databases, volumes, or deployment
state were changed to produce them.

From this repository:

```sh
../spec-lang/.venv/bin/polish check architecture/radioworkx.polishd
../spec-lang/.venv/bin/polish simulate architecture/radioworkx.polishd
../spec-lang/.venv/bin/polish simulate architecture/radioworkx-streaming-capacity.polishd
```

## Evidence and modeling decisions

- `compose.yaml`: app/worker roles, Redis with AOF, LocalStack SQS/S3, persistent
  media and telemetry volumes, separate ELK and OpenSearch pipelines. Compute pools
  represent container roles, not separate machines or measured resource reservations.
- `app/db.py` and `app/schema.sql`: PostgreSQL is authoritative. Older handoff text
  mentioning SQLite is historical. The model includes representative tables, not
  all schema columns, foreign keys, transaction isolation, or advisory-lock behavior.
- `app/library.py`: `/api/library/search` queries PostgreSQL. Elasticsearch and
  OpenSearch are telemetry stores, not the station catalog search backend.
- `app/api.py`, `app/live_audio.py`, and `app/station.py`: audio and SSE use Redis
  Streams with independent cursors. Each request creates an async Redis client;
  the synthetic capacity case assumes one blocking connection per active client.
  Audio has approximate maxlen 160; events use 2000 (`app/events.py`). Polish treats
  those declared values as exact conservative retention bounds; real approximate
  trimming and variable chunk sizes differ. There is one shared station broadcast,
  not one FFmpeg process per listener. FFmpeg execution/CPU itself is not simulated.
- `scripts/deploy.py`: public TLS termination precedes Nginx HTTP forwarding;
  buffering is disabled. This snapshot uses one active API role. It does not model
  api/api-next deployment overlap, draining, rollback, or actual hostname routing.
- `app/queues.py` and `app/workers.py`: LocalStack HTTP SQS, an outbox dispatcher,
  and distinct work consumers. The dispatcher operation represents a batch containing
  work for every modeled queue; real batches can be sparse. Worker operations are
  synthetic invocation handles, not deployed HTTP endpoints. Outbox retries,
  visibility renewal, deduplication, DLQ redrive, and atomicity are not proven.
- `app/object_store.py`: shared local files and LocalStack S3 synchronization/restore
  are distinct. The restore scenario models object read then volume write; it does
  not implement conditional file-existence checks or verify stored media bytes.
- `app/telemetry.py` and the two Logstash configs: file-based background telemetry
  does not synchronously block audio/API delivery. The writer is represented as a
  separate logical service although it is a background thread in app processes.
  In-memory queue overflow/drop policy, JSONL rotation, durable ingest cursors and
  outage recovery are not simulated. Separate scenarios avoid inventing a synchronous
  playback dependency on either search cluster.
- LLM/TTS/video/licensed-download providers are external dependencies. This model
  checks declared connectivity, not provider output, licensing decisions, quotas,
  fallback branches, credentials, or costs. Optional generation workflows are
  represented as explicitly selected scenarios/operations, not always-on dependencies.

Authentication is abstract: `authenticated` means the credential relevant to that
operation is present. For live audio that is the signed anonymous listener session;
for personal music it is a registered account session. `Admin` abstracts admin
credentials. Cookie issuance, CSRF, account ownership, app tokens, and password
verification require the application's actual tests.

RedisState is a logical view of key/sorted-set access sharing RedisContainer with
the two streams. `cache_result = hit` means existing state in these functional
scenarios, not caching of the station catalog. Functional Redis checks allow omitted
memory capacity; workload scenarios require explicit memory/throughput inputs.
No production host CPU, RAM, database connection pool, or stream capacity was inferred.
The source opens PostgreSQL connections directly, so the baseline does not invent
an application connection pool.

## Streaming capacity experiment

`radioworkx-streaming-capacity.polishd` is explicitly hypothetical:

- 100 backend stream connections with 10 reserved gives a budget of 90.
- 40 listeners with audio plus SSE use 80 connections; 50 use 100 and exceed it.
- With an assumed eight audio chunks per second, a 21-second lag needs 168 messages,
  exceeding the modeled 160-message retention.

These are explanatory numbers, not claims about the live server. Measure Redis
maxclients, other connection usage, chunk rate, and the effective retained history
before making operational decisions. The proxy's 4096 `worker_connections` source
setting is intentionally not treated as 4096 listener slots: worker count and upstream
sockets also matter, and Tailscale/API limits are unspecified.

To compare a proposal, copy the capacity specification, change a declaration such
as `response_buffering`, connection capacity, or retention, and run:

```sh
../spec-lang/.venv/bin/polish plan architecture/radioworkx-streaming-capacity.polishd \
  --proposed /path/to/proposed.polishd --json
```

Keep success expectations for requirements you want to preserve. The supplied
negative scenarios deliberately expect failure, so fixing their failure requires
revisiting the test intent; the planner retains baseline expectations by design.
A failing capacity budget does not assert an exact timeout or prove that a real
request fails. The model has no timing, backpressure, audio-decoding, reconnection,
network-bandwidth, or availability simulation. Browser/adversary QA is a separate
test harness, not a production station dependency in these files.

Keep these project-specific specifications in this private repository; only the
generic language features and synthetic examples belong in the public Polish repo.

## GitHub Actions

`.github/workflows/architecture.yml` runs on pull requests, pushes to `main`, and
manual dispatch. It installs Polish from the pinned public commit
`c73cdfe1180ec5f477e3b003320a57bfba080e1f` (0.11.0); no adjacent checkout, API keys,
application containers or production connections are required.

The standard-library test suite runs both baselines (13 functional scenarios and
three synthetic capacity scenarios), then checks the intentional buffering regression.
The proposal must differ from the capacity baseline only in Proxy response buffering.
The planner must report baseline success, proposal `STREAMING_UNSUPPORTED`, classification
`introduced`, and exit code **1**. That expected rejection makes the test pass; an
unexpected success, other error, or changed expectation fails CI. Do not use
`continue-on-error` to hide a failed planner assertion.

Each run uploads `polish-architecture-evidence` with JSON results, stderr and recorded
command exit codes, including when a test fails. Artifacts are retained for 14 days.
The workflow evaluates the specifications only; it does not deploy or benchmark the app.

Run the same checks locally:

```sh
POLISH_BIN=../spec-lang/.venv/bin/polish python3 -m unittest discover -s tests/architecture -v
```

With `polish` installed on PATH, omit `POLISH_BIN`. Evidence defaults to
`runs/polish-ci/`; override with `POLISH_RESULTS_DIR`. When intentionally expanding
the baseline scenarios, update the explicit scenario counts in the test suite.

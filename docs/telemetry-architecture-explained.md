Starting at line 13 of [current-architecture.sequence.txt](current-architecture.sequence.txt#L13), the remaining components form RadioWorkx’s observability pipeline.

## 1. Telemetry writer — bounded async queue

```text
Telemetry writer
bounded async queue
```

Implemented in [telemetry.py](../app/telemetry.py).

Application components call:

```python
telemetry.emit("page.view", ...)
telemetry.emit("api.request", ...)
telemetry.emit("job.completed", ...)
```

`emit()` creates a sanitized ECS-style event and places it into a Python in-memory queue:

```python
_buffer = queue.Queue(maxsize=10000)
```

A background thread consumes that queue and writes events to disk.

```text
API or worker thread
        │
        │ telemetry.emit(...)
        ▼
bounded in-memory queue
        │
        │ background writer thread
        ▼
telemetry JSONL file
```

“Bounded” means the queue can contain no more than 10,000 pending events. If it becomes full, telemetry is dropped instead of blocking API handling, workers, or radio playback.

This makes telemetry deliberately less important than operating the station:

```text
Analytics overloaded
        ↓
Possibly lose telemetry
        ↓
Radio and API continue running
```

Before writing an event, the background thread can query SQLite to enrich it with allowlisted track information:

```text
track title
artists
album
genre
provider
```

Credentials, raw listener messages, source URLs, and arbitrary fields are not accepted. Only fields in the explicit `FIELDS` allowlist are retained.

One important detail: this isn’t necessarily one central writer process. Each instrumented Python service can have its own in-process queue and writer thread, but they all write into the shared telemetry volume.

---

## 2. `telemetry-data` — rotating ECS JSONL

```text
telemetry-data
rotating ECS JSONL
```

This is a shared Docker named volume:

```yaml
telemetry-data:
```

Application services mount it at:

```text
/telemetry
```

Each producer writes a file based on its container hostname:

```text
/telemetry/<container-hostname>.jsonl
```

Every line is one JSON event:

```json
{"@timestamp":"...","event":{"id":"...","action":"page.view"}}
{"@timestamp":"...","event":{"id":"...","action":"api.request"}}
```

The documents follow the Elastic Common Schema style:

```text
@timestamp
event.id
event.action
event.outcome
service.name
user.id
session.id
radioworkx.*
```

### Rotation

Each active file is limited to approximately 20 MiB, with four backups:

```text
service.jsonl      current
service.jsonl.1    previous
service.jsonl.2
service.jsonl.3
service.jsonl.4    oldest retained
```

Rotation prevents telemetry files from growing indefinitely.

Both ingestion pipelines mount this volume read-only:

```text
telemetry-data
   ├── ELK Logstash reads it
   └── OpenSearch ingest reads it
```

Neither ingestion service modifies the source files.

---

## 3. Telemetry observer

```text
Telemetry observer
```

Implemented in [telemetry_collector.py](../app/telemetry_collector.py).

Some important events happen durably in SQLite rather than through an HTTP request. Examples include:

- A broadcast starting or ending
- A request becoming queued, playing, or completed
- An outbox job being dispatched
- A download succeeding or failing
- A configuration value changing

The observer checks SQLite every two seconds:

```text
Telemetry observer
        │
        ▼
SQLite plays, requests, outbox,
tracks and failed_downloads
```

It converts newly discovered state changes into telemetry events:

```text
broadcast.started
broadcast.ended
request.queued
request.fulfilled
job.dispatched
job.completed
download.ready
download.failed
```

### Observer deduplication

The observer keeps a small SQLite database of its own:

```text
/telemetry/observer.sqlite
```

Its `seen` table remembers which derived lifecycle events it already emitted. This prevents each two-second scan from repeatedly generating the same event.

For example:

```text
First scan sees completed job
    → emit job.completed
    → record identifier in observer.sqlite

Next scan sees same job
    → already recorded
    → do not emit it again
```

The observer reads the live database without restarting or inserting itself into the station’s playback path.

---

## 4. ELK Logstash — independent offset and queue

```text
ELK Logstash
independent offset + queue
```

This is the official Elastic Logstash container. Its pipeline is defined in [infra/elk/logstash.conf](../infra/elk/logstash.conf).

It tails:

```text
/telemetry/*.jsonl
/telemetry/*.jsonl.[1-4]
```

### Independent offset

Logstash records how far it has read through each telemetry file in:

```text
/usr/share/logstash/data/radioworkx.sincedb
```

Conceptually:

```text
api.jsonl: read through byte 81,250
worker.jsonl: read through byte 42,100
```

Although the ELK and OpenSearch configurations use the same internal filename, they run in separate containers with separate Docker volumes. Therefore, their `sincedb` files are independent.

### Persistent queue

After reading an event, Logstash stores it in a disk-backed internal queue before sending it onward.

```text
JSONL
  ↓
file input
  ↓
persistent Logstash queue
  ↓
Elasticsearch
```

The queue is configured in [logstash.yml](../infra/elk/logstash.yml):

```yaml
queue.type: persisted
queue.max_bytes: 256mb
```

Its state is preserved in:

```yaml
logstash-data:/usr/share/logstash/data
```

If Elasticsearch becomes temporarily unavailable, Logstash can keep accepted events in that queue and retry them.

### Event processing

The ELK pipeline:

1. Parses each line as JSON.
2. Discards documents without `event.id`.
3. Removes unnecessary Logstash metadata.
4. Uses `event.id` as the Elasticsearch document ID.
5. Writes into a daily index.

```text
radioworkx-events-2026.09.20
```

Using `event.id` as the document ID makes repeated delivery idempotent: retrying the same event replaces the same document rather than creating another copy.

---

## 5. Elasticsearch — `127.0.0.1:9200`

```text
Elasticsearch
127.0.0.1:9200
```

Elasticsearch stores and searches the events delivered by ELK Logstash.

Inside Docker, Logstash reaches it at:

```text
http://elasticsearch:9200
```

The host Mac reaches it at:

```text
http://127.0.0.1:9200
```

It maintains daily indexes matching:

```text
radioworkx-events-*
```

Elasticsearch supports searches and aggregations such as:

- Count `page.view` events
- Find activity for a session
- Calculate API latency
- Group failures by error code
- Count listening heartbeats
- Plot events over time

Its index data is persisted in:

```yaml
elastic-data:/usr/share/elasticsearch/data
```

The port is bound only to loopback, so it is not exposed through the public RadioWorkx URL.

---

## 6. Kibana — `127.0.0.1:5601`

```text
Kibana
127.0.0.1:5601
```

Kibana is the visualization interface for Elasticsearch.

```text
Operator browser
       ↓
Kibana :5601
       ↓
Elasticsearch :9200
```

Kibana does not ingest telemetry. It queries the documents already stored in Elasticsearch and renders:

- Event counts
- Time-series charts
- Listener activity
- API performance
- Error breakdowns
- Audit tables

Its dashboard definitions are imported from:

[infra/elk/dashboards.ndjson](../infra/elk/dashboards.ndjson)

Like Elasticsearch, Kibana is bound to `127.0.0.1`, making it available only from the hosting Mac unless a separate access mechanism is deliberately configured.

---

## 7. OpenSearch ingest — independent offset and queue

```text
OpenSearch ingest
independent offset + queue
```

This is a second Logstash-based ingestion process, built using:

[Dockerfile.logstash](../infra/opensearch/Dockerfile.logstash)

Its pipeline is defined in:

[infra/opensearch/logstash.conf](../infra/opensearch/logstash.conf)

It reads the same JSONL files as ELK Logstash:

```text
telemetry-data
   ├── ELK Logstash
   └── OpenSearch ingest
```

However, it has a different data volume:

```yaml
opensearch-ingest-data:/usr/share/logstash/data
```

Therefore, it has its own:

- `sincedb` offsets
- Persistent queue
- Retry progress
- Container lifecycle

For example:

```text
ELK offset:        byte 90,000
OpenSearch offset: byte 75,000
```

The OpenSearch pipeline can fall behind or restart without affecting Elasticsearch ingestion.

It also derives:

```text
radioworkx.category
```

from the first portion of the action:

```text
page.view          → page
api.request        → api
broadcast.started  → broadcast
job.completed      → job
```

It sends documents to OpenSearch using `event.id` as the document ID, providing the same retry idempotence.

---

## 8. OpenSearch — `127.0.0.1:9201`

```text
OpenSearch
127.0.0.1:9201
```

OpenSearch is the second independent analytics store.

Inside Docker, its native address is:

```text
http://opensearch:9200
```

On the host, port `9200` is mapped to:

```text
http://127.0.0.1:9201
```

The different host port prevents a conflict with Elasticsearch:

```text
Elasticsearch → localhost:9200
OpenSearch    → localhost:9201
```

It stores its own copies of the events in:

```text
radioworkx-events-YYYY.MM.dd
```

Its data is persisted independently in:

```yaml
opensearch-data:/usr/share/opensearch/data
```

This is not an Elasticsearch proxy or replica. It is a separate search engine populated by separately reading the source telemetry files.

---

## 9. OpenSearch Dashboards — `127.0.0.1:5602`

```text
OpenSearch Dashboards
127.0.0.1:5602
```

OpenSearch Dashboards is the visualization UI for OpenSearch:

```text
Operator browser
       ↓
OpenSearch Dashboards :5602
       ↓
OpenSearch :9200 inside Docker
```

Host port `5602` avoids conflicting with Kibana on `5601`.

The RadioWorkx overview includes:

- Event actions over time
- Categories and actions
- Activity audit table
- Page and playback activity
- Search and API activity

Its saved objects are defined in:

[infra/opensearch/dashboards.ndjson](../infra/opensearch/dashboards.ndjson)

The dashboard address is:

```text
http://127.0.0.1:5602/app/dashboards#/view/rwx-activity-overview
```

It is local-only and is not served through Tailscale Funnel.

---

## 10. Operator / smoke test

```text
Operator / smoke test
```

This represents either:

- A human operator inspecting the dashboard, or
- [opensearch_smoke.py](../scripts/opensearch_smoke.py)

The smoke test verifies the entire path using a genuinely new event.

### Step 1: Generate activity

Headless Chrome opens:

```text
https://radioworkx.tail060b33.ts.net/artists
```

The browser telemetry code generates a `page.view` and sends:

```http
POST /api/activity
```

### Step 2: Capture the accepted submission

Playwright waits for the corresponding response:

```python
with page.expect_response(
    lambda r:
        "/api/activity" in r.url
        and r.request.method == "POST"
) as sent:
    ...
```

It verifies:

```python
sent.value.status == 202
```

It then extracts `session_id` from the associated request body.

### Step 3: Verify OpenSearch

The test repeatedly searches OpenSearch for:

```text
event.action = page.view
session.id = captured session
@timestamp >= test start
```

This retry loop is necessary because telemetry processing is asynchronous.

### Step 4: Verify Elasticsearch

After finding the OpenSearch document, the test searches Elasticsearch using the same `event.id`.

This proves that both independent ingestion pipelines received the same source event.

### Step 5: Verify the dashboard

Finally, Playwright opens OpenSearch Dashboards and checks that:

- The overview renders
- Expected panels exist
- No missing-object or loading error appears
- Activity data is visible

It also saves a screenshot for visual evidence.

## Complete flow

```text
FastAPI / workers / observer
            │
            ▼
bounded telemetry queue
            │
            ▼
rotating ECS JSONL files
            │
       ┌────┴────┐
       ▼         ▼
ELK Logstash   OpenSearch ingest
       │         │
       ▼         ▼
Elasticsearch  OpenSearch
       │         │
       ▼         ▼
   Kibana      OpenSearch Dashboards
```

The essential design principle is that everything after the in-memory telemetry queue is asynchronous. A slow or unavailable analytics system should not stop the live station, although sufficiently long outages can eventually exhaust the bounded buffers and cause telemetry loss.

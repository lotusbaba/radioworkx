# RAG chat architecture

RadioWorkx uses retrieval-augmented generation (RAG) to interpret conversational
music requests without allowing the model to execute queue operations directly. The
server retrieves a bounded set of catalog records, asks the model for a strict
structured decision, validates that decision against server-owned state, and only
then writes a request and durable outbox message.

The implementation is primarily in [`app/rag.py`](../app/rag.py), with routing and
the lexical fallback in [`app/requests.py`](../app/requests.py).

## Component overview

```text
Listener message
      ↓
requests.submit()
      ↓
RAG admission control ─────────────→ rag_turns
      ↓
Catalog retrieval ─────────────────→ tracks + rag_embeddings
      ↓
Conversation context ──────────────→ requests + rag_pending
      ↓
OpenAI Responses API
strict JSON Schema decision
      ↓
Server validation and deterministic overrides
      ↓
requests + rag_pending + outbox
      ↓
LocalStack SQS → download worker → station request queue
```

## Entry point and fallback

`app.requests.submit()` selects RAG only when the request mode is `auto` and
`OPENAI_API_KEY` is configured:

```python
if mode == 'auto' and os.getenv('OPENAI_API_KEY'):
    return rag.submit(query, mode, listener, request_id)
```

Provider HTTP errors, malformed provider data, invalid JSON, and RAG validation
failures fall back to `submit_local()`. The local path searches the same authorized
catalog lexically and marks the saved request with `engine='basic'`. Provider error
bodies are never returned to listeners.

## Admission control with `rag_turns`

The check and insertion happen in one `BEGIN IMMEDIATE` SQLite transaction, so two
requests from the same listener cannot both pass the busy check concurrently.

```sql
SELECT 1
FROM rag_turns
WHERE listener = :listener
  AND busy = 1
  AND created > :now_minus_300_seconds;
```

If no active turn exists, the current turn is recorded:

```sql
INSERT OR REPLACE INTO rag_turns (id, listener, created, busy)
VALUES (:request_id, :listener, :now, 1);
```

The same table supplies the usage checks:

| Limit | Query window | Current threshold |
| --- | --- | ---: |
| Per listener | Previous 60 seconds | 10 turns |
| Global | Previous 24 hours | `OPENAI_CHAT_DAILY_LIMIT`, default 500 |

A `finally` block clears the busy marker whether processing succeeds or fails:

```sql
UPDATE rag_turns SET busy = 0 WHERE id = :request_id;
```

The five-minute busy cutoff prevents a crashed process from blocking a listener
forever. `rag_pending` does not participate in rate limiting or locking.

## Catalog eligibility

RAG considers only tracks that belong to the active demo/real station and are not
failed. A track must either already be ready or remain legally and operationally
acquirable. Once the permanent library cap is active, retrieval is limited to the
downloaded library.

The retrieval document for each track contains:

- Title
- Artists
- Album
- Genre
- Mood words derived from the station's genre-to-mood mapping

Private source URLs, rights records, paths, and internal errors are not included in
the model context.

## Embeddings and hybrid retrieval

The embedding request uses:

```json
{
  "model": "text-embedding-3-small",
  "dimensions": 256
}
```

Track vectors are stored as JSON text in `radio.db.rag_embeddings`:

| Column | Meaning |
| --- | --- |
| `track_id` | Catalog track represented by the vector |
| `model` | Cache identity, currently `text-embedding-3-small:256` |
| `digest` | SHA-256 of the exact retrieval document |
| `vector` | JSON array containing 256 floating-point values |

The digest invalidates a cached vector when relevant track metadata changes. Up to
128 missing vectors are created during one turn in batches of 32, allowing a large
catalog to be indexed progressively.

The query is embedded using the same model and dimensionality. Each track receives a
hybrid score:

```text
3 × exact identity match
+ cosine similarity
+ normalized lexical word overlap
```

The highest-scoring 12 tracks become the bounded retrieval result supplied to the
chat model.

## Conversation context

The server builds the following model input:

```python
context = {
    'catalog': items,
    'available_genres': genres,
    'pending_confirmation': pending,
    'conversation': history,
    'station': station,
    'message': query,
}
```

| Field | Source and purpose |
| --- | --- |
| `catalog` | Sanitized top retrieval results the model may cite or select |
| `available_genres` | Genres currently represented in the eligible catalog |
| `pending_confirmation` | Previously offered genres and track IDs from `rag_pending` |
| `conversation` | Up to eight recent `query`/`response` pairs from `requests` |
| `station` | Current track and count of pending station requests |
| `message` | The listener's current text |

`pending_confirmation` gives phrases such as “yes,” “that one,” or a longer reply
meaning relative to the previous offer. It is also used later as server-owned proof
that a confirmation refers to an actually offered genre or track.

## `rag_pending` lifecycle

`rag_pending` has one row per listener:

| Column | Meaning |
| --- | --- |
| `listener` | Signed listener identifier and primary key |
| `genres` | JSON list of offered genres |
| `track_ids` | JSON list of offered catalog tracks |

When a response requires clarification, the server replaces the listener's pending
row with the new choices. Previously offered track IDs are added back to the allowed
catalog on the next turn, even if a short confirmation would not retrieve them by
semantic similarity.

The old pending row is deleted when the outcome is a confirmed request,
cancellation, or replacement clarification. A new row is inserted immediately when
the replacement outcome remains `awaiting_confirmation`.

## Normalization and deterministic resolution

`normalize()` case-folds text, removes accents and punctuation, and collapses
whitespace. It does not understand intent or extract a choice from arbitrary prose.

```text
"YES, please!"  → "yes please"
"Ambient..."    → "ambient"
"Hip-Hop"       → "hip hop"
```

After the model responds, deterministic rules handle several high-confidence cases:

- A fixed set of simple affirmative phrases such as `yes`, `okay`, and `play it`.
- Exact normalized track titles.
- Commands beginning with `play`, `queue`, `fetch`, `download`, or `request` that
  contain a complete track title.
- A message equal to an available genre.
- A simple affirmative response when exactly one track or one genre is pending.

Longer sentences are interpreted by the model using `pending_confirmation` and
conversation history. The RAG path currently relies on the model for ordinal phrases
such as “the second one”; deterministic ordinal handling exists only in the basic
conversation path.

## Strict structured output

The Responses API is called with `text.format.type='json_schema'`, strict mode, and
the `radio_chat` schema. Every response must contain exactly these fields:

| Field | Allowed value |
| --- | --- |
| `action` | `answer`, `clarify`, `request`, or `cancel` |
| `intent` | `specific`, `mood`, `confirmation`, or `question` |
| `reply` | String shown to the listener |
| `track_id` | String or null |
| `genres` | Array of strings |
| `source_ids` | Array of strings |

The model output is extracted from `output_text`, parsed with `json.loads()`, and
validated again locally. Invalid shape, keys, enum values, or field types raise
`rag.Unavailable` and trigger the lexical fallback.

## Server-side authorization and validation

Structured output is a proposal, not an instruction to mutate the queue. The server
checks that:

- `track_id` belongs to the bounded `allowed` catalog.
- Every cited source ID belongs to that same catalog.
- Suggested genres exist in the current eligible catalog.
- A confirmation selects a genre or track recorded in `rag_pending`.
- Mood requests obtain confirmation instead of immediately queuing music.
- The chosen track is still available immediately before commit.
- Explicit missing tracks are not silently replaced with unrelated recordings.

The central confirmation condition is:

```python
confirmed = (
    pending
    and decision['intent'] == 'confirmation'
    and (
        track['genre'] in pending['genres']
        or track['id'] in pending['track_ids']
    )
)
```

Only a validated specific or confirmed choice receives `status='pending'`.

## Persistence and queueing

The final database transaction updates conversational state and saves the durable
request. A successful music request also removes the track from the automatic
playlist and writes an outbox message in the same transaction:

```text
requests row
    + optional requested_genre
    + delete playlist copy
    + outbox request-download message
```

The outbox dispatcher later publishes the work to LocalStack SQS. Download and
station workers—not the model—prepare the recording and decide when it is eligible
to air.

## SQLite tables

| Table | Role |
| --- | --- |
| `tracks` | Authorized catalog and acquisition state |
| `rag_embeddings` | Cached track vectors and metadata digests |
| `rag_pending` | Choices awaiting listener confirmation |
| `rag_turns` | Busy state and usage accounting |
| `requests` | Durable messages, replies, decisions, status and FIFO sequence |
| `plays` | Current and historical broadcasts supplied as station context |
| `playlist` | Automatic selections adjusted after an accepted request |
| `outbox` | Durable request-download work awaiting dispatch |

The older `conversations` table belongs to the basic lexical conversation path. The
RAG path reconstructs history from `requests` and uses `rag_pending` for unresolved
choices.

## End-to-end example

```text
Listener: "Play something dreamy"
    ↓
rag_turns busy=1; limits pass
    ↓
Hybrid retrieval finds vaporwave, trip-hop and ambient candidates
    ↓
Model returns action=clarify with offered genres/tracks
    ↓
Server saves requests(status=awaiting_confirmation)
and rag_pending(offered choices)
    ↓
rag_turns busy=0

Listener: "The ambient one sounds perfect"
    ↓
rag_turns busy=1; previous rag_pending is loaded
    ↓
Pending tracks are restored to the allowed set
    ↓
Model returns action=request, intent=confirmation, track_id=...
    ↓
Server verifies track ID or genre against rag_pending
    ↓
Server writes requests(status=pending) + outbox message
and removes rag_pending
    ↓
Dispatcher → SQS → download worker → eligible station playback
    ↓
rag_turns busy=0
```

## Failure boundaries

- Embedding or Responses API failures fall back to local catalog search.
- Provider error bodies are not exposed to listeners.
- Model output cannot directly invoke SQS, downloads, or playback.
- A stale busy row expires from overlap checks after five minutes.
- A track is rechecked against the current catalog before the request commits.
- Request UUID reuse is idempotent only when listener, query, and mode match.


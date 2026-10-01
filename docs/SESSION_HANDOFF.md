# RadioWorkx session handoff

Updated 2026-09-10, America/Los_Angeles. This is a durable engineering handoff of the
available conversation context, decisions, and implemented work, not a verbatim
chat export or a backup of live databases/media. Never put API keys, passwords,
cookies, or raw private listener conversations in this document.

## Resume here

- Workspace: `/Users/bhaskarjayaraman/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Practice-py/radioworkx`.
- GitHub: private repository https://github.com/lotusbaba/radioworkx ; branch `main`.
- Current public site: https://radioworkx.tail060b33.ts.net/ . No Tailscale client required for visitors.
- Admin: same origin, `/admin`; username `admin`, password stored locally in ignored `.admin-credentials` and `.env`.
- Latest verified application tests: **128 passed** across the full suite and the added deployment recovery check. Browser audio/SSE reconnection across a real rollout, read-only desktop/mobile checks, and rollback passed.
- Latest implementation: Compose API replacement through Nginx. Public Funnel now proxies to **127.0.0.1:8001**. Read the final deployment section before operating containers; the active service can be `api` or `api-next`.
- Experimental ELB work is in draft PR https://github.com/lotusbaba/localstack/pull/1. It has local validation; AWS parity remains outstanding. The live SQS/S3 image is unchanged.
- User prefers implementing fixes directly, preserving earlier requirements, and avoiding repeated confirmation. Never expose credentials. Use approval escalation if a needed operation is blocked by the sandbox.

Start by reading this file and README.md, then `git status --short` and recent commits.
Use the project's `.venv/bin/python`; do not assume system Python has project packages.
For live issues inspect containers, recent station history and public status before changing anything.

## Latest hostname issue: verified cause and resolution

The user renamed the device/MagicDNS address from
`bhaskars-macbook-pro.tail060b33.ts.net` to `radioworkx.tail060b33.ts.net`.
`tailscale status --json` showed the new Self.DNSName and CertDomains, but
`tailscale funnel status` still listed the old hostname. The app itself responded
on `http://127.0.0.1:8000`. HTTPS to the new hostname initially failed with a TLS
internal-error alert. The separate local Tailscale Serve/Funnel configuration had
not followed the device rename.

Applied:

```sh
tailscale funnel --bg --https=443 http://127.0.0.1:8000
```

This added the new hostname's local HTTPS proxy configuration and enabled its
public Funnel route. Initial checks timed out, then both direct public Funnel and
tailnet HTTPS tests returned 200. Browser audio and live updates passed at the new
URL. No app code or binding changes were needed. The old hostname routes remained
in Funnel status; they were not reset/removed. Do not assume the old URL still works.

Network path: public visitor → Tailscale Funnel ingress → Tailscale HTTPS proxy on
this Mac → host loopback `127.0.0.1:8000` → Docker API container. Device DNS naming
and saved proxy routes are separate settings; the CLI reconciled them after rename.
For future renames check actual status instead of assuming automatic route migration.

## Architecture and runtime

- FastAPI/Python radio with SQLite, Redis, LocalStack SQS and S3, vanilla HTML/CSS/JS.
- Docker Compose services: `api`, `station`, `downloads`, `reactions`, `dispatcher`,
  `crawler`, `visuals`, `redis`, `localstack`.
- LocalStack built from the requested lotusbaba/localstack fork via
  `infra/Dockerfile.localstack`; Compose enables SQS and S3.
- API binds `0.0.0.0:8000` inside its container. Compose publishes
  `127.0.0.1:${RADIO_PORT:-8000}:8000` on the Mac. Funnel proxies to host loopback.
- Live state has used `RADIO_DATA_DIR=/data/live`, Redis DB 1 and queue prefix
  `radio-live`. Verify only these selected nonsecret env fields if necessary.
  `.env.example` uses development defaults `/data`, DB 0, `radio`.
- Named volumes: `radio-data`, `redis-data`, `localstack-data`. SQLite and media
  live on the shared data volume. Do not delete volumes or reset playback history
  to resolve eligibility problems.
- SQLite outbox provides durable SQS publishing; worker lock files prevent duplicate
  worker instances on the shared volume. SQLite transactions serialize state/cap decisions.
- Redis streams: `radio:audio` (MP3 chunks), `radio:events` (SSE event source).
- `.env` contains provider credentials, session secret and admin password. It is
  ignored by Git and Docker. `.admin-credentials` is also ignored. Neither belongs
  in chat output. The user previously pasted an OpenAI key; never repeat it.
- API keys are server-side. Relative browser URLs support hostname changes.
- Signed HTTP-only listener cookie initialized by GET `/`; secure on HTTPS. Direct
  audio/reaction access without visiting the station can return “Open the station
  page to start a listener session.”
- Mac must remain awake, with Docker Desktop and Tailscale running.

## Product requirements and implemented behavior

### Music, eligibility, downloading

- Initial station selection targets 10 tracks from 10 genres and different artists.
- Real independent music metadata via Bandcamp plus licensed Internet Archive sources.
- Downloads require supported, verified open licenses; implemented sources accept
  CC BY / BY-SA 3.0 and 4.0, normalized HTTP/HTTPS license URLs. No arbitrary download
  of restricted recordings. Validate exact media hosts, license and identity.
- Enforce the stated performance complement conservatively station-wide:
  artist ≤4 tracks per rolling 3h, ≤3 consecutive; same album ≤3 per 3h, ≤2
  consecutive; compilation ≤4 per 3h, ≤3 consecutive. Include window-overlapping
  performances; consecutive history survives silence/window boundaries.
- Listener requests FIFO ahead of automatic selection. Ineligible requests are
  deferred so later eligible requests/automatic tracks can play. Never bypass policy.
- Genre requests can use another eligible album/artist in the same genre when blocked.
- Low-water refill: current + automatic queue ≤3 triggers a 10-track batch via SQS.
- Recovery acquisition is requested when fewer than three eligible forecast tracks
  remain. Crawler imports can immediately enqueue recovery rather than waiting for
  a later check. Catalog/rights availability can still constrain recovery.
- Stop all new music downloading permanently after 10,000 successful tracks;
  thereafter reuse downloaded music. No bypass for listener/reaction downloads.
- Download jobs expose reason: automatic refill, reaction threshold, listener request,
  or no-eligible-music recovery. Completed fetches remain visible.
- Next-ten preview shares scheduler with actual playback, prefers unplayed/less-recent
  tracks, and does not pad with duplicates. Stops before first repeat; may show <10.
  A small eligible library may still repeat on air to avoid unnecessary silence.

### Reactions, rankings and chat

- Six emoji reactions; same listener may react repeatedly after **1 second** cooldown.
  Earlier 5-second/one-per-session behavior was superseded.
- Accepted reactions persist in SQLite and flow through SQS consumers into Redis
  sorted-set genre demand. SSE broadcasts activity; shared snapshots refresh ~2s.
- More than 20 reactions (21) before a track ends triggers follow-up selection.
  Artist/genre follow-ups still obey eligibility and acquisition limits.
- Genre demand clears on successful matching requested/reaction fetch. Historical
  reaction counts remain. Track totals continue until music ends.
- Reconciliation repairs missing fulfillment projections with Redis WATCH/MULTI,
  preserves post-fetch votes, and ignores delayed older votes using cutoffs.
- Community pulse = outstanding Redis demand, not all-time popularity. Historic
  likes shown in public stats/admin come from SQLite; each accepted emoji is one like.
- Conversational request line: “Hit up the RJ.” / “The request line”; no request-mode
  dropdown. Supports specific song, album, artist, genre, mood discussion and confirmation.
- OpenAI RAG uses catalog retrieval (lexical + cached embeddings), Responses API,
  gpt-4.1-mini default, store=false. Responses grounded in catalog and source citations.
- Mood ambiguity asks for genre confirmation; clear genre requests can proceed.
  “Yes, play it” resolves the offered track; multiple options require clarification.
  Specific confirmations must not silently substitute a different genre track.
- Unsupported/not-found requests give a useful response. Explicit basic-search fallback
  if AI is unavailable. Private chat remains visible only to its owner and admin.
- Request limits have been 10/min/listener, 500 global/day; UUID idempotency.
- All listeners see shared accepted track requests through SSE snapshots, including
  queued/playing/played state. No dedicated track-requested popup/event was implemented.

### Announcer and audio

- Male OpenAI TTS, default `gpt-4o-mini-tts`, voice `onyx`, gain +6 dB with peak limiting.
- Pronounce brand “Radioworks”. Introduce artist/title, use supported page details
  when available; do not invent facts from page text. Evidence validation for facts.
- Say “requested” only for the actual queued request being transmitted, not a later
  automatic replay of a previously requested recording. Cache key includes request context.
- Announcements persist via `tracks.intro_id` / `tracks.requested_intro_id` references
  to the script/audio-path row in `announcements`, with no expiry. A background thread
  continuously checks the next-ten forecast and generates the first missing intro,
  rechecking after each job with a two-second interval. Existing cache is adopted. Current implementation uses only cached/finished speech at track boundary;
  skip unready speech rather than hold music. Next candidate is rechecked atomically.
- Announcer time is separate from music time; reaction/playback clocks start with music.
- ffmpeg streams MP3 in real time; 2048-byte Redis chunks, max ~160 stream entries.
  Live API joins future chunks and drops stale backlog. Existing delay before playback
  was discussed; prebuffer/burst/instant-start architecture was **not implemented**.
- Attempt autoplay on page load; browsers may block unmuted autoplay. First user gesture
  retries. No claim that browser autoplay policy can be bypassed.
- Web Audio analyser drives sound bars from actual audio. Do not connect media source
  to a suspended AudioContext, which can mute otherwise successful autoplay.
- Cassette-style SVG brand icon, independent-radio dark/lime design, responsive UI.

### Artwork video and storage

- Album/track art extracted from artist/source page. Demand-generated OpenAI Sora
  video per track, cached and reused. Request 12s provider output, trim to 10s MP4,
  muted and loop throughout track; album art fallback and reduced-motion controls.
- Demand scheduling covers current/announced and next two tracks. Durable provider ID
  avoids duplicate submission; uncertain submission status is not blindly resubmitted.
- Local file caches plus S3 objects in bucket `radioworkx-media`. Manifest in
  `media_objects`; status in `track_visuals`. Audio is also mirrored/backfilled to S3.
- Public `/api/visuals/{track_id}/{kind}` serves artwork/video with Range support.
- **Video generation is paused:** local `.env` set `VIDEOS_ENABLED=0`; dispatcher
  and visuals workers were recreated. Queued video jobs remain untouched, cached
  videos can still play, already submitted provider work may finish remotely.
- Re-enable by setting `VIDEOS_ENABLED=1`, then `docker compose up -d dispatcher visuals`.
  `.env.example` defaults to 1; preserve actual local preference unless user changes it.
- Storage sync runs separately in the visuals worker even when generation is paused.
- Prior official-doc check recorded Sora API retirement 2026-09-24; verify current
  provider availability before resuming generation or changing the API integration.
- Last reported video count before pause: 21 ready, 1 generating, 5 failed; this was
  a historical observation, NOT a current total.

### Admin and public browsing

- Separate `/admin` with HTTP Basic authentication; all admin assets/APIs protected.
  Main page does not expose admin repository/raw private data.
- Paginated admin tabs: tracks, hosts, requests/chat, reactions, successful downloads,
  crawler runs, artwork videos, stored objects. Page sizes 25/50/100.
- Date filters 24h/7d/30d/custom up to 366d, previous-period comparisons, bucketed
  reaction/download/request trends and genre counts. Host repository includes
  discovered sources and track download counts.
- Bottom of landing page: “Your taste. Our collection.” with library size, likes,
  downloads, track requests, and genre horizontal bars. 24h/7d/all-time filters,
  refresh every 30s while visible. `/api/stats` exposes only aggregates.
- Download queue: `/api/downloads`, ten entries per page, Previous/Next, newest activity
  first, timestamp and cause per entry. Complete acquisition history, repeated empty
  diagnostics collapsed by kind. Active count separate from completed history.
- “What listeners asked for”: `/api/community-requests`, accepted track requests from
  all users, created DESC/sequence DESC, hashed listener labels, no raw chat. Ten/page.
- “Recent automatic acquisition activity”: restored as its own section;
  `/api/downloads?scope=automatic` filters completed refill activity/library reuse and
  terminal outcomes BEFORE pagination. Ten/page.
- All three lists preserve independent selected pages across live refreshes (~5s
  throttled off snapshots). Listing order does not alter FIFO playback/worker priority.

## Important resolved incidents

1. **Playback loop after old history expired (latest playback fix).**
   Preview `peek()` used all plays, `select_next()` used only rolling 3h + last 3.
   Variety ranking disagreed: preview chose “Wasteland Odyssey Pt. 7: Wayfarer
   (Reprise)” while final selection chose “New York November”. Expected-ID check
   rejected forever, burning CPU, leaving “Preparing AI introduction” and no audio
   ~13 minutes. Intro was already cached. Fixed `select_next` to use full ordered
   history, matching preview; eligibility internally still applies the 3h window.
   Added `ready_intro` to prevent unfinished provider work blocking music. Regression
   tests cover >3h history, unfinished future, and request-context mismatch. Verified
   browser audio and station On air after redeploying station. Commit `899ba34`.
2. **Earlier 0:00/no music: exponential diverse batch search held SQLite writer lock.**
   Bounded diverse_sample search to 5,000 states, collapsed equivalent artist/genre
   choices, pruning/memoization. Moved selection computation outside the SQLite write
   transaction in plan_refill, retaining atomic/idempotent commit checks. Existing
   queued refill was resent and completed. Never wipe play history to recover.
3. **Crawler found no eligible new music.** Archive search only matched HTTPS 4.0;
   corrected supported HTTP/HTTPS BY/BY-SA 3.0/4.0 variants. Versioned paging cursor,
   rows 10, retry without advancing on partial metadata failure, immediate recovery
   on new imports. Partial imports accounted even when a crawl defers.
4. **Trip-hop stuck at top.** Missing fulfillment projection kept 23 stale votes.
   Reconciliation preserved 2 votes after fetch and removed 21 before it. Periodic
   reconciliation repairs similar missed Redis updates safely.
5. **Repeated next-ten tracks.** Preview stops before duplicate; station preference
   avoids recent nine when an eligible alternative exists. Full all-history selection
   consistency required the later fix in item 1.
6. **Funnel hostname rename.** See exact cause/command above. Neither application
   binding nor Docker port changes were necessary for this rename.

## Source map

- `app/station.py`: refill/recovery, selection, announcer orchestration, transmission.
- `app/scheduling.py`, `app/policy.py`: shared ordering/preview and performance complement.
- `app/downloads.py`, `app/crawler.py`, `app/discovery.py`, `app/bandcamp.py`,
  `app/archive_source.py`, `app/hosts.py`: acquisition, rights/hosts, source discovery.
- `app/requests.py`, `app/rag.py`: request FIFO/confirmation/conversation and retrieval.
- `app/events.py`, `app/service.py`, `app/queues.py`, `app/workers.py`: reactions,
  outbox/SQS consumers, Redis projections and worker lifecycles.
- `app/announcer.py`: page facts, script, speech, cache/gain.
- `app/visuals.py`, `app/object_store.py`: generation/caching/S3 and storage restoration.
- `app/api.py`, `app/views.py`: public endpoints, SSE, cookies, queue/history pages.
- `app/admin.py`, `app/admin_assets/`: protected admin dashboard.
- `app/static/`: landing-page UI. `app/db.py`: schema/init; `app/config.py`: env defaults.
- `catalog/`: seed/source catalogs and discovery feeds. `README.md`: full requirements.

## Verification and safe operational commands

```sh
# Source checks (no production state mutation)
.venv/bin/python -m pytest -q
node --check app/static/app.js
git diff --check

# Container state; avoid dumping env/secrets or entire user/private tables
docker compose ps
docker compose logs --tail=50 station
tailscale funnel status

# Public browser smoke: --read-only avoids creating real listener requests
.venv/bin/python scripts/browser_smoke.py --read-only --audio-check --url https://radioworkx.tail060b33.ts.net

# Deploy only changed services as appropriate
docker compose up -d --build --no-deps api
docker compose up -d --build --no-deps station
```

`browser_smoke.py` uses installed Chrome via Playwright. It checks responsive layouts,
JS errors, independent pagination and selected-page persistence, stats filters, and
optionally real audio. Screenshots go to `/tmp/radioworkx-browser` (not Git).
Other optional modes: `--admin-check`, `--visual-check`, `--allow-autoplay`,
`--loop-check --video-track <id>`, `--ai-check`; inspect script before running modes
that can submit chat or real track requests. In-app browser previously reported
unavailable; this established script was the fallback.

Some services run older images because only changed services are rebuilt. Read live
code/config if diagnosing version mismatch. Keep current media/data volumes intact.
Shell commands may need sandbox escalation for Docker, Tailscale preferences,
network access or `.git` writes. An apparent gh login failure under sandbox was
resolved by `gh auth status` outside the sandbox; account is `lotusbaba`.

## Git milestones before this handoff

- `02fc526`: initial full application + public stats repository commit.
- `3e7e82b`: paginated download queue, latest first.
- `0fc2c3a`: browser smoke compatibility with download pagination.
- `673d734`: paginated listener requests and automatic acquisition history.
- `899ba34`: playback selection loop and nonblocking speech fix.
- `69ac4d9`: renamed public hostname in README.
- `29925c9`: first comprehensive handoff and AGENTS.md entry point.
- `cb3afa5`: prepare next-ten intros and persist reusable track references.
- `07e6bcc`: genre catalog browsing and exact-track queue APIs.
- `b05920a`: admin-issued app tokens; latest implementation commit before this save.

Repository was created private and pushed to GitHub during this session. Git ignores
`.env`, `.admin-credentials`, `.venv`, caches, `data/`, egg-info. Initial staged source
scan found no embedded actual env secrets or provider-token patterns. Runtime SQLite,
S3/audio/video, local credentials, and full chat transcript were not committed.


## Latest update: persistent intros from the up-next queue (2026-09-08)

Supersedes the previous one-prediction-per-track and seven-day expiry behavior.
`announcer.prepare_upcoming_once()` scans the shared next-ten forecast, reusing
track-linked intros and skipping retry cooldowns before generating one missing
variant. The station runs this in its own background thread during music. Generated
rows are linked to `tracks.intro_id` or `tracks.requested_intro_id` atomically.
Playback never waits for generation. Existing matching audio is adopted on lookup;
no age expiry or automatic regeneration on voice/model changes. Missing audio can
be regenerated. Source tests cover persistent reuse, variant isolation, legacy
adoption, new track references, cooldown fairness and newly arriving requests.

## Earlier update: catalog selection and exact-track queue APIs (2026-09-09)

Historical implementation note: the following original public/session authentication
was replaced by bearer app tokens in the next section. Use that newer contract.

Added `app/catalog_api.py`, API routes and `tests/test_catalog_api.py`.
- GET `/api/catalog/genres`: public selectable genre/count list.
- GET `/api/catalog/tracks`: public pagination (20 default, 100 max), repeated genre
  filter (OR, case-insensitive), title/artist/album `q`, stable title/ID ordering.
- POST `/api/queue`: exact track ID + optional UUID request_id, existing signed
  listener cookie required (GET `/` first). Atomic FIFO request/outbox, idempotent
  retries, 10 requests/minute per listener, no AI call or arbitrary URL imports.
- Ready tracks or licensed downloadable tracks only; permanent download cap,
  DEMO isolation and standard station policy remain effective. Public track DTO
  excludes internal source/path/rights strings. Shared snapshots expose requests.
- README contains curl usage, response shapes and error codes; `/docs` exposes schema.
- 113 tests passed, including genre filters, pagination/privacy, cap enforcement,
  session validation, exact-ID retries/conflicts, deferred downloads and rate limits.


## Latest update: admin-issued calling-app tokens (2026-09-09)

The catalog and exact-track queue APIs now REQUIRE bearer app tokens; earlier
public/session-cookie integration instructions are superseded. `app/app_tokens.py`
issues random opaque credentials and stores only SHA-256 digests in `app_tokens`.
Admin creates labelled tokens, sees plaintext once, copies/hides it, then only a
mask is available. Paginated list includes last use and revocation. No secret reveal
endpoint. Admin mutation requests have a custom-header and origin check in addition
to HTTP Basic auth; token responses are no-store. Calling apps use Authorization:
Bearer, with app-token identity replacing the listener cookie for `/api/queue`.
The three gated routes are `/api/catalog/genres`, `/api/catalog/tracks`, `/api/queue`.
Website listener routes are unchanged. Scope is browse+queue; no expiration setting.
115 tests pass, covering hashed storage, one-time response, masking, revocation,
missing/invalid auth, admin checks, pagination and app-specific request idempotency.


## Handoff refresh: 2026-09-10

The user requested another full session handoff. Repository was clean at the start,
on `main`, with implementation HEAD `b05920a`; all prior implementation changes were
pushed to the private `lotusbaba/radioworkx` repository. No new application changes
were requested after token management. No unfinished feature request is known.
This update preserves the earlier detailed context and adds the latest discussions.

### Current integration API contract (use this, not the historical cookie example)

- `GET /api/catalog/genres`: genre/count list, requires app bearer token.
- `GET /api/catalog/tracks?genre=jazz&genre=funk`: multiple genres (OR), optional `q`,
  paginated, default 20/max 100, requires app bearer token.
- `POST /api/queue`: JSON `track_id` and optional UUID `request_id`, bearer token;
  no listener cookie. App-token identity controls retry idempotency and 10/min rate
  limit. Exact track request enters normal FIFO/SQS processing; existing eligibility
  and permanent music download cap remain in effect.
- Header: `Authorization: Bearer <token>`. No Basic-auth or listener-cookie bypass.
- Manage at `/admin` → **App API tokens**. Generate a labelled app token, copy and
  hide or hide permanently. Full secret appears only on creation, never in list or
  DB; only SHA-256 digest persists. Refresh/navigation removes the displayed secret.
  Lost tokens cannot be recovered; revoke and replace. No auto-expiry.
- Admin APIs: GET/POST `/api/admin/tokens`, DELETE `/api/admin/tokens/{token_id}`;
  admin HTTP Basic required, mutation custom header `X-Admin-Action: tokens` plus
  origin check. Pagination, created/last-use/revoked timestamps, masked list.
- Revocation immediately denies subsequent authentication, but does not cancel
  already accepted requests. Public station UI continues with its listener sessions.
- Live browser verification generated a token named **Browser verification (revoked
  after check)** and revoked it afterward; a revoked test entry may appear in admin.
  It tested one-time reveal, clearing after copy, reload masking, authenticated read,
  and rejection after revocation. No live song was queued by that check.
- Optional repeat check: `scripts/browser_smoke.py --admin-check --token-check
  --read-only --url https://radioworkx.tail060b33.ts.net`. This creates and revokes a
  temporary token, so it is not a purely read-only operation despite the station
  portion using `--read-only`. Token text must never be logged or screenshotted.

### Latest explanatory discussions

**Frontend:** plain JavaScript, HTML and CSS, no TypeScript or frontend framework.
Listener frontend: `app/static/index.html`, `app/static/app.js`,
`app/static/style.css`, `app/static/cassette.svg`. Admin frontend:
`app/admin_assets/`. FastAPI serves these directly; no separate frontend server.

**SQLite:** embedded in API/worker processes, not a separate database server or
network service. Live database `/data/live/radio.db` in the shared named Docker
volume `radio-data` managed by Docker Desktop on this Mac. Multiple containers
access the shared file. No Postgres instance is implemented.

**Persistence:** named volumes survive container stops, crashes, restarts, rebuilds,
and recreation. Ordinary `docker compose down` preserves them. Explicit volume
removal (`docker compose down -v`, deleting in Docker Desktop) or Docker Desktop
data reset can erase them. Disk failure is also a risk. Persistence is not a backup.
No database/media backup, automated backup job, or restore exercise was performed
by this session-handoff request; do not claim otherwise. Do not run destructive
volume commands just to troubleshoot station state.

**Portfolio copy supplied:**
“I built and host RadioWorkx, a live radio station streaming Creative Commons–licensed
music from Bandcamp and the Internet Archive, with scheduling that enforces
SoundExchange performance-complement limits. It features conversational AI song
requests, AI-generated DJ introductions, live emoji reactions, and community-driven
music discovery.”
Stack: FastAPI, JavaScript, SQLite, Redis, SQS and S3 via LocalStack, OpenAI APIs,
Docker, Tailscale Funnel. The user suggested Postgres in draft copy, but SQLite was
correctly used in the final copy. Scheduling implementation is not a blanket claim
of legal/licensing compliance for every possible broadcast.

### Resume checklist

1. Read `AGENTS.md`, this handoff and README.md. Inspect git status before edits.
2. Treat current URL as `https://radioworkx.tail060b33.ts.net/`; older Mac hostname
   in incident history is historical. Check Funnel if reachability changes again.
3. Retain local `.env` and ignored `.admin-credentials`; do not print their contents.
4. Video generation remains paused (`VIDEOS_ENABLED=0` last applied); stored videos
   can play. Intros remain enabled, queued ahead and permanently reused via track refs.
5. Do not infer current music/queue counts from earlier observations. Inspect live
   state only if needed. Services can use different image versions after targeted
   deploys; the latest API image includes token management, station image includes
   queue-based persistent intros. No redeploy was required for this handoff.
6. The handoff is a curated continuation record, not a raw transcript, runtime-volume
   snapshot, or credential backup. GitHub contains source/docs/tests, not live media.

## Latest update: download failure archive and bounded replacement (2026-09-10)

User saw 28 hip-hop reactions; follow-up “Eva Jinek's dream” failed with ValueError.
Original behavior saved a fixed job plan and retried that same track. Added
`app/download_failures.py`, `failed_downloads` SQLite archive and private admin tab.
Failures archive source/page URL and error detail, quarantine track, and enqueue a
notice to passive SQS `download-failures` (14d retention, SQLite persists longer).
Discovery jobs try eligible same-genre alternatives (max3 replacements/job); genre
requests preserve FIFO identity, exact track requests fail without substitution.
Demand clears only on successful fetch. Job handles source failures and returns for
SQS acknowledgment; no infinite known-bad track retry. Infrastructure failures retain
visibility/redrive; completed duplicate deliveries are acknowledged without execution.
Admin/API/dispatcher/downloads require deployment. Source tests: 117 passing before
final live checks. Private failure URLs/details must not be logged publicly or exposed
in public snapshots. Existing initial failure details cannot be reconstructed without
another attempt; recorded historical errors were type-only.

Live verification after deployment: two stuck jobs were resubmitted by setting their
outbox sent timestamps to NULL (not deleting plans/history). Five source attempts
were archived with `ValueError: Unsupported provider host`. The reaction job
completed using cached “Don't get me down” as the alternative to “Eva Jinek's dream”.
At that check, zero download work jobs remained pending and five failure notices
were present in the SQS archive with none awaiting dispatch. Host-validation failures
remain quarantined; no broadening of allowed provider hosts was performed. 119 source
tests passed, including bounded alternatives and completed-message deduplication.

## Latest update: broadcast timestamps (2026-09-10)

User asked to show when both reaction follow-ups and requested tracks played.
`views.broadcast_times` reads music start/actual finish, suppressing future starts,
intro-only/interrupted reservations and active intros. Paginated and SSE community
requests use their exact requests.play_id association; UI distinguishes Requested,
Played, Finished and Not played yet. Reaction follow-up includes source_played_at
and first subsequent target broadcast after job creation/audio availability. No
historical causal boost-play linkage is claimed. 121 tests pass, including exact
request association and exclusion of earlier/future reaction target broadcasts.
Deferred idea remains unimplemented: no replacement → request same-genre crawl and
keep job pending until new music arrives. User explicitly asked to hold that thought.

## Latest update: genre-request variety (2026-09-10)

User reported repeated ambient selections, e.g. Cylinder One. Live catalog had 425
available and 37 ready ambient tracks; it was not a one-track catalog. Earlier
Cylinder One request records were mostly not tagged requested_genre, so those
records do not prove a SQL first-row genre selection bug. Existing genre paths used
uniform random choice without recency preference. Added shared choose_genre_track
for basic chat, RAG explicit/confirmed genre requests and deferred genre replacements:
prefer never played/requested, otherwise least recently used; randomize tied artist
groups then tracks. Exact track requests and offered-track confirmations remain
exact. 123 tests pass, with tests for rotation, history ordering and exact titles.

## Worked flow documentation

README now includes arrow diagrams with illustrative records/messages for reaction
acceptance, per-broadcast threshold detection, outbox dispatch, SQS consumers,
saved download plans, failure/replacement handling, Redis fulfillment and playback.
A second flow covers mood RAG retrieval, confirmation state, genre variety selection,
request FIFO and broadcast linkage. Examples distinguish SQLite records from SQS
messages and identify each worker/container. Documentation only; verified against
current source and with `git diff --check`; no runtime changes or deployment.

## Compose API replacement and rollback (2026-09-10)

Implemented `scripts/deploy.py` with init/deploy/rollback/status/resume commands,
immutable image IDs, a host lock, durable switch/drain state, readiness checks,
Nginx graceful reload and bounded draining. `api` and `api-next` alternate; one
API normally runs. Workers/station remain separate and were not restarted.
The live Funnel route now targets **http://127.0.0.1:8001** (Nginx), not port 8000.
Use the proxy endpoint for all checks; the old direct API slot may be stopped.
Current live drain window is 30 seconds; initialization default is 60 seconds.
Keep ignored `.deploy/` state/config and rollback images. Use the deployment script
for API changes; an unqualified Compose rebuild bypasses its release selection.

The first migration stopped the legacy API before Funnel was repointed, causing
an interruption. Funnel was then changed to the verified proxy endpoint; subsequent
rollouts and rollback use the stable proxy. No SQLite/history/volume reset occurred.

Player now retries live audio after error/end/stall and cancels retries on tune-out.
Verified actual browser audio and SSE reconnect across a same-image container
replacement using `scripts/deployment_smoke.py`. The rollback command also passed.
Read-only desktop/mobile/browser audio checks passed with no JavaScript errors.
128 pytest tests pass, including five deployment recovery tests. An initial broad
browser check hit an old chat-wording assertion; focused read-only/deployment checks
were used for this change. Database migrations still need backward compatibility.

A separate ELBv2 HTTP provider PR is being prepared in lotusbaba/localstack from
`/private/tmp/radioworkx-localstack-elb`, branch `feat/elbv2-http-streaming`.
The radio continues using the existing pinned LocalStack image for SQS/S3; its
runtime does not depend on merging the experimental ELB provider. See follow-up
entry for the PR URL and final verification.

ELB PR opened: https://github.com/lotusbaba/localstack/pull/1 (draft), commit
`15183d6af`. Seven local provider tests and one boto3/HTTP gateway test passed,
including an idle stream closed at its drain deadline. AWS parity validation remains
outstanding and limitations are explicit in the PR. No production LocalStack upgrade
was performed. Same-image radio rollouts now preserve the previous distinct release
instead of replacing the rollback image with the same image.

## Admin track playback counts (2026-09-18)

Tracks now includes all-time `play_count`, derived from existing broadcast history:
starts <= now, actual_end absent or after starts, excluding the active introduction's
play ID. Includes active music and broadcasts interrupted after starting; excludes
future/intro-only reservations. This counts station broadcasts, not listener sessions.
No schema changes or history rewrite. Tracks UI defaults to playback count descending,
with clickable column sorts and inclusive minimum/maximum inputs (blank = unbounded,
0 = never played). Filtering/sorting happen before pagination; chart dates do not
limit these counts. API accepts min_plays, max_plays, sort, direction; sort columns
are allowlisted. Regression suite: 129 passed. Focused browser check available via
`scripts/browser_smoke.py --admin-check --playback-check --url http://127.0.0.1:8001`.
Deployed through scripts/deploy.py to the API slot. Read-only browser verification
passed for ascending/descending counts, inclusive 2–10 filtering (394 matches at
verification time), invalid ranges, clearing filters, pagination and mobile layout.
Station workers and playback volumes were preserved.

## Refill variety and Archive storage-host fix (2026-09-18)

Diagnosis: 694 ready tracks had all played; 2,284 unattempted catalog tracks and
563 failed Archive tracks had zero broadcasts. 560 failures were Unsupported
provider host; three were timeouts. Fresh candidates covered nine genres, so the
old fresh-only ten-genre sampler failed and its mixed fallback favored sparse
artist/genre groups. The only ready orchestral track had 157 broadcasts and appeared
in 153 refill plans. These are historical observations, not live counters.

Added policy.balanced_sample for refill planning: bounded search prioritizes the
largest feasible fresh subset, orders genres by oldest last broadcast (random ties),
and ranks repeat recordings by fewest broadcasts then oldest last broadcast. Keeps
ten distinct genres and disjoint artists; uses a feasible fallback if optimization
exhausts its budget. Search remains outside SQLite writer transactions. Existing
saved jobs, listener priority, station policy checks, cap and playback history remain
intact. Only downloads worker was rebuilt/recreated; station/audio was not restarted.
Live dry-run selected nine new songs plus one cached song in ten genres in 4ms.

Three previously failing Archive URLs redirected from archive.org to numbered
`dnNNNNNN.ca.archive.org` hosts and returned HTTP 200. Added only that exact hostname
pattern to the Archive validator; HTTPS, credentials, port and every-hop checks
remain. Host spoofing tests reject lookalikes and other subdomains. Full suite passed
132 tests; an additional refill integration test then passed with the focused suite
(39 tests), covering nine new tracks, least-played repeat and durable plan reuse.
Full acquisition validation succeeded for archived failure
`ia-275552a5c4c2032b7cd770ae56fec1a0`: license/identity recheck, validated redirects,
4,189,247-byte normalized MP3, 261.8 seconds. Temporary verification audio removed.
Reset exactly 560 failed Archive tracks whose latest archived error was Unsupported
provider host to available/error NULL for gradual normal acquisition. Failure archive,
old jobs and requests preserved; three timeout failures remain quarantined. These
560 are retry candidates, not a claim that all have successfully downloaded. Existing
queued tracks finish normally before new refill selection takes effect.

## Artist/album pages and personal playback (2026-09-18)

User explicitly requested a page for every artist/album with playable tracks. This
supersedes the original live-only/no-on-demand requirement. New public `/artists`
and `/albums` directories support search and pagination; hash-ID detail pages list
tracks and related artists/albums. Featured artists each get their own page; album
identity uses album_id, not title. The station's now-playing names link to detail
pages. No biographies or artwork provenance are invented.

`app/library.py` adds public browse APIs under `/api/library`, plus listener-cookie
protected POST `/api/listen/{id}` preparation and GET `/api/listen/{id}/audio`.
GET `/api/listen/{id}` exposes readiness. MP3 FileResponse supports Range seeking;
paths must resolve beneath DATA/audio. Public payloads exclude filesystem paths,
source download URLs, raw errors and private rights notes. Existing bearer-token
integration APIs remain protected. Source/license attribution is displayed.

Personal preparation emits a deduplicated `listen:{track_id}` job on request-downloads.
Workers acquire exact identity without station playlist insertion, listener requests,
reaction fulfillment or broadcast-history writes. Existing download validation and
10,000-track cap remain. New personal_downloads table limits new preparations to ten
per minute per cookie identity; old entries are pruned. Acquisition already owned by
another consumer now raises TrackReserved for retry instead of quarantining audio.
Unavailable/missing-source tracks remain listed with disabled controls; preparation
failures are reported without leaking private error details. Native personal audio
supports pause/seek/volume; page navigation ends that listening session.

138 tests passed. Browser smoke script `scripts/library_smoke.py <url>` verifies
artist/album navigation, real cached MP3 playback, seeking, stop and mobile layout.
Add `--prepare` to acquire one previously available recording; this changes the
library but does not queue a station request. Downloads worker deployed first; API
uses scripts/deploy.py rollout. Station/audio worker was not restarted.
Live browser verification also passed first-play preparation of an undownloaded
recording, followed by actual MP3 playback and seeking; no JavaScript errors.
Public HTTPS APIs reported 406 artists and 388 albums at verification time.
Final HTTPS browser check passed navigation, cached playback, seeking and station
mobile directory links with no JS errors. API final image begins `8f3cf0f3dba0`;
downloads worker image begins `e4aba2b6a4e1` (same backend feature code; API has the
additional mobile navigation CSS). Personal playback counts are intentionally not
included in the admin's station-broadcast totals.

## User activity and ELK (2026-09-19)

User requested all proposed activity categories. Deployed browser browsing/search,
live and personal playback lifecycle/heartbeat events, API and admin audit,
reactions, requests, downloads, job outcomes/retries, configuration observations,
and sanitized errors. Broadcast counts, personal playback starts and listening
duration remain separate. Collection begins at installation; historical listener
activity cannot be reconstructed.

`app/telemetry.py` buffers allowlisted ECS JSON events asynchronously into rotating
files on telemetry-data. `app/telemetry_api.py` validates cookie-bound browser batches
and instruments API mutations/latency. `app/telemetry_collector.py` runs as the
telemetry-observer service and observes durable database outcomes without restarting
the live station. Browser instrumentation lives in `app/static/activity.js`.
`app/activity_admin.py` and `app/static/admin-activity.js` provide the authenticated
admin activity timeline with action, track, user, session and time filters.

Elasticsearch, Logstash and Kibana use official 9.5.4 images. Logstash tails the
shared files into daily indices with stable event IDs and a persistent queue.
Elasticsearch localhost:9200 and Kibana localhost:5601 are bound to loopback only;
they are not public Funnel endpoints. Preserve elastic-data, logstash-data and
telemetry-data alongside existing application volumes. `scripts/setup_elk.py`
installs the 30-day retention policy, index template and four dashboards:
rwx-audience, rwx-music, rwx-requests, rwx-errors. Saved objects are also recorded in
`infra/elk/dashboards.ndjson`. See README for startup commands and data limitations.

No raw search/chat text, credentials, cookies, IPs, signed URLs or exception messages
are captured. Listener identifiers are HMAC pseudonyms; browser/device labels are
coarse. Heartbeats measure engaged wall time rather than seek position. Counts are
estimates from client reports; background throttling can undercount. Bounded buffers
can drop telemetry during prolonged outages, without blocking audio. Producer files
rotate at 20 MiB with four backups; observer removes files older than seven days.

Verification: full suite 144 passed, JS syntax and git whitespace checks passed.
Real browser playback/search/seek/pause events reached Elasticsearch and the admin
timeline; a roughly 32-second test recorded 31.7 seconds despite seeking forward.
All four Kibana dashboards rendered and were screenshot-checked. The initial combined
smoke test hit Kibana's CSP restriction on Playwright eval; changed it to locator
waiting and verified dashboards independently with `scripts/kibana_smoke.py`.
Downloads/dispatcher/reactions/crawler/visuals and the observer were deployed; the
station was not restarted. Final rolling API deployment completed successfully,
switching api-next to api and draining existing streams. These runtime observations
are historical: inspect current health before diagnosing future incidents.

## OpenSearch alongside ELK (2026-09-20)

User requested OpenSearch with the OVHcloud example's layout: event-action area
chart, category/action donut, and full-width searchable audit table. Added independent
OpenSearch/Dashboards 3.8.0 services on loopback ports 9201/5602, plus opensearch-ingest.
The ingestion image uses Logstash 9.5.4 and OpenSearch output plugin 2.1.1. Plugin
installation needs a 2 GiB build heap; the first smaller-heap build failed, was stopped,
and was successfully rebuilt. Runtime ingestion heap remains 256 MiB with 768 MiB cap.

The pipeline tails the existing sanitized telemetry files with independent offsets,
persistent queue and deterministic event IDs. It adds radioworkx.category from the
first action component. No application playback or event emission changes were needed.
OpenSearch uses opensearch-data; ingestion offsets/queue use opensearch-ingest-data.
Do not remove volumes. Existing ELK remains independent, including the admin timeline.
Admin now links to http://localhost:5602/app/dashboards#/view/rwx-activity-overview;
its rolling API deployment completed without restarting the station.

scripts/setup_opensearch.py installs 30-day ISM retention, mappings, the index pattern,
two native visualizations, saved search and dashboard. Both current event indices were
verified to have the active retention policy. Dashboard uses a 24-hour window and
30-second refresh. Existing retained telemetry files are read on first startup;
there is no historical Elasticsearch backfill. Saved objects are checked in under
infra/opensearch/dashboards.ndjson. See README for startup/setup commands.

Initial browser failure "Cannot read properties of null (reading 'version')" came
from missing panel.version in imported dashboard panels. Fixed panel versions to
3.8.0. Also populated index-pattern fields (with known-field defaults before first
ingestion and live field discovery on later setup) to prevent missing-field chart
errors and enable time sorting. Setup overwrites dashboard customizations but leaves
an existing retention policy intact. Three setup regression tests cover references,
panel versions/fields, retention and repeat setup; full suite passed 147 before the
browser corrections and focused setup tests passed after them.

Final browser smoke passed: a new browser page view reached both OpenSearch and
Elasticsearch under the same event ID. Both charts and the audit table rendered
with real events, and the table showed newest events first. Screenshot saved at
/tmp/rwx-opensearch-check/overview.png. Radio health remained OK.

## Local and public access recovery (2026-09-20)

Both app endpoints became unreachable because the Docker daemon was not running.
Tailscale was connected and the RadioWorkx Funnel route still correctly targeted
127.0.0.1:8001. Starting Docker Desktop with `open -a Docker` restored the existing
containers through their restart policies, including active API slot api-next and
Nginx. Local and public /health both returned HTTP 200 afterward. No rebuild, volume
reset, deployment switch or Tailscale route change was needed. The reason Docker
stopped was not established. Use http://localhost:8001 for this managed deployment;
port 8000 may be unavailable because the api slot is intentionally stopped.
Public page and live MP3 subsequently returned HTTP 200, with audio bytes received.
Station status reported On air. The first status request timed out during startup;
a later request succeeded in 9.4 seconds while services were warming up.

## Listener accounts, likes, and playlists (2026-09-28)

Added email/password registration and sign-in at `/my-music`, with private persistent
liked tracks and personal playlists. Station, artist, and album track controls expose
Like and + Playlist; the save dialog can create a playlist. My music supports playlist
creation, rename/delete, track removal, Play all, sequential automatic advance, native
pause/seek/volume, Next track, and Stop. Saved unavailable tracks remain visible but
are excluded when building a playback queue. Preparation failures leave an explicit
message and allow Next track. Navigation still ends personal playback.

`app/accounts.py` contains account/collection APIs. Additive tables are users,
user_sessions, account_attempts, user_likes, user_playlists, user_playlist_tracks.
Account IDs and collections are separate from anonymous listener identity, live emoji
reactions, and station scheduling/history. Passwords use salted PBKDF2-SHA256 with
600,000 iterations. Session tokens are random, stored only as SHA-256 digests, expire
in 30 days, and are revoked on sign-out. Cookies are HTTP-only and SameSite Strict;
production COOKIE_SECURE remains enabled. Mutations require a custom same-origin
header and reject cross-site requests. Database-backed email/IP/global attempt limits
apply to registration and login. Existing telemetry does not capture credential bodies.
Email verification, password recovery emails, and a mail provider are not configured:
email is currently the sign-in identifier. Do not claim email ownership is verified.

Full suite: 151 passed. `scripts/accounts_smoke.py` uses a temporary database/catalog,
synthetic audio and headless Chrome to verify registration, likes, playlist creation,
adding/removing tracks, rename, actual audio and automatic advance, sign-in persistence,
and desktop/mobile layout with no JS errors. It creates no production accounts.
The API/frontend deployment uses the existing rolling controller; station and workers
remain running with their existing images. No playback history or volumes are reset.

Deployment completed to api-next, image `c5315009f2d0ac54c578a5738419771e4daa95210e8fb12bb5c2afaf6fdae6a1`;
previous API drained and stopped normally. Public `/health` returns OK and `/my-music`
returns 200. Production secure-cookie setting was checked and is enabled.
Public library browser verification passed navigation, actual cached audio, seeking,
and mobile layout with no JS errors after increasing waits in a temporary test copy.
Initial production smoke runs exceeded the default waits. A station browser check
with longer snapshot waits passed live audio, pagination/persistence and stats-filter
steps, then timed out at its separate final `/api/status` fetch (30 seconds), so the
full station smoke is NOT claimed as passed. A direct status request completed in
15.8 seconds with On air, an active play and ten preview tracks; another exceeded
20 seconds. API CPU was about 125% during checks. Catalog count was 6,903 tracks and
history 6,131 plays. Slow production status/catalog responses remain an unresolved
performance observation; no station scheduling/history changes were made to address
this during the account feature work. Existing user-authored untracked docs/test spec
were left untouched. Feature changes remain uncommitted in the workspace.

## Announcer tail preservation (2026-09-28)

User reported missing closing words at the intro-to-music transition. Verified the
running station transmits the full FFmpeg stdout and waits for process completion;
there is no duration-based speech cutoff in station code. Found two loss paths in
API/player: after each batch the API jumped its Redis cursor to the newest chunk
when timestamp lag exceeded three seconds, discarding retained speech; the browser
also replaced its audio source immediately on a `stalled` event, discarding buffered
audio even when playback could continue.

`app/live_audio.py` now anchors each new connection once at the current live edge
and forwards all retained chunks in order, with larger read batches. It does not
seek ahead on transient lag. Redis's existing bounded retention remains the limit;
this cannot recover audio already trimmed after a long outage. The player keeps its
source on waiting/stalled, allows buffered speech to finish, and uses a 15-second
watchdog to reconnect only after progress stops and playable buffers are empty.
Error/end recovery and Tune out cancellation remain. No announcer, speech-generation,
station-worker, history, or media changes were needed. Existing browser tabs need
one refresh to load the updated JavaScript.

153 tests passed, including stream ordering/idle cursor/resource cleanup regressions.
`scripts/transition_smoke.py` verifies in isolated Chrome that transient stalls do
not restart progressing audio, buffered speech survives the watchdog, empty stalled
connections recover, and Tune out cancels timers; no JS errors. API image
`10e430ea0d4c8d6a2d483fb025b25d5d012d4252f24890e5fc61fa7a8c2adcdc`
was rolled to api; public health returned OK. Station remains on its existing image.

Post-deployment real-transition verification succeeded. A temporary read-only capture
compared station Redis bytes, HTTP-delivered MP3 bytes, and the cached introduction
remuxed with the station's exact FFmpeg flags. Over 82 seconds, all 1,221,945 delivered
bytes matched one contiguous source segment, and the complete cached introduction
appeared intact in both source and HTTP audio before the following music. No capture
errors. The initial diagnostic attempt lacked a cookie usable over internal HTTP;
it produced no HTTP audio and was not treated as evidence. The corrected capture
used an ephemeral signed anonymous listener session and retained audio only in memory.

## Still artwork while videos are paused (2026-09-29)

Missing artwork was confirmed: the then-current track had no track_visuals row,
while VIDEOS_ENABLED was 0. Both visual scheduling and queue consumption previously
stopped at that flag, so still covers were only fetched as a prerequisite to video
generation. Existing 28 cached covers could display, but newer tracks had none.

Added an independent artwork loop inside the visuals worker. It fetches one missing
announced/current/queued cover per pass, with ten-minute retry backoff, and stores
covers locally and in S3 without any OpenAI request. The helper uses a per-track file
lock and atomic image replacement so it can coexist with enabled video processing.
Artwork-only rows can later be promoted to video jobs by the scheduler, without
changing existing provider IDs or ready/failed video state. Artwork downloads now
follow bounded, provider-validated redirects. Video generation remains paused.

Visuals and dispatcher were rebuilt; API/frontend rolled to api-next, image
`9afd2b91da7b638ab0cd3bee6e207afe6396565eaa33636d682e7c7087ab5641`.
Station was not restarted. Full suite 156 passed. Public browser verification via
`scripts/artwork_smoke.py` confirmed an HTTP 200 image decoded at 1280×720 and rendered
on desktop/mobile for “September 2015 Instrumental”, with no JS errors. Mobile
artwork screenshot was visually inspected. Current worker VIDEOS_ENABLED=0 was
verified; public visual status was artwork_ready with video_url null. Releases
without usable source artwork still show the existing station fallback.

## Announcement tail pause followed by resumed words (2026-09-29)

User clarified a different symptom: the final words resume after about two seconds,
then music plays. Earlier byte-continuity verification did not establish smooth
wall-clock delivery. Timed an existing cached announcement through separate FFmpeg
processes without publishing any audio: ordinary output had no >0.3-second gaps.
A read-only live Redis/HTTP capture then found smooth speech (max Redis gap 0.168s,
HTTP 0.236s), but a 5.895s Redis / 5.927s HTTP gap from the last speech bytes to the
first music bytes. Full reference speech bytes were present. This supports a
transition starvation explanation; it is not a direct recording of the user's
speaker output or a per-call attribution of every millisecond in the delay.

The main loop synchronously called refill after start_music and before starting the
song's FFmpeg process. Moved this refill to a coalescing station-refill background
thread, retaining the existing pre-selection refill. Music transmission no longer
waits for that acquisition/recovery calculation. Cached inputs are normalized MP3s;
FFmpeg now uses an explicit MP3 demuxer, bounded 32768-byte probe, and packet flushing.
A separate startup test measured the current song's first output at 0.414s with the
old command and 0.072s with explicit input/bounded probe (same existing file).

159 tests passed, including refill concurrency, full tail forwarding, and a main-loop
regression forbidding synchronous refill between intro and music. Built station image
`d64a1d60be419f01afc730fa4fc3764101757bb1316d78769a164227bade1688` and restarted only
station after observing the prior song's recorded end. A short introduction begun
during the deployment was interrupted; the diagnostic explicitly discarded that
incomplete introduction. History and media volumes were preserved. API was unchanged.

The first complete post-deployment transition (“Mir”) delivered all 124,551 cached
speech bytes, with max speech gaps 0.141s Redis / 0.161s HTTP, and only 0.219s between
speech and music in both Redis and HTTP. No capture errors. The observer ran as a
separate temporary process inside api-next so the station restart did not kill it.
This measures actual stream timing, not audible playback on the user's device.
Updated STATION_AUDIO_ARCHITECTURE.md with the refill thread and FFmpeg flags.
Other pending adversarial-spec/docs changes were left untouched. These timing-fix
changes are deployed but have not yet been committed or pushed.

## PostgreSQL refactor prepared; live cutover pending (2026-09-29)

User requested moving all database tables to an existing local PostgreSQL instance.
Found `app-db-1`, image `postgres:13`, publishing host port 5432. The target database,
role, credential-file location, and whether to create a dedicated database have been
requested but not supplied. Do not infer credentials or alter that unrelated app's
database. No live cutover or PostgreSQL deployment has occurred.

Application SQL now uses native Psycopg parameters, PostgreSQL JSON operators,
ON CONFLICT, identity sequences, and DOUBLE PRECISION timestamps. `app/schema.sql`
contains all 28 main tables plus observer_settings/observer_seen, replacing the
separate observer SQLite database. `db.transaction()` takes a transaction-scoped
advisory lock scoped to database/schema to preserve serialized business decisions.
`DATABASE_URL` is mandatory; media still uses DATA_DIR and existing volumes. Compose
now requires this variable even for configuration/status commands. Existing running
containers still have the previous SQLite code, including the deployed timing fix.

`scripts/migrate_postgres.py` imports read-only SQLite snapshots into an empty target
in one transaction. Defaults to rehearsal rollback; --apply commits after all row
fingerprints/multiplicities match. Preserves identity high-water marks, rejects
unknown tables/columns, invalid FKs, unrelated/nonempty targets and wrong source DBs.
Both station and observer snapshots are needed for this installation. Read
`docs/POSTGRES_MIGRATION.md` before cutover: stop every writer, take fresh backups,
import before bootstrap, then recreate previously running application services.
Do not use a rolling overlap across SQLite/PostgreSQL. Downloads remains stopped;
video generation remains paused. Retain original media/history volumes and rollback
images. Once PostgreSQL accepts new writes, switching back requires reconciliation.

Verification used a separate memory-backed PostgreSQL 13 service from compose.test.yaml
on loopback 55432. Tests require TEST_DATABASE_URL and create/drop random schemas;
they never fall back to the production URL. Full suite passed 161 tests, followed by
additional migration rejection/rollback coverage. Isolated Chrome accounts smoke
passed registration, likes, playlist create/add/rename/remove, actual playback and
automatic advance, sign-in persistence, and mobile layout with no JavaScript errors.
A separate Linux verification image successfully built with Psycopg 3.3.6.

Read-only backup-API snapshots of live radio.db and observer.sqlite were copied to
private temporary files for a rehearsal. Imported into a disposable PostgreSQL
schema and verified all 30 tables, including 6,903 tracks, 6,286 plays, 2,886
announcements, 4,194 outbox records, 11,269 observer keys, and all existing accounts,
sessions, likes, playlists and playlist tracks. Repeated init and the real-data
download-history query passed. The temporary schema was removed afterward. These
snapshots were taken while live writers continued and must NOT be used for final
cutover; fresh stopped-writer backups are required. The existing PostgreSQL instance
and production data were not modified. Refactor changes are uncommitted/unpushed.
Preserved the prior station timing edits and unrelated adversarial documentation.

Final focused migration/observer checks: 11 passed, including rollback after a
mid-copy data error and rejection of a wrong source database. Private rehearsal
snapshot files were deleted after verification.


## PostgreSQL live cutover completed (2026-09-29)

User provided local PostgreSQL credentials. Created dedicated database `radioworkx`
and role `radioworkx` with a generated application password in ignored `.env`.
IMPORTANT correction: actual target is Homebrew PostgreSQL 14.15, not the unrelated
`app-db-1` PostgreSQL 13 container. Verified localhost, 127.0.0.1, and ::1 all list
radioworkx on port 5432. Database browsers connected to `postgres` may need a database
list refresh or a direct connection to `radioworkx`; tables are in public schema.
Containers connect through host.docker.internal:5432 to that same dedicated database.

Stopped all writers and migrated 30 tables with exact row verification: 6,903 tracks,
6,293 plays at cutover, all account/session/like/playlist rows, 2,886 announcements,
4,196 outbox rows, and 11,289 observer checkpoint rows. First backup attempt failed
because SQLite needed writable journal/shared-memory state on the read-only mount;
it automatically restarted unchanged SQLite containers before any import. Retried
with copies of the stopped database plus WAL in a private writable directory, then
SQLite's backup API. Successful copy/restart took 18.7 seconds. Original media and
SQLite volumes are retained. Private SQLite snapshots, original configuration/image
inventory, migration counts, and initial PostgreSQL custom-format dump are under
ignored `.deploy/postgres-cutover/`; these contain private data and must stay ignored.

Detected startup DDL deadlocks after the first PostgreSQL rollout. Fixed db.init to
skip DDL when the recorded schema digest matches; importer records that digest too.
Regression holds a read transaction open during repeated initialization. All 164
tests pass. Final application image is
`sha256:d11cb014394226c7fec985768d06b1e695e8732ab101cb4d125f1dd821d5ff1f`.
Managed API deployment switched to `api` with connection draining. Workers use
RADIO_WORKER_IMAGE through shared Compose image configuration. Downloads remains
stopped; VIDEOS_ENABLED=0. SQLite-era API rollback pointers were removed; never
restore those images against a now-active PostgreSQL deployment without reconciliation.

Public/local health, my-music, anonymous account protection, status, and public live
MP3 delivery passed. New plays and observer checkpoints were verified in PostgreSQL.
Chrome library smoke passed artist/album navigation, real cached playback, seeking,
and mobile layout without JavaScript errors. Status requests took about 9–18 seconds;
this existing performance issue is not claimed fixed. No new tracks were downloaded
for verification. Changes remain uncommitted/unpushed.

Final follow-up audit after DBeaver connection was confirmed: all 30 public tables
remain accessible, with 6,903 tracks and five post-cutover plays at verification.
All seven active application services use the final image with zero restarts;
standby api-next and downloads are stopped on that same image. PostgreSQL backup
archive is readable and contains 30 table-data entries. SQLite rollback snapshots
remain private and nonempty. Public health returns 200. No further database cutover
steps remain. The migration implementation, station timing fix, tests, and operational
docs are included in the PostgreSQL release commit; consult Git history for its
revision and remote status. Separate adversarial-testing draft changes remain local.

## Adversarial decision-routing slice (2026-09-29)

User approved starting implementation after refining both engine diagrams and the
hybrid Strategy 2 router. Added standalone `adversary` models for concrete actions,
ordered locators, observations, immutable candidate snapshots, decision identity,
per-strategy routing configuration and explicit remaining budgets. The pure Python
DecisionRouter selects Laya for fully covered bounded choices (default ten max),
LLM otherwise, or blocked when required models/budgets/configuration are unavailable.
Malformed or stale requests fail validation. It never silently changes backends.
Hosted model routing requires explicit opt-in. No model or browser calls occur.

88 tests pass via `.venv/bin/python -m pytest tests/adversary --confcutdir=tests/adversary -q`.
`.venv/bin/python -m adversary.inference.demo` prints three illustrative route outcomes.
The nested test fixture bypasses the parent suite's PostgreSQL setup for domain tests.
Added optional Pydantic dependency and adversary package discovery in pyproject.toml;
production Docker sources and services are unchanged. No model weights downloaded.

This is the first contracts/router slice, not completion of Phase 1 or either engine.
Remaining run/result/failure, recording and security contracts are pending. Browser
Use model-output mapping is still unverified; queue/executor, atomic budget accounting,
ActionPolicy, QA environment, browser execution, recording/replay and both model
integrations remain future work. Read the implementation status in docs/architecture.md.
Preserved the user's existing diagram/spec edits; no commit, deployment or live data
changes were made for this slice.

## Modal authentication and home-page My Music (2026-09-29)

User requested login/registration as a popup, My Music on the home page, and personal
playlist playback that stops the listener's live audio, while retaining both routes.
Implemented one reusable native dialog in music.js for login/register, form switching,
Escape/close/backdrop dismissal and native focus restoration. Signed-out save actions
open it without navigation and resume after authentication. Stale responses cannot
write errors into a reopened form. Password inputs clear on close/mode change.

Home now embeds the saved likes/playlists panel at #my-music, with a separate link to
/my-music. Both standalone routes remain available. Scoped library/account scripts
share rendering and the personal player without colliding with station globals.
Starting a personal track cancels live reconnect/stall timers and clears live audio;
Tune in cancels personal preparation/queue playback and clears its source. This only
changes that listener's audio, not the station broadcast. Browser navigation still
ends playback. Telemetry follows the selected audio element; background live-status
updates cannot relabel personal playback. Save-button state stays synchronized.

Verified isolated Chrome registration, login, likes, playlist creation/add/rename/
remove, actual audio/automatic advance, both playback switches, cancellation of a
pending preparation, mobile overflow, and independent route navigation. Existing
AUTH-07 browser scenario passes normally after removing its now-obsolete expected-
failure marker: repeated opening, Escape/focus restoration, ignored late errors,
unchanged page/search state and uninterrupted audio. Other pending account scenario
and adversary code were preserved. Existing live transition smoke also passes.
Desktop/mobile modal, collection and player screenshots were visually inspected.

Deployed API/frontend via normal rolling deployment to api-next, image
`sha256:0be7787104a0291b430182b99130bdeaad7cadafb2c26155ace43513bcebb54e`.
Public read-only Chrome verification passed inline collection, auth-mode switching,
mobile dialog and standalone navigation with no JS errors. No production accounts
or playlists were created for testing. Station and other workers were not restarted.
Existing tabs need one refresh. These changes are not yet committed/pushed; preserve
parallel adversary files and pyproject/documentation edits. The disposable PostgreSQL
test service was already running at task start and was left available for that work.

## Popup and landing-page adversarial follow-up (2026-09-29)

Added AUTH-08 desktop/mobile mode-switch/password/focus/playback checks and HOME-01
late-collection-response-after-logout check to tests/test_account_scenarios.py.
Latest isolated Chrome run: 3 passed (existing AUTH-07 + both AUTH-08 viewports),
1 failed (HOME-01), 8 duplicate-playlist cases deselected. HOME-01 releases a captured
synthetic collection after logout; Music.user stays null and UI hides the collection,
but Music.refresh assigns stale private playlists back to Music.data. This is a
client-state invalidation bug, not verified cross-account exposure. Kept the test as
a normal failure; app code was not changed. Remaining playback assertions after the
failure were not reached. Native dialog focus may enter browser chrome; the focus
check correctly forbids background page controls, not browser UI.

Saved JUnit /tmp/radioworkx-adversarial-popup/report.xml and per-test trace.zip/final.png.
Fixture now mocks live/status/SSE, patches API Redis to the existing fake, and saves
artifacts via RWX_TEST_ARTIFACTS (defaults to the test's temporary directory). App and
Chrome run locally; only PostgreSQL runs in the disposable container. Future QA app
container remains pending. Updated scenario catalog/inventory: 88 contract/router
cases + 12 account cases = 100 listed. Only the four browser cases ran in this check.

## Shared playlists and listener following (2026-09-29)

Implemented opt-in sharing in `app/social.py` with four additive PostgreSQL tables:
`listener_profiles`, `shared_playlists`, `listener_follows`, `playlist_follows`.
Existing playlists stay private. My Music's Share playlist publishes a playlist to
`/playlists/{id}` and the owner's `/people/{id}` profile, with a copy-link action.
Public names are editable; fallback names use a short account ID, never email.
Public responses contain only public track metadata, owner ID/name and shared
playlists. Likes, email addresses and lists of followed people remain private.

Visitors can play shared tracks without signing in. Follow playlist opens the
existing authentication modal if necessary and saves a live reference in My Music
(on both home and standalone pages). Follower editing is disallowed. Owner changes
appear on collection reload; already playing queues remain snapshots. Follow
listener adds a profile link under Your public profile / Listeners you follow;
it does not auto-follow playlists or send notifications. Both follow limits are
100 and requests are idempotent. Make private and playlist deletion cascade-delete
playlist follows. Republishing does not restore follows. Following people is
independent. Public catalog recordings are still playable after playlist revocation;
this revokes playlist visibility, not recordings already loaded by a visitor.

`Music.refresh` now guards its combined collection/social responses with account
and request generations, preventing stale responses from restoring private browser
state after logout or replacing a newer refresh. Existing HOME-01 regression now
passes without changing the test. Preserved unrelated adversary work.

Verification: account/social API tests (6 passed), social tests including additive
migration (3 passed), existing opt-in auth/logout browser regressions (4 passed,
8 duplicate-name cases deselected), and expanded accounts_smoke passed. Chrome
smoke uses two isolated accounts to verify publish, anonymous playback, in-modal
registration to follow, listener following, owner-only editing, propagated rename,
and revocation, plus existing desktop/mobile home playback and collection tests.
Mobile shared page inspected; no JS errors. Test PostgreSQL container left running
because it was already present. No production test accounts/playlists were created.

For live rollout, `scripts/migrate_social.py` applies only new tables after checking
the previous schema digest, with 3-second lock and 15-second statement timeouts.
It records the new digest to avoid replaying unrelated schema DDL during rolling API
startup. Private `.deploy/social-migrate.py` supplies the existing ignored local
connection configuration. Migration applied successfully to the current Homebrew
PostgreSQL radioworkx database; no existing records changed. Normal rolling API
controller is used; station and other workers remain untouched, downloads remain
stopped and video generation stays disabled.

Rollout completed to `api`, image
`sha256:ac1bb00ac1ea80680dd43f41f56aafd4c5d97ca8781037e57e13ca0bd108d206`;
previous `api-next` drained and stopped. Public health, new routes, correct anonymous
404 messages, and mobile sign-in modal passed a read-only Chrome check with no JS
errors. Changes remain uncommitted, including the earlier modal/home feature.

## Social adversarial coverage completed (2026-09-29)

Implemented all SOC-01–SOC-12 families: 41 API cases in test_social_adversarial.py
and 13 Chrome cases in test_social_browser.py. Covers follow/revocation races,
republish semantics, concurrent quota boundaries, delayed follow/rerender, both
halves of delayed music/social refresh across logout/account switch/newer request,
owner-only mutations, disappearing follows mid-read, public-data canaries and inert
XSS markers, canceled/retried auth-to-follow, clipboard denial/repeated copy, every
social mutation's origin/header/revoked-session enforcement, and revocation on
fresh reads/history. Tests reuse the existing fixture with synthetic identities.

Found/fixed SOC-07: collection now omits a followed playlist revoked/deleted between
READ COMMITTED queries instead of returning 404 for the entire collection; non-404
errors still propagate. Found/fixed SOC-10: copy-link fallback now coalesces pending
clipboard operations and reuses one open dialog instead of stacking modals.
The accountEpoch/refreshEpoch guard already added by the social feature was preserved
and verified by six cases plus HOME-01; no duplicate implementation was introduced.

Consolidated affected-suite verification: 153 passed, 8 xfailed, no unexpected
failures. Includes all 54 new social cases, 88 router/domain cases, 12 account cases,
and seven existing account/social regression cases. The 8 expected failures are
PL-07 duplicate playlist names, still not fixed by this task. Node syntax checks and
git diff --check passed. Inventory now lists 154 adversarial cases plus seven existing
regressions used for verification. Report: /tmp/radioworkx-social/report.html and
report.xml; per-browser-case final.png/trace.zip under browser/<test-name>/.

Browser audio initially stayed at time zero with the host output sink. QA fixtures
now use silent (muted) synthetic 22.05 kHz WAV, with real media-clock progression
and pause/restart-event assertions. A trial host FFmpeg conversion was removed
because FFmpeg is only available in app containers; no new dependency was installed.
App and Chrome still run locally, PostgreSQL in the disposable test container.
No production state touched, no deployment/commit from this task. Existing social,
modal/home, schema and migration work was preserved. These two additional fixes
need the normal API/frontend deployment when requested.

## OpenAI custom and Browser Use framework (2026-09-29)

Implemented runnable `python -m adversary` / `adversary` CLI: run, replay, inspect,
list-runs and list-scenarios. Both the custom observe/candidate/decision loop and
native Browser Use 0.13.10 agent use the existing OpenAI key, selected from only
OPENAI_API_KEY/OPENAI_CHAT_MODEL in ignored .env or environment. No credentials
were copied into source, artifacts or browser/app environments. Custom uses strict
Responses candidate output; Browser Use uses its ChatOpenAI adapter with registered
qa_choose/qa_observe/done tools and all default tools disabled. Both use the shared
serialized DecisionService with atomic global call budget and no provider retries.
The existing Laya router remains separately tested; neither runner loads Laya or
implements the proposed hybrid model adapter. Do not describe the full phase
roadmap as complete.

New runtime modules create synthetic QA app subprocesses, ephemeral PostgreSQL
schemas, fake Redis/status/SSE and synthetic silent audio. `DEMO_MODE=1` requires
fixture metadata demo=True; v2 readiness checks now verify the artist is visible.
All browser requests are restricted to the exact per-session origin; live port8001
is forbidden. Custom agents share Chrome with isolated contexts; Browser Use gets
a temporary Playwright-launched process/profile and CDP attachment. Playwright
owns launching because pinned Browser Use ignores its profile.env when spawning.
This keeps service credentials out of Chrome; service workers are blocked up front.
App and browsers run locally; only PostgreSQL is containerized. No workers/live
DB/media/deployments touched. Test PostgreSQL was already running and remains up.

Action intents are fsynced before execution, followed by results, observations,
findings, final screenshot, trace.zip and JSON/HTML reports. Replay validates journals,
rejects unknown interrupted outcomes and incompatible fixture versions, remaps only
validated QA navigation, starts fresh data and uses Playwright without any model.
Finding reproduction requires matching fingerprints; a no-finding smoke replay is
not claimed as a reproduced bug. Status/exit codes distinguish findings, harness
errors, budget/time limits and completed exploration. Available goals: library
search, auth popup, duplicate playlists and social sharing. They do not replace
all existing deterministic adversarial regressions or assert all their invariants.

Installed dependencies only in ignored .venv-adversary, declared optional extras
in pyproject.toml and kept app/prod venv unchanged. Browser Use is pinned0.13.10;
verified Playwright1.63, OpenAI SDK2.26, Python3.13.3. pip check passes. runs/ ignored.
Read docs/adversary-framework.md for commands, policy/coverage limits and references;
docs/architecture.md now distinguishes runnable OpenAI paths from the Laya roadmap.
Historical current-playwright-architecture.md is labeled accordingly.

Final verification: 126 passed =119 framework tests (88existing +29runtime +2real
browser integration) +7existing account/social API regressions. JUnit:
runs/framework-tests.xml. Browser integration verifies two isolated simultaneous
fixtures, model-free replay, stale target rejection and blocked off-origin redirects.
Both live OpenAI engine smoke checks against fixturev2 completed library search
with three calls and four recorded actions each. Browser Use's actions replayed
with zero model calls. Artifacts: runs/framework-custom-verified/agent-0/,
runs/framework-browser-use-verified/agent-0/ and runs/framework-browser-use-replay/agent-0/.
Earlier smoke directories used fixturev1, whose seed was hidden by the demo filter;
those are historical and intentionally cannot replay asv2. Screenshot inspection
confirmed QA Artist search and the seeded result in the final Browser Use run.
No full model-driven social/auth scenario run or Laya verification claimed.

## Custom agent switched to local Laya (2026-09-30)

User clarified custom must use Laya, with OpenAI remaining only for Browser Use.
Implemented adversary/inference/laya.py (offline local backend, one shared model,
bounded100-request asyncio queue and one executor thread), download_laya.py
(explicit pinned five-artifact download, checksum manifest), custom CLI routing,
--laya-model/--device flags and custom-laya decision telemetry. CLI custom no longer
reads .env/OpenAI credentials; missing models fail with the download command, never
fall back. Each hierarchy inference (at most10choices) consumes the call budget.
Canceled results are discarded, native inference remains serialized and shutdown
waits for it while rejecting queued jobs. Model artifacts ignored under .models/.

Installed Laya0.3.21, torch2.14.1, transformers5.0.0, huggingface-hub1.4.1,
safetensors0.8.0 and numpy2.5.3 only in .venv-adversary; optional extra versions
pinned in pyproject.toml. Initial latest HF dependencies changed Click; pinned hub
and restored Browser Use's click8.3.3. Final pip check passes. English checkpoint
convaiinnovations/laya revision55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851 downloaded
successfully (~820MiB). No production dependency/runtime state changed.

Offline CPU load and prediction verified with socket.connect blocked plus HF and
Transformers offline modes. Cold load26.6s, inference1.5s, peak process RSS1.14GB.
MPS option exists but was not benchmarked. Upstream warns about calibration for
>10choices; adapter never submits that many choices. Answer confidence is model
probability, not browser-testing accuracy. Custom loads on demand per run, not a
persistent server. New tests verify hierarchy, thread serialization/nonblocking,
budgets, canceled requests, invalid labels, cache corruption, no OpenAI credential
access, bounded queue and shutdown. Combined framework + account/social regression
suite:136passed; runs/laya-tests.xml. Browser Use itself was not rerun with paid calls.

Actual browser quality is LIMITED: first CPU smoke and first two-agent run chose
Done immediately. These are historical runs/laya-custom-cpu and laya-custom-two-agents,
not successful searches. Added independent library-search completion checkpoint:
require successful q=QA Artist response containing QA Artist; custom excludes Done
until that checkpoint. Reports now expose goal_achieved and goal_not_met as needed.
Final two-agent run runs/laya-local-verified uses one model,24localcalls,7actions per
session (initial navigation +6reloads), both incomplete/step_limit, no findings,
goal_achieved false. Do not claim Laya completed the task or passed the adversarial
scenarios. Core integration works, but model action-selection quality needs tuning.
README, architecture, framework and Laya docs updated to distinguish these facts.

## Single-candidate selection fix and review pause (2026-09-30)

User authorized this fix first and explicitly forbade coordinated-session work
until reviewing a fresh report and approving. Do not resume coordinated sessions
or additional scenarios without that approval. No changes to either were made.
LayaDecisionService now resolves any sole candidate before budget reservation or
backend invocation, recording selection=deterministic/reason=sole_candidate with
no confidence or inference_ms. Multiple-option calls record selection=model.
Added sole-candidate zero-budget/no-backend and Reload-to-a14 one-call regressions;
adjusted hierarchy test to count only model stages. 129 passed,2browser tests
skipped. Fresh actual CPU run: runs/laya-single-candidate-fix, one agent,six steps,
six local calls (previously12), six direct resolutions, no single-option confidence.
Still incomplete: six reloads, search goal false; not claimed as a quality fix.
Review report: runs/laya-single-candidate-fix/review.html with stage table, actual
operation confidences, direct-selection labels and links to raw records/trace.
Historical reports preserved. No new hosted calls, scenarios or coordinated sessions.

## Full Laya choice probabilities recorded (2026-09-30)

User requested recording probabilities for remaining choices and a fresh report.
Scope remains paused for coordinated sessions/additional scenarios until approval.
LayaBackend returns the full upstream probabilities map; the service validates
choice membership, finite [0,1] values and rounded sum near1 before recording it.
Model stages retain probabilities plus selected-answer confidence; deterministic
single-candidate stages still have neither. Recorder renders ranked per-stage
probability tables above raw events; it does not fabricate missing historical data.
Tests cover actual backend extraction through JSONL/HTML and invalid distributions.
135passed,2opt-in browser tests skipped; runs/laya-probability-tests.xml.

Fresh actual local CPU run runs/laya-choice-probabilities: one agent,six modelcalls,
six deterministic resolutions, initial navigation plus six reloads; incomplete,
step_limit,goal_achieved false. Verified all recorded distributions have the exact
choice keys and selected probability agrees with answer_confidence. First decision:
click19.12%,fill14.00%,key_press8.31%,reload39.69%,wait9.93%,scroll8.96%.
Fresh readable report: runs/laya-choice-probabilities/review.html; session report
and raw actions.jsonl under agent-0. No hosted calls or scenario/session changes.

## Search-goal wording diagnostic (2026-09-30)

User asked what goal is sent, whether Laya infers it correctly, and for a simple-text/
paragraph-goal test. Added scripts/laya_goal_probe.py, a standalone CPU text diagnostic
using the current backend/choices and socket connections blocked. No browser,
production changes, goal configuration changes, coordinated sessions or added
application scenarios. Output: runs/laya-goal-wording/review.html, summary.json and
results.jsonl, including every exact input, choice and probability distribution.
Compared current/simple/paragraph goal wording under two fixed states (empty field
expects fill; QA Artist already filled expects click Search). State explicitly
includes field contents unlike the real browser prompt, so differences from older
browser runs cannot be attributed solely to goal wording. Seventh case uses the
paragraph as plain text, also changing input format. Expectations not sent as answer
labels. One prediction per case, not a reliability benchmark.
Results:0/7expected actions. Current goal selects reload for both states (.5481/.3810);
simple goal wait (.4615/.3377); paragraph wait (.5524/.6213). Plain-text paragraph
with empty field selects reload (.8147). Clearer wording did not fix selection.
Do not claim this proves internal understanding or identifies the root cause;
shows unreliable next-action selection in this configuration. Syntax/diff checks
and JSON evidence verification passed. Broader work remains paused for approval.

## Hosted Jev search-goal comparison (2026-09-30)

User supplied the exact Jev endpoint and authorized use of their ignored .env key
for the same troublesome scenarios. Added adversary/inference/jev.py and
scripts/jev_goal_probe.py, plus separate test_jev.py and test_jev_goal_probe.py
under tests/adversary (18 tests passed). The client uses only
https://jev-ai.pro/api/v1/systemone, accepts JEV_AI_API_KEY or legacy JEV_API_KEY,
and never follows redirects, retries or falls back to another provider. Errors
omit raw provider bodies and headers. Credentials are not copied to reports.

Fresh hosted run: runs/jev-goal-wording/review.html, summary.json, results.jsonl.
All seven calls completed; Jev selected expected fill/click in 7/7 cases versus
local Laya's 0/7 on exactly matching states/choices. Reports retain all choice
probabilities and distinguish selected_probability from provider_confidence.
Seven text-only inputs reuse the existing Laya diagnostic; no browser executed,
no production changes, no full browser-backend switch. Custom defaults remain
Laya. Coordinated sessions and broader scenario additions remain paused pending
user review. See docs/adversary-framework.md for repeat-run commands.

## Laya Browser default swap (2026-09-30)

User approved swapping the local model. Default download and service identity now
use cklxx/laya-browser v19s at 645cf366a2ae35f1086e8c20eff48f909bb49206.
Downloaded five checkpoint artifacts into ignored .models/laya-browser/<revision>;
existing base checkpoint remains untouched. Uses installed laya.Agent, no upstream
remote Python execution. Generic prompt/hierarchy retained to isolate the model
change; upstream model-specific decide adapter has NOT been integrated.

Fresh seven-case report runs/laya-browser-goal-wording/review.html: CPU inference
with socket connections blocked, 3/7 expected actions. Filled-field cases chose
click; empty-field cases chose key_press. Cold load ~8.5s. Previous Laya 0/7 and
Jev 7/7 reports preserved. Real isolated QA run runs/laya-browser-search/report.html:
incomplete/time_limit, initial navigation plus three clicks, last click TimeoutError,
six model calls. Did not enter search text or establish search completion. This is
not a successful browser test. Framework suite 153passed,2skipped; diff check passed.
No coordinated sessions or additional application scenarios; those remain paused.

## Home-page catalog search modal (2026-09-30)

User requested preserving Artists/Albums landing pages and adding a home Search
button opening a modal for artist/album/track fuzzy search. Added search.js/search.css
and GET /api/library/search (registered before dynamic library routes). Search runs
in PostgreSQL via pg_trgm similarity + word_similarity, with literal substring
matches, exact matches ranked first, deduplicated entities, max25 results and total.
Empty/whitespace query returns no results. Demo/live visibility stays separated.
Catalog metadata remains in existing tracks rows; no parallel search store to sync.
Schema now installs pg_trgm in public; deployment DB role needs database CREATE
privilege or an administrator must install it beforehand. Normal db.init applies
the schema update. This was implemented/tested locally, not deployed to production.

Modal uses native dialog focus/Escape handling, labeled type/text controls, 250ms
debounce, request abort/version guards, safe text rendering and clear no-match/error
states. Opening/searching/closing does not navigate or interrupt playback; selecting
an artist/album result navigates to its existing page. Track results open their album
page. Search scans the bounded catalog (currently capped at10k tracks); no trigram
index is added over the dynamically expanded artist arrays. Existing browsing routes
remain unchanged. New tests: tests/test_catalog_search.py and
tests/test_catalog_search_browser.py; browser artifacts runs/catalog-search-tests/.

Verification:17 API/library tests passed;2 real Chrome tests passed (desktop/mobile),
including continued live media playback. Mobile screenshot reviewed; JS syntax and
git diff checks passed. No live deployment or coordinated agent sessions performed.

## Search modal deployed (2026-09-30)

User authorized deployment. Applied pg_trgm in public and refreshed schema digest
with bounded lock/statement timeouts. Active image schema exactly matched the
pre-search source; DB marker was pre-social (older worker), social tables existed;
reapplied only idempotent additive social DDL plus extension, preserving records.
Rolling controller switched api -> api-next and drained/stopped old API. Active image
sha256:d3a7156d42edb6302cb77962d493f8e88b37fc04a0f6cabcb9487b2adf19b901.
Previous image retained for rollback; station/workers not restarted. Docker context
now excludes local model weights, adversary venv and reports.
Public Chrome verification passed: home modal initially empty, real artist query
returns its card, artist/album/track search endpoints HTTP200, close button and
Escape with empty input work. Chrome first clears a populated type=search field on
Escape; initial smoke expected immediate close and was corrected to native behavior.
Screenshot: runs/catalog-search-deploy/live-search.png. Proxy confirmed api-next;
no pending drain/switch state. No production accounts or playlists created.

## Adversarial search tests revised for home modal (2026-09-30)

library-search now starts at home, opens Search, chooses Artist and fills QA Artist.
Completion requires matching artist response plus visible modal result, current
query/type and home URL. Navigation during this goal produces search_navigation.
Dropdown options are now bounded SelectAction candidates; modal observations exclude
background controls. Scripted baseline updated to open/select/fill/done; recorded
navigation plus four actions. Frozen old seven-case text probe goal so historical
Jev/Laya comparisons remain reproducible instead of silently inheriting new workflow.

Added SEARCH-01..05 in docs/adversarial-scenarios.md and five adversarial browser
cases covering input attacks, type boundaries, stale query/type/close responses and
503 recovery. Search tests:19passed (12 API +7 Chrome including desktop/mobile
playback). Framework:154passed,2 opt-in tests skipped; coordinated sessions still
paused. Updated existing two-session test expectations but did not run that test.
Single scripted run completed with goal_achieved true and zero model calls; fresh
single-session replay also completed with goal_achieved true. No new Laya/Jev
browser evaluation or production deployment this turn.
Reports: runs/search-adversarial/review.html, runs/search-modal-scripted/report.html,
runs/search-modal-replay/report.html. JUnit: runs/search-adversarial/results.xml.

## Laya Browser run on home search modal (2026-09-30)

User requested running Laya after search revisions. One isolated custom CPU session,
six action-step limit,18 model-call budget,180s timeout. Report:
runs/laya-browser-search-modal/report.html (detailed agent-0/report.html).
Result incomplete/step_limit, goal_achieved false,12 local model calls, no findings.
After initial home navigation: open Search modal, click Search submit on empty input,
press Enter in Search text, click Search submit three more times. No fill action;
query remained empty. Seven recorded actions includes initial framework navigation.
No hosted calls, coordinated sessions, production mutations or code changes.

## Jev real browser search (2026-09-30)

User requested Jev run. Added explicit --decision-provider jev for custom engine;
Laya remains default. JevDecisionService reuses bounded Laya hierarchy/worker using
hosted backend, records correct custom-jev labels and provider metadata, preserves
sole-candidate bypass.34 adapter tests passed; diff check passed. Same six steps,
18-call cap,180s timeout and one isolated QA session as preceding Laya run.
Actual run runs/jev-search-modal/agent-0/report.html: open modal, select Artist,
fill QA Artist, then wait three times. Independent oracle verified visible matching
result: goal_achieved true. Agent did not select Done despite its availability in
last two requests; stopped at step_limit, status incomplete.10 hosted calls to
user-authorized jev-ai.pro endpoint. Not a fully completed agent run. No text-only
probe rerun, coordinated sessions, production mutations or deployment.

## Deterministic input assignments reviewed across scenarios (2026-10-01)

User asked to eliminate unnecessary model decisions over known test values. Added
Scenario.fills/selects assignments and applied them via coordinator to common browser
candidate builder (custom Laya/Jev and Browser Use). Each configured field gets one
assigned value; unknown fields get no speculative fill. Search kind fixed to artist;
known playlist label resolves observed option ID. Model still chooses actions and
ambiguous targets; existing sole_candidate selection skips inference with no fake
confidence. Input selection is no longer a field × all scenario values cross-product.
Exact/trimmed duplicate-name exploration split into independent scenario IDs; trimmed
variant uses existing duplicate oracle. Existing security and PL-07 deterministic
regressions continue to enumerate inputs independently, not random model coverage.

Added tests/adversary/test_input_bindings.py covering every scenario's mappings,
unknown fields, dropdown values, dynamic playlist IDs, separate duplicate cases and
zero-call deterministic selection. Framework suite164passed,2opt-in skipped. Single
scripted QA browser runs/search-deterministic-inputs completed,goal_achieved true,
zero model calls. No hosted model reruns, coordinated sessions or deployment.

## Laya/Jev runs with assigned search inputs (2026-10-01)

User requested both runs. Sequential independent single-agent QA browser sessions,
six action steps,18 model-call cap,180s timeout. Laya Browser:9 local calls; Jev:8
hosted calls to configured endpoint. Both goal_achieved true, incomplete/step_limit:
neither selected Finish. Laya actions: Enter on Playback volume, open Search, Enter
on empty Search text, fill QA Artist, Enter, select Artist. Jev: open Search, select
Artist, fill QA Artist, Enter, wait, wait. No application findings reported.
Smaller assigned-input candidate set fits modal decisions in one model call choosing
the concrete action; no redundant payload-selection calls or deterministic second
stages were recorded (0 deterministic stages for both). Values remain scenario-assigned.
One run per provider is not a reliability benchmark. No coordinated sessions or
production changes. Reports runs/laya-deterministic-search/agent-0/report.html and
runs/jev-deterministic-search/agent-0/report.html; side-by-side summary and exact action
lists runs/deterministic-search-comparison/review.html (+summary.json).

## Restore observed dropdown choices (2026-10-01)

User corrected deterministic input scope: all dropdown options observed on the page
must be offered to the model. Removed Scenario.selects and coordinator/select candidate
filtering. Search now offers Artist, Album, Track; playlist dropdowns preserve all
observed enabled labels and actual option IDs. Text input bindings remain deterministic
(e.g. QA Artist only, no competing XSS/empty payload). Shared candidate builder applies
to both custom providers and Browser Use. Existing disabled-option filtering remains.
Updated regression expectations for complete dropdown choices and unchanged assigned
text. Framework164passed,2opt-in skipped; diff check passed. No model reruns or deploy;
prior HTML reports remain historical and still show the previously restricted choices.

## Both models rerun with all dropdown options (2026-10-01)

User requested runs. Separate single-agent sessions, six steps,18 call cap,180s.
Laya runs/laya-all-options-search: goal_achieved true,incomplete/step_limit,10 calls.
Steps Enter volume,open Search,Enter empty search,fill QA Artist,select Artist,click Search.
Jev runs/jev-all-options-search: harness_error/JevError,6 calls attempted. Opened
Search,selected Artist,filled QA Artist; next inference failed. Existing exception
handling retained only JevError type, not safe error detail, so root cause unknown;
no automatic retry or false completion claim. Dropdown choices Artist/Album/Track
verified in recorded Jev stages. Original reports preserved. Comparison:
runs/all-options-search-comparison/review.html (+summary.json), linking both detailed
agent-0 reports. No coordinated sessions, production changes or model/text-probe edits.

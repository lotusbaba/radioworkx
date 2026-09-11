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
- Latest verified application tests: **115 passed** after app-token changes. Live admin token creation/hiding/revocation and desktop/mobile browser checks passed. Tests were not rerun for this documentation-only handoff.
- Last completed discussion: portfolio summary, SQLite location, and named-volume persistence. Latest implementation: admin-issued bearer tokens for calling apps. Details below.
- No known unfinished feature request at handoff. Live state changes; do not assume old track names, counters, or worker states remain current.
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

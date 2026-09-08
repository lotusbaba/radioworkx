# RadioWorkx session handoff

Saved 2026-09-08, America/Los_Angeles. This is a durable engineering handoff of the
available conversation context, decisions, and implemented work, not a verbatim
chat export or a backup of live databases/media. Never put API keys, passwords,
cookies, or raw private listener conversations in this document.

## Resume here

- Workspace: `/Users/bhaskarjayaraman/Library/Mobile Documents/com~apple~CloudDocs/Desktop/Practice-py/radioworkx`.
- GitHub: private repository https://github.com/lotusbaba/radioworkx ; branch `main`.
- Current public site: https://radioworkx.tail060b33.ts.net/ . No Tailscale client required for visitors.
- Admin: same origin, `/admin`; username `admin`, password stored locally in ignored `.admin-credentials` and `.env`.
- Latest application tests: **110 passed**. Public browser smoke with audio passed after the playback fix and hostname change.
- Last completed request before saving: explain why renaming MagicDNS required reapplying Funnel. The answer is below.
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

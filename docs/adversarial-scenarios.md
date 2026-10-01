# RadioWorkx adversarial and security scenarios

Scenario catalog, 2026-09-29. Scenarios are planned unless execution is explicitly
recorded below; they are not vulnerability findings. Read-only retrieval of
https://radioworkx.tail060b33.ts.net/ confirmed
My music, Artists, Albums, live playback/reactions, the RJ request line, upcoming,
history/download/community lists and statistics. Browser preview failed to attach;
authenticated UI behavior was not exercised. Account details below come from
app/accounts.py and app/static/account.html, account.js and music.js, not a claim
that the deployed backend was exercised.

The target architecture uses a separate QA app container, synthetic users A/B,
anonymous context and test-admin identity. Current executable browser cases use a
temporary local FastAPI server with disposable PostgreSQL schemas in the test
container; they do not yet run the app itself in a QA container. Seed synthetic audio and catalog, mock providers,
and isolate database, storage and queues. Preserve the live download pause. Restore
fixtures before replay. Reach quotas through fixture seeding, not request floods.

## Required workflows and oracles

| ID | Scenario | Expected outcome |
| --- | --- | --- |
| REG-01 | Register, refresh, revisit My music | One account; correct profile and persistent session. |
| REG-02 | Email whitespace/case, invalid format, 254/255 characters, null/wrong-type JSON | Normalization follows contract; controlled validation errors without partial accounts. |
| REG-03 | Password lengths 11/12/128/129, Unicode, bypass client validation | Backend enforces 12–128; no plaintext passwords in DB, responses, logs or recordings. |
| REG-04 | Concurrent registration with equivalent normalized emails | One account; controlled conflict, no duplicate identity or 500. |
| AUTH-01 | Valid/wrong/unknown credentials; logout; reuse old cookie | Generic invalid-login response; logged-out session rejected by private APIs. |
| AUTH-02 | New login with existing cookie; expired/tampered token; HTTPS | Session replacement/expiry enforced; HttpOnly/Secure/SameSite policy correct; no credentials in browser storage. |
| AUTH-03 | Seed near per-email/IP/global attempt limits; bounded concurrent attempts | Current 10/60/300 limits over 15 minutes enforced; forged forwarding headers cannot bypass limits; proxy aggregation reviewed. |
| AUTH-04 | Two tabs, logout in one, stale writes/back navigation/account switch | Revoked-session writes rejected; no old account data displayed as the new account's collection. |
| AUTH-05 | Missing custom header, foreign Origin, cross-site fetch/preflight | Mutation policy enforced; evaluate complete origin including scheme/host/port. Missing-Origin behavior follows explicit custom-header contract. |
| AUTH-06 | Profile caching and credential errors | Private responses use no-store; no secrets; registration conflict enumeration reviewed as policy rather than automatically marked vulnerable. |
| AUTH-07 | During synthetic audio playback, rapidly activate login/register, repeatedly switch forms, dismiss with Close/Escape and reopen. In a separate attempt, delay the QA authentication response, submit, then dismiss/reopen before releasing the response; repeat with a controlled failure response. | At most one authentication dialog exists. These sequences must not navigate away, reset the underlying page/scroll/input state, or stop/restart playback. Keyboard focus remains usable and returns to the trigger on dismissal. Late responses must not reopen a dismissed dialog, overwrite a newer form's input/errors, or trigger a redirect. Controls recover after failure. If a submitted request succeeds after dismissal, account UI reconciles with the server session without navigation; dismissing before submission creates no authentication request. |
| AUTH-08 | On desktop and mobile, repeatedly switch login/register while a synthetic track plays; refill the password each time, traverse focus with Tab, close and reopen | Clear passwords on every mode change and dismissal; issue no authentication requests until submission. Keep one modal, prevent focus reaching background page controls, restore trigger focus on dismissal, and preserve URL and audio without restart. Native browser-chrome focus is allowed. |
| PL-01 | Create/rename/add/remove/delete synthetic playlist; reload | Correct owned state persists; unrelated collections and likes unchanged; membership cleanup verified. |
| PL-02 | Empty/whitespace, name length 1/80/81, Unicode, harmless markup | Name validation enforced and accepted text safely rendered in tabs, forms and dialogs. |
| PL-03 | Seed 99/100 playlists and 499/500 members; concurrent final additions | Caps of 100 playlists/account and 500 tracks/playlist upheld atomically. |
| PL-04 | Duplicate add, repeat removal, rename/delete race, reordered responses | No duplicate membership or invalid order; controlled errors and UI convergence. Duplicate add at capacity needs explicit contract review: current code checks capacity before deduplication. |
| PL-05 | B supplies A's playlist ID to rename/delete/add/remove; anonymous direct API access | A's data unchanged; no private contents exposed; ownership required on every operation. |
| PL-06 | Cancel/Escape dialog, double Save, create succeeds but add fails | Cancel causes no write; controls recover; partial completion is visible. Creating playlists is not assumed idempotent without a defined contract. |
| PL-07 | A creates `Road trip`, then creates another with the same name or renames a different playlist to that name; repeat with surrounding whitespace and concurrent create/rename attempts through UI and API | Playlist names must be unique within an account after trimming surrounding whitespace. Reject collisions with a controlled conflict and clear UI message; preserve existing playlists and tracks, and enforce uniqueness atomically under concurrency. Renaming a playlist to its own name succeeds without duplication. B may independently use the same name. |
| HOME-01 | On the landing page, open a private playlist, hold an in-flight collection refresh, log out, then release the old response | Keep signed-out UI empty and user null; discard the stale collection rather than restoring it in client state. Preserve live playback and prevent personal playback from restarting. |
| HOME-02 | Switch from account A to B while A’s collection response is delayed; release A’s response after B signs in | Only B’s likes/playlists may appear or remain in client state; stale A responses cannot replace B’s collection. Planned follow-up, not executed. |
| HOME-03 | Start personal playlist preparation, switch to live, then release the delayed preparation response; rapidly alternate modes | Only the last selected playback mode remains active; canceled preparation cannot restart personal audio, and personal actions do not change the station-wide queue. Existing smoke coverage exercises one delayed preparation; repeated-mode variation remains planned. |
| LIKE-01 | Like/unlike from station, album/artist and My music; reload | Server collection and aria-pressed agree; repeated PUT gives one relation and repeated DELETE is harmless. |
| LIKE-02 | A/B like same track; rapid toggles/delayed responses | Independent collections; UI reflects final acknowledged state; no cross-user mutation. |
| LIKE-03 | Anonymous save, unknown ID, expiry during click | Sign-in guidance or controlled rejection; no orphan relation; buttons re-enable. |
| LIKE-04 | Save likes/add playlist tracks while checking station state | Personal collections do not create broadcast requests, reaction counts or acquisition work. Account likes and station emoji reactions remain distinct. |

PL-07 now has eight executable API cases in
[`test_account_scenarios.py`](../tests/test_account_scenarios.py): create, rename,
concurrent create and concurrent rename, each with exact and whitespace-padded names.
All eight reproduced duplicate acceptance against disposable PostgreSQL state and
are marked strict expected failures, not passes. They also check per-account name
scope, self-rename and preservation of the original playlist's membership. UI error
messaging remains untested. The create/rename handlers trim names but do not check
for duplicate names. Case-only
and Unicode-equivalent name matching remain an explicit policy decision; the scenario
above requires exact-name and surrounding-whitespace collision checks.

AUTH-07 targets repeated interactions and response-timing races. Its prerequisite
is the requested in-page authentication dialog, verified separately by a normal UI
regression test. If activation still navigates away, report that baseline requirement
as unmet and the dialog-specific adversarial checks as blocked, not passed. Use
bounded repetitions and QA-only response interception with synthetic identities/audio.
Dismissing a dialog does not guarantee cancellation of an already-submitted server
request. AUTH-07 now passes against the implemented popup: repeated activation,
Escape/focus restoration, a delayed login error, unchanged album state and uninterrupted
synthetic audio. Its obsolete expected-failure marker has been removed.
AUTH-08 also passes in desktop and mobile viewports. Late successful authentication,
full scroll/input preservation and other source pages remain follow-ups.

HOME-01 originally exposed stale private client state after logout. The social feature
now includes account/request-generation guards in `Music.refresh()`; the original
regression and the six SOC-05 delayed-response variants verify that guard. Current
verification results and saved reports are recorded with the social coverage below.

Run the account scenarios (12 collected cases) with the disposable database:

```sh
docker compose -f compose.test.yaml up -d --wait
TEST_DATABASE_URL=postgresql://radioworkx_test:local-test-only@127.0.0.1:55432/radioworkx_test \
RWX_BROWSER_TESTS=1 RWX_TEST_ARTIFACTS=/tmp/radioworkx-adversarial-popup \
.venv/bin/python -m pytest tests/test_account_scenarios.py -q -ra \
  --junitxml=/tmp/radioworkx-adversarial-popup/report.xml
```

The browser cases require installed Playwright and Chrome; without
`RWX_BROWSER_TESTS=1` they are explicitly skipped. These tests reuse the existing app and
disposable database fixture; the browser uses synthetic audio and blocks requests
outside its temporary QA origin. Expected-failure markers match only the specific
known gap exceptions, so unrelated errors still fail. Remove the markers when fixing
the app; an unexpected pass fails the test run. Add `--runxfail` to see the gaps as
ordinary failures. Social fixes accompanying this coverage are listed below.

## Social feature: adversarial scenarios

Source inspection covers `app/social.py`, `app/static/social.js` and
`app/static/shared-page.js`. Existing `tests/test_social.py` already checks basic
sharing privacy, ownership, repeated follows, self-follow rejection, profile-name
validation, origin protection, revocation and deletion cleanup. The additions below have executable coverage in `tests/test_social_adversarial.py`
and `tests/test_social_browser.py`. They use synthetic owners/followers and guests,
with bounded concurrent requests and explicit delayed-response barriers.

| ID | Adversarial sequence | Expected outcome / oracle |
| --- | --- | --- |
| SOC-01 | C follows A's shared playlist while A makes it private; repeat with deletion | After both requests finish, public reads return 404, C's next collection read contains no playlist follow, and no dangling follow row remains. A follow may succeed before revocation or return a controlled rejection after it; neither ordering should produce a 500. |
| SOC-02 | Repeatedly share/unshare the same playlist, then republish it after C previously followed it | Shared/private state agrees with the final completed operation. Unsharing removes playlist follows; republishing never silently restores them. Listener follows remain separate and unchanged. |
| SOC-03 | Seed C with 99 followed listeners or playlists, then concurrently follow two distinct valid targets; repeat a follow already present when at 100 | Exactly one new target fits under the cap of 100. Repeating an existing follow succeeds without another row or a limit error. Exercise both follow types with bounded concurrent requests. |
| SOC-04 | Rapidly double-click Follow/Unfollow, delay a response, and rerender the profile or playlist while it is pending | No duplicate follow rows, stuck controls or misleading final button state. After pending work settles, displayed state agrees with C's server-side collection; controls from an old render cannot mutate a different target. |
| SOC-05 | Hold A's `/api/me/social` response, log out or sign in as B, then release it; also reverse completion order of two collection refreshes | Old profile, shared IDs, followed listeners and followed playlists must not repopulate client state or B's UI. A result is applied only to the current account and current refresh. Test both halves of the combined music/social refresh. |
| SOC-06 | C follows A's playlist, then tries rename, track add/remove, delete and sharing changes using A's ID; repeat as guest and with revoked session | Following grants read/follow access only. Ownership and authentication checks reject writes, and A's playlist/memberships/sharing state remain unchanged. Use fixture snapshots to verify effects, not status codes alone. |
| SOC-07 | C reads their social collection while A unshares or deletes one of its followed playlists | A consistent collection or a refreshed collection omitting the unavailable playlist; one disappearing item must not turn the entire collection into a 404/500. Reproduce the select-follow-ID/read-playlist interleaving deterministically. |
| SOC-08 | A uses a public display name or playlist name containing harmless HTML/script execution markers; visit the profile, shared playlist, follower collection and clipboard fallback | Names render as text without marker execution or unexpected requests. Public responses expose only intended public profile/playlist fields, never email, private likes, private playlist canaries, source credentials or audio filesystem paths. |
| SOC-09 | On a shared page, click Follow while signed out, cancel authentication, then retry and complete it; repeat activation while the popup is open | Cancel creates no follow. Completion performs the intended follow for the signed-in identity once; one auth dialog is open, page/playback persists, and controls recover after cancellation or failure. |
| SOC-10 | Deny clipboard permission while sharing, repeatedly activate copy-link, close/reopen the fallback dialog, then make the playlist private | Fallback shows the correct same-origin link, closes cleanly and cannot leave stacked dialogs or unintended repeated sharing writes. Fresh access after revocation fails. Clipboard failure must not be confused with a failed share operation. |
| SOC-11 | Send mutation requests without the required request header, with a foreign Origin, or after logout to every social write endpoint | Profile edits, share/unshare and both follow/unfollow types reject unauthorized requests without changing fixture state. Public read access does not imply mutation permission. |
| SOC-12 | Open a shared playlist, then revoke sharing in another context and refresh, revisit via history, or attempt Follow | Fresh API requests enforce private state and return no playlist content. Already-delivered data cannot be retracted; define an explicit UI refresh/revalidation rule before asserting immediate removal from an already-open page. Revocation does not revoke independent public catalog/audio access. |

### Social implementation and verification

All 12 scenario families now map to executable tests (41 API cases + 13 browser
cases). The browser tests reuse the actual application, a temporary local server,
isolated Chrome contexts and disposable PostgreSQL schemas. PostgreSQL runs in the
test container; the application/browser do not yet run in a QA app container.
External browser requests are blocked; synthetic audio is muted while its real
media clock and interruption events are checked. No real media is downloaded.

| Scenario | Test function(s) | Cases |
| --- | --- | --- |
| SOC-01 | `test_soc01_follow_races_with_revocation` | 2 |
| SOC-02 | `test_soc02_republish_does_not_resubscribe_or_remove_listener_follow` | 1 |
| SOC-03 | `test_soc03_concurrent_last_slot_and_idempotency_at_limit` | 2 |
| SOC-04 | `test_soc04_duplicate_follow_and_old_button_after_rerender` | 2 |
| SOC-05 | `test_soc05_old_responses_cannot_restore_account_or_refresh_state` | 6 |
| SOC-06 | `test_soc06_following_never_grants_owner_mutations` | 12 |
| SOC-07 | `test_soc07_disappearing_follow_does_not_fail_collection` | 2 |
| SOC-08 | `test_soc08_public_payloads_exclude_private_canaries`, `test_soc08_names_render_as_text_in_public_and_follower_views` | 2 |
| SOC-09 | `test_soc09_cancel_then_authenticate_follow_during_playback` | 1 |
| SOC-10 | `test_soc10_clipboard_denial_single_fallback_and_revocation` | 1 |
| SOC-11 | `test_soc11_all_social_mutations_enforce_request_and_session_rules` | 21 |
| SOC-12 | `test_soc12_revoked_shared_page_rejects_follow_and_fresh_reads` | 2 |

Consolidated verification: **153 passed, 8 expected failures, 0 unexpected failures**.
All **54 new social cases passed**. The run also covered 88 contract/router cases,
12 account scenario cases and seven existing account/social regression tests.
Saved HTML report: `/tmp/radioworkx-social/report.html`; JUnit:
`/tmp/radioworkx-social/report.xml`. JavaScript syntax and `git diff --check` passed.

Two defects were reproduced and fixed in the workspace:

- SOC-07: a revoked/deleted followed playlist between reads caused a 404 for the
  entire social collection. Collection loading now omits items that disappear,
  while propagating errors other than not-found.
- SOC-10: repeated copy-link activation after clipboard denial stacked fallback
  dialogs. Copy operations now coalesce while pending and reuse the open dialog.

The account/request-generation stale-response fix already present in the social
feature is preserved and covered by SOC-05. SOC-12 verifies fresh reads, reload,
history navigation and attempted follow after revocation; it does not claim to erase
already-delivered data or instantly remove it from an untouched open page.

```sh
TEST_DATABASE_URL=postgresql://radioworkx_test:local-test-only@127.0.0.1:55432/radioworkx_test \
RWX_BROWSER_TESTS=1 RWX_TEST_ARTIFACTS=/tmp/radioworkx-social/browser \
.venv/bin/python -m pytest tests/test_social_adversarial.py tests/test_social_browser.py \
  tests/test_social.py tests/test_accounts.py tests/test_account_scenarios.py tests/adversary \
  -q -ra --junitxml=/tmp/radioworkx-social/report.xml
```

Browser screenshots and Playwright traces are stored beneath
`/tmp/radioworkx-social/browser/<test-name>/`. Reports and artifacts contain only QA
fixture data but stay outside source control. The duplicate-playlist-name PL-07
requirements remain separate known expected failures; these social changes do not
implement name uniqueness. No deployment is included in this verification work.

## Security cases tied to actual inputs

- Stored XSS: synthetic playlist names in tabs, rename controls and playlist dialog;
  revisit in a fresh authenticated context. Require unique harmless execution-marker
  evidence; merely reflected markup is not proof. Test admin rendering only where
  those records actually appear.
- Reflected/DOM XSS: search display, validation errors, catalog labels and mocked
  chat replies. Catalog payloads come from isolated fixtures, not live imports.
  Harness instrumentation must never itself evaluate the injected string.
- SQL injection: login/registration email, playlist names/IDs, track IDs and search/
  filter parameters. Compare curated quotation/boolean probes with fixed baseline
  records and permissions. Confirm semantic or ownership violations, not merely 500s.
  No extraction, destructive statements, commands or delay payloads.
- Access matrix: anonymous, account A/B, test admin and revoked app tokens. Listener
  cookies, account sessions and admin Basic credentials are separate mechanisms;
  test their privilege boundaries explicitly.
- Leakage: seed private canaries and check public community lists, stats, telemetry,
  error bodies and headers. Store credential references, not raw credentials, in
  recordings. Traces/screenshots remain private QA artifacts.

## Additional public-station coverage

| ID | Sequence | Invariant |
| --- | --- | --- |
| CHAT-01 | Empty/300/301 characters; double submit; mood selection after reload; cancel then confirm | Backend limits and per-listener pending state hold; idempotency key prevents duplicate work; provider mocked. |
| CHAT-02 | Parallel A/B chat and public queue inspection | No private messages or raw identity in shared summaries. |
| REACT-01 | Rapid emoji, stale broadcast ID, unknown emoji, threshold race | Cooldown/validation/idempotency hold; one threshold job in QA outbox, no real downloading. |
| PLAY-01 | Tune in/out, blocked autoplay, transport failure/reconnect | Stop cancels retries; no leaked stream loops. Define expected live/personal player exclusivity before gating it. |
| PLAY-02 | Play all/Next/Stop, final/unavailable item, playlist deleted during playback, logout | Defined queue progression, graceful errors, bounded preparation polling and no external acquisition. |
| LIB-01 | Existing Artists/Albums landing pages, nonexistent deep link, back/forward | Browse pages remain available; clear not-found states. Home search uses the modal scenarios below. |
| SEARCH-01 | From home, open Search; select Artist/Album/Track and enter a misspelled name; clear input | PostgreSQL fuzzy results match the selected type. No initial/blank-query cards; clearing removes results. Existing landing pages remain unchanged. |
| SEARCH-02 | Whitespace, SQL-like input, `%`, `_`, harmless markup; switch type while text remains | No catalog-wide wildcard expansion, script execution or cross-type stale cards; clear empty states. |
| SEARCH-03 | Hold an old search response, then change query/type or close/reopen; release old response | Late results cannot replace newer results or restore cards in a reopened empty modal. |
| SEARCH-04 | Return HTTP503 during search, then restore the endpoint and retry | Visible controlled error; retry succeeds without reload or stuck controls. |
| SEARCH-05 | Search all types during playback on desktop/mobile, clear input, dismiss with Escape | URL unchanged; audio clock continues; focus returns to Search. With populated native search input, first Escape may clear input and next dismisses. |

| MEDIA-01 | Synthetic audio ranges, invalid ranges/IDs, path-like IDs | Correct content or controlled 4xx; no access outside audio directory. |
| LIST-01 | Page 2 during SSE refresh, shrinking last page, rapid statistics periods | Independent page state retained or safely clamped; late response cannot overwrite newer selection. |
| VISUAL-01 | Broken/missing artwork/video, reduced motion, pause | Usable fallback; audio unaffected; motion preference honored. |
| ADMIN-01 | Anonymous/account access to admin assets/APIs and invalid/revoked app tokens | No privilege escalation; protected resources denied. |
| TELEMETRY-01 | Invalid/bounded oversized batches, forged session IDs, unknown fields | Validation/sanitization and identity rules hold; private canaries absent from events. |


Search coverage: `tests/test_catalog_search.py` covers PostgreSQL matching, query
boundaries, privacy and existing pages. `tests/test_catalog_search_browser.py`
covers SEARCH-01/05 in desktop/mobile Chrome. `tests/test_catalog_search_adversarial.py`
covers SEARCH-02/03/04 with controlled response ordering and failures. These are
deterministic checks, separate from model exploration and the seven historical
text-only model probes. Browser tests require `RWX_BROWSER_TESTS=1` and disposable
`TEST_DATABASE_URL`; artifacts are in `runs/search-adversarial/`.

The agent scenario `library-search` now starts at `/`, opens Search, chooses Artist,
enters QA Artist and stays on home. Completion requires a successful artist search
response and a visible matching modal result with the current query/type. Merely
clicking a pre-existing artist card or receiving a model “done” answer is insufficient.
The scripted version is a baseline qualification check, not adversarial exploration.

Scenario inputs are assigned deterministically per observed field label. Search
assigns `QA Artist` as the text value; all observed dropdown options remain available
for model selection according to the goal. Blank/XSS inputs run in their separate
deterministic regressions, not as competing model choices. Authentication assigns
email and password to their own fields. Playlist/social scenarios assign their
playlist names to playlist fields. Exact and whitespace duplicate cases have separate
agent scenario IDs (`playlist-duplicate`, `playlist-duplicate-trimmed`); the existing
PL-07 parameterized regressions remain the coverage gate for both variants.
Unknown text fields receive no speculative values. The model may still choose
which action/target to use; one remaining candidate is resolved without inference.

Inject network failures through QA-only route interception, never live outages.
Starting scenarios include anonymous_registration, signed_in_music_A/B,
playlist_near_capacity, account_near_rate_limit, artists_search,
mocked_station_playback and test_admin. Strategy and scenario are independent.
Cross-identity checks use coordinator-owned fixtures and explicit observations.

Prioritize deterministic registration/login/logout, playlists, likes and ownership
checks, followed by security oracles and autonomous variations. Phase 1 defines
contracts; Phase 2 supplies the isolated container/fixtures; Phases 3–6 prove
execution/recording/replay/detection; Phase 8 adds strategy-driven exploration.
Report coverage, confirmed/suspected findings and reproduction separately. Missing
paths or unspecified policy are not applicable/pending, never silently counted as pass.

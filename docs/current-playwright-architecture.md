# Current Playwright architecture

Phase 0 inspection, 2026-09-28. This describes repository evidence, not a browser
test run. See [proposed architecture](architecture.md).

## Inventory

RadioWorkx is Python >=3.11. The local environment is Python 3.13.3 with Playwright
1.62.0, pytest 8.4.2 and Pydantic 2.13.5. Playwright is installed locally but is not
declared in pyproject.toml or requirements.lock. There is no playwright.config file,
Node Playwright runner, pytest-playwright fixture layer, page-object library,
storage-state file, setup/teardown project or shared browser lifecycle helper.

| Existing entry point | Conventions and effects |
| --- | --- |
| scripts/browser_smoke.py | Sync Python; --url/RADIO_URL; desktop/mobile; optional admin, chat, reactions and audio checks. Default run mutates application state. |
| scripts/library_smoke.py | Artist/album navigation and cached personal playback; --prepare acquires music. |
| scripts/telemetry_smoke.py | Personal playback and analytics checks; uses live data and admin credentials. |
| scripts/opensearch_smoke.py | Public page activity plus local analytics; emits real telemetry. |
| scripts/kibana_smoke.py | Dashboard screenshots. |
| scripts/deployment_smoke.py | Performs an actual API deployment; unsuitable as exploration setup. |
| scripts/integration_smoke.py | HTTP demo check, not Playwright; creates reactions. |

Browser scripts launch installed Chrome using `chromium.launch(channel='chrome')`.
They create Pages/Contexts directly, run at module import, and should not be imported
as libraries. Existing tests remain unchanged. Reuse their selectors and workflows
through thin scenario helpers, without executing the scripts as exploration fixtures.

## Authentication, selectors and artifacts

Listener pages establish signed HTTP-only cookies. Admin scripts create contexts
with HTTP Basic credentials read from ignored .env. No storage_state reuse was found;
authenticated scenarios will need explicit setup, with secrets excluded from artifacts.
Existing tests use roles/names, text, and stable CSS IDs/classes. No configured custom
test-ID attribute or data-testid usage was found. Prefer roles/labels where unique;
record CSS fallback and resolve ambiguity explicitly rather than selecting first.

Desktop viewports commonly use 1440px width; mobile uses 390x844. Screenshots are
written beneath /tmp. No trace/video setup was found. Assertions are ordinary Python
asserts and Playwright waits, not @playwright/test assertions. Timeout values vary
by operation (including long playback waits); there is no central timeout config.
Some scripts use networkidle; the discovery layer should use domcontentloaded plus
explicit readiness because the station has long-lived audio and SSE connections.

## Existing test data and application startup

tests/conftest.py supplies an autouse isolated fixture: temporary SQLite DATA and
fakeredis, plus metadata/playing fixtures. These monkeypatches affect pytest's
process only, not a separately launched server. Keep this unit suite in place and
place new tests under tests/adversary. Fake-driver tests should require no browser,
model or network. Reuse app/db setup and metadata helpers for isolated browser
integration where practical; never point those writes at the live volume.

Compose currently provides the real application with SQLite, Redis and LocalStack;
the managed live proxy is localhost:8001. A localhost URL is therefore not evidence
of a disposable environment. Downloads were intentionally stopped on 2026-09-28;
do not start them as test setup.

The first scenario should browse the actual /artists page with a seeded disposable
RadioWorkx instance on port 8011, fill search, submit search and navigate back/reload.
Use the existing FastAPI app with test-only dependency wiring derived from the
fixtures; disable providers and background acquisition. Verify its required Redis
calls work through the isolated fixture before claiming that server needs no services.
Later full-stack tests can use explicitly separate Compose volumes/ports. The
testing tool itself has no Redis or cloud dependency; the target application's
requirements are separate.

## Verified Playwright approach

Use the installed Python package's async API for the coordinator, one browser and
one context per active agent. Inject existing async Page/Context objects into the
adapter; synchronous objects from current scripts cannot be passed into this loop.
No second runner or TypeScript framework is needed.

BrowserContext.new_page and browser.new_context provide isolation. Attach listeners
before scenario navigation, covering new pages as well as the initial page. Observe
response status for HTTP 5xx; requestfailed captures transport failures, not HTTP
error responses. Capture console errors, pageerror, crash, dialogs and action
timeouts separately. Attribute harness errors separately from application failures.

Start context tracing with screenshots/snapshots/sources and stop to a zip before
closing the context. Screenshots can be failure-only; traces have their own capture
policy. A trace is diagnostic, not the replay input. Finalize artifacts in finally
blocks; forced process termination may prevent trace finalization.

Primary references:

- https://playwright.dev/python/docs/api/class-browsercontext
- https://playwright.dev/python/docs/api/class-page
- https://playwright.dev/python/docs/api/class-tracing

Future generated regressions should be Python and match local assertion/selector
style. Because there is no browser fixture today, introduce only a small reusable
fixture/helper when required, rather than assuming one already exists.

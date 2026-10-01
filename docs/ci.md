# Continuous integration

GitHub Actions runs `.github/workflows/tests.yml` for pull requests, pushes to `main`,
and manual dispatch. Its four independent jobs use Python 3.13, locked application
dependencies and disposable PostgreSQL 13 service containers. Browser jobs install
Playwright 1.62.0, verify the runner’s Chrome can launch, and install Chrome if needed. The database-wide `pg_trgm` extension is provisioned
once before concurrent QA sessions create their isolated schemas, avoiding a cold-start
extension-creation race. No live API keys or production connections are configured.

| Job | Coverage | Evidence artifact |
| --- | --- | --- |
| application | Application unit/API tests, social permission/race tests, duplicate-playlist requirements | tests-application |
| agent-framework | Mocked Laya/Jev/OpenAI routing and contracts, isolated search goals, replay and coordinated social sessions (`RWX_FRAMEWORK_TESTS=1`) | tests-agent-framework |
| adversarial-browser | Authentication popups, account switching, social stale-state/race cases, modal/fuzzy search (`RWX_BROWSER_TESTS=1`) | tests-adversarial-browser |
| isolated-smoke | Account/social UI and playback transition scripts using temporary accounts/catalog and synthetic audio | tests-isolated-smoke |

Pytest jobs publish JUnit XML. Browser regression fixtures save screenshots and traces;
framework temporary run directories preserve their reports/traces. Smoke jobs publish
console logs and account screenshots. Artifacts upload even on failure and are retained
for 14 days. Shell pipefail ensures smoke failures cannot be hidden by log capture.

The application job deliberately leaves four browser-only account cases to the browser
job. Existing duplicate-playlist requirement gaps remain **strict expected failures**,
not passing requirements; pytest reports them with `-ra` and JUnit records them as skipped.
Do not remove or weaken these expectations to make CI green.

The separate `architecture.yml` workflow runs Polish baselines and the intentional
buffering regression; see [architecture checks](../architecture/README.md).

Live Laya/Jev/OpenAI exploration and deployment/infrastructure smoke scripts are not
part of these automatic jobs. They require separate opt-in runs with bounded model
calls or a disposable deployment stack. These workflows do not deploy the application
or run smoke scripts against the public station. Branch protection is not modified;
requiring these checks before merging is a separate repository setting.

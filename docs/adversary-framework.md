# Running the agent test framework

Both engines are implemented with separate decision backends:

- `custom`: our observe → candidate builder → shared DecisionService → validated
  action loop. A single local Laya model chooses concrete candidates. No OpenAI key
  is read and there is no hosted fallback.
- `browser-use`: the native Browser Use 0.13.10 agent and its OpenAI chat model
  adapter. Registered QA tools execute the same closed actions through Playwright.
  Its default navigation, JavaScript, file, shell, search and tab tools are disabled.
- `scripted`: a deterministic library-search smoke sequence; no model or key.

Browser Use owns its agent loop. It is not a browser driver below another agent.
Custom sessions share a bounded queue and one inference thread/model. Browser Use
retains its serialized OpenAI service. The pure Laya/LLM router remains a separate
contract for the future Browser Use hybrid path; custom now calls local Laya directly.
Model-generated code is never evaluated.

## Install and run

Keep the optional Browser Use dependency tree separate from the application venv:

```sh
.venv/bin/python -m venv .venv-adversary
.venv-adversary/bin/python -m pip install -e '.[adversary,browser-use,laya,test]'
docker compose -f compose.test.yaml up -d --wait

# One-time pinned checkpoint download (~820 MiB), stored under ignored .models/.
.venv-adversary/bin/python -m adversary.inference.download_laya

# Custom uses only the local model. Browser Use reads the existing OpenAI key.
.venv-adversary/bin/python -m adversary run --engine custom --max-steps 12 --max-model-calls 12
.venv-adversary/bin/python -m adversary run --engine browser-use --max-steps 12 --max-model-calls 12

# Show Chrome while running, or verify the plumbing without paid model calls.
.venv-adversary/bin/python -m adversary run --engine custom --headed
.venv-adversary/bin/python -m adversary run --engine scripted --agents 2 --max-steps 5
```

Installed Google Chrome is the default. `--channel chromium` uses a Playwright
Chromium installation instead (`python -m playwright install chromium`).
`--model` overrides only Browser Use's OpenAI model; account access is required.
Custom uses `--laya-model <local-directory>` and `--device cpu` (default) or `mps`.
A pinned, complete manifest and matching file checksums are required before loading.
Missing/corrupt artifacts fail; inference never downloads a replacement. CPU is the
verified device; MPS is an optional explicitly selected path, not benchmarked here.
The API key is read into the inference service, never written to reports or passed
to browser pages. Only Browser Use sends synthetic QA page state to OpenAI; custom decisions stay local. No Browser Use
cloud key is needed; cloud sync, telemetry and extensions are disabled.

The default database URL is the disposable `compose.test.yaml` service on port
55432. `TEST_DATABASE_URL` can explicitly select another **disposable** PostgreSQL
server. Every session creates a new random schema and removes it on graceful exit.
Do not point that variable at a production server. Forced process termination can
leave its temporary schema behind; no automatic bulk schema deletion is performed.

**Where it runs:** the QA FastAPI app and Chrome run locally; PostgreSQL runs in
the test container. Each session starts a fresh app subprocess on a random loopback
port, with a synthetic track, silent audio and fake Redis/status/SSE. No app
container, production application, station workers, download providers or live
volumes are started or modified. App-container isolation remains future work.
There is deliberately no arbitrary `--url` or live target option.

Custom sessions share one Chromium process with separate browser contexts; each
Browser Use session gets a fresh temporary Chromium profile/process, controlled
by Playwright and attached to Browser Use over CDP. All target requests are restricted
to that session's exact origin, including port. Service workers, external redirects,
WebSockets and downloads are blocked. This is a QA guardrail, not an OS/network sandbox.

## Scenarios and budgets

```sh
.venv-adversary/bin/python -m adversary list-scenarios
.venv-adversary/bin/python -m adversary run --engine custom --scenario auth-popup
.venv-adversary/bin/python -m adversary run --engine browser-use --scenario playlist-duplicate --max-steps 30 --max-model-calls 30 --timeout 600
.venv-adversary/bin/python -m adversary run --engine custom --scenario social-sharing --max-steps 30 --max-model-calls 30 --timeout 600
```

These goals and their explicit input variants are exploration entry points, not a conversion of all 154 cataloged
regression cases into agent tasks. The API/browser regressions remain in pytest.
Agents may not finish a goal within a small budget. Actions and input payloads are
bounded; generic complex widgets, arbitrary generated input and multi-account social
orchestration are not yet supported. Available candidates cover visible clicks,
synthetic fills, Enter, reload, wait, scroll and finish. The executor also supports
other closed action contracts for future builders and replay.

`--agents` permits 1–4 simultaneous sessions with independent app/database/browser
state. `--max-model-calls` is a **total across all sessions**, reserved before dispatch,
including failed requests. Local Laya uses at most ten choices per inference;
operation/target/group selection may require multiple calls per browser action and
each consumes budget. The queue holds at most 100 waiting requests, with a single
executor thread keeping native inference off the asyncio/browser loop. Cancellation
discards an expired caller's result but does not interrupt native inference; shutdown
waits for the active call and rejects queued requests. No hosted fallback exists.
Browser Use's OpenAI retries are disabled and output is capped at 1,024 tokens per
call; its call limit is not a dollar-cost guarantee. `--max-steps` bounds agent iterations; the separate
executor budget includes initial navigation. `--timeout` bounds session work.

Deterministic oracles record uncaught page errors, crashes, same-origin HTTP 5xx,
a synthetic XSS marker, authentication navigation and duplicate trimmed playlist
names within one account. A model's completion/success message is not a test oracle. Library search additionally
requires observing the successful `q=QA Artist` catalog response containing QA Artist;
custom cannot choose Done before that checkpoint. Reports expose `goal_achieved`
and mark early model completion as `goal_not_met`, not a completed test.
Playback continuity, ownership, quota and race requirements are covered by the
existing deterministic tests, not asserted by these generic exploration oracles.

## Results and replay

Every run is saved under ignored `runs/<run-id>/`, or the new directory supplied
with `--output`. Existing directories are never overwritten. The root has
`summary.json` and `report.html`; each `agent-N/` has:

- `actions.jsonl`: observations, decisions, flushed pre-action intents, results,
  findings and termination. In-flight actions retain their unknown outcome.
- `summary.json` and `report.html`: actual termination and oracle findings.
- `trace.zip` and `final.png`: browser evidence. A trace is not a replay script.

```sh
.venv-adversary/bin/python -m adversary list-runs
.venv-adversary/bin/python -m adversary inspect runs/<run-id>
.venv-adversary/bin/python -m adversary replay runs/<run-id>/agent-0
.venv-adversary/bin/python -m playwright show-trace runs/<run-id>/agent-0/trace.zip
```

Replay validates the journal/fixture version, rejects interrupted or corrupt action
sequences, starts a clean fixture, remaps recorded navigation to its new origin and
executes the saved concrete actions using Playwright. Neither engine nor OpenAI is
called. Locator ambiguity/missing targets are errors. Replay reruns the same oracles;
`REPRODUCED` requires the original finding fingerprints. A successful replay of a
run without findings is `COMPLETED_NO_ORIGINAL_FINDING`, not a reproduced bug.
Timing-dependent failures can fail to reproduce; no automatic minimization or
regression-test generation is implemented yet.

Session statuses: `no_findings`, `findings`, `incomplete` (budget/time limit) and
`harness_error`. No findings means only that these oracles found nothing during
this exploration. CLI exits: 0 completed without findings; 1 findings; 2 harness
error; 3 incomplete exploration or a finding that did not reproduce.

## Verification

```sh
# No API key, network, browser or database required (browser cases skip).
.venv-adversary/bin/python -m pytest tests/adversary --confcutdir=tests/adversary -q

# Includes real Chrome, two parallel app fixtures, replay, stale-target and
# cross-origin/redirect checks. Uses the disposable PostgreSQL container.
RWX_FRAMEWORK_TESTS=1 .venv-adversary/bin/python -m pytest tests/adversary --confcutdir=tests/adversary -q --junitxml=runs/framework-tests.xml
```

Verified 2026-09-29: 119 framework cases passed including two browser integration
cases. Both OpenAI engines completed library search with three model calls each
against fixture v2. Browser Use's four recorded actions replayed using Playwright
with zero model calls. These are framework smoke checks, not full adversarial
scenario coverage. See `runs/framework-custom-verified/agent-0/report.html`,
`runs/framework-browser-use-verified/agent-0/report.html` and
`runs/framework-browser-use-replay/agent-0/report.html` locally.

Implementation references: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Browser Use custom tools](https://docs.browser-use.com/open-source/customize/tools/add),
[Browser Use agent parameters](https://docs.browser-use.com/open-source/customize/agent/all-parameters).
The pinned installed Browser Use source was also checked for lifecycle/tool behavior.

## Local Laya verification (2026-09-30)

Custom now uses Laya 0.3.21 and English checkpoint revision
`55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`. The optional dependency versions are pinned
in pyproject.toml; the installed Browser Use dependency set still passes pip check.
The checkpoint occupies approximately 820 MiB. CPU loading/inference was verified
with socket connections blocked as well as HF/Transformers offline modes. A cold
load measured 26.6 seconds, a two-choice decision 1.5 seconds, and process peak RSS
about 1.14 GB; these are one-run observations, not a performance guarantee.

The model initially chose Done before searching, so an independent goal checkpoint
now gates that action. This illustrates that running a local model does not establish
its browsing quality. Early smoke reports without that gate are historical.
The upstream loader warns about an out-of-range calibration temperature for >10
choices; this adapter never supplies >10 choices in one call. Confidence is recorded
as model answer probability, never reported as browser-test accuracy.

Laya loads once per custom run and is released at run exit; it is not a continuously
running background server. Browser Use remains OpenAI-backed. Model-free replay
continues to use neither Laya nor OpenAI. No production service or data was changed.

Final Laya verification: **136 tests passed** (129 framework + seven account/social
regressions). Two local agents made 24 Laya calls and hit their six-step limits,
repeatedly choosing reload; neither completed search. Full report:
`runs/laya-report.html`. These findings are a model-quality limitation, not a
claim that the requested search passed.

### Single-candidate selection fix (2026-09-30)

When any selection stage has only one candidate, the framework now resolves it
without invoking Laya or consuming model-call budget. Its record is labeled
`selection: deterministic`, `reason: sole_candidate`, with no confidence or
inference-duration field. Choices among multiple candidates remain labeled
`selection: model` with the model's answer confidence. This avoids the redundant
Reload-to-a14 model call and misleading single-option 100% score. Historical
reports remain unchanged; use the new `runs/laya-single-candidate-fix/` report.
Coordinated sessions and additional scenarios are paused pending user review.

### Full choice probabilities (2026-09-30)

Every Laya model stage now retains the upstream `probabilities` mapping for all
choices, alongside the selected answer's confidence. The adapter checks matching
choice IDs, finite probabilities in [0,1], and a sum near one (allowing upstream
rounding). HTML session reports show ranked probability tables above raw records;
deterministic sole-candidate resolutions still have no probability or confidence.
These probabilities describe alternatives within one model stage, not task success.
Historical reports cannot recover discarded distributions. Fresh evidence is in
`runs/laya-choice-probabilities/`; test results are `runs/laya-probability-tests.xml`.

### Hosted Jev comparison (2026-09-30)

`scripts/jev_goal_probe.py` repeats the seven text-only search-goal cases from
`scripts/laya_goal_probe.py` with identical states, choices and question instructions.
It calls the user-specified `https://jev-ai.pro/api/v1/systemone` endpoint using
`JEV_AI_API_KEY` (or the existing `JEV_API_KEY`) from the environment or ignored
`.env`. Environment values take precedence. It makes at most seven requests,
without retries, redirects or provider fallback, and stops on API failure.

```sh
.venv-adversary/bin/python scripts/jev_goal_probe.py --output runs/jev-goal-wording
.venv-adversary/bin/python -m pytest tests/adversary/test_jev.py tests/adversary/test_jev_goal_probe.py --confcutdir=tests/adversary -q
```

Choose a new output directory for each run. `review.html`, `summary.json` and
`results.jsonl` record exact inputs, resolved model, latency, token usage, all choice
probabilities and provider confidence separately. Expected labels are used only
for evaluation, never sent as answers. Existing Laya results are compared only
when inputs match. The first live Jev run selected the expected action in **7/7**
cases versus Laya's **0/7**. This is one prediction per case, not a browser test or
reliability benchmark. The separate mocked client/report tests passed **18/18**.
The custom browser agent still defaults to local Laya; coordinated sessions remain
paused pending review. Wire format: <https://jev-ai.pro/docs>.

### Laya Browser checkpoint swap (2026-09-30)

The custom engine now defaults to `cklxx/laya-browser` v19s, pinned at
`645cf366a2ae35f1086e8c20eff48f909bb49206`, cached in
`.models/laya-browser/<revision>`. Run the existing download command once for this
checkpoint. The installed Laya runtime loads its weights locally without executing
the model repository's Python code. Prior weights and reports are preserved.

This is a checkpoint-only swap: generic prompts, candidate hierarchy and action
guards remain as before. The upstream specialized browser input adapter is not yet
integrated. The seven-case CPU probe with outbound sockets blocked selected the
expected action in **3/7**, versus base Laya **0/7** and hosted Jev **7/7**.
See `runs/laya-browser-goal-wording/review.html` (exact states and probabilities).
The new one-agent real browser run is `runs/laya-browser-search/report.html`:
**incomplete**, three model-selected clicks, last click timed out; search was not
completed. Six model calls were made. Framework checks: **153 passed, 2 skipped**.
Coordinated sessions remain paused.

### Jev browser comparison

The custom agent also supports `--decision-provider jev`, using the same bounded
hierarchy, goals, candidates and executor as Laya (which remains the default).
It reads JEV_AI_API_KEY or legacy JEV_API_KEY from the ignored env file; browser and
QA app never receive the key. No fallback or automatic retries. Example:

```sh
.venv-adversary/bin/python -m adversary run --engine custom --decision-provider jev --scenario library-search --agents 1 --max-steps 6 --max-model-calls 18 --timeout 180 --output runs/jev-search-modal
```

Report stages record resolved model, token usage, all choice probabilities and
provider confidence separately from selected probability (`answer_confidence`).
First run reached the verified search goal but never selected Done: open Search,
select Artist, fill QA Artist, wait three times. Summary is incomplete/step_limit
with goal_achieved true;10 hosted calls. Do not label it fully completed. Compare
Laya's same six-step run: goal_achieved false. Reports: runs/jev-search-modal/.

### Deterministic scenario inputs (2026-10-01)

Reviewed all agent scenarios and replaced the field × payload cross-product with
explicit per-field text assignments in Scenario.fills. The coordinator applies
these bindings to the common BrowserAdapter, so custom Laya, custom Jev and Browser
Use all receive the same assigned inputs. Unmapped text fields have no Fill candidate;
Dropdowns expose all observed enabled options, retaining their actual values and
labels. The model selects using the goal; scenario bindings do not filter options.

Search: QA Artist text only; Artist, Album and Track are all available dropdown choices. Auth: invalid-email for the invalid
email goal plus a fixed synthetic password. Playlist/social: fixed registration
credentials and QA Playlist only in name fields. Added playlist-duplicate-trimmed as
an independent input variant rather than letting the model choose coverage. Existing
parameterized deterministic regressions cover blank/XSS and duplicate-name variants.

Once one candidate remains, the existing deterministic sole_candidate branch
records it without inference, confidence or call-budget consumption. Action/target
selection remains model-driven when alternatives genuinely exist. This is not a
rewrite of Browser Use's planning loop or a claim that every scenario is covered by
an autonomous run. Historical reports remain unchanged. Verification:164 framework
checks passed,2 opt-in browser checks skipped; one scripted search run completed
with goal_achieved true,zero model calls (runs/search-deterministic-inputs/report.html).

## Goal-driven decision-model testing

The framework assigns a goal and synthetic text inputs. At each step it sends the
model a fresh observation, available page actions/options, and recent action history.
The model has no persistent memory: the framework reconstructs its context on every
request. It chooses an action and target; the executor performs it and independent
oracles check progress, failure and completion. Dropdown choices come from the page;
text payloads belong to the individual scenario, not a model-selected coverage menu.

Six steps was a comparison budget, not an architectural requirement. Budgets should
match each goal's complexity. Known regression/security cases remain deterministic;
model-driven scenarios explore paths toward different goals and supplement coverage.
A completed API request or successful click does not establish test success.

Next implementation stage: focus observations on the active modal, include current
non-secret field values, and automatically stop when an independent completion check
succeeds. Preserve recorded actions for model-free replay and distinguish incomplete
exploration, application findings and harness/provider failures. Do not require a
model to choose Finish after the framework has already verified the goal.

### Focused observations and verified completion (2026-10-01)

Implemented the next stage: observe the active dialog text and current non-password
field values, supplying those fields to both custom model backends and Browser Use.
Custom exploration stops before further inference once the independent goal oracle
is satisfied; a goal verified at the final step boundary is also completed rather
than mislabeled step_limit. Browser Use checks the goal after executed QA actions.
Safe adapter-authored JevError details are recorded separately; provider bodies and
credentials remain excluded.

New independent goals: search-album, search-track, search-artist-typo, plus the existing
library-search artist goal. All expose the page's dropdown choices and bind only text
payloads. Scripted baselines support all four. No claim that new goals have yet passed
with Laya/Jev: verification uses deterministic policies and scripted execution.

All three roadmap areas remain relevant: broader goals, coordinated social sessions,
and routing/generative fallback. This stage implements the prerequisite state and
completion handling plus broader search goals. Shared-fixture social coordination
and live fallback integration are subsequent stages, not implemented by this change.

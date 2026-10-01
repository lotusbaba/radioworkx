# Adversarial browser testing: architecture and roadmap

Updated 2026-09-29. The local Laya custom runner and OpenAI-backed native Browser Use runner are
implemented. The diagrams further below retain the broader Laya/hybrid target
architecture; they are not claims that every roadmap phase is complete.
See [running the framework](adversary-framework.md) for current commands, evidence
and limits. Source specification: [Adversarial Test Spec](../tests/Adversarial%20Test%20Spec.md).
RadioWorkx's application architecture remains in [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md).

## Implemented local Laya and OpenAI execution paths

```text
                     TestCoordinator (asyncio)
                               |
                  creates isolated QA sessions
                 /                             \
        Custom AgentSession              Browser Use Agent
        observes/builds candidates       owns native agent loop
                 |                             |
                 +--- Shared DecisionService --+
                      Laya queue / OpenAI calls
                 |                             |
          bounded candidate              registered QA tools
          selection                      (choose/observe/done)
                 |                             |
                 +----- ActionPolicy ----------+
                        intent recorder
                        Playwright adapter
                 |                             |
         separate contexts in             fresh Chromium process
         shared Chromium process          per session, CDP attachment
                 |                             |
                 +--- deterministic oracles ---+
                      actions / traces / reports
                               |
                 fresh-fixture Playwright replay
                      (no model calls)
```

The service is called by each agent, not a layer that owns Browser Use. The
Playwright adapter is inside the session's execution path. Browser contexts are
separate sessions within the custom engine's browser process; Browser Use currently
uses one temporary process/profile per session. Each session also has an independent
app subprocess and disposable database schema, fake Redis and synthetic media.
Only PostgreSQL runs in a container today.

Custom now uses one locally loaded Laya model on a dedicated inference thread,
with a bounded queue and hierarchical choices capped at ten per call. It never
reads OpenAI credentials or falls back to a hosted model. Browser Use continues to
use the existing OpenAI key. The pure DecisionRouter below is retained for future
Browser Use hybrid routing; it is not in the custom runner's direct local path. Action replay, origin guards,
call/step/time limits and artifact reports are implemented. Full security probes,
complex-widget generation, multi-account exploration, app-container isolation,
cost reservations in dollars, minimization and generated regressions remain roadmap work.

## Implemented slice: contracts and decision routing

The standalone `adversary` package now contains:

- `models/action.py`: a closed, discriminated union of concrete browser actions,
  ordered semantic locator alternatives and candidate IDs. Missing targets/values,
  unknown operations and extraneous fields fail validation; empty fill values are
  valid test inputs and remain exact during JSON round trips.
- `models/observation.py`: bounded observations and observation-scoped elements.
- `models/decision.py`: immutable versioned request/config/budget/route contracts,
  per-strategy bounded-operation allowlists and candidate-label resolution tied to
  request, session, observation and step identity.
- `inference/router.py`: deterministic Laya/LLM/blocked routing with a default
  ten-candidate limit. Missing coverage defaults to the LLM path. Malformed or stale
  requests fail validation; they are not escalated to another model. Required model
  unavailability, exhausted budgets or disallowed hosted access block dispatch.

The router does not call models, execute actions, enforce target-origin policy,
reserve budgets or create an inference queue itself. The new OpenAI service
serializes and atomically reserves calls, while ActionPolicy guards browser actions.
Dollar-cost reservations remain future work. Custom Laya dispatch is implemented. The native OpenAI
Browser Use adapter is verified; its proposed Laya hybrid adapter is not implemented.
The phase table remains the broader roadmap, including richer domain contracts.

Verified with 88 unit cases (no browser, network, model or database required):

```sh
.venv/bin/python -m pytest tests/adversary --confcutdir=tests/adversary -q
.venv/bin/python -m adversary.inference.demo
```

The demo prints one route for each of `laya`, `llm` and `blocked`, using illustrative
availability inputs; it does not claim a model is loaded. Package discovery includes
`adversary*`, with Pydantic declared in the optional `adversary` extra. The production
Dockerfile still copies only the application package. Browser/model dependencies
are installed only in the separate test environment; live services are unchanged. These domain tests override the application suite's
database fixture; `--confcutdir` also avoids loading its application imports.

## Decisions

Add a separate adversary Python package beside app. Domain models and protocols
must not import Playwright, Laya or Browser Use. The coordinator owns bounded
sessions, browser lifecycle and engine cleanup. One Chromium browser instance with isolated
contexts is the custom-engine MVP and the Browser Use integration target. Support
two exploration engines: the existing
scripted/Laya agent loop and a Browser Use integration. Strategies are data. In the
existing loop, one shared decision service selects validated candidate labels;
application code builds and executes all actions. Browser Use has its own model-driven
decision loop behind an adapter, with the same policy and evidence requirements.
Strategy 2 proposes a hybrid model adapter routing bounded choices to Laya and other
decisions to a configured generative model; that compatibility is not yet verified.

## Architecture diagrams: both exploration engines

Here, **Browser Use** means the browser automation agent framework. It complements
the existing custom agent architecture. Select an engine for each session; never let
two engines control the same page concurrently. Both engines must produce the same
versioned action/result records so findings use a common replay and reporting path.

### Shared platform

The shared platform is our test infrastructure, not an additional agent layer.
Arrows below show control or data flow; boxes show ownership. Each engine owns its
observe → decide → execute loop and returns observations to that same session.

```text
                       Your test coordinator
                         (Python / asyncio)
                    QA setup, budgets, cleanup
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
        Custom agent sessions           Browser Use agent sessions
          ↔ Scripted / Laya                ↔ Hybrid model adapter
                 │                               │
        Policy + recording hooks        Policy + recording hooks
                 │                               │
        Playwright executor             Framework browser automation
                 │                               │
                 ▼                               ▼
         Isolated contexts                Isolated contexts
                 │                               │
                 └───────────────┬───────────────┘
                                 ↕
                       Disposable RadioWorkx QA
                      (synthetic data and services)

     Both execution paths emit actions, results and browser evidence
                                 │
                                 ▼
                       Common recording + oracles
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
        Original fingerprints          Versioned action records
                 │                               │
                 │                               ▼
                 │                    Reset QA + fresh context
                 │                               │
                 │                               ▼
                 │                     Playwright action replay
                 │                      (policy; no inference)
                 │                               │
                 │                               ▼
                 │                       Same failure oracles
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
                   Compare fingerprints → report
```
```
Test Strategy 1 - How the custom agent architecture works.
                      Python process

                  asyncio event loop
                         │
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
    Agent A           Agent B           Agent C
    asyncio task      asyncio task      asyncio task
       │                 │                 │
       │ strategy A      │ strategy B      │ strategy C
       │                 │                 │
       ▼                 ▼                 ▼
 BrowserObservation BrowserObservation BrowserObservation
       │                 │                 │
       ▼                 ▼                 ▼
 ActionGenerator    ActionGenerator    ActionGenerator
       │                 │                 │
       └──────────────┬──┴─────────────────┘
                      │
              decision requests
                      ▼
              ┌───────────────┐
              │ asyncio.Queue │
              └───────┬───────┘
                      │
                      ▼
            Shared DecisionService
                      │
                      ▼
              ┌───────────────┐
              │ ONE local     │
              │ Laya model    │
              └───────┬───────┘
                      │
                 decisions
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
       Agent A     Agent B     Agent C
          │           │           │
          ▼           ▼           ▼
      Playwright  Playwright  Playwright
          │           │           │
          ▼           ▼           ▼
      Context A   Context B   Context C
          │           │           │
          └───────────┼───────────┘
                      ▼
                traces/results
```


Replay reads exact normalized action records, not screenshots or trace files.
Traces, screenshots and console/network logs are supporting evidence. Both the
original execution and replay run the same oracles before comparing fingerprints.

QA state reset belongs to the coordinator: isolated browser contexts do not isolate
the database. Serialize scenarios that reset shared state, or give concurrent
scenarios separate backend fixtures. Typed HTTP security probes use a separate
policy-checked adapter and explicit probe records; they are not browser clicks.

### Existing agent architecture: scripted and Laya

The coordinator starts custom AgentSession loops. Each session builds observations
and candidate actions, requests a decision, validates it and executes it in its own
context. The shared decision service returns each choice only to its requesting
session; choices are not broadcast to all agents.

```text
                       Your test coordinator
                         (Python / asyncio)
                                 │
             ┌───────────────────┼───────────────────┐
             ▼                   ▼                   ▼
       Custom Agent 1      Custom Agent 2      Custom Agent N
       observe/decide/act  observe/decide/act  observe/decide/act
             ↕                   ↕                   ↕
       ┌───────────────────────────────────────────────────┐
       │ Shared DecisionService: request ↔ selected label  │
       │ Scripted choices OR one Laya model + serial queue │
       └───────────────────────────────────────────────────┘

       Each agent executes only its own selected candidate:
             │                   │                   │
             ▼                   ▼                   ▼
       Validate choice     Validate choice     Validate choice
       Policy + intent     Policy + intent     Policy + intent
             │                   │                   │
             ▼                   ▼                   ▼
        Playwright          Playwright          Playwright
         executor            executor            executor
             ↕                   ↕                   ↕
       ┌───────────────────────────────────────────────────┐
       │ Shared Chromium browser instance                  │
       │    Context 1           Context 2        Context N │
       └───────────────────────────────────────────────────┘
                                 ↕
                       RadioWorkx QA target

       Executors + browser observers → results and evidence
                    │                         │
                    ▼                         ▼
           Owning agent's next step    Common recording + oracles
                                      → Playwright action replay
```

Laya chooses among application-generated candidates; it does not execute browser
commands. Candidate snapshots and decision responses carry session, observation and
step identity. Only the Laya backend needs model inference; scripted runs load no
model. The executors are per-session uses of the same adapter implementation, not
separate browser processes. Contexts live inside Chromium, rather than forwarding
actions to it as an additional execution layer.

Scripted decisions exercise the same executor, recording and replay path before
model integration. A blocked action or execution error is recorded separately from
a confirmed application failure.

### Browser Use architecture: framework integration

#### Test Strategy 2 — Browser Use + Laya + generative LLM

Proposed hybrid integration; Laya-to-Browser Use compatibility is **unverified**.
The routing rules alone are implemented in `adversary/inference/router.py`.
Each session is a Browser Use agent. Its model calls go through our proposed
Browser Use-compatible model adapter; Browser Use retains ownership of the agent
loop and browser execution. The adapter is not another agent.

```text
                         TestCoordinator
                         Python / asyncio
                               │
             creates agents; assigns goals and budgets
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
     Browser Use          Browser Use          Browser Use
       Agent A              Agent B              Agent C
   malformed-input      navigation-abuse       normal-user
          │                    │                    │
          └────────────────────┼────────────────────┘
                               ▼
           Browser Use-compatible model adapter (proposed)
            state + goal + history + session/step identity
                               │
                               ▼
                    Candidate Action Builder
                  supported actions + exact values
                               │
                               ▼
                       Decision Router
                    explicit configured rules
                               │
               ┌───────────────┴────────────────┐
               ▼                                ▼
       Covered bounded choice          Outside bounded coverage
               │                                │
               ▼                                ▼
       Shared DecisionService            Configured generative LLM
       ┌──────────────────────┐           local or explicitly enabled
       │ Bounded async queue  │           hosted provider
       │ Dedicated executor   │                   │
       │ thread → one Laya    │                   │
       └──────────────────────┘                   │
               │                                  │
        candidate label                  structured proposal
               └───────────────┬──────────────────┘
                               ▼
              Adapter maps and validates both outputs
               against Browser Use's response contract
                               │
                               ▼
              Return only to the requesting agent/step
                  (no broadcast to other agents)
                               │
               Each owning agent's execution path:
                               │
                               ▼
              Revalidate target + action + ActionPolicy
                               │
                               ▼
                  Flush normalized action intent
                               │
                               ▼
                Browser Use browser automation
                               ↕
                Agent's assigned context and page
                  in managed Chromium instance(s)
                               ↕
                     Disposable RadioWorkx QA

          Execution results + browser observations/events
                               │
                               ▼
              Flush results + capture supporting evidence
                               │
               ┌───────────────┴────────────────┐
               ▼                                ▼
      Owning agent's next step          Run Recorder + oracles
      until goal/budget/stop            (all steps, not just failures)
                                                │
                      ┌─────────────────────────┼─────────────┐
                      ▼                         ▼             ▼
             actions.jsonl +              traces/logs    screenshots
             original fingerprints
                      │
                      ▼
            Restore QA fixtures + fresh context
                      │
                      ▼
            Playwright action replay + same policy
                   (NO Laya / NO LLM)
                      │
                      ▼
            Same oracles + compare original fingerprint
                      │
                      ▼
                  Replay verdict
                      │
                 if reproduced
                      ▼
             Generate regression test
           (fixture setup + failure assertion)
```

Routing is rule-based initially: use Laya only when the operation is in a configured
bounded-decision allowlist, the candidate set is nonempty and within its limit,
and all target/value parameters are already resolved. Other decisions go to the
configured generative model. Invalid or expired responses are recorded; bounded
retry or fallback must be explicitly configured and stay within the session budget.
Do not assume a confidence score proves that an action or route is correct.

The adapter must translate Browser Use's model request into Laya's candidate-choice
input and translate the selected label into the required structured response.
Generative responses pass the same contract validation. This is more than a queue
wrapper and needs compatibility tests against a pinned Browser Use version before
acceptance. Session, observation and step identifiers keep responses associated
with their original request; stale targets are rejected before execution.

Strategy 1 retains its local scripted/Laya decision path. Strategy 2 adds a separate
configurable generative backend: hosted access must be explicitly enabled, with
bounded sanitized observations and call/time/cost limits. A local-only run must use
a compatible local generative backend or stop when routing requires one; it must
never silently fall back to a hosted provider.

Each action in a multi-action response gets its own policy check, flushed intent
and result. Record blocked actions and interrupted intents explicitly. Traces and
screenshots are evidence, not replay instructions. Replay verdicts include
REPRODUCED, NOT_REPRODUCED, PARTIAL and REPLAY_FAILED; matching the original failure
fingerprint is required for REPRODUCED. Regression generation follows verified
reproduction and does not automatically commit the generated test.

The hooks map supported proposed operations to typed actions and flush normalized
intent records **before** framework execution, then record actual results afterward.
Browser Use retains its browser automation layer; the design does not assume it
uses our custom Playwright executor internally. The shared replay executor is a
separate consumer of these normalized records.

This is an integration contract, not a claim about a particular Browser Use API.
Pin and validate the framework version during implementation. The adapter must
intercept operations **before** execution, enforce navigation/popup/download policy,
and record each executed operation, including operations in a multi-action response.
Do not allow an unrecorded framework executor to bypass this boundary. Unsupported
operations fail explicitly until their contracts and replay behavior are implemented.
Model-facing observations must be bounded and sanitized; credentials remain fixture
references rather than prompt or artifact contents.

Browser Use is a separate engine, not a replacement Laya backend. Replay consumes
the normalized records through the common executor without invoking either model.
Whether Browser Use can attach to the coordinator-owned browser and expose the
required execution hooks is an acceptance gate. If its pinned version requires a
separate browser process, retain per-session isolation and coordinator-owned cleanup
and document that exception before enabling the engine.

### Implementation placement and acceptance

Keep the existing package layout below and add `adversary/engines/browser_use/` for
the optional framework adapter. Domain models must also remain free of Browser Use
imports. Install its dependencies only in the testing environment.

Phases 1–6 establish shared contracts, QA setup, execution, recording, replay and
oracles. Retain Phases 7–10 for the existing Laya engine and introduce Browser Use
against those same contracts. Both engines are required targets; neither is marked
complete until isolated execution, policy rejection, interrupted recording, model-free
replay, evidence capture and cancellation/cleanup pass. Prove one session first,
then bounded multi-session operation. Framework hook compatibility must be tested
before claiming that the shared execution boundary is enforceable.

```text
adversary/
  models/          typed actions, observations, decisions, results, failures
  browser/         protocol, observation builder, resolver, async adapter
  scenarios/       deterministic setup using existing app workflows
  agent/           candidate generation, strategy data, session loop
  inference/       protocol, scripted service; later laya/backend and service
  recording/       versioned JSONL, metadata, run artifacts
  replay/          action replay and failure classification
  detection/       deterministic detectors and fingerprints
  policy/          allowed origins/actions and environment restrictions
  data/            seeded test values
  orchestrator/    lifecycle, bounded concurrency, cancellation
  config/          validated YAML and CLI overrides
  cli.py
  minimize/        Phase 11 only
  generation/      Phase 12 only
tests/adversary/   unit and integration tests, small test-only server wiring
examples/adversary.yaml
runs/             ignored artifacts
```

Create modules only as their phase needs them. Later packaging must explicitly
include adversary: current setuptools discovery includes only app*. Keep browser
and model dependencies optional and out of production Docker installation.

## Corrections and limits

- The existing suite is synchronous Python smoke scripts, not a reusable Playwright
  runner. Preserve those tests; use async Playwright for new concurrent orchestration.
- One Chromium process with isolated contexts is the custom-engine MVP; Browser Use
  sharing is subject to the integration gate above. Contexts do not isolate backend
  database state.
- Laya supports MPS upstream. Choose the official Agent backend first; ONNX needs
  export and benchmarks. Choice outputs are labels and browser efficacy is unverified.
- The default Laya Router can load multiple models. Use one explicit checkpoint.
- Replaying recorded actions is deterministic instruction playback; reproducing
  application outcomes still depends on reset state, IDs, external services and timing.
- JSONL needs flushed intent/result records, schema versions and partial-last-line
  recovery. It does not automatically guarantee durability on power loss. A killed
  process may leave an intent without a result; retain it as interrupted/unknown.
- Exact text may contain secrets. Record reproducible synthetic values and redact
  credentials; bound DOM text/network logs and keep artifacts ignored. Traces and
  screenshots may contain private data and require the same artifact handling.
- Live localhost:8001 is not a default adversarial target. Require disposable target
  setup. Browser contexts alone cannot undo a submitted request or music download.
- Replay before failure detectors proves action execution; REPRODUCED requires a
  matching original fingerprint after Phase 6. An action error alone is not a bug.
- Blocking native inference needs an executor; asyncio timeout alone cannot kill it.

## Smallest executable slice

Use a disposable instance of the existing RadioWorkx FastAPI app with a fixed small
catalog and no acquisition workers. StartingScenario opens /artists and waits for
the existing search form. Observe the page, use ScriptedDecisionService to select
fill/search/navigation operations, execute them, flush actions.jsonl, then replay
in a fresh context after restoring the same seeded state. Assert matching action
sequence and expected URL/search state. No Laya or new fixture application needed.

The candidate snapshot is bound to the observation and step. Locators carry ordered
alternatives (test ID, role/name, label, text, CSS); ambiguous or stale targets fail
explicitly. Intent and result records share a sequence ID. Record generated values,
wait conditions, timing and selected locator so replay never regenerates choices.
Apply ActionPolicy during exploration and replay, including redirects/popups; limit
external navigation and destructive controls, and distinguish blocked actions from
target failures. Default download handling rejects downloads.

## Phase gates

| Phase | Deliverable and acceptance |
| --- | --- |
| 0 | These documents plus Laya/runtime and existing-suite evidence. No implementation. |
| 1 | Typed domain models, action union, enums and serialization contracts; round-trip and invalid-input tests without browser/model. |
| 2 | Thin async adapter, scenarios, observations, locator resolution and policy; verify against isolated RadioWorkx. |
| 3 | Scripted decisions drive one bounded browser session; action failure does not crash the coordinator. |
| 4 | Incremental intent/result recording, metadata and artifact paths; interrupted-tail recovery test. |
| 5 | Replay the scripted sequence without inference; validate setup/reset and exact action values. |
| 6 | HTTP, JS, console, transport, crash/navigation/timeout detection and deduplication; use test-only route interception for controlled errors if the real app has no safe deterministic error path. |
| 7 | Pinned single-model backend, serialized queue, metrics, offline verification; one/two/five-agent checks. |
| 8 | Strategy data and seeded boundary generation; reproducible candidate/value tests. |
| 9 | Bounded agent concurrency, cancellation, cleanup and one-agent failure isolation. |
| 10 | Per-context traces, screenshots and console/network artifacts; verify normal/error cleanup. |
| 11 | Replay-based minimization with unchanged original record and matching fingerprint; report flaky outcomes. |
| 12 | Native Python regression generation with setup and assertion against the original failure. Never automatically commit it. |
| 13 | Optional dashboard only after engine reliability. |

Trace capture is required for final MVP acceptance even though scheduled late. Basic
resource cleanup and bounded loops apply from the first browser phase. At each phase
run relevant unit/integration checks and report failures; no browser integration
applies to Phase 1's deliberately browser-free models.

## Phase 1 implementation plan

Use Pydantic v2 (already installed) for validated, versioned JSON contracts. Define
TestRun, AgentSession, AgentGoal, AgentStrategy and StartingScenario references;
BrowserObservation/BrowserElement/ElementLocator; a discriminated BrowserAction
union; DecisionRequest/Decision; ActionResult/ActionRecord; Failure/Fingerprint;
AgentResult/RunResult and replay classification enums. Include observation-scoped
element identity, locator alternatives, action parameters, intent/result lifecycle,
timestamps/durations, stable event IDs and bounded configuration values.

Validate operation-specific fields, candidate bounds, finite numeric values and
required locator/value combinations. Test JSON round trips, rejected malformed
actions and schema-version handling. Do not implement browser calls or Laya yet.

## Dependencies, mocks and future commands

Reuse Python, Pydantic, pytest and installed Playwright 1.62.0. Declare Playwright
and PyYAML in a separate testing extra and lock them; YAML already exists in the
environment. asyncio/dataclasses/argparse need no installation. Use pytest plus
asyncio.run initially rather than requiring another plugin. Pin Chromium or retain
the existing Chrome channel as configurable. Laya and its tensor dependencies are
Phase 7 only; details in [laya-integration.md](laya-integration.md).

Mock BrowserDriver, DecisionService, clock, artifact failure paths and inference
backend for unit tests. Use a real browser against isolated RadioWorkx for adapter
and replay tests. Only model-specific acceptance checks need real weights. Do not
use fake Laya results as evidence of offline model operation or decision quality.

Historical target CLI examples below are not the implemented command syntax; use
[the current run/replay commands](adversary-framework.md). Port 8011 denotes the disposable
test instance, not the production proxy. The setup fixture must supply that instance.

```sh
.venv/bin/python -m pytest tests/adversary -q
adversary run examples/adversary.yaml --target http://127.0.0.1:8011 --engine scripted --agents 1 --concurrency 1 --steps 5 --headed
adversary replay <run-id> agent-001
# After Phase 7–10 acceptance:
adversary run examples/adversary.yaml --target http://127.0.0.1:8011 --engine laya --agents 5 --concurrency 5 --steps 50 --headed
adversary list-runs
adversary inspect <run-id>
adversary minimize <run-id> agent-001
adversary generate-test <run-id> agent-001
```

CLI overrides YAML. Standardize on inference.queue_size (the spec also calls it
max_queue_size). A future separate inference install/lock may be needed if tensor
dependencies conflict with the app environment. No dependencies were installed,
browser tests executed, live services changed or model weights downloaded in Phase 0.

## Security QA extension

See the [RadioWorkx scenario catalog](adversarial-scenarios.md) for registration,
login/logout, account playlists, saved likes and additional station workflows.
It records fixture requirements, deterministic oracles and the limits of the
2026-09-29 read-only public-site inspection. These scenarios are planned, not executed.

The approved scope now includes bounded application penetration tests, XSS and SQL
injection checks. Detailed requirements are in section 64 of the specification.
This extends the plan; no security probes have been implemented or executed yet.

Use a separate RadioWorkx QA container with its own synthetic database, identities,
storage and queues. Disable/mock external providers and music acquisition. Require
the configured QA target identity before exploration, replay or minimization; the live
proxy at localhost:8001 must be rejected. Introduce this explicit container setup in
Phase 2, using existing app code and reusable test-data setup rather than a replacement
application. Context isolation alone does not isolate server-side records.

| Test family | Evidence needed |
| --- | --- |
| Authorization / session isolation | A synthetic identity receives a record or operation forbidden by an explicit access matrix. |
| Revoked tokens / request forgery | A protected operation succeeds despite the configured authentication or origin rule. |
| Reflected, stored or DOM XSS | A unique harmless marker actually executes through the tested rendering path; reflected text alone is insufficient. |
| SQL injection | Reproducible query-semantic or ownership violation against a fixed dataset; an HTTP 500 alone is not confirmation. |
| Error disclosure | Response exposes a seeded secret marker or database/stack internals; classify independently of injection. |
| Duplicate / rate-limit bypass | Bounded attempts exceed the explicitly configured business rule. |

Proposed additions, created only when the relevant phase begins:

- models/security.py: SecurityScenario, identity references, probe definitions,
  expected invariants, evidence and finding classifications.
- security/cases/: deterministic authorization, XSS and SQLi cases.
- security/probes.py: constrained HTTP request adapter for cases browser actions
  cannot express. Keep typed HTTP probes separate from BrowserActions.
- security/oracles.py: fixture-backed verdicts and fingerprints.
- data/security_values.py: curated, harmless, versioned inputs.
- tests/adversary/security/: oracle, policy, replay and isolated integration checks.

Each scenario declares setup/reset, roles, target paths, allowed methods, budget and
safe behavior. Use independent contexts for cross-user and stored-XSS tests. Instrument
execution markers without evaluating payloads in the harness. SQLi comparisons use
baseline/paired probes and synthetic record IDs; exclude extraction, destructive SQL,
command execution and time-delay probes. Restrict request forgery to configured local
test origins. No broad network scanning, brute-force or denial-of-service cases.

Record exact synthetic values, identity aliases, response evidence and actions, while
keeping credentials out of artifacts. Replay reconstructs credentials from fixture
references. Use CONFIRMED/SUSPECTED/INCONCLUSIVE/EXPECTED_REJECTION independently of
REPRODUCED/NOT_REPRODUCED/PARTIAL/REPLAY_FAILED; neither confidence nor an error status
alone establishes a vulnerability.

Phase 1 adds contracts only; Phase 2 adds isolated setup and policy/probe interfaces;
Phases 4–5 add faithful recording/replay; Phase 6 adds deterministic oracles; Phase 8
adds exploration strategies. Start with scripted authorization plus one applicable
XSS and SQLi case before Laya exploration. Stored/DOM cases depend on actual app paths.
Validate positive detector behavior through test-only controlled faults when needed,
never by weakening application routes. Reports are advisory until the relevant oracle
and replay are reliable enough for a release gate.

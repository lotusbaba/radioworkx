# Adversarial browser testing: proposed architecture

Phase 0 proposal, 2026-09-28. Implementation awaits approval. Source specification:
[Adversarial Test Spec](../tests/Adversarial%20Test%20Spec.md).
This is the testing platform; RadioWorkx's application architecture remains in
[SYSTEM_DESIGN.md](SYSTEM_DESIGN.md).

## Decisions

Add a separate adversary Python package beside app. Domain models and protocols
must import neither Playwright nor Laya. The coordinator owns one browser, bounded
agent contexts and one decision service. Strategies are data. Laya selects validated
candidate labels; application code builds and executes all actions.

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
- One Chromium process with isolated contexts is the MVP, despite the earlier spec
  drawing separate Chromium instances. Contexts do not isolate backend database state.
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

Proposed commands below are not implemented yet. Port 8011 denotes the disposable
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

# PROJECT SPECIFICATION
# Local Parallel Adversarial Browser Testing Platform

You are building a local-first, open-source adversarial browser testing
platform.

Read this entire specification before writing code.

Do not attempt to build everything at once. Follow the implementation phases
at the end of this document.

The architecture should remain modular and testable throughout development.


======================================================================
1. OBJECTIVE
======================================================================

Build a system that launches multiple independent Chromium browser sessions
against a web application and allows autonomous testing agents to explore the
application concurrently.

The agents should attempt to discover:

- HTTP 5xx failures
- JavaScript exceptions
- failed network requests
- broken navigation
- malformed input handling
- boundary-condition failures
- invalid application states
- duplicate submissions
- unusual navigation behavior
- unexpected authorization behavior
- session problems
- crashes
- UI states that violate configured invariants

This system supplements conventional testing.

It does NOT replace:

    unit tests
    integration tests
    deterministic Playwright tests

Instead:

    unit tests
        ↓
    integration tests
        ↓
    deterministic E2E tests
        ↓
    adversarial browser exploration     ← THIS PROJECT
        ↓
    discovered failure
        ↓
    deterministic replay
        ↓
    minimized reproduction
        ↓
    generated Playwright regression test


The central design principle is:

    AI/decision model = discovery

    deterministic action recording = reproducibility

    Playwright = browser execution, debugging and regression testing


======================================================================
2. EXISTING PLAYWRIGHT SUITE IS AN ASSET
======================================================================

This repository ALREADY contains a working application and a working
Playwright test suite.

Do NOT create a replacement Playwright framework.

Do NOT rewrite or restructure existing Playwright tests merely to support
this project.

Before implementation, inspect and document:

- playwright.config.*
- test directories and naming conventions
- fixtures
- authentication setup
- storageState usage
- setup/teardown projects
- page objects and helper functions
- baseURL and webServer configuration
- application startup mechanism
- environment variables
- test-data setup and cleanup
- configured testIdAttribute / data-testid usage
- trace, screenshot, and video configuration
- browser projects/devices
- timeout and assertion conventions

Reuse existing Playwright infrastructure wherever practical.

The adversarial system is a DISCOVERY LAYER that feeds useful discoveries
back into the existing deterministic Playwright suite. It is not a competing
test framework.

Introduce a StartingScenario abstraction that deterministically establishes
meaningful application state before adversarial exploration begins. Examples:

    anonymous_homepage
    authenticated_homepage
    account_settings
    checkout_started
    existing_customer
    admin_user

StartingScenario should reuse existing fixtures, helpers, page objects,
storageState, authentication setup, and test-data utilities.

Example:

    existing deterministic login/setup
                ↓
        authenticated application state
                ↓
          /settings/billing
                ↓
        START ADVERSARIAL EXPLORATION

Do NOT make Laya spend inference rediscovering deterministic setup the
existing Playwright suite already knows.

Future versions may use existing deterministic tests as exploration seeds or
checkpoints, but automatic parsing of existing tests is NOT part of the MVP.


======================================================================
3. LOCAL-FIRST REQUIREMENT
======================================================================

The MVP must run entirely on a developer machine after dependencies and model
weights have been downloaded.

The basic execution path must NOT require:

- Runlayer
- Jev
- OpenAI API
- Anthropic API
- hosted inference
- Kubernetes
- Kafka
- Redis
- Temporal
- cloud infrastructure


Primary stack:

    existing repository language/runtime
    existing Playwright installation
    Laya (local inference)
    Chromium

Do NOT force Python 3.12+/asyncio for browser orchestration before inspecting
the repository. If the existing Playwright suite is TypeScript/JavaScript,
prefer keeping browser orchestration in that ecosystem. If Laya requires
Python, isolate it behind a single local inference service/process rather
than moving the entire test system to Python.


Laya inference runs locally.

Model weights may initially be downloaded from their distribution source and
cached locally.

After the model is available locally, browser testing should not require
remote inference.


======================================================================
4. HIGH-LEVEL ARCHITECTURE
======================================================================


                         Test Run
                            │
                            ▼
                 ┌─────────────────────┐
                 │   TestCoordinator   │
                 │                     │
                 │ Python / asyncio    │
                 └──────────┬──────────┘
                            │
                       create agents
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ▼                  ▼                  ▼
    AgentSession 1     AgentSession 2     AgentSession N
         │                  │                  │
         │                  │                  │
         ▼                  ▼                  ▼
 BrowserObservation   BrowserObservation   BrowserObservation
         │                  │                  │
         └──────────────────┼──────────────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ DecisionService     │
                 │                     │
                 │ Laya loaded ONCE    │
                 │ locally             │
                 └──────────┬──────────┘
                            │
                    bounded decisions
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
         ▼                  ▼                  ▼
   BrowserAction       BrowserAction       BrowserAction
         │                  │                  │
         ▼                  ▼                  ▼
 Playwright Driver    Playwright Driver   Playwright Driver
         │                  │                  │
         ▼                  ▼                  ▼
   Chromium #1          Chromium #2         Chromium #N
         │                  │                  │
         └──────────────────┼──────────────────┘
                            │
                            ▼
                         Recorder
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
    actions.jsonl      Playwright trace   screenshots
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
                     FailureDetector
                            │
                            ▼
                      Failure Report
                            │
                            ▼
                       ReplayEngine
                            │
                            ▼
                    Failure Minimizer
                            │
                            ▼
                 Playwright Test Generator


======================================================================
5. IMPORTANT: DO NOT LOAD LAYA ONCE PER AGENT
======================================================================

Browser agents are lightweight logical workers.

They MUST NOT each load their own copy of Laya.

Incorrect:

    Agent 1 → Laya instance
    Agent 2 → Laya instance
    Agent 3 → Laya instance
    Agent 4 → Laya instance
    Agent 5 → Laya instance


Correct:

    Agent 1 ─┐
    Agent 2 ─┤
    Agent 3 ─┼──► LayaInferenceService
    Agent 4 ─┤          │
    Agent 5 ─┘          ▼
                    ONE model
                   loaded locally


The model should be loaded once.

All agents submit decision requests to the same inference service.


======================================================================
6. LAYA INFERENCE SERVICE
======================================================================

Create a component conceptually named:

    LayaInferenceService


Responsibilities:

- load Laya once
- retain model/tokenizer/runtime in memory
- accept concurrent decision requests
- serialize or batch inference where appropriate
- return structured decisions
- expose health/status information
- expose basic inference metrics
- isolate Laya-specific implementation details


Example conceptual interface:

    class DecisionService(Protocol):

        async def choose(
            self,
            request: DecisionRequest
        ) -> Decision:
            ...


Laya implementation:

    class LayaDecisionService(DecisionService):

        async def start(self):
            # load model exactly once

        async def choose(self, request):
            ...

        async def close(self):
            ...


The rest of the application should NOT import Laya directly.

Only the Laya adapter/service should know how Laya works.


======================================================================
7. INVESTIGATE LAYA RUNTIME BEFORE IMPLEMENTATION
======================================================================

Before implementing Laya integration:

1. Inspect the current official Laya repository/documentation.
2. Determine the recommended inference runtime.
4. Determine model loading APIs.
5. Determine Apple Silicon support.
6. Determine whether MPS is supported/recommended.
7. Determine whether ONNX is preferable on macOS.
8. Determine batching capabilities.
9. Determine the exact choice/score APIs.
10. Determine recommended choice-set sizes.

Do not invent APIs.

Create a short document:

    docs/laya-integration.md

containing the findings before implementing the adapter.

If multiple viable runtimes exist, hide them behind:

    LayaBackend

For example:

    LayaBackend
        ├── TransformersLayaBackend
        └── OnnxLayaBackend

Do NOT implement both initially unless necessary.

Choose the simplest reliable local backend first.


======================================================================
8. LAYA IS A DECISION ENGINE, NOT THE AGENT
======================================================================

This distinction is fundamental.

Laya does NOT control Chromium directly.

Laya does NOT execute arbitrary commands.

Laya does NOT own agent state.

Laya does NOT determine application architecture.

Laya performs bounded decisions.

Our application owns:

- agent lifecycle
- goals
- browser state
- DOM interpretation
- available actions
- test-data generation
- browser execution
- safety boundaries
- recording
- failure detection
- replay
- termination


Conceptually:

    application determines legal actions

                    ↓

                [A]
                [B]
                [C]
                [D]

                    ↓

             Laya chooses B

                    ↓

         application executes B


Laya must never be allowed to generate arbitrary executable operations.


======================================================================
9. CORE DOMAIN TYPES
======================================================================

Define strongly typed models.

At minimum:

    TestRun
    AgentSession
    AgentGoal
    AgentStrategy
    StartingScenario
    BrowserObservation
    BrowserElement
    BrowserAction
    DecisionRequest
    Decision
    ActionRecord
    Failure
    AgentResult
    RunResult


Prefer dataclasses or Pydantic models where appropriate.

Do not pass unstructured dictionaries throughout the application.


======================================================================
10. BROWSER DRIVER ABSTRACTION
======================================================================

Create:

    BrowserDriver


Conceptual interface:

    class BrowserDriver(Protocol):

        async def start(...):
            ...

        async def navigate(url):
            ...

        async def observe() -> BrowserObservation:
            ...

        async def execute(
            action: BrowserAction
        ) -> ActionResult:
            ...

        async def screenshot(...):
            ...

        async def close():
            ...


Initial implementation should be a thin adapter around the EXISTING Playwright
setup rather than a new standalone framework:

    ExistingPlaywrightAdapter


Architecture should permit future drivers:

    BrowserDriver
        ├── PlaywrightBrowserDriver
        └── AgentBrowserDriver


Do not introduce agent-browser into MVP unless it provides a concrete
advantage.

The existing Playwright infrastructure is sufficient for the first implementation.


======================================================================
11. BROWSER ISOLATION
======================================================================

Each agent requires an isolated browser context.

For MVP, prefer:

    ONE Chromium browser process

with:

    N independent BrowserContexts

unless independent browser processes are required for isolation.

Conceptually:

                  Chromium
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
     Context 1    Context 2    Context N
        │            │            │
     Agent 1      Agent 2      Agent N


Each context should isolate:

- cookies
- local storage
- session storage
- authentication
- cache where appropriate


Add an option later for:

    --browser-isolation process

which launches separate Chromium processes.


======================================================================
12. BROWSER OBSERVATION
======================================================================

Do NOT send the entire raw DOM to Laya.

Create a compact normalized representation.

Example:

    BrowserObservation(
        url="/signup",
        title="Create account",
        visible_text="...",
        interactive_elements=[...],
        console_errors=[],
        network_failures=[],
        dialogs=[],
    )


BrowserElement:

    element_id
    role
    accessible_name
    label
    type
    value
    disabled
    checked
    selected
    test_id
    href
    semantic_group


Example:

    [
        BrowserElement(
            element_id=0,
            role="textbox",
            accessible_name="Email"
        ),

        BrowserElement(
            element_id=1,
            role="textbox",
            accessible_name="Password"
        ),

        BrowserElement(
            element_id=2,
            role="button",
            accessible_name="Create Account"
        )
    ]


Prefer accessibility/semantic information over raw HTML.


======================================================================
13. BROWSER ACTION MODEL
======================================================================

Define a closed set of browser operations.

Examples:

    NavigateAction
    ClickAction
    FillAction
    SelectAction
    HoverAction
    ScrollAction
    BackAction
    ForwardAction
    ReloadAction
    WaitAction
    KeyPressAction
    SubmitAction
    DoneAction


Laya can ONLY select from actions generated by the application.

Never execute arbitrary Laya-generated strings.


Example candidate table:

    0 → Click(Create Account)
    1 → Fill(Email)
    2 → Fill(Password)
    3 → Back()
    4 → Reload()


Laya returns:

    1


Application resolves:

    candidates[1]


Then executes it.


======================================================================
14. SEMANTIC LOCATORS
======================================================================

Do NOT make CSS selectors the canonical element identity.

Prefer:

1. test-id
2. role + accessible name
3. label
4. text
6. CSS fallback


Record multiple locator strategies where possible.

Example:

    ElementLocator(
        test_id="profile-save",
        role="button",
        accessible_name="Save",
        css_fallback="#profile button.primary"
    )


This is important for replay reliability.


======================================================================
15. HIERARCHICAL DECISION MAKING
======================================================================

Avoid asking Laya to choose among hundreds of elements.

Use hierarchical decisions.


STEP 1:

Choose operation type.

Candidates:

    CLICK
    TYPE
    SELECT
    SCROLL
    BACK
    FORWARD
    RELOAD
    WAIT
    DONE


STEP 2:

Filter elements compatible with operation.

For TYPE:

    Email
    Password
    Search


STEP 3:

Ask Laya which element.

Example:

    Email


STEP 4:

If data is required:

    TestDataGenerator


STEP 5:

Construct BrowserAction.


This produces:

    observation
        ↓
    choose operation
        ↓
    filter candidates
        ↓
    choose target
        ↓
    generate data if necessary
        ↓
    BrowserAction


======================================================================
16. OPTIONAL SEMANTIC GROUPING
======================================================================

Large pages may contain many elements.

Introduce optional semantic groups:

    navigation
    authentication
    forms
    account
    checkout
    destructive
    content
    search
    settings


If candidate count exceeds a configurable threshold:

    elements
       ↓
    choose semantic group
       ↓
    filter elements
       ↓
    choose element


Do not prematurely implement complex ML-based grouping.

Start with deterministic heuristics.


======================================================================
17. TEST DATA GENERATOR
======================================================================

Laya is a decision model, not a general-purpose text generator.

Therefore create:

    TestDataGenerator


Interface:

    generate(
        element,
        strategy,
        history
    ) -> GeneratedValue


Initial implementation should be deterministic.


EMAIL EXAMPLES

    ""
    "x"
    "foo@"
    "foo@@bar.com"
    " foo@example.com "
    Unicode addresses
    extremely long strings


NUMBER EXAMPLES

    0
    -1
    1
    MAX_INT
    MAX_INT + 1
    huge values
    decimals
    invalid numeric strings


TEXT EXAMPLES

    ""
    " "
    very long strings
    Unicode
    emoji
    newline sequences
    punctuation
    HTML-like text


Do NOT include destructive security payload libraries in MVP.

The goal is application robustness testing, not exploit development.


======================================================================
18. AGENT STRATEGIES
======================================================================

Different agents should explore differently.

Strategies are configuration/data, not subclasses.

Initial strategies:

    normal_user
    malformed_input
    boundary_values
    navigation_abuse
    rapid_interaction
    state_transition


Examples:


NORMAL USER

Attempt realistic application workflows.


MALFORMED INPUT

Prefer form fields.

Try malformed and unusual values.


BOUNDARY VALUES

Prefer fields with measurable limits.

Try empty/minimum/maximum/extreme values.


NAVIGATION ABUSE

Prefer:

    back
    forward
    reload
    leaving workflows
    returning to previous states


RAPID INTERACTION

Try:

    repeated submit
    repeated navigation
    double actions


STATE TRANSITION

Try performing valid operations in unusual sequences.


======================================================================
19. AGENT EXECUTION LOOP
======================================================================

Conceptually:

    async def run_agent(session):

        await browser.start()

        for step in range(max_steps):

            observation = await browser.observe()

            failures = failure_detector.inspect(
                observation
            )

            if failures:
                recorder.record_failures(failures)

            candidates = action_generator.generate(
                observation,
                strategy,
                history
            )

            decision = await decision_service.choose(
                DecisionRequest(
                    observation=observation,
                    candidates=candidates,
                    goal=session.goal,
                    history=history
                )
            )

            action = candidates[decision.choice]

            recorder.record_intent(...)

            result = await browser.execute(action)

            recorder.record_result(...)

            if should_terminate(...):
                break

        await browser.close()


The browser loop must survive individual action failures.


======================================================================
20. SHARED LAYA INFERENCE AND CONCURRENCY
======================================================================

Five browser agents may request decisions simultaneously.

Do not assume the Laya runtime is thread-safe.

Initially implement:

    asyncio.Queue

or equivalent.


Conceptually:

    Agent 1 ─┐
    Agent 2 ─┤
    Agent 3 ─┼──► Decision Queue
    Agent 4 ─┤          │
    Agent 5 ─┘          ▼
                   Laya Worker
                        │
                        ▼
                   local model


Start with safe serialized inference if necessary.

Correctness first.

Then benchmark.

Later support batching:

    requests accumulated for a short interval
                 ↓
               batch
                 ↓
              Laya
                 ↓
        distribute responses


Do NOT implement batching until single-request inference works correctly.


======================================================================
21. BACKPRESSURE
======================================================================

Browser agents must not overwhelm the inference engine.

Use bounded queues.

Configuration:

    inference:
        max_queue_size: 100
        timeout_seconds: 10


Record:

    queue wait time
    inference duration
    total decision latency


This lets us determine whether:

    browser execution

or:

    Laya inference

is the bottleneck.


======================================================================
22. FAILURE DETECTION
======================================================================

Failure detection must primarily be deterministic.

Do NOT rely on Laya to decide whether the application failed.


Initial detectors:

    HTTP5xxDetector
    ConsoleErrorDetector
    JavaScriptExceptionDetector
    NetworkFailureDetector
    PageCrashDetector
    NavigationFailureDetector
    TimeoutDetector


Support configurable application invariants later.


Example:

    forbidden_text:
        - "Internal Server Error"
        - "Something went wrong"


Example:

    forbidden_status:
        - 500
        - 502
        - 503


======================================================================
23. FAILURE DEDUPLICATION
======================================================================

Parallel agents may discover the same bug.

Create a FailureFingerprint.

Potential fields:

    detector type
    URL
    HTTP status
    exception class
    normalized error message
    failing endpoint
    top stack frame


Example:

    hash(
        "HTTP_500" +
        "/api/profile" +
        "POST"
    )


Run summary should show:

    failures discovered: 37
    unique failures: 4


Do not require sophisticated clustering initially.


======================================================================
24. RECORD EVERYTHING
======================================================================

Every intended and executed action must be recorded.

Canonical format:

    JSONL


Why JSONL:

- append incrementally
- survives crashes
- streamable
- easy to inspect
- easy to replay


Example:

    {
      "sequence": 14,

      "timestamp": "...",

      "agent_id": "agent-003",

      "strategy": "malformed_input",

      "observation": {
          "url": "/signup"
      },

      "decision": {
          "engine": "laya",
          "operation": "TYPE",
          "operation_confidence": 0.82,
          "target": "email",
          "target_confidence": 0.74,
          "queue_ms": 4,
          "inference_ms": 81
      },

      "action": {
                   "type": "fill",

          "target": {
              "role": "textbox",
              "accessible_name": "Email",
              "test_id": "signup-email"
          },

          "value": "foo@@example.com"
      },

      "result": {
          "success": true,
          "duration_ms": 31,
          "url_after": "/signup"
      },

      "failures": []
    }


======================================================================
25. ARTIFACT DIRECTORY STRUCTURE
======================================================================

Use:

    runs/

      <run-id>/

        run.json
        summary.json

        agents/

          agent-001/

            metadata.json
            actions.jsonl
            result.json

            screenshots/
                000001.png
                000002.png

            traces/
                trace.zip

            logs/
                console.jsonl
                network.jsonl

          agent-002/
              ...

          agent-003/
              ...


run.json:

    run_id
    target_url
    git_commit
    start_time
    end_time
    configuration
    Laya model/version
    runtime/backend
    Playwright version
    browser version
    random seed


metadata.json:

    agent_id
    strategy
    browser context
    start/end
    random seed


result.json:

    status
    termination_reason
    number_of_steps
    failures
    unique_failure_ids
    duration
    decision_count
    total_inference_ms
    total_queue_ms


======================================================================
26. PLAYWRIGHT TRACING
======================================================================

Enable Playwright tracing for each agent/context.

Capture where practical:

    DOM snapshots
    browser actions
    screenshots
    network activity


The trace is for debugging.

IMPORTANT:

A Playwright trace is NOT our canonical replay mechanism.

We maintain our own structured BrowserAction history.

Think of:

    Playwright trace
        =
    developer debugging artifact


    actions.jsonl
        =
    machine-readable execution history


======================================================================
27. SCREENSHOTS
======================================================================

Do not necessarily screenshot every step by default because many parallel
agents can generate large amounts of data.

Configuration:

    screenshots:
        mode: failures

Possible modes:

    none
    failures
    every_step


When a failure occurs, capture:

    current screenshot

and if feasible retain:

    previous screenshot


======================================================================
28. DETERMINISTIC REPLAY
======================================================================

Replay is a FIRST-CLASS feature.

This is one of the most important architectural requirements.


Original exploration:

    BrowserObservation
            ↓
          Laya
            ↓
      BrowserAction
            ↓
        Chromium
            ↓
         Recorder


Replay:

       actions.jsonl
            ↓
       ReplayEngine
            ↓
      BrowserAction
            ↓
        Chromium


During replay:

    DO NOT call Laya.

    DO NOT call any LLM.

    DO NOT make new agent decisions.

Execute recorded actions directly.


CLI:

    adversary replay \
        <run-id> \
        <agent-id>


Example:

    adversary replay \
        2026-09-28-001 \
        agent-003


======================================================================
29. REPLAY LOCATOR RESOLUTION
======================================================================

DOMs change.

Resolve recorded targets using ordered strategies.

Example:

    1. test-id
    2. role + accessible name
    3. label
    4. exact text
    5. CSS fallback


Implement:

    LocatorResolver


Conceptually:

    locator = resolver.resolve(
        recorded_element,
        current_page
    )


Record which strategy succeeded.


======================================================================
30. REPLAY CLASSIFICATION
======================================================================

Replay result must be classified as:

    REPRODUCED

    NOT_REPRODUCED

    PARTIAL

    REPLAY_FAILED


REPRODUCED

The original failure fingerprint occurred again.


NOT_REPRODUCED

The sequence completed but the original failure did not occur.


PARTIAL

Some original behavior occurred but reproduction was inconclusive.


REPLAY_FAILED

The recorded sequence could not be executed reliably.


Do not treat replay infrastructure failures as application failures.


======================================================================
31. APPLICATION STATE AND REPLAY
======================================================================

Recognize that replaying browser actions alone may not reproduce a failure.

The application may depend on:

    database contents
    generated IDs
    authentication
    timestamps
    random values
    server state
    third-party services
    feature flags


Design for future support of:

    TestEnvironment

and:

    StateFixture


Example:

    TestEnvironment:

        async setup()
        async reset()
        async snapshot()
        async restore()


Do NOT implement sophisticated environment snapshotting in MVP.

Document this limitation.


======================================================================
32. FAILURE MINIMIZATION
======================================================================

After deterministic replay works, implement optional sequence minimization.

Example original sequence:

    A
    B
    C
    D
    E
    F
    G
    H

Failure occurs after H.


Potential minimized reproduction:

    A
    C
    F
    H


Use delta-debugging concepts.

Algorithm conceptually:

    remove subset
        ↓
    replay
        ↓
    same failure fingerprint?
        │
       yes
        ↓
    keep subset removed


Output:

    minimal-reproduction.jsonl


Never modify the original:

    actions.jsonl


======================================================================
33. PLAYWRIGHT REGRESSION TEST GENERATION
======================================================================

A successfully reproduced failure should be convertible into a conventional
Playwright test.

Command:

    adversary generate-test \
        <run-id> \
        <agent-id>


Prefer:

    minimal-reproduction.jsonl

when available.

Otherwise:

    actions.jsonl


Output example:

    generated_tests/
        test_profile_update_500.spec.ts


Generated test should contain:

    // GENERATED BY ADVERSARY
    //
    // Source run:
    // 2026-09-28-001
    //
    // Source agent:
    // agent-003


Translate BrowserActions into conventional Playwright operations.


Example:

    FillAction

becomes:

    await page
        .getByRole("textbox", { name: "Email" })
        .fill("foo@@example.com");


The generated test should assert the discovered failure condition does NOT
occur.

Example discovered failure:

    POST /api/profile → 500


Regression assertion:

    expect(response.status()).toBeLessThan(500);


Before generating code, inspect the EXISTING Playwright suite and match its:

    language (TypeScript/JavaScript/etc.)
    imports
    fixtures
    authentication setup
    page objects and helpers
    directory structure
    naming conventions
    assertion style

Generated tests must look like native tests from this repository and should
reuse existing fixtures rather than launching standalone browsers.

Do NOT automatically commit generated tests.


======================================================================
34. ORCHESTRATOR
======================================================================

Implement:

    TestCoordinator


Responsibilities:

    load configuration

    initialize shared services

    start LayaInferenceService ONCE

    start Chromium

    create browser contexts

    create AgentSessions

    enforce concurrency

    collect results

    handle cancellation

    close browser

    close inference service

    generate run summary


Do not put browser or Laya implementation details inside TestCoordinator.


======================================================================
35. CONCURRENCY MODEL
======================================================================

Initial implementation:

    asyncio


Configuration:

    agents: 20
    concurrency: 5


means:

    create 20 total agent sessions

    maximum 5 actively executing at once


Use:

    asyncio.Semaphore


or a worker queue.


Do not launch unlimited browser contexts.


======================================================================
36. FAILURE ISOLATION
======================================================================

One agent crashing must NOT terminate the test run.

Example:

    Agent 1 → running

    Agent 2 → Playwright exception

    Agent 3 → running

    Agent 4 → running

    Agent 5 → running


Coordinator records Agent 2 as:

    AGENT_FAILED


Remaining agents continue.


======================================================================
37. RESOURCE CLEANUP
======================================================================

Correct cleanup is mandatory.

Handle:

    normal completion

    timeout

    agent exception

    browser crash

    Laya inference failure

    Ctrl+C

    process termination where practical


Ensure:

    contexts close

    browser closes

    traces finalize

    files flush

    inference service closes


Use:

    try/finally

and:

    async context managers

where appropriate.


======================================================================
38. HEADLESS AND HEADED MODES
======================================================================

Support:

    --headless

and:

    --headed


Example:

    adversary run \
        --target http://localhost:3000 \
        --agents 5 \
        --concurrency 5 \
        --headed


Headed mode should make it possible to visually watch the agents operating.


======================================================================
39. FUTURE MOSAIC VIEW
======================================================================

Eventually build a dashboard resembling a browser swarm.

Example:

    ┌───────────┬───────────┬───────────┐
    │ Agent 001 │ Agent 002 │ Agent 003 │
    │           │           │           │
    │ browser   │ browser   │ browser   │
    │ preview   │ preview   │ preview   │
    ├───────────┼───────────┼───────────┤
    │ Agent 004 │ Agent 005 │ Agent 006 │
    │           │           │           │
    │ browser   │ browser   │ browser   │
    └───────────┴───────────┴───────────┘


Each tile could eventually show:

    current screenshot
    URL
    strategy
    current action
    steps
    failures
    status


Possible future implementation:

    local FastAPI server
           │
           ▼
      WebSocket/SSE
           │
           ▼
      local dashboard


Do NOT implement this for MVP.

The execution engine must not depend on the dashboard.


======================================================================
40. CLI
======================================================================

Create a CLI named:

    adversary


Commands:

    adversary run

    adversary list-runs

    adversary inspect

    adversary replay

    adversary minimize

    adversary generate-test


Examples:


RUN

    adversary run \
        --target http://localhost:3000 \
        --agents 5 \
        --concurrency 5 \
        --steps 50 \
        --headed


REPLAY

    adversary replay \
        2026-09-28-001 \
        agent-003


MINIMIZE

    adversary minimize \
        2026-09-28-001 \
        agent-003


GENERATE TEST

    adversary generate-test \
        2026-09-28-001 \
        agent-003


======================================================================
41. CONFIGURATION FILE
======================================================================

Support YAML configuration.

Example:

    target:
        url: http://localhost:3000

    run:
        agents: 5
        concurrency: 5
        max_steps: 50
        timeout_seconds: 600
        seed: 42

    browser:
        engine: chromium
        headless: false
        isolation: context

    inference:
        engine: laya
        local: true
        queue_size: 100
        timeout_seconds: 10

    recording:
        actions: true
        playwright_trace: true

    screenshots:
        mode: failures

    strategies:
        - normal_user
        - malformed_input
        - boundary_values
        - navigation_abuse
        - state_transition


Command:

    adversary run adversary.yaml


CLI arguments should override YAML values.


======================================================================
42. REPRODUCIBILITY
======================================================================

Random behavior should be seedable.

Record:

    run seed

and:

    agent seed


Example:

    run_seed = 42

derive:

    agent-001 = deterministic child seed
    agent-002 = deterministic child seed
    ...


TestDataGenerator should use the agent-specific RNG.

Do not use uncontrolled global randomness.


======================================================================
43. METRICS
======================================================================

Collect basic metrics without requiring Prometheus initially.


RUN METRICS

    total agents
    successful agents
    failed agents
    total actions
    total failures
    unique failures
    total duration


INFERENCE METRICS

    decisions
    queue wait
    inference latency
    p50
    p95
    p99 if sample size permits


BROWSER METRICS

    action duration
    navigation duration
    action failures


Useful future question:

    At what number of concurrent browser agents
    does Laya become the bottleneck?


======================================================================
44. LOGGING
======================================================================

Use structured logging.

Each log entry should include where relevant:

    run_id
    agent_id
    sequence
    component


Example:

    {
        "level": "INFO",
        "run_id": "...",
        "agent_id": "agent-003",
        "component": "browser",
        "message": "executing click"
    }


Avoid noisy raw print statements.


======================================================================
45. SECURITY / EXECUTION BOUNDARY
======================================================================

This project controls browsers.

Treat model output as untrusted.


Laya MUST NOT be able to directly execute:

    Python
    shell commands
    JavaScript
    arbitrary URLs
    filesystem operations


The application constructs all legal actions.

Laya chooses only among them.


Architecture:

                 application

              allowed actions

          ┌─────┬─────┬─────┬─────┐
          │  A  │  B  │  C  │  D  │
          └─────┴─────┴─────┴─────┘
                       │
                       ▼
                     Laya
                       │
                    returns
                       │
                       B
                       │
                       ▼
              application validates
                       │
                       ▼
                 execute action


Never:

    Laya output
        ↓
    eval()
        ↓
    execution


======================================================================
46. DESTRUCTIVE ACTION PROTECTION
======================================================================

Eventually users may point the system at real environments.

Default policy must assume:

    local/dev/test environments only.


Add an ActionPolicy abstraction.

Example:

    ActionPolicy.allow(action, context)


MVP protections:

    do not navigate outside configured origin unless allowed

    do not interact with file-download dialogs unless allowed

    do not submit obvious financial transactions

    do not perform destructive account deletion by default


Allow explicit configuration later:

    policy:
        destructive_actions: false
        external_navigation: false


======================================================================
47. PROJECT STRUCTURE
======================================================================

Use approximately:

    adversary/

        __init__.py

        cli.py

        config/
            schema.py
            loader.py

        models/
            run.py
            agent.py
            action.py
            observation.py
            decision.py
            failure.py
            result.py

        orchestrator/
            coordinator.py
            executor.py

        agent/
            session.py
            strategy.py
            action_generator.py

        inference/
            base.py
            service.py

            laya/
                backend.py
                service.py
                mapper.py

            scripted.py
            random.py

        browser/
            base.py
            playwright_driver.py
            observation_builder.py
            locator.py

        data/
            generator.py
            boundary_values.py

        detection/
            base.py
            http.py
            console.py
            javascript.py
            network.py
            crash.py
            fingerprint.py

        recording/
            recorder.py
            artifacts.py

        replay/
            engine.py
            locator_resolver.py
            result.py

        minimize/
            delta.py

        generation/
            playwright.py

        metrics/
            collector.py

        policy/
            action_policy.py


    tests/

        unit/
        integration/
        fixtures/


    docs/

        architecture.md
        laya-integration.md
        replay.md


    examples/

        adversary.yaml


Do not force this exact structure if a simpler organization is demonstrably
better, but preserve the architectural boundaries.


======================================================================
48. DEPENDENCY INVERSION
======================================================================

The core domain must not depend directly on:

    Playwright

or:

    Laya


Instead:

            AgentSession
               │
        ┌──────┴───────┐
        ▼              ▼
 BrowserDriver    DecisionService
        ▲              ▲
        │              │
   Playwright         Laya


This allows unit testing the agent loop without:

    Chromium
    Laya
    network access


======================================================================
49. TESTABILITY
======================================================================

The architecture must support deterministic tests.


Example:

    FakeBrowserDriver

returns:

    Observation A

then after Click:

    Observation B


ScriptedDecisionService returns:

    Click(button)


This should allow testing:

    agent loop
    recorder
    failure detection
    replay

without loading Chromium or Laya.


======================================================================
50. UNIT TESTS
======================================================================

At minimum test:

    action generation

    locator serialization

    locator resolution

    TestDataGenerator

    strategy behavior

    action policy

    failure fingerprinting

    JSONL recording

    replay classification

    configuration parsing

    seeded randomness

    Laya response mapping


Do not require the real Laya model for normal unit tests.


======================================================================
51. INTEGRATION VALIDATION AGAINST THE EXISTING APPLICATION
======================================================================

Do NOT create a separate fixture application by default.

Use the existing application, existing Playwright environment, and existing
test-data/setup utilities to validate the adversarial architecture.

Prefer selecting safe, deterministic existing workflows that exercise:

    forms
    navigation
    authenticated state
    network requests
    application state transitions

If the existing repository already contains intentionally failing test
fixtures or deterministic error paths, they may be used to verify failure
detection.

Only create a tiny synthetic fixture if there is no reasonable existing path
for validating a specific infrastructure behavior, and document why it was
necessary.

Do NOT optimize agents specifically for known bugs.

======================================================================
52. MVP DEMONSTRATION
======================================================================

The first meaningful demonstration should be:

    one laptop

    one locally loaded Laya model

    one Chromium process

    five isolated BrowserContexts

    five concurrent AgentSessions

    five different strategies


For example:

    Agent 001
        normal_user

    Agent 002
        malformed_input

    Agent 003
        boundary_values

    Agent 004
        navigation_abuse

    Agent 005
        state_transition


Command:

    adversary run \
        --target http://localhost:3000 \
        --agents 5 \
        --concurrency 5 \
        --headed \
        --steps 50


I should be able to visually watch multiple agents explore the application.


======================================================================
53. MVP SUCCESS CRITERIA
======================================================================

MVP is successful when all of these work:


1.

Laya model loads locally exactly once.


2.

No cloud inference API is required.


3.

Five agents can operate concurrently.


4.

Agents have isolated browser contexts.


5.

Each agent can use a different adversarial strategy.


6.

Browser state is normalized into BrowserObservation.


7.

Laya receives bounded decisions rather than arbitrary control.


8.

Laya cannot execute arbitrary commands.


9.

Every action is recorded to actions.jsonl.


10.

HTTP 5xx failures are detected.


11.

JavaScript exceptions are detected.


12.

console.error is captured.


13.

Failed network requests are captured.


14.

Failures receive fingerprints.


15.

Duplicate failures can be identified.


16.

Playwright traces are generated.


17.

Failure screenshots can be generated.


18.

A discovered sequence can be replayed WITHOUT Laya.


19.

Replay determines:
        REPRODUCED
        NOT_REPRODUCED
        PARTIAL
        REPLAY_FAILED


20.

The same failure fingerprint can be detected during replay.


21.

The system shuts down cleanly.


======================================================================
54. PHASED IMPLEMENTATION PLAN
======================================================================

DO NOT BUILD EVERYTHING SIMULTANEOUSLY.

Follow this order.


----------------------------------------------------------------------
PHASE 0 — RESEARCH / VERIFY ASSUMPTIONS
----------------------------------------------------------------------

Before implementation:

1. Inspect current Laya documentation/repository/model artifacts.
2. Determine exact local model loading mechanism.
4. Determine recommended macOS/Apple Silicon runtime.
5. Determine whether Transformers, ONNX, or another runtime is preferred.
6. Verify actual Laya decision API.
7. Determine model memory requirements.
8. Determine whether concurrent inference is safe.
9. Determine whether batching is supported.
10. Verify Playwright APIs required for:
       browser contexts
       tracing
       console events
       page errors
       network events
11. Document findings.

Produce:

    docs/laya-integration.md
    docs/current-playwright-architecture.md
    docs/architecture.md

DO NOT invent undocumented Laya APIs.

If anything in this specification conflicts with the actual current Laya
implementation, document the discrepancy and adapt behind our interfaces
rather than compromising the architecture.


----------------------------------------------------------------------
PHASE 1 — DOMAIN MODEL
----------------------------------------------------------------------

Implement:

    BrowserObservation
    BrowserElement
    ElementLocator
    BrowserAction
    Decision
    Failure
    AgentResult

No browser.

No Laya.


----------------------------------------------------------------------
PHASE 2 — EXISTING PLAYWRIGHT INTEGRATION
----------------------------------------------------------------------

Do NOT create a second Playwright framework.

Inspect the existing Playwright setup and create only the thin abstractions
needed by the adversarial layer. Reuse existing Page/BrowserContext objects,
fixtures, authentication/storageState, helpers, page objects, test IDs, and
application startup.

Implement/adapt:

    BrowserObservationBuilder
    BrowserActionExecutor
    StartingScenario
    ElementLocator / LocatorResolver primitives

Support the browser operations required by BrowserAction while preserving the
existing project's Playwright conventions.

Verify against the existing application and existing test environment.


----------------------------------------------------------------------
PHASE 3 — SCRIPTED AGENT
----------------------------------------------------------------------

Implement:

    ScriptedDecisionService


Run:

    observation
        ↓
    scripted choice
        ↓
    BrowserAction
        ↓
    Chromium


This proves the entire agent/browser abstraction WITHOUT AI.


----------------------------------------------------------------------
PHASE 4 — RECORDING
----------------------------------------------------------------------

Implement:

    actions.jsonl
    metadata
    run artifacts


Verify that killing an agent does not corrupt previously recorded actions.


----------------------------------------------------------------------
PHASE 5 — REPLAY
----------------------------------------------------------------------

Implement ReplayEngine BEFORE integrating Laya.

This is intentional.

Prove:

    scripted exploration
            ↓
      actions.jsonl
            ↓
         replay
            ↓
    same browser sequence


If this doesn't work reliably, stop and fix the architecture before adding
AI.


----------------------------------------------------------------------
PHASE 6 — FAILURE DETECTION
----------------------------------------------------------------------

Implement:

    HTTP 5xx
    console.error
    JavaScript exceptions
    network failures
    navigation failures

Add fingerprinting.

Verify against deliberately broken fixture routes.


----------------------------------------------------------------------
PHASE 7 — LAYA
----------------------------------------------------------------------

Only now integrate Laya.

Implement:

    LayaBackend
    LayaDecisionService


Requirements:

    model loaded once
    local inference
    bounded choices
    queue requests
    record latency
    clean shutdown


First test:

    ONE agent.


Then:

    TWO agents.


Then:

    FIVE agents.


Do not immediately attempt high concurrency.


----------------------------------------------------------------------
PHASE 8 — STRATEGIES
----------------------------------------------------------------------

Implement:

    normal_user
    malformed_input
    boundary_values
    navigation_abuse
    state_transition


Use deterministic TestDataGenerator.


----------------------------------------------------------------------
PHASE 9 — PARALLEL EXECUTION
----------------------------------------------------------------------

Implement proper:

    asyncio concurrency
    bounded browser concurrency
    inference backpressure
    cancellation
    failure isolation


Run:

    5 agents concurrently.


----------------------------------------------------------------------
PHASE 10 — TRACE / DEBUG ARTIFACTS
----------------------------------------------------------------------

Add:

    Playwright traces
    screenshots
    browser console logs
    network logs


----------------------------------------------------------------------
PHASE 11 — FAILURE MINIMIZATION
----------------------------------------------------------------------

Implement basic delta debugging against reproducible failures.


----------------------------------------------------------------------
PHASE 12 — TEST GENERATION
----------------------------------------------------------------------

Convert minimized BrowserActions into Playwright regression tests.


----------------------------------------------------------------------
PHASE 13 — DASHBOARD
----------------------------------------------------------------------

Only after the execution engine is reliable, consider a local browser-swarm
dashboard.

Do not couple execution to UI.


======================================================================
55. IMPORTANT ARCHITECTURAL DISTINCTION: SYSTEM 1 VS SYSTEM 2
======================================================================

Design the architecture so we can eventually introduce a slower reasoning
model without changing the browser system.

Think of Laya as:

    System 1

    fast
    cheap/local
    bounded decision making


Potential future LLM:

    System 2

    slower
    richer reasoning
    used only when necessary


Future architecture:

                    BrowserObservation
                           │
                           ▼
                    ActionGenerator
                           │
                           ▼
                         Laya
                           │
                    confidence/state
                      /          \
                   clear        uncertain
                    │              │
                    ▼              ▼
                 execute      System-2 LLM
                                   │
                                   ▼
                                execute


Do NOT implement the System-2 path for MVP.

But do not make architectural choices that prevent it.


======================================================================
56. POTENTIAL FUTURE LAYA BATCHING
======================================================================

Because many browser agents may reach decision points simultaneously, future
performance optimization may batch Laya requests.

Current MVP:

    Agent 1 ─┐
    Agent 2 ─┤
    Agent 3 ─┼── queue → Laya → responses
    Agent 4 ─┤
    Agent 5 ─┘


Future:

    Agent requests
          │
          ▼
     short batching
        window
          │
          ▼
    ┌───────────────┐
    │ request batch │
    │ 1 2 3 4 5 ... │
    └───────┬───────┘
            │
            ▼
           Laya
            │
            ▼
     batch decisions


Do not implement until measurements show it is useful.


======================================================================
57. SCALING MODEL
======================================================================

Keep future scaling in mind without implementing distributed infrastructure.

MVP:

                laptop
                   │
            TestCoordinator
                   │
             5 agents
                   │
              Chromium
                   │
                Laya


Future workstation:

            TestCoordinator
                   │
             50 agents
                   │
            Chromium pool
                   │
          local Laya service


Future distributed:

                 Coordinator
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
     Worker 1     Worker 2     Worker N
        │            │            │
    Chromium      Chromium      Chromium


The interfaces should make distributed workers possible later.

Do NOT implement them now.


======================================================================
58. NON-GOALS FOR MVP
======================================================================

Do NOT build:

    Kubernetes deployment

    distributed scheduling

    SaaS multi-tenancy

    authentication system for this tool

    billing

    hosted Laya inference

    Kafka

    Redis

    Temporal

    elaborate dashboard

    browser streaming

    vector database

    RAG

    autonomous code fixing

    automatic PR creation

    automatic production deployment


The MVP objective is much narrower:

    Can several local, cheap decision agents independently explore
    a web application, discover failures, record exactly how they
    reached them, and deterministically replay those failures?


======================================================================
59. ENGINEERING PRINCIPLES
======================================================================

Optimize for:

    correctness
    observability
    reproducibility
    modularity
    debuggability


before:

    maximum concurrency
    clever abstractions
    distributed infrastructure


Prefer:

    boring interfaces
    explicit data models
    structured logs
    deterministic tests


Avoid:

    giant classes
    global state
    hidden side effects
    model-specific logic leaking everywhere
    raw dictionaries everywhere
    premature distributed systems


======================================================================
60. FIRST DELIVERABLE
======================================================================

DO NOT immediately implement the whole project.

First:

1. Inspect the repository.
2. Inspect current official Laya resources.
4. Determine local inference requirements.
5. Determine Playwright requirements.
6. Propose the concrete repository structure.
7. Identify any assumptions in this specification that are incorrect or
   unsupported by the current libraries.
8. Produce an implementation plan mapped to the phases above.
9. Identify dependencies to install.
10. Identify which pieces should be mocked during development.
11. Identify the smallest vertical slice we can execute end-to-end.

The smallest desired vertical slice is:

    existing application + existing Playwright setup
          ↓
    existing Playwright Page/BrowserContext
          ↓
    observe page
          ↓
    ScriptedDecisionService
          ↓
    BrowserAction
          ↓
    execute
          ↓
    actions.jsonl
          ↓
    ReplayEngine
          ↓
    successfully replay same sequence


Only after this works should we introduce Laya.


======================================================================
61. WHEN YOU START CODING
======================================================================

Work incrementally.

After each phase:

1. Run tests.
2. Run relevant integration test.
4. Report what was implemented.
5. Report commands used to validate it.
6. Report failures or limitations.
7. Do not silently skip requirements.
8. Do not replace architecture with a simpler shortcut without explaining why.


For each major component, maintain the dependency direction:

                     DOMAIN

                       ▲
                       │

              interfaces/protocols

                 ▲             ▲
                 │             │

            Playwright       Laya

              adapter        adapter


Domain code must remain independent of both external implementations.


======================================================================
62. FINAL MENTAL MODEL
======================================================================

The complete system should eventually look like this:


                              RELEASE
                                 │
                                 ▼
                       TestCoordinator
                                 │
                     spawn adversarial agents
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
          ▼                      ▼                      ▼
       Agent 1                Agent 2                Agent N
    malformed-input       navigation-abuse       state-machine
          │                      │                      │
          ▼                      ▼                      ▼
    BrowserObservation     BrowserObservation     BrowserObservation
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                                 ▼
                        Decision Request Queue
                                 │
                                 ▼
                     ┌──────────────────────┐
                     │     LOCAL LAYA       │
                     │                      │
                     │ model loaded ONCE    │
                     └──────────┬───────────┘
                                │
                         bounded choices
                                │
          ┌─────────────────────┼──────────────────────┐
          │                     │                      │
          ▼                     ▼                      ▼
    BrowserAction         BrowserAction          BrowserAction
          │                     │                      │
          ▼                     ▼                      ▼
      Chromium               Chromium                Chromium
       Context                Context                 Context
          │                     │                      │
          ▼                     ▼                      ▼
       Recorder              Recorder               Recorder
          │                     │                      │
          └─────────────────────┼──────────────────────┘
                                │
                                ▼
                         Failure Detection
                                │
                                ▼
                       Failure Fingerprinting
                                │
                                ▼
                     ┌─────────────────────┐
                     │ Was a bug found?    │
                     └─────────┬───────────┘
                               │
                              YES
                               │
                               ▼
                          actions.jsonl
                               │
                               ▼
                          ReplayEngine
                               │
                               ▼
                    same failure reproduced?
                          /            \
                        YES             NO
                         │               │
                         ▼               ▼
                 Failure Minimizer    mark flaky /
                         │            non-reproduced
                         ▼
               minimal-reproduction
                         │
                         ▼
                 Playwright Generator
                         │
                         ▼
               deterministic regression
                         │
                         ▼
                  conventional CI suite


The key idea is:

    Exploration is probabilistic.

    Detection is deterministic where possible.

    Recording is exact.

    Replay is deterministic.

    Regression testing is conventional.


======================================================================
63. START
======================================================================

Begin with PHASE 0.

Do not write the Laya integration yet.

Inspect the current project and current upstream documentation/code first.

Return:

1. proposed repository structure
2. verified Laya local inference approach
3. verified Playwright approach
4. dependencies
5. assumptions/corrections
7. Phase 1 implementation plan
7. commands I will eventually use to run the MVP

Then wait for approval before proceeding to implementation.


======================================================================
64. SECURITY QA AND BOUNDED PENETRATION TESTING — SCOPE ADDITION
======================================================================

Include application security testing alongside robustness exploration. This addition
extends the MVP's scenario scope without changing the phase order or permitting
arbitrary model-generated payloads/commands. The prohibition on destructive payload
libraries remains. Security cases are curated, versioned test data selected by the
application; Laya may choose only permitted actions and targets.

Run security exploration against a separate QA container serving the actual RadioWorkx
frontend and backend, with a separate database, synthetic catalog, test identities,
storage and queues. Downloads and external AI calls must be disabled or mocked.
Never use the live frontend, production credentials, live volumes or production queues.
Loopback alone is insufficient: localhost:8001 is the live station. The QA setup must
provide an explicit target identity and reject production URLs before running probes.

Security scenarios:

- Authorization: anonymous/listener/admin access matrix; direct endpoint access and
  cross-identity access to synthetic private chat, requests and owned records.
- Sessions and tokens: cookie/context separation, revoked tokens, missing/invalid
  credentials and session expiry where the application supports it.
- Request forgery: cross-origin mutation attempts and Origin/CSRF protections where
  applicable, using a separately configured local test origin.
- Input exposure: errors must not disclose SQL internals, stack traces or seeded
  secret canaries; response status alone is not a security verdict.
- Business rules: bounded duplicate submissions, rate limits and state transitions;
  no brute-force credential guessing, denial-of-service or unrestricted scanning.

Cross-site scripting (XSS):

- Test reflected, stored and DOM rendering paths with inert control strings and
  curated harmless execution markers. Use unique per-run identifiers.
- Confirm execution only through an observable in-page marker or instrumented
  local callback attributable to the injected value. Merely finding HTML-like text
  in a response is insufficient. Never read cookies, steal data or call external hosts.
- For stored cases, create a synthetic record, visit the relevant rendering path in
  a second QA context, then reset the record/environment. Test listener and admin
  rendering separately when the field is shown to both roles.
- Track whether input is rejected, encoded, safely rendered, or actually executes.
  A harness-installed observer must not itself execute the injected value.

SQL injection:

- Use a small curated corpus of quotation, delimiter and paired boolean-condition
  probes on designated search/filter/identifier inputs. Record exact probe values.
- Compare with a baseline against a fixed synthetic dataset and expected ownership
  rules. Confirm only a reproducible unauthorized result, authentication bypass or
  demonstrated change to intended query semantics. A 500 or SQL error disclosure
  is separately reported, not automatically labeled confirmed injection.
- Do not use schema dumping, real-data extraction, stacked destructive statements,
  file operations, command execution or intentional database-delay payloads.
- Reset test data between attempts; compare allowed record IDs/counts using fixture
  truth rather than unpredictable live results. Query parameters must not accidentally
  be normalized away in a way that merges distinct findings.

Browser exploration and direct HTTP probes are complementary. Add a narrow typed
HTTP-probe interface for requests within configured QA origins when a browser cannot
exercise the required headers or endpoint. Its executor uses predefined methods,
paths, synthetic identity references and bounded bodies; no arbitrary model-authored
HTTP traffic. Record and replay these probes through the same intent/result protocol.
Browser-only cases remain BrowserActions; do not disguise HTTP probes as clicks.

Every case defines its threat hypothesis, roles, fixture state, permitted operations,
request/time budget, deterministic oracle, cleanup and expected safe behavior.
Classify results as CONFIRMED, SUSPECTED, INCONCLUSIVE or EXPECTED_REJECTION, alongside
the existing replay classification. Keep these distinct from severity and confidence.
Record a fingerprint, affected input/endpoint, identity alias, evidence and original
actions. A missing or invalid QA fixture yields a harness error, not a security finding.

First build deterministic security cases with scripted decisions, then let agents
explore permitted variations. Keep security modules optional. Add models/contracts in
Phase 1, QA isolation/policy and probe adapters during Phase 2, recording/replay during
Phases 4–5, security oracles during Phase 6 and security strategy/data sets in Phase 8.
Start with authorization and one reflected-XSS and search-SQLi case supported by the
actual app; report absent rendering paths as not applicable. No vulnerable production
route should be introduced for testing. Use test-only controlled faults to verify
detectors when no known vulnerability exists in RadioWorkx.

Reports initially supplement QA review. Only replay-confirmed findings with reliable
oracles should become release gates. Generated regression tests assert the safe
behavior and match the repository's Python test conventions. A clean exploration run
does not establish security completeness or replace code/dependency review and
dedicated penetration testing.

# Laya integration research

Phase 0, researched 2026-09-28. Source inspection only: no model was installed,
downloaded or benchmarked. Hardware observed: arm64, Python 3.13.3.

## Verified upstream

Official repository: https://github.com/NandhaKishorM/laya

Inspected revision: `9d955671415fc19f069b9cc998928075c1f255ec`;
package metadata: 0.3.21, Python >=3.10, Apache-2.0.
Pin source and checkpoint revisions separately before Phase 7.

Evidence below refers to files at that revision:

- [Agent implementation](https://github.com/NandhaKishorM/laya/blob/9d955671415fc19f069b9cc998928075c1f255ec/laya/agent.py)
- [Runtime and choice-budget guidance](https://github.com/NandhaKishorM/laya/blob/9d955671415fc19f069b9cc998928075c1f255ec/README.md)
- [ONNX documentation](https://github.com/NandhaKishorM/laya/blob/9d955671415fc19f069b9cc998928075c1f255ec/docs/reference/agent.md)
- [Dependencies](https://github.com/NandhaKishorM/laya/blob/9d955671415fc19f069b9cc998928075c1f255ec/pyproject.toml)

## Selected approach

Use a single `laya.Agent`, backed by PyTorch/Transformers, wrapped by our
`LayaBackend`. The default is now `cklxx/laya-browser` (v19s), replacing the
general English `convaiinnovations/laya` checkpoint. Avoid automatic Router checkpoint selection: it can keep
multiple checkpoints resident. There is no need for a local HTTP server initially.

Verified interface, illustrative only:

```python
from laya import Agent

agent = Agent('/absolute/path/to/pinned/checkpoint', device='cpu')
result = agent.predict(compact_state, {
    'operation': {
        'type': 'choice',
        'instructions': 'Choose the next permitted testing operation.',
        'criteria': {'click': 'Activate a control', 'back': 'Return to prior page'},
    },
})
selected_label = result['answers']['operation']['choice']
```

`predict` aliases `system_one`. Choices are returned as labels, not our candidate
indices: validate membership and map labels to application-owned actions.
Score questions use `type='score'` and an ordered criteria list. `noul` returns a
yes probability. Use `answer_confidence`, not entropy-derived `confidence`, when
recording the selected answer probability; do not treat it as browser-test accuracy.

Agent accepts a local directory or Hub model ID, `revision`, `device`, and optional
artifact digests. Required artifacts include `rl_agent_config.json`,
`model.safetensors`, tokenizer files and encoder configuration. Missing local
tokenizer/encoder assets can trigger upstream resolution: validate a complete cached
snapshot and test with HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1 and network disabled.
Offline operation remains an acceptance test, not a claim verified in Phase 0.

## Apple Silicon, memory and alternatives

The official Agent explicitly supports MPS and automatically selects it when CUDA
is absent and MPS is available. Requested unavailable MPS falls back to CPU; record
the actual device. Establish CPU correctness first, then benchmark MPS on this Mac.
MPS autocast is gated by row count (default five); do not infer latency from GPU
marketing benchmarks. No extra community Mac port is required for the first backend.

The English model has 421M parameters: roughly 1.68 GB of FP32 parameter storage
alone, plus tokenizer, activations, framework and loading overhead. Actual peak
resident/unified memory has not been measured; measure with Chromium active before
accepting five-agent operation.

Official ONNXAgent exists and requires an exported graph. Upstream reports an INT8
English graph around 581 MB versus 1.6 GB FP32, but that is graph size, not total RAM.
ONNX is a later CPU optimization, not established as preferable to MPS on this host.
Implement only the PyTorch backend first; retain the backend protocol for alternatives.

## Concurrency and bounded decisions

Use one bounded asyncio request queue (100) and one dedicated inference worker.
Run synchronous model loading/inference in a single executor thread, so it does not
block browser coroutines. Upstream synchronizes tokenizer access, but do not assume
unrestricted concurrent calls are desirable or validated for our usage.

`predict_batch(states, questions, batch_size=..., sort_by_length=...)` exists and
shares a question schema across states. Agents can have different candidates, so
arbitrary requests cannot simply be batched under one schema. Defer batching.

Choose operation, then target (and deterministic semantic group when needed).
Proposed initial cap: ten short candidates per decision, configurable and measured.
Upstream warns that >20 options can become indistinguishable under the head token
budget (English default 192). The HTTP server's 100-option limit is not a recommended
choice size. Check `usage.options` for collapsed option representations.

Record queue wait, inference duration and total latency separately. A request timeout
does not terminate a running native inference call: discard expired responses, keep
the single worker occupied until it finishes, and reject/drain pending futures at
shutdown. Hard cancellation would require a separately supervised process later.

## Dependencies and Phase 7 gates

Install Laya only in the testing environment, never production images. Its core
dependencies are torch, transformers, safetensors, huggingface_hub and numpy.
Resolve and lock compatible versions together; no ONNX/serve/fast extras initially.
Before integration acceptance: pin/download one checkpoint, verify disconnected
loading, measure RAM and CPU/MPS latency, validate label mapping, then run one, two
and five agents. Zero-shot browser exploration quality is unproven and needs
comparison against scripted/seeded random choices. Never substitute a hosted model.

## Implemented local backend (2026-09-30)

The research above is historical. `adversary/inference/laya.py` now implements
LayaBackend and LayaDecisionService. Custom CLI runs use this backend exclusively;
Browser Use remains on OpenAI. Install the optional `laya` extra and run
`python -m adversary.inference.download_laya` once. Runtime/checkpoint versions
are pinned separately; model revision is `645cf366a2ae35f1086e8c20eff48f909bb49206`.
The five required artifacts are cached under ignored `.models/laya-browser/<revision>`;
a checksum manifest is validated before offline loading. No weights are committed.
This swap keeps the existing generic question format and hierarchy for a controlled
checkpoint comparison; it does not adopt the upstream model-specific `decide` adapter.
Historical base-model weights and reports remain in place. Its manifest is rejected
by the new default validator rather than mislabeled as Laya Browser.

One lazily loaded CPU model serves the bounded asyncio queue through one dedicated
executor thread. Hierarchical operation/group/candidate selection retains the full
candidate set while limiting each inference to ten choices. Every hierarchy call
consumes the shared budget. Queue and per-stage inference timings, selected labels,
actual device and answer_confidence are recorded. Canceled callers cannot execute
late results; the worker finishes native inference before accepting the next job.
Shutdown rejects waiting jobs and waits for the active call.

Offline CPU loading and prediction passed with socket.connect patched to reject
all outbound connections, plus HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE enabled.
Observed cold load 26.6s, one two-choice inference 1.5s, process peak RSS about1.14GB.
Checkpoint disk size is ~820MiB, not the earlier FP32 storage estimate. These are
one-run observations. MPS is selectable but not verified or benchmarked in this task.

Two simultaneous browser sessions shared one CPU model and made24 local inferences,
with no hosted calls. Both hit the six-step limit after repeatedly selecting reload;
this is incomplete exploration, not a search success. The earlier model chose Done
prematurely; an independent catalog-response checkpoint now gates library-search
completion. The integration is functional; zero-shot exploration quality is still
unproven and needs strategy/model evaluation. No quality claim is inferred from
confidence. The upstream loader's calibration warning concerns >10 choices, which
this adapter never submits. See runs/laya-local-verified/ for the complete evidence.

"""One offline Laya model, one bounded queue, one dedicated inference thread."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import time

from .download_laya import DEFAULT_PATH, FILES, REPOSITORY, REVISION
from .openai import BudgetExhausted


def validate_checkpoint(path):
    path = Path(path).resolve()
    manifest = json.loads((path / 'manifest.json').read_text())
    if manifest['repository'] != REPOSITORY or manifest['revision'] != REVISION:
        raise ValueError('Unsupported Laya checkpoint revision')
    if set(manifest['sha256']) != set(FILES):
        raise ValueError('Incomplete Laya checkpoint manifest')
    for name in FILES:
        with (path / name).open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        if digest != manifest['sha256'][name]:
            raise ValueError('Laya checkpoint checksum mismatch: ' + name)
    return path


class LayaBackend:
    def __init__(self, path=DEFAULT_PATH, device='cpu'):
        self.path, self.device = path, device
        self.agent = None

    def load(self):
        if self.agent is not None:
            return
        path = validate_checkpoint(self.path)
        os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                          TOKENIZERS_PARALLELISM='false')
        import torch
        from laya import Agent
        if self.device == 'mps' and not torch.backends.mps.is_available():
            raise RuntimeError('MPS requested but unavailable; use --device cpu')
        torch.set_num_threads(4)
        self.agent = Agent(str(path), device=self.device)
        self.device = str(self.agent.device)

    def predict(self, state, choices):
        self.load()
        result = self.agent.predict(state, {'action': {'type': 'choice',
            'instructions': 'Choose the next action to achieve the testing goal, using current state and completed actions.',
            'criteria': choices}})
        # Reject choices that were indistinguishable under the model token budget.
        if result.get('usage', {}).get('options'):
            raise ValueError('Laya option representations collapsed; shorten the candidates')
        answer = result['answers']['action']
        choice = answer['choice']
        if choice not in choices:
            raise ValueError('Laya returned an unknown choice')
        return choice, answer.get('answer_confidence'), answer['probabilities']


class LayaDecisionService:
    model = REPOSITORY + '@' + REVISION

    def __init__(self, path=DEFAULT_PATH, device='cpu', max_calls=12, queue_size=100, backend=None):
        self.backend = backend or LayaBackend(path, device)
        self.max_calls, self.calls = max_calls, 0
        self.exhausted = False
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='laya-inference')
        self.worker = None
        self.closed = False
        self.metrics = {}

    def _predict(self, state, choices, stages):
        if not 1 <= len(choices) <= 10:
            raise ValueError('Laya decisions require 1..10 choices')
        if len(choices) == 1:
            label = next(iter(choices))
            stages.append({'selection': 'deterministic', 'reason': 'sole_candidate',
                           'choices': choices, 'selected': label})
            return label
        if self.calls >= self.max_calls:
            self.exhausted = True
            raise BudgetExhausted('Local Laya call budget exhausted')
        self.calls += 1
        start = time.monotonic()
        label, confidence, probabilities = self.backend.predict(state, choices)
        if label not in choices:
            raise ValueError('Laya returned an unknown choice')
        if (set(probabilities) != set(choices)
                or any(type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1
                       for p in probabilities.values())
                or not math.isclose(sum(probabilities.values()), 1.0, abs_tol=.001)):
            raise ValueError('Laya returned an invalid probability distribution')
        stages.append({'selection': 'model', 'choices': choices, 'selected': label, 'answer_confidence': confidence,
                       'probabilities': dict(probabilities),
                       'inference_ms': (time.monotonic() - start) * 1000})
        return label

    def _decide(self, request, history):
        stages = []
        candidates = list(request.candidates)
        if not candidates:
            raise ValueError('No bounded candidates; local custom agent cannot generate actions')
        state = {'goal': request.agent.goal, 'completed_actions': history[-5:],
                 'page': request.observation.title, 'url': request.observation.url,
                 'visible_text': request.observation.visible_text[:1200],
                 'fields': [{'name': e.accessible_name, 'value': e.current_value}
                            for e in request.observation.elements if e.current_value is not None]}
        # Hierarchical selection retains every candidate instead of truncating to
        # ten. Each actual model invocation consumes budget independently.
        if len(candidates) > 10:
            groups = {}
            for candidate in candidates:
                groups.setdefault(candidate.action.type.value, []).append(candidate)
            if len(groups) <= 10:
                descriptions = {
                    'fill': 'Enter text needed for the goal into a field.',
                    'click': 'Activate a link or button needed for the goal.',
                    'key_press': 'Submit the entered text with Enter.',
                    'reload': 'Refresh the current page to check persistence.',
                    'wait': 'Wait for an operation already in progress to finish.',
                    'scroll': 'Reveal controls below the visible area.',
                    'done': 'Stop only when the testing goal has already been achieved.',
                }
                operation = self._predict(state, {k: descriptions.get(k, k.replace('_', ' ')) for k in groups}, stages)
                candidates = groups[operation]
        while len(candidates) > 10:
            width = (len(candidates) + 9) // 10
            groups = [candidates[i:i + width] for i in range(0, len(candidates), width)]
            choices = {f'g{i}': '; '.join(c.description[:45] for c in group)[:150] for i, group in enumerate(groups)}
            label = self._predict(state, choices, stages)
            candidates = groups[int(label[1:])]
        label = self._predict(state, {c.id: c.description[:150] for c in candidates}, stages)
        return label, stages

    async def _work(self):
        loop = asyncio.get_running_loop()
        while True:
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            request, history, future, queued = item
            started = time.monotonic()
            try:
                if future.cancelled():
                    continue
                label, stages = await loop.run_in_executor(self.executor, self._decide, request, history)
                if not future.cancelled():
                    self.metrics[request.id] = {'queue_ms': (started - queued) * 1000,
                        'total_ms': (time.monotonic() - queued) * 1000,
                        'device': self.backend.device, 'stages': stages}
                    future.set_result(label)
            except Exception as error:
                if not future.cancelled():
                    future.set_exception(error)
            finally:
                self.queue.task_done()

    async def choose(self, request, history):
        if self.closed:
            raise RuntimeError('Laya service is closed')
        if self.worker is None:
            self.worker = asyncio.create_task(self._work())
        future = asyncio.get_running_loop().create_future()
        try:
            self.queue.put_nowait((request, tuple(history), future, time.monotonic()))
        except asyncio.QueueFull:
            raise RuntimeError('Laya request queue is full') from None
        return await future

    def take_metrics(self, request_id):
        return self.metrics.pop(request_id, {})

    async def aclose(self):
        self.closed = True
        # Cancel queued requests; native inference already running must finish
        # before the sole worker/model is released. Never overlap another call.
        while not self.queue.empty():
            item = self.queue.get_nowait()
            if item is not None and not item[2].done():
                item[2].set_exception(RuntimeError('Laya service shut down'))
            self.queue.task_done()
        if self.worker:
            await self.queue.put(None)
            await self.worker
        self.executor.shutdown(wait=True)

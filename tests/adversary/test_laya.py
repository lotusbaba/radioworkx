import asyncio
import hashlib
import json
import threading
import time

import pytest

from adversary.inference.download_laya import FILES, REPOSITORY, REVISION
from adversary.inference.laya import LayaDecisionService, validate_checkpoint
from adversary.inference.openai import BudgetExhausted
from adversary.models.action import CandidateAction, DoneAction
from adversary.models.decision import AgentContext, DecisionRequest
from adversary.models.observation import BrowserObservation


def request(count=2, rid='r1'):
    return DecisionRequest(id=rid, agent=AgentContext(session_id='s1', strategy='custom-laya', goal='Explore'),
        observation=BrowserObservation(id='o1', session_id='s1', step=0, url='http://127.0.0.1:8011/'),
        candidates=tuple(CandidateAction(id=f'a{i}', description=f'Choice {i}', action=DoneAction(reason=f'Choice {i}')) for i in range(count)))


class Backend:
    device = 'cpu'
    def __init__(self):
        self.choices = []
        self.threads = set()
    def predict(self, state, choices):
        self.threads.add(threading.get_ident())
        self.choices.append(choices)
        time.sleep(.01)
        return list(choices)[-1], .8, {k: 1 / len(choices) for k in choices}


def test_hierarchy_preserves_candidates_and_caps_each_call():
    async def check():
        backend = Backend()
        service = LayaDecisionService(backend=backend)
        try:
            assert await service.choose(request(120), []) == 'a119'
            assert all(1 <= len(c) <= 10 for c in backend.choices)
            assert service.calls == len(backend.choices)
            metrics = service.take_metrics('r1')
            assert sum(s['selection'] == 'model' for s in metrics['stages']) == service.calls
            assert metrics['device'] == 'cpu'
            assert metrics['total_ms'] > 0
        finally:
            await service.aclose()
    asyncio.run(check())


def test_shared_worker_runs_off_event_loop_and_does_not_overlap():
    async def check():
        backend = Backend()
        service = LayaDecisionService(backend=backend)
        ticks = 0
        async def heartbeat():
            nonlocal ticks
            for _ in range(15):
                ticks += 1
                await asyncio.sleep(.002)
        try:
            result = await asyncio.gather(*(service.choose(request(rid=f'r{i}'), []) for i in range(5)), heartbeat())
            assert result[:5] == ['a1'] * 5
            assert service.calls == 5 and ticks == 15
            assert len(backend.threads) == 1
            assert threading.get_ident() not in backend.threads
        finally:
            await service.aclose()
    asyncio.run(check())


def test_hierarchical_calls_consume_budget_without_fallback():
    async def check():
        service = LayaDecisionService(max_calls=1, backend=Backend())
        try:
            with pytest.raises(BudgetExhausted):
                await service.choose(request(20), [])
            assert service.calls == 1 and service.exhausted
        finally:
            await service.aclose()
    asyncio.run(check())


def test_cancelled_request_keeps_worker_busy_and_discards_result():
    async def check():
        started, release = threading.Event(), threading.Event()
        class Slow(Backend):
            def predict(self, state, choices):
                started.set()
                assert release.wait(5)
                return super().predict(state, choices)
        backend = Slow()
        service = LayaDecisionService(backend=backend)
        task = asyncio.create_task(service.choose(request(), []))
        while not started.is_set():
            await asyncio.sleep(.002)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        next_task = asyncio.create_task(service.choose(request(rid='r2'), []))
        await asyncio.sleep(.01)
        assert service.calls == 1
        release.set()
        assert await next_task == 'a1'
        assert 'r1' not in service.metrics
        await service.aclose()
        with pytest.raises(RuntimeError, match='closed'):
            await service.choose(request(), [])
    asyncio.run(check())


def test_unknown_label_rejected():
    class Bad(Backend):
        def predict(self, state, choices):
            return 'invented', .99, {k: 1 / len(choices) for k in choices}
    async def check():
        service = LayaDecisionService(backend=Bad())
        try:
            with pytest.raises(ValueError, match='unknown'):
                await service.choose(request(), [])
        finally:
            await service.aclose()
    asyncio.run(check())


@pytest.mark.parametrize('problem', ['missing', 'tampered', 'revision'])
def test_checkpoint_manifest_fails_closed(tmp_path, problem):
    hashes = {}
    for name in FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic')
        hashes[name] = hashlib.sha256(b'synthetic').hexdigest()
    manifest = dict(repository=REPOSITORY, revision=REVISION, sha256=hashes)
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    assert validate_checkpoint(tmp_path) == tmp_path
    if problem == 'missing':
        (tmp_path / FILES[0]).unlink()
    elif problem == 'tampered':
        (tmp_path / FILES[0]).write_bytes(b'changed')
    else:
        manifest['revision'] = 'main'
        (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_checkpoint(tmp_path)


def test_custom_cli_never_reads_openai_key(tmp_path, monkeypatch, capsys):
    import sys
    from adversary import cli
    from adversary.inference import openai, laya
    checkpoint = tmp_path / 'checkpoint'
    checkpoint.mkdir()
    (checkpoint / 'manifest.json').write_text('{}')
    def forbidden(*args, **kwargs):
        raise AssertionError('Custom engine must not read OpenAI credentials')
    monkeypatch.setattr(openai, 'credentials', forbidden)
    seen = {}
    async def coordinate(output, config, service, events):
        assert isinstance(service, laya.LayaDecisionService)
        seen['config'] = config
        return {'sessions': [], 'model_calls': 0}
    monkeypatch.setattr(cli, 'coordinate', coordinate)
    monkeypatch.setattr(sys, 'argv', ['adversary', 'run', '--engine', 'custom', '--laya-model', str(checkpoint)])
    cli.main()
    assert seen['config']['model'] == REPOSITORY + '@' + REVISION


def test_queue_is_bounded_and_shutdown_rejects_waiters():
    async def check():
        service = LayaDecisionService(queue_size=1, backend=Backend())
        # Hold the worker before it consumes the queue.
        blocker = asyncio.Event()
        service.worker = asyncio.create_task(blocker.wait())
        first = asyncio.create_task(service.choose(request(), []))
        await asyncio.sleep(0)
        with pytest.raises(RuntimeError, match='full'):
            await service.choose(request(rid='r2'), [])
        blocker.set()
        await service.aclose()
        with pytest.raises(RuntimeError, match='shut down'):
            await first
    asyncio.run(check())


def test_sole_candidate_needs_no_model_or_budget():
    class Forbidden(Backend):
        def predict(self, state, choices):
            raise AssertionError('Single candidate must not invoke Laya')
    async def check():
        service = LayaDecisionService(max_calls=0, backend=Forbidden())
        try:
            assert await service.choose(request(1), []) == 'a0'
            assert service.calls == 0 and not service.exhausted
            stage, = service.take_metrics('r1')['stages']
            assert stage == {'selection': 'deterministic', 'reason': 'sole_candidate',
                             'choices': {'a0': 'Choice 0'}, 'selected': 'a0'}
        finally:
            await service.aclose()
    asyncio.run(check())


def test_reload_operation_resolves_single_action_without_second_call():
    from adversary.models.action import ReloadAction
    class ChooseReload(Backend):
        def predict(self, state, choices):
            assert 'reload' in choices
            self.choices.append(choices)
            return 'reload', .4, {'done': .6, 'reload': .4}
    async def check():
        backend = ChooseReload()
        service = LayaDecisionService(max_calls=1, backend=backend)
        original = request(11)
        req = original.model_copy(update={'candidates': original.candidates + (
            CandidateAction(id='a14', description='Reload', action=ReloadAction()),)})
        try:
            assert await service.choose(req, []) == 'a14'
            assert service.calls == len(backend.choices) == 1
            first, second = service.take_metrics('r1')['stages']
            assert first['selection'] == 'model' and first['answer_confidence'] == .4
            assert second['selection'] == 'deterministic'
            assert second['selected'] == 'a14'
            assert 'answer_confidence' not in second and 'inference_ms' not in second
        finally:
            await service.aclose()
    asyncio.run(check())


def test_full_distribution_survives_backend_and_recording(tmp_path):
    from adversary.inference.laya import LayaBackend
    from adversary.runtime.recording import Recorder
    probabilities = {'a0': .2345, 'a1': .7655}
    class Agent:
        def predict(self, state, questions):
            return {'answers': {'action': {'choice': 'a1', 'answer_confidence': .7655,
                                           'probabilities': probabilities}}, 'usage': {}}
    async def check():
        backend = LayaBackend()
        backend.agent = Agent()  # Real backend extraction without loading weights.
        service = LayaDecisionService(backend=backend)
        try:
            assert await service.choose(request(), []) == 'a1'
            metrics = service.take_metrics('r1')
            assert metrics['stages'][0]['probabilities'] == probabilities
            recorder = Recorder(tmp_path / 'record')
            recorder.write('decision', request_id='r1', inference=metrics)
            recorder.finish({'status': 'no_findings'})
            event = json.loads((tmp_path / 'record/actions.jsonl').read_text().splitlines()[0])
            assert event['inference']['stages'][0]['probabilities'] == probabilities
            report = (tmp_path / 'record/report.html').read_text()
            assert '23.45%' in report and '76.55%' in report
        finally:
            await service.aclose()
    asyncio.run(check())


@pytest.mark.parametrize('probabilities', [
    {'a0': 1.0}, {'a0': .3, 'invented': .7}, {'a0': -.1, 'a1': 1.1},
    {'a0': float('nan'), 'a1': .7}, {'a0': .2, 'a1': .2},
])
def test_invalid_probability_distributions_rejected(probabilities):
    class Invalid(Backend):
        def predict(self, state, choices):
            return 'a1', .7, probabilities
    async def check():
        service = LayaDecisionService(backend=Invalid())
        try:
            with pytest.raises(ValueError, match='probability distribution'):
                await service.choose(request(), [])
        finally:
            await service.aclose()
    asyncio.run(check())

import asyncio
import json

import httpx
import pytest

from adversary.inference.openai import BudgetExhausted, DecisionService, credentials
from adversary.models.action import CandidateAction, DoneAction
from adversary.models.decision import AgentContext, DecisionRequest
from adversary.models.observation import BrowserObservation
from adversary.runtime.browser import ActionPolicy
from adversary.runtime.recording import Recorder, fingerprint


def request():
    return DecisionRequest(id='r1', agent=AgentContext(session_id='s1', strategy='custom', goal='Finish'),
        observation=BrowserObservation(id='o1', session_id='s1', step=0, url='http://127.0.0.1:8011/'),
        candidates=(CandidateAction(id='a1', description='Finish', action=DoneAction(reason='complete')),))


@pytest.mark.parametrize('url', ['https://example.com', 'http://127.0.0.1:8001', 'http://localhost:8011',
                                 'http://127.0.0.1:8000'])
def test_live_or_nonfixture_origin_rejected(url):
    with pytest.raises(ValueError):
        ActionPolicy(url)


@pytest.mark.parametrize('url', ['//example.com/', 'http://127.0.0.1:8001/', 'javascript:alert(1)',
    'file:///etc/passwd', 'http://user:password@127.0.0.1:8011/', 'https://127.0.0.1:8011/',
    'http://127.0.0.1.evil.example:8011/'])
def test_cross_origin_action_rejected(url):
    with pytest.raises(ValueError):
        ActionPolicy('http://127.0.0.1:8011').resolve(url)


def test_relative_qa_path_preserves_query():
    assert ActionPolicy('http://127.0.0.1:8011').resolve('/artists?q=a') == 'http://127.0.0.1:8011/artists?q=a'


def test_credentials_only_parse_selected_values(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_CHAT_MODEL', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    path = tmp_path / '.env'
    path.write_text('OPENAI_API_KEY=synthetic-key\nOPENAI_CHAT_MODEL=synthetic-model\nDATABASE_URL=must-not-load\n')
    assert credentials(path) == ('synthetic-key', 'synthetic-model')
    import os
    assert 'DATABASE_URL' not in os.environ
    assert 'OPENAI_API_KEY' not in os.environ


def test_concurrent_budget_is_atomic_and_errors_are_charged():
    async def check():
        service = DecisionService('synthetic', 'model', 2)
        entered = []
        async def call():
            entered.append(1)
            await asyncio.sleep(.01)
            raise ValueError('provider failed')
        results = await asyncio.gather(*(service.invoke(call) for _ in range(6)), return_exceptions=True)
        assert len(entered) == service.calls == 2
        assert sum(isinstance(x, BudgetExhausted) for x in results) == 4
    asyncio.run(check())


@pytest.mark.parametrize('output', ['{"candidate_id":"a1"}', '{"candidate_id":"unknown"}',
                                   '{"candidate_id":"a1","code":"evil"}', 'invalid'])
def test_openai_structured_choice_validation(output):
    async def check():
        def handler(req):
            body = json.loads(req.content)
            assert body['store'] is False
            assert body['max_output_tokens'] == 256
            assert body['text']['format']['schema']['properties']['candidate_id']['enum'] == ['a1']
            return httpx.Response(200, json={'status': 'completed', 'output': [
                {'type': 'message', 'content': [{'type': 'output_text', 'text': output}]}]})
        service = DecisionService('synthetic', 'model', 1, httpx.MockTransport(handler))
        if output == '{"candidate_id":"a1"}':
            assert await service.choose(request(), []) == 'a1'
        else:
            with pytest.raises((ValueError, KeyError)):
                await service.choose(request(), [])
        assert service.calls == 1
    asyncio.run(check())


def test_openai_error_does_not_expose_response_credentials():
    async def check():
        transport = httpx.MockTransport(lambda req: httpx.Response(401, text='sensitive-provider-body'))
        service = DecisionService('synthetic', 'model', 1, transport)
        with pytest.raises(RuntimeError, match='HTTP 401') as error:
            await service.choose(request(), [])
        assert 'sensitive-provider-body' not in str(error.value)
    asyncio.run(check())


def test_intent_is_readable_before_execution_and_report_escapes_html(tmp_path):
    recorder = Recorder(tmp_path / 'run')
    recorder.write('intent', step=0, action={'type': 'click'})
    assert json.loads((recorder.directory / 'actions.jsonl').read_text())['kind'] == 'intent'
    recorder.write('finding', message='<script>bad()</script>')
    recorder.finish({'status': 'findings'})
    assert '<script>bad()' not in (recorder.directory / 'report.html').read_text()
    with pytest.raises(FileExistsError):
        Recorder(tmp_path / 'run')


def test_fingerprint_ignores_ephemeral_origin_but_not_failure_type():
    assert fingerprint('error', 'http://127.0.0.1:1234/a') == fingerprint('error', 'http://127.0.0.1:4567/a')
    assert fingerprint('error', 'a') != fingerprint('crash', 'a')


@pytest.mark.parametrize('mutation', ['orphan', 'duplicate_result', 'out_of_order', 'external_navigation', 'wrong_version'])
def test_replay_rejects_corrupt_or_incomplete_journal(tmp_path, mutation):
    from adversary.runtime.qa import FIXTURE_VERSION
    from adversary.runtime.replay import load_session
    events = [dict(schema_version=1, kind='run', fixture=FIXTURE_VERSION, origin='http://127.0.0.1:8011', config={}),
              dict(schema_version=1, kind='intent', step=0, action={'type': 'navigate', 'url': '/artists'}),
              dict(schema_version=1, kind='result', step=0, status='ok')]
    if mutation == 'orphan':
        events.pop()
    elif mutation == 'duplicate_result':
        events.append(events[-1])
    elif mutation == 'out_of_order':
        events[1]['step'] = 1
    elif mutation == 'external_navigation':
        events[1]['action']['url'] = 'http://127.0.0.1:8001/'
    else:
        events[0]['schema_version'] = 2
    (tmp_path / 'actions.jsonl').write_text('\n'.join(json.dumps(e) for e in events))
    with pytest.raises(ValueError):
        load_session(tmp_path)


def test_replay_accepts_complete_failed_action(tmp_path):
    from adversary.runtime.qa import FIXTURE_VERSION
    from adversary.runtime.replay import load_session
    recorder = Recorder(tmp_path / 'run')
    recorder.write('run', fixture=FIXTURE_VERSION, origin='http://127.0.0.1:8011', config={})
    recorder.write('intent', step=0, action={'type': 'navigate', 'url': '/artists'})
    recorder.write('result', step=0, status='error')
    recorder.finish({'status': 'harness_error'})
    assert len(load_session(tmp_path / 'run')[0]) == 4


def test_browser_use_model_uses_same_budget_without_hidden_retries():
    from adversary.engines.browser_use import BoundedModel
    class FakeModel:
        model = 'synthetic-model'
        calls = 0
        async def ainvoke(self, messages, output_format, **kwargs):
            self.calls += 1
            return 'choice'
    async def check():
        service = DecisionService('synthetic', 'synthetic-model', 1)
        model = FakeModel()
        wrapper = BoundedModel(model, service)
        assert await wrapper.ainvoke([]) == 'choice'
        with pytest.raises(BudgetExhausted):
            await wrapper.ainvoke([])
        assert model.calls == service.calls == 1
        assert service.exhausted
    asyncio.run(check())


def test_long_accessible_name_does_not_break_candidate_contract():
    from adversary.runtime.browser import BrowserAdapter
    from adversary.models.action import ElementLocator, LocatorAlternative
    from adversary.models.observation import BrowserElement
    adapter = BrowserAdapter(None, 'http://127.0.0.1:8011', 's1', None)
    locator = ElementLocator(observation_id='o1', element_id='e0', alternatives=(LocatorAlternative(kind='css', value='#search'),))
    adapter.observation = BrowserObservation(id='o1', session_id='s1', step=0, url='http://127.0.0.1:8011',
        elements=(BrowserElement(locator=locator, accessible_name='x' * 512),))
    adapter.raw = [dict(tag='input', type='text', disabled=False)]
    candidates = adapter.candidates(('synthetic value',))
    assert all(len(c.description) <= 512 for c in candidates)
    assert candidates[-1].action.type == 'done'


def test_dropdown_candidates_preserve_option_values():
    from adversary.runtime.browser import BrowserAdapter
    from adversary.models.action import ElementLocator, LocatorAlternative
    from adversary.models.observation import BrowserElement
    adapter = BrowserAdapter(None, 'http://127.0.0.1:8011', 's1', None)
    locator = ElementLocator(observation_id='o1', element_id='e0',
                             alternatives=(LocatorAlternative(kind='css', value='#catalog-search-kind'),))
    adapter.observation = BrowserObservation(id='o1', session_id='s1', step=0, url='http://127.0.0.1:8011',
        elements=(BrowserElement(locator=locator, accessible_name='Search by'),))
    adapter.raw = [dict(tag='select', type='select-one', options=[
        {'value':v,'label':v.title()} for v in ('artist','album','track')])]
    choices = adapter.candidates(())
    assert [c.action.values for c in choices[:3]] == [('artist',),('album',),('track',)]
    assert choices[2].description == 'Select Track in Search by'

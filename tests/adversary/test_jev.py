import json

import httpx
import pytest

from adversary.inference.jev import ENDPOINT, JevClient, JevError, credentials


def response():
    return {'model': 'jev-test', 'answers': {'action': {'type': 'choice', 'choice': 'fill',
            'probabilities': {'fill': .8, 'reload': .2}, 'confidence': .6}},
            'usage': {'input_tokens': 25, 'output_tokens': 3}}


def test_wire_format_and_distinct_confidence():
    def handle(request):
        assert str(request.url) == ENDPOINT
        assert request.headers['authorization'] == 'Bearer test-key'
        assert request.method == 'POST'
        body = json.loads(request.content)
        assert body['state'] == 'Empty search field'
        assert body['questions']['action']['criteria'] == {'fill': 'Type', 'reload': 'Refresh'}
        assert 'expected' not in body
        return httpx.Response(200, json=response())
    result = JevClient('test-key', transport=httpx.MockTransport(handle)).predict(
        'Empty search field', {'fill': 'Type', 'reload': 'Refresh'})
    assert result['selected_probability'] == .8
    assert result['provider_confidence'] == .6


@pytest.mark.parametrize('status', [302, 401, 402, 422, 429, 500])
def test_http_errors_redacted_without_retries_or_redirects(status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, text='secret-key', headers={'location': 'https://example.com'})
    with pytest.raises(JevError) as caught:
        JevClient('secret-key', transport=httpx.MockTransport(handle)).predict('state', {'a': 'A', 'b': 'B'})
    assert str(status) in str(caught.value)
    assert 'secret-key' not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize('mutation', ['unknown', 'missing', 'negative', 'sum', 'confidence', 'json'])
def test_invalid_responses(mutation):
    data = response()
    answer = data['answers']['action']
    if mutation == 'unknown': answer['choice'] = 'unknown'
    if mutation == 'missing': del answer['probabilities']['reload']
    if mutation == 'negative': answer['probabilities']['reload'] = -.1
    if mutation == 'sum': answer['probabilities']['reload'] = .8
    if mutation == 'confidence': answer['confidence'] = True
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text='invalid') if mutation == 'json'
                                    else httpx.Response(200, json=data))
    with pytest.raises(JevError, match='invalid choice response'):
        JevClient('test', transport=transport).predict('state', {'fill': 'Type', 'reload': 'Refresh'})


def test_credentials_precedence_and_no_environment_loading(tmp_path, monkeypatch):
    monkeypatch.delenv('JEV_AI_API_KEY', raising=False)
    monkeypatch.delenv('JEV_API_KEY', raising=False)
    env = tmp_path / '.env'
    env.write_text('JEV_API_KEY=legacy\nJEV_AI_API_KEY=canonical\n')
    assert credentials(env) == 'canonical'
    monkeypatch.setenv('JEV_API_KEY', 'environment')
    assert credentials(env) == 'environment'
    monkeypatch.setenv('JEV_AI_API_KEY', 'preferred')
    assert credentials(env) == 'preferred'


def test_transport_error_redacted():
    def fail(request):
        raise httpx.ConnectError('secret-key')
    with pytest.raises(JevError, match='transport failed') as caught:
        JevClient('secret-key', transport=httpx.MockTransport(fail)).predict('state', {'a': 'A', 'b': 'B'})
    assert 'secret-key' not in str(caught.value)

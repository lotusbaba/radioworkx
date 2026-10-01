import json

from adversary.inference.jev import JevError
from scripts.jev_goal_probe import run_probe
from scripts.laya_goal_probe import CHOICES, cases


class FakeClient:
    model = 'fake-model'

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def predict(self, state, choices):
        self.calls.append((state, choices))
        if self.fail:
            raise JevError('Jev request failed (HTTP 401)')
        return {'selected': 'fill', 'probabilities': {c: float(c == 'fill') for c in choices},
                'provider_confidence': .7, 'selected_probability': 1, 'model': self.model, 'usage': {}}


def test_same_seven_inputs_and_report(tmp_path):
    client = FakeClient()
    output = tmp_path / 'run'
    result = run_probe(client, output)
    assert client.calls == [(case['state'], CHOICES) for case in cases()]
    assert result['completed_cases'] == 7
    assert result['matches_expected'] == 4
    assert not result['browser_executed']
    assert len((output / 'results.jsonl').read_text().splitlines()) == 7
    assert json.loads((output / 'summary.json').read_text()) == result
    assert 'Text-only diagnostic' in (output / 'review.html').read_text()


def test_failure_stops_calls_but_writes_report(tmp_path):
    client = FakeClient(fail=True)
    result = run_probe(client, tmp_path / 'run')
    assert len(client.calls) == 1
    assert result['completed_cases'] == 0
    assert result['requests_attempted'] == 1
    assert [r['status'] for r in result['results']] == ['error'] + ['not_run'] * 6


def test_only_comparable_baseline_included(tmp_path):
    baseline = {'results': [{**case, 'choices': CHOICES, 'selected': 'reload',
                            'probabilities': {}, 'matches_expected': False} for case in cases()]}
    baseline['results'][0]['state'] = 'different input'
    result = run_probe(FakeClient(), tmp_path / 'run', baseline)
    assert 'laya_comparison' not in result['results'][0]
    assert all('laya_comparison' in row for row in result['results'][1:])

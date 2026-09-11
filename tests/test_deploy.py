import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('deploy', Path(__file__).parents[1] / 'scripts/deploy.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, 'STATE', tmp_path)
    return {'active': 'api', 'images': {'api': 'sha256:old', 'api-next': 'sha256:new'},
            'drain_seconds': 30, 'switching': {'old': 'api', 'new': 'api-next'}}


def test_recover_switch_keeps_previous_image_and_drains_old_only(state, monkeypatch):
    monkeypatch.setattr(deploy, 'upstream', lambda state: 'api-next')
    observed = []
    monkeypatch.setattr(deploy, 'finish_drain', lambda state: observed.append(state['draining']['service']))
    deploy.recover(state)
    assert state['active'] == 'api-next'
    assert state['previous'] == 'sha256:old'
    assert observed == ['api']
    assert 'switching' not in state


def test_failed_switch_recovery_keeps_serving_old(state, monkeypatch):
    monkeypatch.setattr(deploy, 'upstream', lambda state: 'api')
    monkeypatch.setattr(deploy, 'finish_drain', lambda state: None)
    deploy.recover(state)
    assert state['active'] == 'api'
    assert 'draining' not in state
    assert 'set $radio_backend api:8000' in (deploy.STATE / 'nginx/nginx.conf').read_text()


def test_unknown_route_never_stops_a_container(state, monkeypatch):
    monkeypatch.setattr(deploy, 'upstream', lambda state: 'unexpected')
    monkeypatch.setattr(deploy, 'compose', lambda *args, **kwargs: pytest.fail('Must not stop containers'))
    with pytest.raises(RuntimeError, match='refusing to stop'):
        deploy.recover(state)
    assert state['active'] == 'api'


def test_drain_cleared_only_after_successful_stop(state, monkeypatch):
    state['draining'] = {'service': 'api', 'until': 0}
    def fail(*args, **kwargs):
        raise RuntimeError('Docker unavailable')
    monkeypatch.setattr(deploy, 'compose', fail)
    with pytest.raises(RuntimeError):
        deploy.finish_drain(state)
    assert state['draining']['service'] == 'api'


def test_same_image_rollout_preserves_previous_release(state, monkeypatch):
    state['images']['api-next'] = state['images']['api']
    state['previous'] = 'sha256:older-release'
    monkeypatch.setattr(deploy, 'upstream', lambda state: 'api-next')
    monkeypatch.setattr(deploy, 'finish_drain', lambda state: None)
    deploy.recover(state)
    assert state['previous'] == 'sha256:older-release'

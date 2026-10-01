"""SOC-01/02/03/06/07/08/11: isolated API adversarial checks."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from fastapi.testclient import TestClient

from app import db, social
from app.api import app
from tests.test_accounts import register, seed, HEADERS


@pytest.fixture
def social_case(metadata):
    seed(metadata)
    owner = register('owner@example.com')
    follower = register('follower@example.com')
    uid = owner.get('/api/account').json()['id']
    fid = follower.get('/api/account').json()['id']
    pid = owner.post('/api/me/playlists', json={'name': 'Public fixture'}).json()['id']
    own = '/api/me/playlists/' + pid
    assert owner.put(own + '/tracks/one').status_code == 200
    assert owner.put(own + '/sharing').status_code == 200
    yield owner, follower, uid, fid, pid
    owner.close()
    follower.close()


def concurrent_calls(calls):
    barrier = threading.Barrier(len(calls))
    def run(call):
        client, method, path = call
        with TestClient(app, headers=HEADERS, cookies=dict(client.cookies)) as isolated_client:
            barrier.wait(timeout=10)
            return isolated_client.request(method, path)
    with ThreadPoolExecutor(max_workers=len(calls)) as executor:
        return list(executor.map(run, calls))


@pytest.mark.parametrize('revoke', ['unshare', 'delete'])
def test_soc01_follow_races_with_revocation(social_case, revoke):
    owner, follower, _, fid, pid = social_case
    path = '/api/me/playlists/' + pid + ('/sharing' if revoke == 'unshare' else '')
    follow, removed = concurrent_calls([
        (follower, 'PUT', '/api/me/following/playlists/' + pid), (owner, 'DELETE', path),
    ])
    assert follow.status_code in (200, 404)
    assert removed.status_code == 200
    assert follower.get('/api/shared/playlists/' + pid).status_code == 404
    response = follower.get('/api/me/social')
    assert response.status_code == 200
    assert response.json()['playlists'] == []
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM playlist_follows WHERE user_id=%s', (fid,)).fetchone()[0] == 0


def test_soc02_republish_does_not_resubscribe_or_remove_listener_follow(social_case):
    owner, follower, uid, _, pid = social_case
    share = '/api/me/playlists/' + pid + '/sharing'
    follow = '/api/me/following/playlists/' + pid
    assert follower.put('/api/me/following/people/' + uid).status_code == 200
    for _ in range(3):
        assert owner.put(share).status_code == 200
        assert owner.put(share).status_code == 200
        assert follower.get('/api/me/social').json()['playlists'] == []
        assert follower.put(follow).status_code == 200
        assert owner.delete(share).status_code == 200
        assert owner.delete(share).status_code == 200
        result = follower.get('/api/me/social').json()
        assert result['playlists'] == []
        assert [p['id'] for p in result['people']] == [uid]
    assert owner.put(share).status_code == 200
    assert follower.get('/api/me/social').json()['playlists'] == []


@pytest.mark.parametrize('kind', ['people', 'playlists'])
def test_soc03_concurrent_last_slot_and_idempotency_at_limit(social_case, kind):
    owner, follower, uid, fid, _ = social_case
    # Seed the quota directly; do not issue a request flood or hash 101 passwords.
    with db.transaction() as c:
        template = c.execute('SELECT * FROM users WHERE id=%s', (uid,)).fetchone()
        targets = [f'quota-{i}' for i in range(101)]
        for i, target in enumerate(targets):
            if kind == 'people':
                c.execute('INSERT INTO users(id,email,password_hash,created) VALUES(%s,%s,%s,%s)',
                          (target, f'quota-{i}@example.com', template['password_hash'], template['created']))
                if i < 99:
                    c.execute('INSERT INTO listener_follows VALUES(%s,%s)', (fid, target))
            else:
                c.execute('INSERT INTO user_playlists VALUES(%s,%s,%s,%s)', (target, uid, target, i))
                c.execute('INSERT INTO shared_playlists VALUES(%s)', (target,))
                if i < 99:
                    c.execute('INSERT INTO playlist_follows VALUES(%s,%s)', (fid, target))
    responses = concurrent_calls([(follower, 'PUT', f'/api/me/following/{kind}/{target}') for target in targets[-2:]])
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert follower.put(f'/api/me/following/{kind}/{targets[0]}').status_code == 200
    result = follower.get('/api/me/social')
    assert result.status_code == 200
    assert len(result.json()[kind]) == 100


def social_snapshot():
    with db.connect() as c:
        return {table: sorted(repr(dict(row)) for row in c.execute('SELECT * FROM ' + table))
                for table in ('user_playlists', 'user_playlist_tracks', 'shared_playlists',
                              'listener_profiles', 'listener_follows', 'playlist_follows')}


@pytest.mark.parametrize('identity', ['follower', 'guest'])
@pytest.mark.parametrize('operation', ['rename', 'add_track', 'remove_track', 'delete', 'share', 'unshare'])
def test_soc06_following_never_grants_owner_mutations(social_case, identity, operation):
    owner, follower, _, _, pid = social_case
    assert follower.put('/api/me/following/playlists/' + pid).status_code == 200
    path = '/api/me/playlists/' + pid
    method, suffix, body = {
        'rename': ('PATCH', '', {'name': 'stolen'}),
        'add_track': ('PUT', '/tracks/two', None),
        'remove_track': ('DELETE', '/tracks/one', None),
        'delete': ('DELETE', '', None), 'share': ('PUT', '/sharing', None),
        'unshare': ('DELETE', '/sharing', None),
    }[operation]
    before = social_snapshot()
    client = follower if identity == 'follower' else TestClient(app, headers=HEADERS)
    response = client.request(method, path + suffix, json=body)
    assert response.status_code == (404 if identity == 'follower' else 401)
    assert social_snapshot() == before


@pytest.mark.parametrize('revoke', ['unshare', 'delete'])
def test_soc07_disappearing_follow_does_not_fail_collection(social_case, monkeypatch, revoke):
    owner, follower, _, _, pid = social_case
    assert follower.put('/api/me/following/playlists/' + pid).status_code == 200
    original = social.shared_playlist
    called = False
    def disappear(c, playlist_id):
        nonlocal called
        if playlist_id == pid and not called:
            called = True
            # This callback runs after collection() has fetched the follow IDs,
            # but before it reads the corresponding playlist (READ COMMITTED).
            suffix = '/sharing' if revoke == 'unshare' else ''
            assert owner.delete('/api/me/playlists/' + pid + suffix).status_code == 200
        return original(c, playlist_id)
    monkeypatch.setattr(social, 'shared_playlist', disappear)
    response = follower.get('/api/me/social')
    assert called
    assert response.status_code == 200, response.text
    assert response.json()['playlists'] == []


@pytest.mark.parametrize('protection', ['missing_header', 'foreign_origin', 'revoked'])
@pytest.mark.parametrize('operation', ['profile', 'share', 'unshare', 'follow_person', 'unfollow_person', 'follow_playlist', 'unfollow_playlist'])
def test_soc11_all_social_mutations_enforce_request_and_session_rules(social_case, protection, operation):
    owner, follower, uid, _, pid = social_case
    method, path, body, authenticated = {
        'profile': ('PUT', '/api/me/profile', {'name': 'unexpected'}, owner),
        'share': ('PUT', f'/api/me/playlists/{pid}/sharing', None, owner),
        'unshare': ('DELETE', f'/api/me/playlists/{pid}/sharing', None, owner),
        'follow_person': ('PUT', f'/api/me/following/people/{uid}', None, follower),
        'unfollow_person': ('DELETE', f'/api/me/following/people/{uid}', None, follower),
        'follow_playlist': ('PUT', f'/api/me/following/playlists/{pid}', None, follower),
        'unfollow_playlist': ('DELETE', f'/api/me/following/playlists/{pid}', None, follower),
    }[operation]
    assert follower.put(f'/api/me/following/people/{uid}').status_code == 200
    assert follower.put(f'/api/me/following/playlists/{pid}').status_code == 200
    cookies = dict(authenticated.cookies)
    headers = {} if protection == 'missing_header' else HEADERS.copy()
    if protection == 'foreign_origin':
        headers['Origin'] = 'https://foreign.example'
    if protection == 'revoked':
        assert authenticated.post('/api/account/logout').status_code == 200
    before = social_snapshot()
    with TestClient(app, cookies=cookies, headers=headers) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == (401 if protection == 'revoked' else 403)
    assert social_snapshot() == before


def test_soc08_public_payloads_exclude_private_canaries(social_case):
    owner, follower, uid, _, pid = social_case
    create = owner.post('/api/me/playlists', json={'name': 'PRIVATE-PLAYLIST-CANARY'})
    assert create.status_code == 201
    assert owner.put('/api/me/likes/two').status_code == 200
    public = follower.get('/api/shared/playlists/' + pid)
    profile = follower.get('/api/people/' + uid)
    for response in (public, profile):
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        for secret in ('owner@example.com', 'PRIVATE-PLAYLIST-CANARY', 'private.example', 'private rights', 'password_hash'):
            assert secret not in response.text
    assert set(public.json()) == {'id', 'name', 'owner', 'tracks'}
    assert set(profile.json()) == {'id', 'name', 'playlists'}
    assert set(public.json()['owner']) == {'id', 'name'}

"""PL-07 and AUTH-07 regression scenarios against disposable RadioWorkx state.

Known requirement gaps are strict xfails, limited to specific exception types.
Remove the relevant marker when implementing the feature. Other failures are errors.
Browser coverage is opt-in: RWX_BROWSER_TESTS=1 (installed Chrome + Playwright).
"""
import json
import math
import os
import re
import socket
import struct
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app import db
from app.api import app
from app.library import album_ref


HEADERS = {'X-RWX-Request': '1'}
PASSWORD = 'synthetic-test-password-123'


class DuplicatePlaylistNameAllowed(AssertionError):
    """The known PL-07 requirement gap, not an arbitrary test error."""


class AuthenticationNavigatesAway(AssertionError):
    """The known AUTH-07 prerequisite gap."""


def account(email):
    client = TestClient(app, headers=HEADERS)
    response = client.post('/api/account/register', json={'email': email, 'password': PASSWORD})
    assert response.status_code == 201, response.text
    return client


def create(client, name):
    response = client.post('/api/me/playlists', json={'name': name})
    assert response.status_code == 201, response.text
    return response.json()['id']


def playlists(client):
    response = client.get('/api/me/music')
    assert response.status_code == 200, response.text
    return response.json()['playlists']


@pytest.mark.xfail(strict=True, raises=DuplicatePlaylistNameAllowed,
                   reason='PL-07: create/rename currently allow duplicate playlist names')
@pytest.mark.parametrize('operation', ['create', 'rename', 'concurrent_create', 'concurrent_rename'])
@pytest.mark.parametrize('name', ['Road trip', '  Road trip  '], ids=['exact', 'trimmed'])
def test_playlist_duplicate_names(operation, name, metadata):
    """Reject collisions, including races, without losing existing memberships."""
    a = account('a@example.com')
    b = account('b@example.com')
    original = create(a, 'Road trip')
    with db.transaction() as c:
        c.execute('INSERT INTO tracks(id,metadata,status,source,rights) VALUES(%s,%s,%s,%s,%s)',
                  ('one', json.dumps({**metadata, 'id': 'one'}), 'available',
                   'https://example.invalid/synthetic-audio', 'test fixture'))
    assert a.put(f'/api/me/playlists/{original}/tracks/one').status_code == 200
    # Uniqueness is per account, and retaining one's own name is valid.
    create(b, name)
    assert a.patch(f'/api/me/playlists/{original}', json={'name': name}).status_code == 200
    assert playlists(a)[0]['name'] == 'Road trip'

    if operation == 'create':
        before = playlists(a)
        responses = [a.post('/api/me/playlists', json={'name': name})]
        expected = [409]
    elif operation == 'rename':
        other = create(a, 'Evening')
        before = playlists(a)
        responses = [a.patch(f'/api/me/playlists/{other}', json={'name': name})]
        expected = [409]
    else:
        # Race to a previously unused name: exactly one winner is required.
        target = name.replace('Road trip', 'Race playlist')
        ids = [create(a, 'First'), create(a, 'Second')] if operation == 'concurrent_rename' else [None, None]
        before = playlists(a)
        barrier = threading.Barrier(2)

        def attempt(pid):
            # Independent clients share only the synthetic account session.
            client = TestClient(app, headers=HEADERS, cookies=dict(a.cookies))
            try:
                barrier.wait(timeout=5)
                if pid:
                    return client.patch(f'/api/me/playlists/{pid}', json={'name': target})
                return client.post('/api/me/playlists', json={'name': target})
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(attempt, ids))
        expected = [200 if operation == 'concurrent_rename' else 201, 409]

    statuses = sorted(response.status_code for response in responses)
    success = 200 if 'rename' in operation else 201
    # A 500, authorization error, etc. must not be hidden by the xfail marker.
    assert all(status in (success, 409) for status in statuses), statuses
    after = playlists(a)
    by_id = {p['id']: p for p in after}
    old_by_id = {p['id']: p for p in before}
    assert by_id[original] == old_by_id[original], 'Original playlist or tracks changed'
    assert len(playlists(b)) == 1 and playlists(b)[0]['name'] == 'Road trip'
    names = [p['name'] for p in after]
    if statuses != sorted(expected) or len(names) != len(set(names)):
        raise DuplicatePlaylistNameAllowed(f'{operation}: statuses={statuses}; duplicate names accepted')
    if operation in ('create', 'rename'):
        assert after == before, 'Rejected collision changed saved state'
    elif operation == 'concurrent_create':
        assert len(after) == len(before) + 1
    else:
        assert len(after) == len(before)
        for pid in ids:
            assert by_id[pid]['tracks'] == old_by_id[pid]['tracks']


@pytest.fixture
def qa_browser_page(tmp_path, metadata, monkeypatch, request):
    """Reuse app + parent's synthetic DB/Redis fixture and existing smoke pattern."""
    playwright = pytest.importorskip('playwright.sync_api')
    from app import api as api_module, events
    monkeypatch.setattr(api_module, 'r', events.r)
    (tmp_path / 'audio').mkdir()
    audio = tmp_path / 'audio' / 'sample.mp3'
    # Use the same 22.05 kHz synthetic WAV fixture as accounts_smoke.py.
    # Chrome sniffs its format; no host FFmpeg or media download is required.
    with wave.open(str(audio), 'wb') as recording:
        recording.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
        recording.writeframes(b''.join(struct.pack('<h', int(1000 * math.sin(i / 10)))
                                       for i in range(60 * 22050)))
    meta = {**metadata, 'id': 'popup-audio'}
    with db.transaction() as c:
        c.execute('INSERT INTO tracks(id,metadata,status,source,rights,path,duration) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                  (meta['id'], json.dumps(meta), 'ready', 'https://example.invalid/audio',
                   'synthetic fixture', str(audio), 60))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    origin = f'http://127.0.0.1:{sock.getsockname()[1]}'
    # Parent fixture already initialized the isolated schema; no app startup tasks.
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started, 'Disposable QA server did not start'
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            try:
                context = browser.new_context()
                # Synthetic QA playback is intentionally silent. The media clock
                # and pause/restart events remain real; no host audio sink is needed.
                context.add_init_script("document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('audio').forEach(a => a.muted = true), {once:true})")
                artifacts = Path(os.getenv('RWX_TEST_ARTIFACTS', str(tmp_path / 'browser-artifacts'))) / request.node.name
                artifacts.mkdir(parents=True, exist_ok=True)
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                # No request from this context may reach production or a provider.
                context.route('**/*', lambda route: route.continue_()
                              if route.request.url.startswith(origin + '/') else route.abort())
                snapshot = api_module.status()
                context.route(origin + '/api/status', lambda route: route.fulfill(json=snapshot))
                context.route(origin + '/api/events', lambda route: route.fulfill(
                    content_type='text/event-stream', body='event: snapshot\ndata: ' + json.dumps(snapshot) + '\n\n'))
                context.route(origin + '/api/live*', lambda route: route.fulfill(
                    content_type='audio/wav', body=audio.read_bytes()))
                page = context.new_page()
                page.goto(origin + '/albums/' + album_ref(meta)['id'])
                try:
                    yield page, playwright.expect
                finally:
                    try:
                        if not page.is_closed():
                            page.screenshot(path=str(artifacts / 'final.png'), full_page=True)
                    finally:
                        context.tracing.stop(path=str(artifacts / 'trace.zip'))
            finally:
                browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), 'QA server did not shut down'


@pytest.mark.skipif(os.getenv('RWX_BROWSER_TESTS') != '1',
                    reason='Set RWX_BROWSER_TESTS=1 for isolated Chrome integration coverage')
def test_auth_popup_repeated_activation_and_late_failure(qa_browser_page):
    """AUTH-07: repeated opening/dismissal plus a late login failure during playback.

    Successful late login and other source pages remain follow-ups.
    """
    page, expect = qa_browser_page
    page.get_by_role('button', name=re.compile('^Play ')).first.click()
    page.wait_for_function('!document.querySelector("audio").paused && document.querySelector("audio").currentTime > .2')
    original_tracks = page.locator('.track-row').all_text_contents()
    page.evaluate('''() => {
        window.qaAudio = document.querySelector('audio');
        window.qaPlaybackInterruptions = [];
        for (const type of ['pause', 'emptied', 'loadstart'])
            window.qaAudio.addEventListener(type, () => window.qaPlaybackInterruptions.push(type));
    }''')
    start_url = page.url
    start_time = page.locator('audio').evaluate('(a) => a.currentTime')
    trigger = page.locator('[data-account-link]')
    trigger.click()
    # Navigation is now an ordinary regression failure: the popup is implemented.
    if page.url != start_url:
        raise AuthenticationNavigatesAway('Opening authentication navigated away; dialog adversarial steps blocked')
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    auth_requests = []
    page.on('request', lambda req: auth_requests.append(req.url)
            if req.method == 'POST' and '/api/account/' in req.url else None)
    for _ in range(3):
        # Dispatch duplicate activation while the overlay is present.
        trigger.evaluate('(e) => { e.click(); e.click(); }')
        expect(dialog).to_have_count(1)
        page.keyboard.press('Escape')
        expect(dialog).to_be_hidden()
        expect(trigger).to_be_focused()
        trigger.click()
        expect(dialog).to_be_visible()
    assert auth_requests == [], 'Opening/dismissing authentication submitted a request'

    pending = []
    page.route('**/api/account/login', lambda route: pending.append(route))
    try:
        dialog.locator('#email').fill('synthetic@example.com')
        dialog.locator('#password').fill(PASSWORD)
        dialog.get_by_role('button', name='Sign in', exact=True).click()
        deadline = time.monotonic() + 5
        while not pending and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert len(pending) == 1, 'Expected exactly one pending login request'
        page.keyboard.press('Escape')
        expect(dialog).to_be_hidden()
        trigger.click()
        expect(dialog).to_be_visible()
        dialog.locator('#email').fill('new-form@example.com')
        pending.pop().fulfill(status=401, content_type='application/json',
                              body=json.dumps({'detail': 'qa-stale-login-error'}))
        # Allow the fulfilled fetch and its UI continuation to settle.
        page.wait_for_timeout(200)
        expect(dialog.locator('#email')).to_have_value('new-form@example.com')
        expect(dialog).not_to_contain_text('qa-stale-login-error')
        expect(dialog.get_by_role('button', name='Sign in', exact=True)).to_be_enabled()
        page.keyboard.press('Escape')
        expect(dialog).to_be_hidden()
        assert page.url == start_url
        assert page.locator('.track-row').all_text_contents() == original_tracks
        assert page.evaluate('document.querySelector("audio") === window.qaAudio')
        assert page.evaluate('window.qaPlaybackInterruptions') == []
        assert page.locator('audio').evaluate('(a) => !a.paused && a.currentTime') > start_time
    finally:
        for route in pending:
            route.abort()


@pytest.mark.skipif(os.getenv('RWX_BROWSER_TESTS') != '1',
                    reason='Set RWX_BROWSER_TESTS=1 for isolated Chrome integration coverage')
@pytest.mark.parametrize('viewport', [{'width': 1440, 'height': 1000}, {'width': 390, 'height': 844}],
                         ids=['desktop', 'mobile'])
def test_auth_popup_mode_switching_clears_password_without_submitting(qa_browser_page, viewport):
    """AUTH-08: repeated login/register switching, focus, dismissal and audio."""
    page, expect = qa_browser_page
    page.set_viewport_size(viewport)
    page.get_by_role('button', name=re.compile('^Play ')).first.click()
    page.wait_for_function('!document.querySelector("audio").paused && document.querySelector("audio").currentTime > .2')
    initial_url = page.url
    page.evaluate('''() => {
        window.qaAudio = document.querySelector('audio');
        window.qaInterruptions = [];
        for (const kind of ['pause', 'loadstart', 'emptied'])
            qaAudio.addEventListener(kind, () => qaInterruptions.push(kind));
    }''')
    requests = []
    page.on('request', lambda req: requests.append(req.url)
            if req.method == 'POST' and '/api/account/' in req.url else None)
    trigger = page.locator('header [data-auth-mode="login"]')
    trigger.click()
    dialog = page.locator('#auth-dialog')
    expect(dialog).to_be_visible()
    for _ in range(3):
        dialog.locator('#password').fill(PASSWORD)
        dialog.locator('#auth-switch').click()
        expect(dialog.locator('#auth-submit')).to_have_text('Create account')
        expect(dialog.locator('#password')).to_have_value('')
        expect(dialog.locator('#password')).to_have_attribute('autocomplete', 'new-password')
        dialog.locator('#password').fill(PASSWORD)
        dialog.locator('#auth-switch').click()
        expect(dialog.locator('#auth-submit')).to_have_text('Sign in')
        expect(dialog.locator('#password')).to_have_value('')
        expect(page.locator('dialog[open]')).to_have_count(1)
    # Real keyboard traversal stays in the modal, including wrapping.
    dialog.locator('#email').focus()
    for _ in range(8):
        page.keyboard.press('Tab')
        # Native dialogs may transfer focus to browser chrome, never to the
        # inert background page's controls.
        assert dialog.evaluate('(d) => d.contains(document.activeElement) || !document.hasFocus()'), page.evaluate('({tag:document.activeElement.tagName,id:document.activeElement.id,focused:document.hasFocus()})')
    dialog.locator('#password').fill(PASSWORD)
    dialog.get_by_role('button', name='Close sign in', exact=True).click()
    expect(dialog).to_be_hidden()
    expect(trigger).to_be_focused()
    expect(dialog.locator('#password')).to_have_value('')
    trigger.click()
    expect(dialog.locator('#password')).to_have_value('')
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    assert requests == [], 'Mode switching or dismissal submitted authentication'
    assert page.url == initial_url
    assert page.evaluate('qaInterruptions') == []
    assert page.evaluate('document.querySelector("audio") === qaAudio && !qaAudio.paused')
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0


@pytest.mark.skipif(os.getenv('RWX_BROWSER_TESTS') != '1',
                    reason='Set RWX_BROWSER_TESTS=1 for isolated Chrome integration coverage')
def test_home_playlist_late_refresh_after_logout_does_not_restore_private_state(qa_browser_page):
    """HOME-01: release an old collection response after logout completes."""
    page, expect = qa_browser_page
    origin = page.url.split('/albums/')[0]
    owner = account('private-owner@example.com')
    pid = create(owner, 'Private QA playlist')
    assert owner.put(f'/api/me/playlists/{pid}/tracks/popup-audio').status_code == 200
    old_collection = owner.get('/api/me/music').json()
    page.context.add_cookies([{'name': 'rwx_account', 'value': owner.cookies.get('rwx_account'), 'url': origin}])
    page.goto(origin + '/')
    collection = page.locator('#my-music')
    expect(collection.get_by_role('button', name='Private QA playlist (1)', exact=True)).to_be_visible()
    collection.get_by_role('button', name='Private QA playlist (1)', exact=True).click()
    expect(collection.locator('.track-row')).to_have_count(1)
    if not page.evaluate('tuned'):
        page.locator('#listen').click()
    page.wait_for_function('!document.querySelector("#audio").paused && document.querySelector("#audio").currentTime > .1')
    pending = []
    page.route('**/api/me/music', lambda route: pending.append(route))
    try:
        # Deterministically start a refresh without adding a fake UI control.
        page.evaluate('() => { window.qaRefresh = Music.refresh(); }')
        deadline = time.monotonic() + 5
        while not pending and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert len(pending) == 1
        collection.get_by_role('button', name='Sign out', exact=True).click()
        expect(collection.locator('#auth-panel')).to_be_visible()
        expect(collection.locator('.track-row')).to_have_count(0)
        pending.pop().fulfill(json=old_collection)
        # Await the actual refresh continuation, not an arbitrary sleep.
        page.evaluate('() => window.qaRefresh')
        expect(collection).not_to_contain_text('Private QA playlist')
        assert page.url == origin + '/'
        assert page.evaluate('Music.user') is None
        assert page.evaluate('Music.data') == {'likes': [], 'playlists': []}, 'Stale private collection restored after logout'
        assert page.locator('#recording').evaluate('(a) => a.paused && !a.getAttribute("src")')
        assert page.locator('#audio').evaluate('(a) => !a.paused'), 'Logout interrupted live playback'
    finally:
        for route in pending:
            route.abort()
        owner.close()

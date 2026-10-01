"""Browser coverage for SOC-04/05/08/09/10/12; isolated app, synthetic accounts."""
import os
import time

import pytest

from tests.test_account_scenarios import qa_browser_page, account, create, PASSWORD

pytestmark = pytest.mark.skipif(os.getenv('RWX_BROWSER_TESTS') != '1',
                               reason='Set RWX_BROWSER_TESTS=1 for isolated Chrome coverage')


def await_routes(page, pending, count=1):
    deadline = time.monotonic() + 5
    while len(pending) < count and time.monotonic() < deadline:
        page.wait_for_timeout(20)
    assert len(pending) == count


def session(page, client):
    origin = page.url.split('/albums/')[0].split('/playlists/')[0].split('/people/')[0].rstrip('/')
    # All tests call this while on the initial album or known shared page.
    page.context.add_cookies([{'name': 'rwx_account', 'value': client.cookies.get('rwx_account'), 'url': origin}])
    return origin


@pytest.fixture
def sharing(qa_browser_page):
    page, expect = qa_browser_page
    origin = page.url.split('/albums/')[0]
    owner, follower = account('owner@example.com'), account('follower@example.com')
    pid = create(owner, 'Shared QA playlist')
    uid = owner.get('/api/account').json()['id']
    assert owner.put(f'/api/me/playlists/{pid}/tracks/popup-audio').status_code == 200
    assert owner.put(f'/api/me/playlists/{pid}/sharing').status_code == 200
    yield page, expect, origin, owner, follower, uid, pid
    owner.close(); follower.close()


@pytest.mark.parametrize('endpoint', ['music', 'social'])
@pytest.mark.parametrize('change', ['logout', 'account_switch', 'newer_refresh'])
def test_soc05_old_responses_cannot_restore_account_or_refresh_state(sharing, endpoint, change):
    page, expect, origin, owner, follower, _, _ = sharing
    session(page, owner)
    page.goto(origin + '/my-music')
    expect(page.locator('#account-panel')).to_be_visible()
    page.evaluate('() => Music.ready')
    pending = []
    old = owner.get('/api/me/' + endpoint).json()
    page.route('**/api/me/' + endpoint, lambda route: pending.append(route))
    try:
        page.evaluate('() => { window.oldRefresh = Music.refresh(); }')
        await_routes(page, pending)
        if change == 'logout':
            page.locator('#logout').click()
            expect(page.locator('#auth-panel')).to_be_visible()
            expected = {'likes': [], 'playlists': []}
        elif change == 'account_switch':
            page.locator('#logout').click()
            expect(page.locator('#auth-panel')).to_be_visible()
            # Set the synthetic B session, then use the real authentication UI.
            # Login, not direct Music.setUser, owns the account transition.
            page.locator('#auth-panel [data-auth-mode="login"]').click()
            page.locator('#email').fill('follower@example.com')
            page.locator('#password').fill(PASSWORD)
            page.locator('#auth-submit').click()
            await_routes(page, pending, 2)
            pending.pop().fulfill(json=follower.get('/api/me/' + endpoint).json())
            page.wait_for_function('Music.data.social?.profile.name !== undefined && Music.user.email === "follower@example.com"')
            expected = page.evaluate('Music.data')
        else:
            assert owner.put('/api/me/profile', json={'name': 'New public name'}).status_code == 200
            create(owner, 'New playlist')
            page.evaluate('() => { window.newRefresh = Music.refresh(); }')
            await_routes(page, pending, 2)
            pending.pop().fulfill(json=owner.get('/api/me/' + endpoint).json())
            page.evaluate('() => window.newRefresh')
            expected = page.evaluate('Music.data')
        pending.pop().fulfill(json=old)
        page.evaluate('() => window.oldRefresh')
        assert page.evaluate('Music.data') == expected
        if change != 'newer_refresh':
            expect(page.locator('#content')).not_to_contain_text('Shared QA playlist')
    finally:
        for route in pending:
            route.abort()


@pytest.mark.parametrize('kind', ['people', 'playlists'])
def test_soc04_duplicate_follow_and_old_button_after_rerender(sharing, kind):
    page, expect, origin, _, follower, uid, pid = sharing
    session(page, follower)
    page.goto(origin + ('/people/' + uid if kind == 'people' else '/playlists/' + pid))
    label = 'Follow listener' if kind == 'people' else 'Follow playlist'
    button = page.get_by_role('button', name=label, exact=True)
    expect(button).to_be_visible()
    page.evaluate('() => Music.ready')
    pending, methods = [], []
    path = f'**/api/me/following/{kind}/' + (uid if kind == 'people' else pid)
    def hold(route):
        methods.append(route.request.method)
        pending.append(route)
    page.route(path, hold)
    try:
        button.evaluate('(b) => {window.oldButton=b; b.click(); b.click();}')
        await_routes(page, pending)
        # Re-render while the operation is pending; the old control is detached.
        page.evaluate('document.dispatchEvent(new Event("music-changed"))')
        page.evaluate('oldButton.click()')
        route = pending.pop()
        route.fulfill(response=route.fetch())
        expect(page.get_by_role('button', name='Unfollow', exact=True)).to_be_visible()
        assert methods == ['PUT']
        assert len(follower.get('/api/me/social').json()[kind]) == 1
        page.get_by_role('button', name='Unfollow', exact=True).click()
        await_routes(page, pending)
        route = pending.pop(); route.fulfill(response=route.fetch())
        expect(page.get_by_role('button', name=label, exact=True)).to_be_visible()
        assert follower.get('/api/me/social').json()[kind] == []
        assert methods == ['PUT', 'DELETE']
    finally:
        for route in pending:
            route.abort()


def test_soc09_cancel_then_authenticate_follow_during_playback(sharing):
    page, expect, origin, _, follower, _, pid = sharing
    page.goto(origin + '/playlists/' + pid)
    page.get_by_role('button', name='▶ Play all', exact=True).click()
    page.wait_for_function('!document.querySelector("#recording").paused && document.querySelector("#recording").currentTime>.1')
    page.evaluate('''() => {window.interruptions=[];
        for(const kind of ['pause','emptied','loadstart'])
            document.querySelector('#recording').addEventListener(kind,()=>interruptions.push(kind));}''')
    follow = page.get_by_role('button', name='Follow playlist', exact=True)
    requests = []
    page.on('request', lambda request: requests.append(request.method)
            if '/api/me/following/' in request.url else None)
    follow.click()
    expect(page.locator('#auth-dialog')).to_be_visible()
    page.keyboard.press('Escape')
    expect(follow).to_be_enabled()
    assert requests == []
    follow.click()
    page.locator('#email').fill('follower@example.com')
    page.locator('#password').fill(PASSWORD)
    page.locator('#auth-submit').click()
    expect(page.get_by_role('button', name='Unfollow', exact=True)).to_be_visible()
    assert requests == ['PUT']
    assert [p['id'] for p in follower.get('/api/me/social').json()['playlists']] == [pid]
    assert page.url == origin + '/playlists/' + pid
    assert page.evaluate('interruptions') == []


def test_soc08_names_render_as_text_in_public_and_follower_views(sharing):
    page, expect, origin, owner, follower, uid, pid = sharing
    marker = '<svg onload="window.qaXss=1">'
    assert owner.put('/api/me/profile', json={'name': marker}).status_code == 200
    assert owner.patch('/api/me/playlists/' + pid, json={'name': marker}).status_code == 200
    assert follower.put('/api/me/following/playlists/' + pid).status_code == 200
    page.add_init_script('window.qaXss=0')
    for path in ('/people/' + uid, '/playlists/' + pid):
        page.goto(origin + path)
        expect(page.locator('#heading')).to_have_text(marker)
        assert page.evaluate('window.qaXss') == 0
        assert page.locator('#content svg').count() == 0
    session(page, follower)
    page.goto(origin + '/my-music')
    expect(page.locator('#content')).to_contain_text(marker)
    assert page.evaluate('window.qaXss') == 0
    assert page.locator('#content svg').count() == 0


def test_soc10_clipboard_denial_single_fallback_and_revocation(sharing):
    page, expect, origin, owner, _, _, pid = sharing
    session(page, owner)
    page.goto(origin + '/my-music')
    page.get_by_role('button', name='Shared QA playlist (1)', exact=True).click()
    page.evaluate('''() => {Object.defineProperty(navigator,'clipboard',{
        configurable:true,value:{writeText:async()=>{throw Error('QA denied');}}});}''')
    copy = page.get_by_role('button', name='Copy playlist link', exact=True)
    copy.evaluate('(b) => { b.click(); b.click(); }')
    expect(page.locator('dialog[open]')).to_have_count(1)
    copy.evaluate('(b) => b.click()')
    # The overlay must remain unique even if another copy action is dispatched.
    expect(page.locator('dialog[open]')).to_have_count(1)
    expect(page.get_by_role('textbox', name='Share link')).to_have_value(origin + '/playlists/' + pid)
    page.get_by_role('button', name='Done', exact=True).click()
    expect(page.locator('dialog[open]')).to_have_count(0)
    copy.click()
    expect(page.locator('dialog[open]')).to_have_count(1)
    page.keyboard.press('Escape')
    page.once('dialog', lambda dialog: dialog.accept())
    page.get_by_role('button', name='Make private', exact=True).click()
    expect(page.get_by_role('button', name='Share playlist', exact=True)).to_be_visible()
    assert owner.get('/api/shared/playlists/' + pid).status_code == 404


@pytest.mark.parametrize('revoke', ['unshare', 'delete'])
def test_soc12_revoked_shared_page_rejects_follow_and_fresh_reads(sharing, revoke):
    page, expect, origin, owner, follower, _, pid = sharing
    session(page, follower)
    page.goto(origin + '/playlists/' + pid)
    expect(page.locator('#heading')).to_have_text('Shared QA playlist')
    suffix = '/sharing' if revoke == 'unshare' else ''
    assert owner.delete('/api/me/playlists/' + pid + suffix).status_code == 200
    page.get_by_role('button', name='Follow playlist', exact=True).click()
    expect(page.locator('#error')).to_contain_text('private or no longer available')
    assert follower.get('/api/me/social').json()['playlists'] == []
    page.reload()
    expect(page.locator('#heading')).to_have_text('Music unavailable')
    expect(page.locator('.track-row')).to_have_count(0)
    # Navigate and return: revalidated public content must remain unavailable.
    page.goto(origin + '/artists'); page.go_back()
    expect(page.locator('#heading')).to_have_text('Music unavailable')
    assert follower.get('/api/shared/playlists/' + pid).status_code == 404

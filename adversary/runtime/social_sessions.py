"""Deterministic multi-identity social protocol with shared disposable data.

API requests use each browser context's cookie jar. Race scheduling is concurrent,
not claimed to reproduce a particular database interleaving.
"""
import asyncio
from adversary.runtime.qa import qa_target
from adversary.runtime.recording import Recorder
from adversary.runtime.coordinator import browser_env


async def social_protocol(clients, record):
    async def call(role, method, path, body=None, expected=(200,)):
        response = await clients[role].fetch(path, method=method, data=body,
            headers={'X-RWX-Request': '1'})
        record('social_request', role=role, method=method, path=path,
               status=response.status, expected=list(expected))
        if response.status not in expected:
            raise AssertionError(f'{role} {method} {path}: unexpected status {response.status}')
        return response

    async def check(name, condition):
        record('check', name=name, passed=bool(condition))
        if not condition:
            raise AssertionError(name)

    for role in ('owner', 'follower'):
        await call(role, 'POST', '/api/account/register',
            {'email': f'{role}@example.com', 'password': 'Synthetic QA password 123!'}, (201,))
    owner = (await (await call('owner', 'GET', '/api/account')).json())['id']
    follower = (await (await call('follower', 'GET', '/api/account')).json())['id']
    await check('distinct authenticated identities', owner != follower)
    await call('guest', 'GET', '/api/account', expected=(401,))
    playlist = (await (await call('owner', 'POST', '/api/me/playlists',
                                 {'name': 'Coordinated QA playlist'}, (201,))).json())['id']
    own = '/api/me/playlists/' + playlist
    public = '/api/shared/playlists/' + playlist
    follow = '/api/me/following/playlists/' + playlist
    await call('owner', 'PUT', own + '/tracks/qa-track')
    await call('guest', 'GET', public, expected=(404,))
    await call('owner', 'PUT', own + '/sharing')
    await call('guest', 'GET', public)
    await call('follower', 'PUT', follow)
    for role, status in (('follower', 404), ('guest', 401)):
        await call(role, 'PATCH', own, {'name': 'Unauthorized'}, (status,))
    data = await (await call('owner', 'GET', public)).json()
    await check('unauthorized rename leaves playlist unchanged', data['name'] == 'Coordinated QA playlist')
    await call('follower', 'PUT', '/api/me/following/people/' + owner)
    for revoke in ('unshare', 'delete'):
        record('barrier', phase=revoke, participants=['owner', 'follower'])
        await asyncio.gather(
            call('follower', 'PUT', follow, expected=(200, 404)),
            call('owner', 'DELETE', own + ('/sharing' if revoke == 'unshare' else '')))
        await call('guest', 'GET', public, expected=(404,))
        await call('follower', 'GET', public, expected=(404,))
        data = await (await call('follower', 'GET', '/api/me/social')).json()
        await check(revoke + ': playlist follows removed', not data['playlists'])
        await check(revoke + ': listener follow preserved', [p['id'] for p in data['people']] == [owner])
        if revoke == 'unshare':
            await call('owner', 'PUT', own + '/sharing')
            data = await (await call('follower', 'GET', '/api/me/social')).json()
            await check('republishing does not resubscribe follower', not data['playlists'])
            await call('follower', 'PUT', follow)


async def coordinate_social(directory, channel='chrome'):
    from playwright.async_api import async_playwright
    recorder = Recorder(directory)
    summary = {'status': 'harness_error', 'scenario': 'coordinated-social',
               'model_calls': 0, 'identities': ['owner', 'follower', 'guest']}
    contexts = []
    try:
        async with asyncio.timeout(120), qa_target() as origin, async_playwright() as pw:
            browser = await pw.chromium.launch(channel=channel, headless=True, env=browser_env())
            try:
                clients = {}
                for role in summary['identities']:
                    context = await browser.new_context(base_url=origin, service_workers='block')
                    contexts.append(context)
                    await context.tracing.start(screenshots=True, snapshots=True)
                    page = await context.new_page()
                    # The protocol never navigates to user-provided URLs.
                    await page.goto(origin + '/')
                    clients[role] = context.request
                await social_protocol(clients, recorder.write)
                summary['status'] = 'passed'
            finally:
                for role, context in zip(summary['identities'], contexts):
                    await context.tracing.stop(path=str(directory / (role + '-trace.zip')))
                    await context.close()
                await browser.close()
    except AssertionError as error:
        summary.update(status='failed', failure=str(error))
    except Exception as error:
        summary.update(status='harness_error', error_type=type(error).__name__)
    finally:
        summary['checks'] = sum(e['kind'] == 'check' for e in recorder.events)
        summary['requests'] = sum(e['kind'] == 'social_request' for e in recorder.events)
        recorder.finish(summary)
    return summary

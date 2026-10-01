"""Opt-in real Chrome + synthetic RadioWorkx checks; no model calls."""
import asyncio
import json
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv('RWX_FRAMEWORK_TESTS') != '1', reason='Set RWX_FRAMEWORK_TESTS=1; requires Chrome + disposable PostgreSQL')


def test_two_sessions_and_fresh_fixture_replay(tmp_path):
    from adversary.runtime.coordinator import coordinate
    from adversary.runtime.replay import load_session
    config = dict(engine='scripted', scenario='library-search', agents=2, max_steps=5,
                  timeout=90, headed=False, channel='chrome')
    async def check():
        result = await coordinate(tmp_path / 'original', config)
        assert result['model_calls'] == 0
        assert all(s['status'] == 'no_findings' and s['termination'] == 'completed' and s['actions'] == 5 for s in result['sessions'])
        events, first = load_session(tmp_path / 'original' / 'agent-0')
        other = load_session(tmp_path / 'original' / 'agent-1')[1]
        assert first['origin'] != other['origin']
        replay = await coordinate(tmp_path / 'replay', {**config, 'agents': 1}, replay=events)
        assert replay['model_calls'] == 0
        assert replay['sessions'][0]['termination'] == 'replay_complete'
        assert replay['sessions'][0]['actions'] == 5
        for directory in [tmp_path / 'original' / 'agent-0', tmp_path / 'replay' / 'agent-0']:
            assert (directory / 'trace.zip').stat().st_size > 1000
            assert (directory / 'final.png').stat().st_size > 1000
    asyncio.run(check())


def test_policy_and_stale_targets_fail_before_mutation(tmp_path):
    from playwright.async_api import async_playwright
    from adversary.runtime.browser import BrowserAdapter
    from adversary.runtime.coordinator import browser_env
    from adversary.runtime.qa import qa_target
    from adversary.runtime.recording import Recorder
    from adversary.models.action import FillAction, NavigateAction
    async def check():
        async with qa_target() as origin, async_playwright() as playwright:
            browser = await playwright.chromium.launch(channel='chrome', env=browser_env())
            context = await browser.new_context(service_workers='block')
            recorder = Recorder(tmp_path / 'session')
            page = await context.new_page()
            adapter = BrowserAdapter(page, origin, 'test', recorder)
            try:
                await adapter.attach()
                await adapter.execute(NavigateAction(url='/artists'))
                obs = await adapter.observe()
                field = next(e.locator for e in obs.elements if e.accessible_name == 'Search the collection')
                await adapter.observe()
                with pytest.raises(ValueError, match='Stale'):
                    await adapter.execute(FillAction(target=field, value='not applied'))
                assert await page.locator('#search').input_value() == ''
                with pytest.raises(ValueError, match='origin'):
                    await adapter.execute(NavigateAction(url='http://127.0.0.1:8001/'))
                assert adapter.step == 1
                # A same-origin redirect cannot escape the context network guard.
                await context.route(origin + '/escape', lambda route: route.fulfill(status=302, headers={'Location': 'http://127.0.0.1:1/private'}))
                from playwright.async_api import Error
                with pytest.raises(Error):
                    await page.goto(origin + '/escape')
            finally:
                await context.tracing.stop(path=str(tmp_path / 'trace.zip'))
                await browser.close()
                recorder.finish({'status': 'verified'})
    asyncio.run(check())

import asyncio
from contextlib import asynccontextmanager
import json
import html
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, parse_qs

from adversary.models.action import NavigateAction, browser_action_adapter
from adversary.inference.openai import BudgetExhausted
from adversary.runtime.browser import BrowserAdapter
from adversary.runtime.qa import qa_target, FIXTURE_VERSION
from adversary.runtime.recording import Recorder
from adversary.scenarios import SCENARIOS


def browser_env():
    return {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'DISPLAY', 'SYSTEMROOT') if k in os.environ}


@asynccontextmanager
async def browser_use_page(playwright, directory, origin, headed, channel):
    from adversary.engines.browser_use import configure
    configure(directory)
    from browser_use import BrowserSession
    with tempfile.TemporaryDirectory(prefix='rwx-browser-use-') as profile:
        # Playwright owns process creation: the pinned Browser Use launcher does
        # not pass its profile.env to subprocess creation. This keeps credentials
        # out of Chrome and blocks service workers before any target navigation.
        context = await playwright.chromium.launch_persistent_context(
            profile, channel=channel, headless=not headed, env=browser_env(),
            accept_downloads=False, service_workers='block',
            args=['--remote-debugging-port=0', '--autoplay-policy=no-user-gesture-required'])
        session = None
        try:
            port_file = Path(profile) / 'DevToolsActivePort'
            for _ in range(50):
                if port_file.exists():
                    break
                await asyncio.sleep(.1)
            port = int(port_file.read_text().splitlines()[0])
            session = BrowserSession(cdp_url=f'http://127.0.0.1:{port}',
                allowed_domains=[origin], keep_alive=True, enable_default_extensions=False,
                downloads_path=str(Path(profile) / 'downloads'))
            await session.start()
            page = context.pages[0] if context.pages else await context.new_page()
            yield page, session
        finally:
            try:
                if session:
                    await session.stop()
            finally:
                await context.close()


async def oracle(adapter, scenario, start_url):
    if SCENARIOS[scenario].search_kind and adapter.page.url != start_url:
        adapter.find('search_navigation', 'Modal search navigated away from the home page before completion')
    if scenario == 'auth-popup' and adapter.page.url != start_url:
        adapter.find('auth_navigation', 'Authentication interaction navigated away from the starting page')
    if await adapter.page.evaluate('Boolean(window.qaXss)'):
        adapter.find('script_execution', 'Synthetic input executed as page script')
    if scenario in ('playlist-duplicate', 'playlist-duplicate-trimmed'):
        response = await adapter.page.request.get(adapter.policy.origin + '/api/me/music')
        if response.status == 200:
            playlists = (await response.json()).get('playlists', [])
            names = [item['name'].strip() for item in playlists]
            if len(names) != len(set(names)):
                adapter.find('duplicate_playlist', 'Duplicate trimmed playlist names accepted in one account')


async def scripted(adapter, scenario=None):
    scenario = scenario or SCENARIOS['library-search']
    from adversary.models.action import ClickAction, FillAction, SelectAction, DoneAction
    observation = await adapter.observe()
    target = next(e.locator for e in observation.elements if e.accessible_name == 'Search')
    await adapter.execute(ClickAction(target=target))
    await adapter.observe()
    target = next(e.locator for e in adapter.observation.elements if e.accessible_name == 'Search by')
    await adapter.execute(SelectAction(target=target, values=(scenario.search_kind,)))
    await adapter.observe()
    target = next(e.locator for e in adapter.observation.elements if e.accessible_name == 'Search text')
    await adapter.execute(FillAction(target=target, value=scenario.search_query))
    await adapter.page.locator('.catalog-search-result').filter(has_text=scenario.search_result).first.wait_for()
    await adapter.execute(DoneAction(reason='Scripted search smoke complete'))
    return 'completed'


async def run_session(playwright, browser, directory, session_id, config, service, replay=None):
    recorder = Recorder(directory)
    adapter = None
    summary = {'session_id': session_id, 'engine': config['engine'], 'scenario': config['scenario'],
               'fixture': FIXTURE_VERSION, 'status': 'harness_error', 'termination': 'not_started', 'findings': []}
    context = None
    manager = None
    try:
        async with asyncio.timeout(config['timeout']):
            async with qa_target() as origin:
                if config['engine'] == 'browser-use' and replay is None:
                    manager = browser_use_page(playwright, directory, origin, config['headed'], config['channel'])
                    page, native_session = await manager.__aenter__()
                    context = page.context
                else:
                    context = await browser.new_context(accept_downloads=False, service_workers='block')
                    page = await context.new_page()
                    native_session = None
                adapter = BrowserAdapter(page, origin, session_id, recorder, config['max_steps'] + 2)
                adapter.input_bindings = dict(SCENARIOS[config['scenario']].fills)
                await adapter.attach()
                search_finished = asyncio.Event()
                scenario = SCENARIOS[config['scenario']]
                if scenario.search_kind:
                    adapter.goal_complete = search_finished.is_set
                async def check_search(response):
                    parsed = urlsplit(response.url)
                    if (adapter.policy.allows(response.url) and parsed.path == '/api/library/search'
                            and parse_qs(parsed.query).get('kind') == [scenario.search_kind]
                            and parse_qs(parsed.query).get('q') == [scenario.search_query] and response.status == 200):
                        try:
                            data = await response.json()
                            if any(item.get('name') == scenario.search_result for item in data.get('items', [])):
                                await page.locator('dialog[open] .catalog-search-result').filter(has_text=scenario.search_result).first.wait_for(timeout=2000)
                                if (urlsplit(page.url).path == '/'
                                        and await page.locator('#catalog-search-kind').input_value() == scenario.search_kind
                                        and await page.locator('#catalog-search-query').input_value() == scenario.search_query):
                                    search_finished.set()
                        except Exception:
                            pass
                page.on('response', check_search)
                scenario = SCENARIOS[config['scenario']]
                recorder.write('run', config=config, fixture=FIXTURE_VERSION, origin=origin)
                start_url = origin + scenario.path
                try:
                    if replay is not None:
                        for event in replay:
                            if event['kind'] != 'intent':
                                continue
                            action = browser_action_adapter.validate_python(event['action'])
                            if isinstance(action, NavigateAction):
                                parts = urlsplit(action.url)
                                action = action.model_copy(update={'url': parts.path + ('?' + parts.query if parts.query else '')})
                            await adapter.execute(action, replay=True)
                            await oracle(adapter, config['scenario'], start_url)
                        summary['termination'] = 'replay_complete'
                    else:
                        await adapter.execute(NavigateAction(url=scenario.path))
                        # App scripts load data asynchronously; wait for the page's
                        # loading label to clear without networkidle (SSE/media).
                        if scenario.search_kind:
                            await page.locator('#open-catalog-search').wait_for()
                        original_execute = adapter.execute
                        async def checked(action, replay=False):
                            await original_execute(action, replay=replay)
                            await oracle(adapter, config['scenario'], start_url)
                        adapter.execute = checked
                        if config['engine'] == 'scripted':
                            summary['termination'] = await scripted(adapter, scenario)
                        elif config['engine'] == 'custom':
                            from adversary.engines.custom import run
                            summary['termination'] = await run(adapter, service, scenario.goal, scenario.values, config['max_steps'])
                        else:
                            from adversary.engines.browser_use import run
                            summary['termination'] = await run(adapter, native_session, service, scenario.goal, scenario.values, config['max_steps'])
                    summary['status'] = 'findings' if adapter.findings else 'no_findings'
                    if scenario.search_kind:
                        try:
                            await asyncio.wait_for(search_finished.wait(), 1)
                        except TimeoutError:
                            pass
                        summary['goal_achieved'] = search_finished.is_set()
                        if search_finished.is_set() and replay is None and summary['termination'] == 'step_limit':
                            recorder.write('completion', selection='deterministic', reason='goal_verified_at_budget_boundary')
                            summary['termination'] = 'completed'
                        if not search_finished.is_set() and replay is None and summary['termination'] == 'completed':
                            summary.update(termination='goal_not_met', status='incomplete')
                    if summary['termination'] in ('step_limit', 'model_call_limit') and not adapter.findings:
                        summary['status'] = 'incomplete'
                    if summary['termination'] == 'agent_error':
                        summary['status'] = 'harness_error'
                finally:
                    # Evidence is finalized before destroying the QA app/browser.
                    try:
                        await page.screenshot(path=str(directory / 'final.png'), full_page=True, timeout=5000)
                    finally:
                        await context.tracing.stop(path=str(directory / 'trace.zip'))
    except (BudgetExhausted, TimeoutError) as error:
        summary.update(status='findings' if adapter and adapter.findings else 'incomplete',
                       termination='model_call_limit' if isinstance(error, BudgetExhausted) else 'time_limit')
    except Exception as error:
        # Exception bodies from SDKs may contain request details. Store type only.
        summary.update(status='harness_error', termination=type(error).__name__)
        recorder.write('harness_error', error_type=type(error).__name__)
        from adversary.inference.jev import JevError
        if isinstance(error, JevError):
            # JevError contains only adapter-authored messages, never raw provider bodies.
            recorder.write('provider_error', error_type='JevError', detail=str(error))
    finally:
        if adapter:
            summary['findings'] = adapter.findings
            summary['actions'] = adapter.step
            if adapter.findings and summary['status'] in ('no_findings', 'incomplete'):
                summary['status'] = 'findings'
        try:
            if manager:
                await manager.__aexit__(None, None, None)
            elif context:
                await context.close()
        except Exception as error:
            summary.update(status='harness_error', termination='cleanup_' + type(error).__name__)
        finally:
            recorder.finish(summary)
    return summary


async def coordinate(directory, config, service=None, replay=None):
    from playwright.async_api import async_playwright
    directory.mkdir(parents=True, exist_ok=False)
    async with async_playwright() as playwright:
        browser = None
        try:
            if config['engine'] != 'browser-use' or replay is not None:
                browser = await playwright.chromium.launch(channel=config['channel'], headless=not config['headed'],
                    env=browser_env(), args=['--autoplay-policy=no-user-gesture-required'])
            summaries = await asyncio.gather(*(run_session(playwright, browser, directory / f'agent-{i}',
                f'agent-{i}', config, service, replay) for i in range(config['agents'])))
        finally:
            if browser:
                await browser.close()
    result = {'sessions': summaries, 'model_calls': service.calls if service else 0}
    (directory / 'summary.json').write_text(json.dumps(result, indent=2))
    links = ''.join(f'<li><a href="{s["session_id"]}/report.html">{s["session_id"]}</a>: '
                    f'{html.escape(s["status"])} ({html.escape(s["termination"])})</li>' for s in summaries)
    (directory / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Adversary sessions</title>'
        '<h1>Adversary sessions</h1><p>Exploration results; no findings does not prove all requirements passed.</p>'
        f'<p>Model calls: {result["model_calls"]}</p><ul>{links}</ul>')
    return result

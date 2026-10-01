"""Independent single-session goals; no model inference or coordinated sessions."""
import asyncio
import json
import os
import pytest

pytestmark=pytest.mark.skipif(os.getenv('RWX_FRAMEWORK_TESTS')!='1',reason='Opt-in Chrome + disposable PostgreSQL')


@pytest.mark.parametrize('scenario',['library-search','search-album','search-track','search-artist-typo'])
def test_search_goal_and_focused_observation(tmp_path,scenario):
    from adversary.runtime.coordinator import coordinate
    async def check():
        result=await coordinate(tmp_path/'run',dict(engine='scripted',scenario=scenario,
            agents=1,max_steps=6,timeout=90,headed=False,channel='chrome'))
        session=result['sessions'][0]
        assert session['goal_achieved'] and session['termination']=='completed'
        assert result['model_calls']==0
        events=[json.loads(l) for l in (tmp_path/'run/agent-0/actions.jsonl').read_text().splitlines()]
        observations=[e['observation'] for e in events if e['kind']=='observation']
        modal=observations[-1]
        assert 'Search the collection' in modal['visible_text']
        assert 'COMMUNITY PULSE' not in modal['visible_text']
        selected=next(e for e in modal['elements'] if e['accessible_name']=='Search by')
        assert selected['current_value'] in ('artist','album','track')
    asyncio.run(check())


def test_field_values_exclude_password_and_background(tmp_path):
    from playwright.async_api import async_playwright
    from adversary.runtime.browser import BrowserAdapter
    from adversary.runtime.recording import Recorder
    from adversary.runtime.coordinator import browser_env
    async def check():
        async with async_playwright() as p:
            browser=await p.chromium.launch(channel='chrome',env=browser_env())
            try:
                page=await browser.new_page()
                await page.route('**/*',lambda route:route.fulfill(body='''<body>BACKGROUND
                  <dialog><label>Search text<input value="QA Artist"></label>
                  <label>Password<input type="password" value="must-not-record"></label>
                  <label for="kind">Search by</label><select id="kind"><option value="artist">Artist</option>
                  <option value="album" selected>Album</option><option value="track">Track</option></select></dialog>
                  <script>document.querySelector('dialog').showModal()</script>''',content_type='text/html'))
                await page.goto('http://127.0.0.1:8011/')
                adapter=BrowserAdapter(page,'http://127.0.0.1:8011','s',Recorder(tmp_path/'observations'))
                observation=await adapter.observe()
                fields={e.accessible_name:e.current_value for e in observation.elements}
                assert fields['Search text']=='QA Artist'
                assert fields['Password'] is None
                assert fields['Search by']=='album'
                assert 'BACKGROUND' not in observation.visible_text
                assert 'must-not-record' not in observation.model_dump_json()
                options=[c.action.values for c in adapter.candidates(()) if c.action.type=='select']
                assert options==[('artist',),('album',),('track',)]
            finally:await browser.close()
    asyncio.run(check())


@pytest.mark.parametrize('max_steps',[2,6])
def test_custom_engine_stops_on_verified_goal_including_final_step(tmp_path,max_steps):
    from adversary.runtime.coordinator import coordinate
    class Policy:
        calls=0
        def take_metrics(self,_):return {}
        async def choose(self,request,history):
            self.calls+=1
            fields={e.accessible_name:e.current_value for e in request.observation.elements}
            if 'Search text' not in fields:description='Click Search'
            elif fields['Search text']=='':description="Fill Search text: 'QA Artist'"
            else:description='Wait for UI'
            return next(c.id for c in request.candidates if c.description==description)
    async def check():
        policy=Policy()
        result=await coordinate(tmp_path/'run',dict(engine='custom',scenario='library-search',
            agents=1,max_steps=max_steps,timeout=90,headed=False,channel='chrome'),policy)
        session=result['sessions'][0]
        assert session['goal_achieved'] and session['termination']=='completed'
        assert session['status']=='no_findings'
        events=[json.loads(l) for l in (tmp_path/'run/agent-0/actions.jsonl').read_text().splitlines()]
        assert any(e['kind']=='completion' and e['selection']=='deterministic' for e in events)
    asyncio.run(check())

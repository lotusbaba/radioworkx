"""Exercise browser telemetry, indexed events, authenticated timeline and Kibana."""
import json
import time
from pathlib import Path
import httpx
from dotenv import dotenv_values
from playwright.sync_api import sync_playwright

BASE='http://127.0.0.1:8001';ES='http://127.0.0.1:9200';KB='http://127.0.0.1:5601'
out=Path('/tmp/rwx-telemetry-check');out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1050})
    page=context.new_page();errors=[];responses=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on(
        'response',
        lambda response: responses.append(response.status) if '/api/activity' in response.url else None,
    )
    page.goto(BASE+'/artists',wait_until='networkidle')
    page.locator('#search').fill('telemetry-private-search-no-match')
    page.locator('#search-form button').click()
    page.wait_for_function('document.querySelector("#summary").textContent.startsWith("0 ")')
    session=page.evaluate('sessionStorage.getItem("rwx-session")')
    albums=context.request.get(BASE+'/api/library/albums?page_size=100').json()['items']
    album=next(a for a in albums if a['ready'])
    page.goto(BASE+'/albums/'+album['id'],wait_until='networkidle')
    data=context.request.get(BASE+'/api/library/albums/'+album['id']).json()
    track=next(t for t in data['items'] if t['status']=='ready')
    page.get_by_role('button',name='Play '+track['title'],exact=True).click()
    page.wait_for_function('!document.querySelector("audio").paused && document.querySelector("audio").currentTime>32',timeout=60000)
    page.evaluate('document.querySelector("audio").currentTime=90')
    page.wait_for_function('document.querySelector("audio").currentTime>=90')
    page.evaluate('document.querySelector("audio").pause()')
    page.wait_for_timeout(2000)
    page.locator('#stop').click()
    page.wait_for_timeout(6000)
    assert responses and all(s==202 for s in responses),responses
    assert not errors,errors
    with httpx.Client(timeout=15) as client:
        query={'size':100,'query':{'term':{'session.id':session}}}
        for _ in range(30):
            search_response=client.post(ES+'/radioworkx-events-*/_search',json=query)
            search_response.raise_for_status()
            docs=[hit['_source'] for hit in search_response.json()['hits']['hits']]
            actions={d['event']['action'] for d in docs}
            if {'search.results','playback.started','playback.heartbeat','playback.seek','playback.paused'}<=actions:break
            time.sleep(2)
        else:raise AssertionError(actions)
        assert 'telemetry-private-search-no-match' not in json.dumps(docs)
        listened=sum(d['radioworkx'].get('listened_ms',0) for d in docs)
        assert 20000<listened<60000,listened
        print(json.dumps({'indexed_session_actions':sorted(actions),'estimated_listening_seconds':listened/1000,'privacy_verified':True}),flush=True)
    admin=browser.new_context(http_credentials={'username':'admin','password':dotenv_values('.env')['ADMIN_PASSWORD']},viewport={'width':1440,'height':1000}).new_page()
    admin.goto(BASE+'/admin',wait_until='networkidle')
    admin.locator('#activity-rows tr').first.wait_for(timeout=30000)
    admin.locator('#activity-session').fill(session)
    admin.locator('#activity-form button').click()
    admin.wait_for_function('(s)=>document.querySelector("#activity-rows").textContent.includes(s)',arg=session)
    assert not admin.locator('#activity-error').inner_text()
    admin.locator('#activity-panel').screenshot(path=str(out/'admin-activity.png'))
    print(json.dumps({'admin_activity_verified':True}),flush=True)
    kibana=context.new_page()
    for name in ['audience','music','requests','errors']:
        kibana.goto(KB+'/app/dashboards#/view/rwx-'+name,wait_until='domcontentloaded')
        kibana.get_by_text('RadioWorkx',exact=False).first.wait_for(timeout=60000)
        kibana.wait_for_timeout(10000)
        text=kibana.locator('body').inner_text()
        (out/(name+'.txt')).write_text(text)
        kibana.screenshot(path=str(out/(name+'.png')),full_page=True)
        errors_found=[message for message in ['Error loading','Cannot read properties','Unrecognized signal','Cannot find field','Failed to load'] if message in text]
        assert not errors_found,(name,errors_found,text[:3000])
        print(json.dumps({'dashboard':name,'rendered':True,'text_excerpt':text[:200]}),flush=True)
    browser.close()

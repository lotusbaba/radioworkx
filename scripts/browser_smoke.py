"""Optional browser smoke check; pip install playwright and provide local Chrome."""
import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

url=sys.argv[sys.argv.index('--url')+1] if '--url' in sys.argv else os.getenv('RADIO_URL','http://127.0.0.1:8000')
out=Path(os.getenv('BROWSER_OUTPUT','/tmp/radioworkx-browser'))
out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True,args=['--autoplay-policy='+('no-user-gesture-required' if '--allow-autoplay' in sys.argv else 'document-user-activation-required')])
    if '--admin-check' in sys.argv:
        from dotenv import dotenv_values
        password=dotenv_values('.env')['ADMIN_PASSWORD']
        context=browser.new_context(http_credentials={'username':'admin','password':password},viewport={'width':1440,'height':1050})
        admin=context.new_page()
        admin_errors=[]
        admin.on('pageerror',lambda e:admin_errors.append(str(e)))
        admin.goto(url.rstrip('/')+'/admin',wait_until='networkidle')
        admin.wait_for_function('document.querySelectorAll("#metrics .card").length===4')
        if '--token-check' in sys.argv:
            admin.locator('#token-name').fill('Browser verification (revoked after check)')
            with admin.expect_response(
                lambda response: response.url.endswith('/api/admin/tokens') and response.request.method=='POST'
            ) as token_response_info:
                admin.locator('#token-create').click()
            issued=token_response_info.value.json()
            try:
                admin.locator('#token-reveal').wait_for(state='visible')
                assert admin.locator('#token-value').input_value()==issued['token']
                assert issued['token'] not in admin.locator('#token-rows').inner_text()
                assert admin.evaluate("async token=>(await fetch('/api/catalog/genres',{headers:{Authorization:'Bearer '+token}})).status",issued['token'])==200
                admin.evaluate("window.tokenCopied=false;Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{window.tokenCopied=true;}}});")
                admin.locator('#token-copy').click()
                admin.wait_for_function('window.tokenCopied && document.querySelector("#token-reveal").hidden')
                assert admin.locator('#token-value').input_value()==''
                admin.reload(wait_until='networkidle')
                assert admin.locator('#token-value').input_value()==''
                assert issued['token'] not in admin.content()
                admin.locator('#token-rows tr').filter(has_text='Browser verification').first.get_by_role('button',name='Revoke').click()
                admin.wait_for_function("document.querySelector('#token-rows').textContent.includes('Revoked')")
                assert admin.evaluate("async token=>(await fetch('/api/catalog/genres',{headers:{Authorization:'Bearer '+token}})).status",issued['token'])==401
            finally:
                context.request.delete(url.rstrip('/')+'/api/admin/tokens/'+issued['id'],headers={'X-Admin-Action':'tokens'})
                issued.clear()
        assert admin.locator('#rows tr').count()>0
        if admin.locator('#next').is_enabled():
            admin.locator('#next').click()
            admin.wait_for_function('document.querySelector("#pagination").textContent.startsWith("Page 2")')
        for title in ['Source hosts','Requests and chat','Reaction events','Successful downloads','Crawler runs','Artwork videos','Stored objects','Failed downloads','Tracks']:
            admin.get_by_role('button',name=title,exact=True).click()
            admin.wait_for_function('(title)=>document.querySelector("#table-title").textContent===title',arg=title)
        if '--playback-check' in sys.argv:
            def counts():
                return admin.locator('#rows tr td:nth-child(3)').all_text_contents()
            admin.get_by_role('button',name='Playbacks ↓',exact=True).wait_for()
            values=list(map(int,counts()))
            assert values==sorted(values,reverse=True)
            with admin.expect_response(
                lambda response:'/repository/tracks?' in response.url and 'direction=asc' in response.url
            ):
                admin.get_by_role('button',name='Playbacks ↓',exact=True).click()
            admin.get_by_role('button',name='Playbacks ↑',exact=True).wait_for()
            values=list(map(int,counts()))
            assert values==sorted(values)
            admin.locator('#min-plays').fill('2')
            with admin.expect_response(
                lambda response:'/repository/tracks?' in response.url and 'max_plays=10' in response.url
            ) as filtered_response_info:
                admin.locator('#max-plays').fill('10')
            expected=filtered_response_info.value.json()
            admin.wait_for_function('(n)=>document.querySelector("#pagination").textContent.includes(n.toLocaleString()+" records")',arg=expected['total'])
            assert all(2<=int(value)<=10 for value in counts())
            admin.locator('#min-plays').fill('11')
            admin.wait_for_function('document.querySelector("#error").textContent.includes("Minimum playbacks")')
            with admin.expect_response(
                lambda response:'/repository/tracks?' in response.url and 'min_plays' not in response.url
            ):
                admin.locator('#clear-plays').click()
            admin.wait_for_function('!document.querySelector("#error").textContent')
            print(json.dumps({'playback_filters_verified':True,'sorting_verified':True,'matching_tracks':expected['total']}))
        admin.screenshot(path=str(out/'admin-desktop.png'),full_page=True)
        admin.set_viewport_size({'width':390,'height':844})
        assert admin.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
        admin.screenshot(path=str(out/'admin-mobile.png'),full_page=True)
        assert not admin.locator('#error').inner_text()
        assert not admin_errors,admin_errors
        print(json.dumps({'admin_verified':True,'pagination_verified':True,'responsive':True}))
        context.close()
        if '--playback-check' in sys.argv:
            browser.close()
            sys.exit(0)
    page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    if '--visual-check' in sys.argv:
        import io, wave, math, struct
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as tone:
            tone.setnchannels(1);tone.setsampwidth(2);tone.setframerate(16000)
            tone.writeframes(b''.join(struct.pack('<h',int(9000*math.sin(2*math.pi*440*n/16000))) for n in range(16000*8)))
        if '--allow-autoplay' not in sys.argv:
            page.add_init_script("const realPlay=HTMLMediaElement.prototype.play;let denied=false;HTMLMediaElement.prototype.play=function(){if(this.id==='audio'&&!denied){denied=true;return Promise.reject(new DOMException('Autoplay blocked','NotAllowedError'));}return realPlay.call(this);};")
        page.route('**/api/live',lambda route:route.fulfill(status=200,content_type='audio/wav',body=buffer.getvalue()))
    page.goto(url,wait_until='domcontentloaded')
    page.get_by_text('Connected live',exact=True).wait_for(timeout=20000)
    page.wait_for_function('state && document.querySelectorAll("#playlist .queue-track").length === state.playlist.length && state.playlist.length <= 10',timeout=15000)
    assert page.get_by_role('heading',name='Download queue.').is_visible()
    assert page.locator('#request-form select').count()==0
    assert page.locator('#community-requests').is_visible()
    assert page.locator('#download-summary').inner_text()
    page.wait_for_function("document.querySelector('#downloads-page').textContent.includes('Page 1 of')")
    if '--visual-check' in sys.argv:
        assert page.get_by_role('heading',name='Hit up the RJ.').is_visible()
        assert page.locator('header .brandmark').get_attribute('src')=='/static/cassette.svg'
        if '--allow-autoplay' not in sys.argv:
            page.wait_for_function('autoplayBlocked===true')
            assert 'browser blocked autoplay' in page.locator('#audio-status').inner_text()
            page.get_by_role('heading',name='Hit up the RJ.').click()  # Any user click unlocks blocked sound.
        page.wait_for_function('audio.currentTime>.2 && audioContext?.state==="running" && frequencies?.some(v=>v>0)',timeout=15000)
        assert page.locator('.wave i').evaluate_all('(bars)=>bars.some(b=>parseFloat(b.style.height)>6)')
        page.locator('#listen').click()
        page.wait_for_function('!tuned && audio.paused')
        if '--allow-autoplay' in sys.argv:
            page.reload(wait_until='domcontentloaded')
            page.wait_for_function('audio.currentTime>.2 && tuned',timeout=15000)
            page.locator('#listen').click()
        print(json.dumps({'autoplay_allowed':'--allow-autoplay' in sys.argv,'autoplay_fallback_verified':'--allow-autoplay' not in sys.argv,'audio_reactive_bars':True,'rj_and_cassette':True}))
    if '--loop-check' in sys.argv:
        track_id=sys.argv[sys.argv.index('--video-track')+1]
        import urllib.parse
        base='/api/visuals/'+urllib.parse.quote(track_id,safe='')
        # Present a cached visual in this browser only, without changing station history/queue.
        page.evaluate('(base)=>{events.close();state={...state,visual:{video_url:base+"/video",artwork_url:base+"/artwork"}};syncVisual(state);}',base)
        page.wait_for_function('document.querySelector("#track-video").currentTime>.1',timeout=20000)
        video=page.locator('#track-video')
        assert video.evaluate('(v)=>v.muted && v.loop && Math.abs(v.duration-10)<.15')
        video.evaluate('(v)=>v.currentTime=9.5')
        page.wait_for_function('document.querySelector("#track-video").currentTime<3',timeout=10000)
        page.get_by_role('button',name='Pause artwork motion').click()
        assert video.evaluate('(v)=>v.paused')
        page.get_by_role('button',name='Play artwork motion').click()
        page.wait_for_function('!document.querySelector("#track-video").paused')
        page.emulate_media(reduced_motion='reduce')
        page.wait_for_function('document.querySelector("#track-video").paused')
        page.screenshot(path=str(out/'video-loop.png'),full_page=False)
        print(json.dumps({'cached_video_playback':True,'duration_seconds':10,'loop_and_motion_controls':True}))
    if '--ai-check' in sys.argv:
        assert 'AI music chat' in page.locator('#chat-engine').inner_text()
        page.locator('#request-query').fill('I am winding down after a long day. Can you help me choose a mood?')
        with page.expect_response(
            lambda response: response.url.endswith('/api/requests') and response.request.method=='POST',
            timeout=60000,
        ) as ai_response_info:
            page.locator('#request-send').click()
        result=ai_response_info.value.json()
        assert result['engine']=='rag' and result['status']=='awaiting_confirmation'
        assert result['track_id'] is None
        page.get_by_text('Catalog-grounded AI',exact=True).wait_for()
        print(json.dumps({'ai_chat_verified':True,'response':result['response']}))
    if '--chat-check' in sys.argv:
        before=page.request.get(url+'/api/status').json()['request_queue']
        page.locator('#request-query').fill('get me a reggae track')
        with page.expect_response(
            lambda response: response.url.endswith('/api/requests') and response.request.method=='POST'
        ) as request_response_info:
            page.locator('#request-send').click()
        request_response=request_response_info.value.json()
        assert request_response['status']=='awaiting_confirmation'
        assert "don't have playable reggae" in request_response['response']
        page.locator('.chat-choices button').first.wait_for()
        assert page.request.get(url+'/api/status').json()['request_queue']==before
        page.wait_for_function('!document.querySelector("#request-send").disabled')
        page.locator('#request-query').fill('no thanks')
        with page.expect_response(
            lambda response: response.url.endswith('/api/requests') and response.request.method=='POST'
        ) as cancellation_response_info:
            page.locator('#request-send').click()
        assert cancellation_response_info.value.json()['status']=='cancelled'
        page.wait_for_function('!document.querySelector("#request-send").disabled')
    if url.startswith('https://'):
        assert page.evaluate('window.isSecureContext && typeof crypto.randomUUID === "function"')
        assert next(c for c in page.context.cookies() if c['name']=='radio_listener')['secure']
        assert page.request.get(url.rstrip('/')+'/api/session').status==200
    if '--audio-check' in sys.argv:
        if page.locator('#play-label').inner_text()=='Tune in':page.locator('#listen').click()
        page.wait_for_function('document.querySelector("audio").currentTime > 1 && !document.querySelector("audio").paused',timeout=20000)
        page.get_by_role('button',name='Tune out').click()
    if '--waiting-check' in sys.argv:
        assert page.get_by_role('button',name='Tune in').is_enabled()
        page.get_by_role('button',name='Tune in').click()
        page.get_by_role('button',name='Tune out').wait_for()
        page.wait_for_function('document.querySelector("#audio-status").textContent.includes("audio will start automatically")')
        page.get_by_role('button',name='Tune out').click()
    if '--read-only' in sys.argv:
        navigated=[]
        for prefix in ['community','automatic']:
            page.wait_for_function("prefix=>document.querySelector('#'+prefix+'-page').textContent.includes('Page 1 of')",arg=prefix)
            if page.locator(f'#{prefix}-next').is_enabled():
                page.locator(f'#{prefix}-next').click()
                page.wait_for_function("prefix=>document.querySelector('#'+prefix+'-page').textContent.includes('Page 2 of')",arg=prefix)
                navigated.append(prefix)
        page.wait_for_timeout(5500)
        for prefix in navigated:
            assert 'Page 2 of' in page.locator(f'#{prefix}-page').inner_text()
            page.locator(f'#{prefix}-previous').click()
            page.wait_for_function("prefix=>document.querySelector('#'+prefix+'-page').textContent.includes('Page 1 of')",arg=prefix)
        page.locator('#automatic-history').screenshot(path=str(out/'automatic-desktop.png'))
        page.locator('#community-requests').locator('..').screenshot(path=str(out/'community-desktop.png'))
        page.wait_for_function("document.querySelector('#downloads-page').textContent.includes('Page 1 of')")
        if page.locator('#downloads-next').is_enabled():
            page.locator('#downloads-next').click()
            page.wait_for_function("document.querySelector('#downloads-page').textContent.includes('Page 2 of')")
            page.wait_for_timeout(5500)
            assert 'Page 2 of' in page.locator('#downloads-page').inner_text()
            page.locator('#downloads-previous').click()
            page.wait_for_function("document.querySelector('#downloads-page').textContent.includes('Page 1 of')")
        page.locator('.download-section').screenshot(path=str(out/'downloads-desktop.png'))
        page.locator('#stats-metrics .stat-metric').first.wait_for()
        for period in ['all','24h','7d']:
            page.locator(f'[data-period="{period}"]').click()
            page.wait_for_function("document.querySelector('#stats-status').textContent.includes('Refreshes every 30 seconds')")
            assert page.locator(f'[data-period="{period}"]').get_attribute('aria-pressed')=='true'
        page.locator('#station-stats').screenshot(path=str(out/'stats-desktop.png'))
        status=page.request.get(url+'/api/status').json()
        follow=status.get('reaction_followup')
        if follow:
            assert page.locator('#reaction-followup').is_visible()
            if follow['source']:assert follow['source']['title'] in page.locator('#reaction-followup').inner_text()
            if follow['target']:assert follow['target']['title'] in page.locator('#reaction-followup').inner_text()
        assert page.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
        page.screenshot(path=str(out/'desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#station-stats').screenshot(path=str(out/'stats-mobile.png'))
        page.locator('.download-section').screenshot(path=str(out/'downloads-mobile.png'))
        page.locator('#automatic-history').screenshot(path=str(out/'automatic-mobile.png'))
        page.locator('#community-requests').locator('..').screenshot(path=str(out/'community-mobile.png'))
        assert page.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
        page.screenshot(path=str(out/'mobile.png'),full_page=True)
        assert not errors,errors
        print(json.dumps({'read_only':True,'followup':follow,'responsive':True,'javascript_errors':errors}))
        browser.close()
        sys.exit(0)
    page.get_by_role('heading',name='Hit up the RJ.').wait_for()
    page.locator('#request-query').fill('zzzz nonexistent recording 928173')
    page.locator('#request-send').click()
    page.get_by_text("I couldn't find a playable match",exact=False).wait_for()
    page.reload(wait_until='domcontentloaded')
    page.get_by_text("I couldn't find a playable match",exact=False).wait_for()
    page.get_by_text('Connected live',exact=True).wait_for()
    snapshot=page.request.get(url+'/api/status').json()
    choices=[x['metadata'] for x in snapshot['playlist'] if x['metadata']['id']!=snapshot.get('play',{}).get('track_id')][:2]
    for choice in choices:
        page.locator('#request-query').fill(choice['title'])
        with page.expect_response(
            lambda response: response.url.endswith('/api/requests') and response.request.method=='POST'
        ) as request_response_info:
            page.locator('#request-send').click()
        assert request_response_info.value.json()['track_id']==choice['id']
        page.wait_for_function('!document.querySelector("#request-send").disabled')
    queue=page.request.get(url+'/api/status').json()['request_queue']
    assert [q['metadata']['id'] for q in queue][-2:]==[c['id'] for c in choices]
    page.screenshot(path=str(out/'desktop.png'),full_page=True)
    assert page.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
    listen=page.get_by_role('button',name='Tune in')
    if listen.is_enabled():
        listen.click()
        page.get_by_text('You’re on the live frequency.',exact=True).wait_for(timeout=20000)
        page.wait_for_function('document.querySelector("audio").currentTime > 1',timeout=20000)
        fire=page.get_by_role('button',name='Fire:',exact=False)
        with page.expect_response(
            lambda response: response.url.endswith('/api/reactions') and response.request.method=='POST'
        ) as first_reaction_response_info:
            fire.click()
        first_reaction_response=first_reaction_response_info.value
        first_body=first_reaction_response.json()
        assert first_reaction_response.status==202
        page.wait_for_function('document.querySelectorAll("#emojis button:disabled").length === 6')
        page.wait_for_function('document.querySelectorAll("#emojis button:disabled").length === 0',timeout=3000)
        with page.expect_response(
            lambda response: response.url.endswith('/api/reactions') and response.request.method=='POST'
        ) as second_reaction_response_info:
            fire.click()
        second_reaction_response=second_reaction_response_info.value
        second_body=second_reaction_response.json()
        assert second_reaction_response.status==202
        assert second_body['event_id']!=first_body['event_id']
        assert 1 <= second_body['server_time']-first_body['server_time'] < 3

        page.locator('.feed-item').first.wait_for(timeout=15000)
        assert page.locator('#rankings .rank').count()>0
        page.screenshot(path=str(out/'desktop-playing.png'),full_page=True)
        page.get_by_role('button',name='Tune out').click()
    before=page.request.get(url+'/api/status').json()['request_queue']
    page.locator('#request-query').fill('I want something matching my mood right now')
    with page.expect_response(
        lambda response: response.url.endswith('/api/requests') and response.request.method=='POST'
    ) as suggestion_response_info:
        page.locator('#request-send').click()
    assert suggestion_response_info.value.json()['status']=='awaiting_confirmation'
    assert page.request.get(url+'/api/status').json()['request_queue']==before
    page.reload(wait_until='domcontentloaded')
    page.locator('.chat-choices button').first.wait_for()
    choice=page.locator('.chat-choices button').first.inner_text()
    with page.expect_response(
        lambda response: response.url.endswith('/api/requests') and response.request.method=='POST'
    ) as confirmation_response_info:
        page.locator('.chat-choices button').first.click()
    assert confirmation_response_info.value.json()['status']=='pending'
    page.wait_for_function('!document.querySelector("#request-send").disabled')
    assert page.request.get(url+'/api/status').json()['request_queue'][-1]['metadata']['genre']==choice
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(out/'mobile.png'),full_page=True)
    assert page.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
    assert not errors,errors
    print(json.dumps({'page':page.title(),'javascript_errors':errors,'screenshots':str(out),'responsive':True}))
    browser.close()

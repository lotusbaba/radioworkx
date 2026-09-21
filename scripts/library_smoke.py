"""Verify public artist/album pages and actual personal playback without station requests."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8001'
out=Path('/tmp/radioworkx-library');out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000})
    page=context.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url+'/artists',wait_until='networkidle')
    page.locator('.collection-card').first.wait_for()
    assert page.locator('h1').inner_text()=='Meet the artists.'
    page.screenshot(path=str(out/'artists.png'),full_page=True)
    page.locator('.collection-card').first.click()
    page.locator('.track-row').first.wait_for()
    page.locator('#related a').first.click()
    page.locator('.track-row').first.wait_for()
    assert '/albums/' in page.url
    # Choose an album known to have cached audio; browsing is read-only.
    albums=context.request.get(url+'/api/library/albums?page_size=100').json()['items']
    album=next(a for a in albums if a['ready'])
    page.goto(url+'/albums/'+album['id'],wait_until='networkidle')
    detail=context.request.get(url+'/api/library/albums/'+album['id']).json()
    preparing='--prepare' in sys.argv
    track=next(t for t in detail['items'] if t['status']==('available' if preparing else 'ready'))
    page.get_by_role('button',name='Play '+track['title'],exact=True).click()
    page.wait_for_function('document.querySelector("audio").currentTime>.3 && !document.querySelector("audio").paused',timeout=300000 if preparing else 30000)
    page.evaluate('document.querySelector("audio").currentTime=10')
    page.wait_for_function('document.querySelector("audio").currentTime>=10')
    page.screenshot(path=str(out/'album-player.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
    assert page.locator('#stop').is_visible()
    page.screenshot(path=str(out/'mobile.png'),full_page=True)
    page.locator('#stop').click()
    assert page.locator('#player').is_hidden()
    page.goto(url,wait_until='domcontentloaded')
    assert page.get_by_role('link',name='Artists',exact=True).is_visible()
    assert page.get_by_role('link',name='Albums',exact=True).is_visible()
    assert page.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
    assert not errors,errors
    print(json.dumps({'artist_album_navigation':True,'actual_audio_playback':True,'prepared_new_audio':preparing,'seeking':True,'mobile':True,'js_errors':errors}))
    browser.close()

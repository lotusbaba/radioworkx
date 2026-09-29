"""Read-only public artwork check: verify the image actually decodes in Chrome."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8001'
out=Path('/tmp/radioworkx-artwork');out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url,wait_until='domcontentloaded')
    page.wait_for_function("(()=>{const a=document.querySelector('#track-artwork');return a&&!a.hidden&&a.complete&&a.naturalWidth>0;})()",timeout=120000)
    result=page.evaluate("({title:document.querySelector('#title').textContent,url:document.querySelector('#track-artwork').getAttribute('src'),width:document.querySelector('#track-artwork').naturalWidth,height:document.querySelector('#track-artwork').naturalHeight})")
    response=page.request.get(url.rstrip('/')+result['url'])
    assert response.status==200 and response.headers['content-type'].startswith('image/')
    page.locator('.art').screenshot(path=str(out/'desktop-artwork.png'))
    page.set_viewport_size({'width':390,'height':844})
    page.locator('.art').scroll_into_view_if_needed()
    assert page.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
    assert page.locator('#track-artwork').is_visible()
    page.locator('.art').screenshot(path=str(out/'mobile-artwork.png'))
    assert not errors, errors
    print(json.dumps({**result,'public_image_decoded':True,'mobile':True,'js_errors':errors}))
    browser.close()

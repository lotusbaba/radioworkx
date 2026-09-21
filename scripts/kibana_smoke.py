"""Check dashboard rendering without bypassing Kibana's content security policy."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
out=Path('/tmp/rwx-telemetry-check');out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1100})
    for name in ['audience','music','requests','errors']:
        page.goto('http://127.0.0.1:5601/app/dashboards#/view/rwx-'+name,wait_until='domcontentloaded')
        page.get_by_text('RadioWorkx',exact=False).first.wait_for(timeout=60000)
        page.wait_for_timeout(10000)
        text=page.locator('body').inner_text();(out/(name+'.txt')).write_text(text)
        page.screenshot(path=str(out/(name+'.png')),full_page=True)
        print(json.dumps({'dashboard':name,'body':text[:9000]}),flush=True)
    browser.close()

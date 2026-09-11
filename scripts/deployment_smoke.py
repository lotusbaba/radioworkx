"""Explicit live deployment test: rolls current API image and verifies browser recovery."""
import json
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
state = json.loads((root / '.deploy/state.json').read_text())
image = state['images'][state['active']]
url = 'http://127.0.0.1:8001'
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True, args=['--autoplay-policy=no-user-gesture-required'])
    page = browser.new_page()
    page.add_init_script("window.sseOpens=0;const ES=window.EventSource;window.EventSource=class extends ES{constructor(...args){super(...args);this.addEventListener('open',()=>window.sseOpens++);}}")
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function('tuned && audio.currentTime>1 && sseOpens>=1', timeout=30000)
    old_src = page.locator('audio').get_attribute('src')
    old_upstream = page.request.get(url + '/health').headers['x-radio-upstream']
    print('Audio and SSE active on', old_upstream, flush=True)
    log = open('/tmp/radioworkx-deployment-smoke.log', 'w')
    process = subprocess.Popen([sys.executable, 'scripts/deploy.py', 'deploy', '--image', image], cwd=root, stdout=log, stderr=subprocess.STDOUT)
    try:
        while process.poll() is None:
            page.wait_for_timeout(1000)
        if process.returncode:
            raise RuntimeError(Path(log.name).read_text())
        print(page.evaluate('({tuned,src:audio.src,paused:audio.paused,time:audio.currentTime,ready:audio.readyState,error:audio.error?.code,sseOpens})'),flush=True)
        page.wait_for_function('tuned && !audio.paused && audio.currentTime>1 && audio.src.includes("reconnect=") && sseOpens>=2', timeout=30000)
        new_upstream = page.request.get(url + '/health').headers['x-radio-upstream']
        assert old_upstream != new_upstream
        assert old_src != page.locator('audio').get_attribute('src')
        # A user tuning out must cancel all retry attempts.
        page.evaluate('stop()')
        page.wait_for_timeout(1500)
        assert page.evaluate('!tuned && audio.paused && reconnectTimer===null')
        print(json.dumps({'old': old_upstream, 'new': new_upstream, 'audio_reconnected': True, 'sse_reconnected': True, 'tune_out_cancels_retry': True}))
    finally:
        log.close()
        browser.close()

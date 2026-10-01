"""Isolated browser smoke: temporary accounts/catalog/audio, never production data."""
import json
import io
import socket
import math
import struct
import wave
import tempfile
import threading
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fakeredis
import uvicorn
from playwright.sync_api import sync_playwright
from app.testing import database
from app import api, db, events
from app.api import app
from app.library import album_ref


def main():
    with database(), tempfile.TemporaryDirectory(prefix='rwx-accounts-') as tmp:
        db.DATA=Path(tmp);db.init();api.r=events.r=fakeredis.FakeRedis(decode_responses=True)
        audio=db.DATA/'audio';audio.mkdir();path=audio/'sample.mp3'
        # Chrome sniffs the synthetic WAV fixture; production recordings are MP3.
        with wave.open(str(path),'wb') as recording:
            recording.setparams((1,2,22050,0,'NONE','not compressed'))
            recording.writeframes(b''.join(struct.pack('<h',int(3000*math.sin(2*math.pi*440*i/22050))) for i in range(4*22050)))
        with db.transaction() as c:
            for i in range(2):
                meta={'id':f'test-{i}','title':f'Test song {i+1}','artists':['Test artist'],'album':'Test album','album_id':'test-album','genre':'jazz'}
                c.execute('INSERT INTO tracks(id,metadata,status,source,rights,path,duration) VALUES(%s,%s,%s,%s,%s,%s,%s)',(meta['id'],json.dumps(meta),'ready','https://example.com/audio','test fixture',str(path),4))
        snapshot=api.status()
        live=io.BytesIO()
        with wave.open(live,'wb') as recording:
            recording.setparams((1,2,22050,0,'NONE','not compressed'))
            recording.writeframes(b'\x00\x00'*(22050*90))
        album=album_ref(meta)['id']
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        for _ in range(100):
            if server.started:break
            time.sleep(.05)
        url=f'http://127.0.0.1:{port}'
        out=Path('/tmp/radioworkx-accounts');out.mkdir(exist_ok=True)
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1000});page=context.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(url+'/my-music');page.locator('#auth-panel').get_by_role('button',name='Sign in',exact=True).click();page.locator('#auth-switch').click();page.screenshot(path=str(out/'auth-desktop.png'));page.locator('#email').fill('smoke@example.com');page.locator('#password').fill('smoke-test-password-123')
                page.locator('#auth-dialog').get_by_role('button',name='Create account',exact=True).click();page.locator('#account-panel').wait_for(state='visible')
                page.goto(url+'/albums/'+album);page.locator('.track-row').first.wait_for()
                page.locator('.track-row').first.get_by_role('button',name='♡ Like',exact=True).click()
                page.locator('.track-row').first.get_by_role('button',name='♥ Liked',exact=True).wait_for()
                page.locator('.track-row').first.get_by_role('button',name='+ Playlist',exact=True).click()
                page.get_by_role('dialog').get_by_role('textbox',name='New playlist name').fill('Evening favorites')
                page.get_by_role('button',name='Save track',exact=True).click();page.get_by_role('dialog').wait_for(state='hidden')
                page.locator('.track-row').nth(1).get_by_role('button',name='+ Playlist',exact=True).click()
                page.get_by_role('button',name='Save track',exact=True).click();page.get_by_role('dialog').wait_for(state='hidden')
                page.route('**/api/status',lambda r:r.fulfill(json=snapshot))
                page.route('**/api/events',lambda r:r.fulfill(content_type='text/event-stream',body='event: snapshot\ndata: '+json.dumps(snapshot)+'\n\n'))
                page.route('**/api/live*',lambda r:r.fulfill(content_type='audio/wav',body=live.getvalue()))
                page.goto(url)
                page.get_by_role('button',name='Evening favorites (2)',exact=True).click()
                page.locator('#listen').click()
                page.wait_for_function('!document.querySelector("#audio").paused && document.querySelector("#audio").currentTime>.1')
                page.locator('#my-music .track-row').first.get_by_role('button',name='Play Test song 1',exact=True).click()
                page.wait_for_function('!document.querySelector("#recording").paused && document.querySelector("#recording").currentTime>.1')
                assert page.evaluate('!tuned && audio.paused && !audio.getAttribute("src")')
                assert page.url==url+'/'
                page.locator('#listen').click()
                page.wait_for_function('!document.querySelector("#audio").paused && document.querySelector("#audio").currentTime>.1')
                assert page.evaluate('document.querySelector("#recording").paused && !document.querySelector("#recording").getAttribute("src")')
                # Cancel an in-flight personal preparation by returning to live radio.
                pending=[]
                page.route('**/api/listen/test-0',lambda r:pending.append(r))
                page.locator('#my-music .track-row').first.get_by_role('button',name='Play Test song 1',exact=True).click()
                page.wait_for_function('document.querySelector("#player").hidden===false')
                page.locator('#listen').click()
                deadline=time.monotonic()+5
                while not pending and time.monotonic()<deadline:page.wait_for_timeout(20)
                assert pending
                pending.pop().fulfill(json={'status':'ready'})
                page.unroute('**/api/listen/test-0')
                page.wait_for_timeout(250)
                assert page.evaluate('tuned && !document.querySelector("#recording").getAttribute("src")')
                page.get_by_role('button',name='▶ Play all',exact=True).click()
                page.wait_for_function('document.querySelector("#recording").currentTime>.1 && !document.querySelector("#recording").paused')
                page.wait_for_function('document.querySelector("#recording").src.includes("test-1/audio") && document.querySelector("#recording").currentTime>.1',timeout=15000)
                page.locator('#my-music').screenshot(path=str(out/'desktop.png'))
                page.set_viewport_size({'width':390,'height':844})
                page.locator('#my-music').screenshot(path=str(out/'mobile.png'));page.screenshot(path=str(out/'mobile-player.png'))
                assert page.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth'), page.evaluate('[...document.querySelectorAll("body *")].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>({tag:e.tagName,id:e.id,cls:e.className,width:e.getBoundingClientRect().width}))')
                page.locator('#stop').click();page.locator('#logout').click();page.locator('#auth-panel').wait_for(state='visible')
                page.locator('#auth-panel').get_by_role('button',name='Sign in',exact=True).click();page.screenshot(path=str(out/'auth-mobile.png'));page.locator('#email').fill('smoke@example.com');page.locator('#password').fill('smoke-test-password-123');page.locator('#auth-dialog').get_by_role('button',name='Sign in',exact=True).click()
                page.get_by_role('button',name='Evening favorites (2)',exact=True).wait_for()
                page.get_by_role('button',name='Evening favorites (2)',exact=True).click()
                page.get_by_role('textbox',name='Playlist name',exact=True).fill('After hours');page.get_by_role('button',name='Rename',exact=True).click()
                page.get_by_role('button',name='After hours (2)',exact=True).wait_for()
                page.locator('.track-row').first.get_by_role('button',name='Remove',exact=True).click();page.get_by_role('button',name='After hours (1)',exact=True).wait_for()
                page.get_by_role('link',name='Open My music page',exact=False).click()
                page.get_by_role('button',name='After hours (1)',exact=True).wait_for()
                assert page.url==url+'/my-music'
                # Share as the owner, then follow from a separate browser account.
                page.get_by_role('button',name='After hours (1)',exact=True).click()
                page.get_by_label('Public name',exact=True).fill('Smoke curator')
                page.get_by_role('button',name='Save name',exact=True).click()
                page.wait_for_function("Music.data.social?.profile.name==='Smoke curator'")
                page.get_by_role('button',name='Share playlist',exact=True).click()
                shared=page.get_by_role('link',name='Open shared playlist',exact=False)
                shared.wait_for();shared_url=url+shared.get_attribute('href')
                visitor=browser.new_context(viewport={'width':390,'height':844});other=visitor.new_page()
                other.on('pageerror',lambda e:errors.append(str(e)))
                other.goto(shared_url);other.get_by_role('heading',name='After hours',exact=True).wait_for()
                other.get_by_role('button',name='▶ Play all',exact=True).click()
                other.wait_for_function('document.querySelector("#recording").currentTime>.1')
                other.get_by_role('button',name='Follow playlist',exact=True).click()
                other.locator('#auth-switch').click();other.locator('#email').fill('follower@example.com');other.locator('#password').fill('smoke-test-password-123')
                other.locator('#auth-submit').click();other.get_by_role('button',name='Unfollow',exact=True).wait_for()
                other.screenshot(path=str(out/'shared-mobile.png'))
                assert other.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth')
                other.get_by_role('link',name='By Smoke curator',exact=True).click()
                other.get_by_role('button',name='Follow listener',exact=True).click();other.get_by_role('button',name='Unfollow',exact=True).wait_for()
                other.goto(url+'/my-music');other.get_by_role('button',name='Following · After hours (1)',exact=True).click()
                assert other.get_by_role('button',name='Rename',exact=True).count()==0
                assert other.get_by_role('button',name='Remove',exact=True).count()==0
                other.get_by_role('link',name='Smoke curator',exact=True).wait_for()
                other.screenshot(path=str(out/'following-mobile.png'))
                # Live owner changes are reflected, and revocation removes the follow.
                page.get_by_role('textbox',name='Playlist name',exact=True).fill('Shared evening');page.get_by_role('button',name='Rename',exact=True).click()
                page.get_by_role('button',name='Shared evening (1)',exact=True).wait_for()
                other.reload();other.get_by_role('button',name='Following · Shared evening (1)',exact=True).wait_for()
                page.on('dialog',lambda dialog:dialog.accept())
                page.get_by_role('button',name='Make private',exact=True).click()
                page.get_by_role('button',name='Share playlist',exact=True).wait_for()
                other.reload();other.wait_for_function('Music.data.social && Music.data.social.playlists.length===0')
                other.goto(shared_url);other.get_by_text('This playlist is private or no longer available.',exact=True).wait_for()
                visitor.close()
                assert not errors,errors
                browser.close()
                print(json.dumps({'registration_modal':True,'inline_home_collection':True,'mutually_exclusive_players':True,'cancel_pending_preparation':True,'standalone_navigation':True,'likes':True,'playlist_create_add_rename_remove':True,'automatic_audio_advance':True,'sign_in_persistence':True,'mobile':True,'sharing_and_following':True,'revocation':True,'js_errors':errors}))
        finally:
            server.should_exit=True;thread.join(timeout=10)


if __name__=='__main__':main()

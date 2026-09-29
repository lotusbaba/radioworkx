"""Isolated browser smoke: temporary accounts/catalog/audio, never production data."""
import json
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
from app import db, events
from app.api import app
from app.library import album_ref


def main():
    with tempfile.TemporaryDirectory(prefix='rwx-accounts-') as tmp:
        db.DATA=Path(tmp);db.init();events.r=fakeredis.FakeRedis(decode_responses=True)
        audio=db.DATA/'audio';audio.mkdir();path=audio/'sample.mp3'
        # Chrome sniffs the synthetic WAV fixture; production recordings are MP3.
        with wave.open(str(path),'wb') as recording:
            recording.setparams((1,2,22050,0,'NONE','not compressed'))
            recording.writeframes(b''.join(struct.pack('<h',int(3000*math.sin(2*math.pi*440*i/22050))) for i in range(4*22050)))
        with db.transaction() as c:
            for i in range(2):
                meta={'id':f'test-{i}','title':f'Test song {i+1}','artists':['Test artist'],'album':'Test album','album_id':'test-album','genre':'jazz'}
                c.execute('INSERT INTO tracks(id,metadata,status,source,rights,path,duration) VALUES(?,?,?,?,?,?,?)',(meta['id'],json.dumps(meta),'ready','https://example.com/audio','test fixture',str(path),4))
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
                page.goto(url+'/my-music');page.locator('#email').fill('smoke@example.com');page.locator('#password').fill('smoke-test-password-123')
                page.get_by_role('button',name='Create account',exact=True).click();page.locator('#account-panel').wait_for(state='visible')
                page.goto(url+'/albums/'+album);page.locator('.track-row').first.wait_for()
                page.locator('.track-row').first.get_by_role('button',name='♡ Like',exact=True).click()
                page.locator('.track-row').first.get_by_role('button',name='♥ Liked',exact=True).wait_for()
                page.locator('.track-row').first.get_by_role('button',name='+ Playlist',exact=True).click()
                page.get_by_role('dialog').get_by_role('textbox',name='New playlist name').fill('Evening favorites')
                page.get_by_role('button',name='Save track',exact=True).click();page.get_by_role('dialog').wait_for(state='hidden')
                page.locator('.track-row').nth(1).get_by_role('button',name='+ Playlist',exact=True).click()
                page.get_by_role('button',name='Save track',exact=True).click();page.get_by_role('dialog').wait_for(state='hidden')
                page.goto(url+'/my-music');page.get_by_role('button',name='Evening favorites (2)',exact=True).click()
                page.get_by_role('button',name='▶ Play all',exact=True).click()
                page.wait_for_function('document.querySelector("audio").currentTime>.1 && !document.querySelector("audio").paused')
                page.wait_for_function('document.querySelector("audio").src.includes("test-1/audio") && document.querySelector("audio").currentTime>.1',timeout=15000)
                page.screenshot(path=str(out/'desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(out/'mobile.png'),full_page=True)
                assert page.locator('body').evaluate('(e)=>e.scrollWidth<=innerWidth'), page.evaluate('[...document.querySelectorAll("body *")].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>({tag:e.tagName,id:e.id,cls:e.className,width:e.getBoundingClientRect().width}))')
                page.locator('#stop').click();page.locator('#logout').click();page.locator('#auth-panel').wait_for(state='visible')
                page.locator('#email').fill('smoke@example.com');page.locator('#password').fill('smoke-test-password-123');page.get_by_role('button',name='Sign in',exact=True).click()
                page.get_by_role('button',name='Evening favorites (2)',exact=True).wait_for()
                page.get_by_role('button',name='Evening favorites (2)',exact=True).click()
                page.get_by_role('textbox',name='Playlist name',exact=True).fill('After hours');page.get_by_role('button',name='Rename',exact=True).click()
                page.get_by_role('button',name='After hours (2)',exact=True).wait_for()
                page.locator('.track-row').first.get_by_role('button',name='Remove',exact=True).click();page.get_by_role('button',name='After hours (1)',exact=True).wait_for()
                assert not errors,errors
                browser.close()
                print(json.dumps({'registration':True,'likes':True,'playlist_create_add_rename_remove':True,'automatic_audio_advance':True,'sign_in_persistence':True,'mobile':True,'js_errors':errors}))
        finally:
            server.should_exit=True;thread.join(timeout=10)


if __name__=='__main__':main()

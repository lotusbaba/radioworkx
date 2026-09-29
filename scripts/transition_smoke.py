"""Isolated Chrome regression: transient stalls must not discard buffered speech."""
import io
import json
import math
import socket
import struct
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fakeredis
import uvicorn
from playwright.sync_api import sync_playwright
from app import api, db, events


def main():
    with tempfile.TemporaryDirectory(prefix='rwx-transition-') as tmp:
        db.DATA=Path(tmp);db.init();api.r=events.r=fakeredis.FakeRedis(decode_responses=True)
        snapshot=api.status()
        raw=io.BytesIO()
        with wave.open(raw,'wb') as tone:
            tone.setparams((1,2,16000,0,'NONE','not compressed'))
            tone.writeframes(b''.join(struct.pack('<h',int(3000*math.sin(2*math.pi*440*i/16000))) for i in range(25*16000)))
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(api.app,log_level='error'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        while not server.started:time.sleep(.05)
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True,args=['--autoplay-policy=no-user-gesture-required'])
                page=browser.new_page();errors=[];requests=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/api/status',lambda r:r.fulfill(json=snapshot))
                page.route('**/api/events',lambda r:r.fulfill(content_type='text/event-stream',body='event: snapshot\ndata: '+json.dumps(snapshot)+'\n\n'))
                def audio(route):
                    requests.append(route.request.url)
                    route.fulfill(content_type='audio/wav',body=raw.getvalue())
                page.route('**/api/live*',audio)
                page.goto(f'http://127.0.0.1:{port}',wait_until='domcontentloaded')
                page.wait_for_function('audio.currentTime>.2 && !audio.paused')
                initial=page.evaluate('({src:audio.src,time:audio.currentTime})')
                page.evaluate("audio.dispatchEvent(new Event('stalled'))")
                page.wait_for_timeout(2000)
                assert len(requests)==1, 'Transient stall replaced audio and cut off buffered speech'
                assert page.evaluate('audio.src')==initial['src']
                assert page.evaluate('audio.currentTime')>initial['time']+1
                # Check the watchdog decision without waiting 15 seconds in real time.
                page.evaluate('clearStall()');page.clock.install()
                page.evaluate("audio.pause();Object.defineProperty(audio,'buffered',{configurable:true,value:{length:1,start:()=>0,end:()=>audio.currentTime+5}});waitForSignal()")
                page.clock.run_for(15100)
                assert len(requests)==1, 'Watchdog discarded buffered speech'
                page.evaluate("clearStall();Object.defineProperty(audio,'buffered',{configurable:true,value:{length:0}});waitForSignal()")
                page.clock.run_for(16500)
                page.wait_for_function("audio.src.includes('reconnect=')")
                # Tune out must cancel a pending stall recovery.
                page.evaluate('clearStall();waitForSignal();stop()');page.clock.run_for(20000)
                assert page.evaluate("!tuned && !audio.getAttribute('src') && stallTimer===null && reconnectTimer===null")
                assert not errors, errors
                browser.close()
                print(json.dumps({'transient_stall_preserves_audio':True,'buffered_speech_not_discarded':True,'empty_stalled_stream_recovers':True,'tune_out_cancels_recovery':True,'js_errors':errors}))
        finally:
            server.should_exit=True;thread.join(timeout=10)


if __name__=='__main__':main()

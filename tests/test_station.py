import json
from app import db
from app.station import select_next

def test_boost_cannot_bypass_policy(metadata):
    with db.transaction() as c:
        for i in range(3):
            m={**metadata,'album_id':str(i)}
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) VALUES(%s,%s,%s,%s,%s,%s)',
                      (str(i),'track-a',json.dumps(m),i*100,i*100+90,i*100+90))
        for id,artists,priority in [('boost',['Artist A'],1),('safe',['Artist B'],0)]:
            m={**metadata,'id':id,'artists':artists}
            c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES(%s,%s,'ready',100,%s)",(id,json.dumps(m),id+'.mp3'))
            c.execute('INSERT INTO playlist(track_id,priority) VALUES(%s,%s)',(id,priority))
    selected=select_next(now=500)
    assert selected[0]['track_id']=='safe'
    with db.connect() as c:
        assert c.execute('SELECT track_id FROM playlist').fetchone()[0]=='boost'

def test_station_waits_when_every_candidate_ineligible(metadata):
    with db.transaction() as c:
        for i in range(2):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(%s,%s,%s,%s,%s)',
                      (str(i),'track-a',json.dumps(metadata),i*100,i*100+90))
        c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES('track-a',%s,'ready',100,'a.mp3')",(json.dumps(metadata),))
        c.execute("INSERT INTO playlist(track_id) VALUES('track-a')")
    assert select_next(now=500) is None


def test_blocked_queue_uses_eligible_cached_library(metadata):
    with db.transaction() as c:
        for i in range(2):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(%s,%s,%s,%s,%s)',(str(i),'blocked',json.dumps(metadata),i*100,i*100+90))
        c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES('blocked',%s,'ready',100,'blocked.mp3')",(json.dumps(metadata),))
        c.execute("INSERT INTO playlist(track_id) VALUES('blocked')")
        safe={**metadata,'id':'cached','artists':['Other'],'album_id':'other'}
        c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES('cached',%s,'ready',100,'cached.mp3')",(json.dumps(safe),))
    assert select_next(500)[0]['track_id']=='cached'


def test_peek_and_transmission_agree_after_old_history_expires(metadata):
    from app.station import peek
    from app.policy import WINDOW
    with db.transaction() as c:
        for n in range(5):
            tid=str(n)
            meta={**metadata,'id':tid,'artists':[tid],'album_id':tid}
            c.execute("INSERT INTO tracks(id,metadata,status,duration,path,downloaded_at) VALUES(%s,%s,'ready',100,'test.mp3',%s)",(tid,json.dumps(meta),n))
            if n<4:
                c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) VALUES(%s,%s,%s,%s,%s,%s)',(tid,tid,json.dumps(meta),n*100,n*100+90,n*100+90))
    at=WINDOW+1000
    candidate=peek(at)
    assert candidate['id']=='4'
    selected=select_next(at,expected_track_id=candidate['id'],expected_request_id=candidate.get('request_id'))
    assert selected and selected[0]['track_id']=='4'


def test_refill_notification_does_not_block_transmission(monkeypatch):
    import threading
    from app import station
    pending=threading.Event();stop=threading.Event();entered=threading.Event();release=threading.Event()
    calls=[]
    def slow_refill():
        calls.append(1);entered.set();assert release.wait(3)
    monkeypatch.setattr(station,'refill',slow_refill)
    worker=threading.Thread(target=station.refill_loop,args=(pending,stop))
    worker.start()
    try:
        pending.set();assert entered.wait(2)
        # The transmission thread remains free while the calculation is blocked.
        pending.set();pending.set()
        assert worker.is_alive() and calls==[1]
    finally:
        stop.set();release.set();pending.set();worker.join(timeout=3)
    assert not worker.is_alive()


def test_transmit_uses_bounded_mp3_probe_and_flushes_complete_tail(monkeypatch):
    import io
    from app import station
    from types import SimpleNamespace
    data=b'encoded-audio'*500+b'last-words'
    commands=[];published=[]
    class Process:
        def __init__(self,args,**kwargs):commands.append(args);self.stdout=io.BytesIO(data)
        def wait(self,**kwargs):return 0
        def poll(self):return 0
    monkeypatch.setattr(station.subprocess,'Popen',Process)
    monkeypatch.setattr(station,'audio_redis',SimpleNamespace(xadd=lambda stream,fields,**kwargs:published.append(fields['chunk'])))
    station.transmit('cached.mp3')
    cmd=commands[0]
    assert cmd.index('-probesize')<cmd.index('-i') and cmd[cmd.index('-probesize')+1]=='32768'
    assert cmd[cmd.index('-flush_packets')+1]=='1'
    assert b''.join(published)==data and len(published[-1])<2048


def test_intro_to_music_has_no_synchronous_refill(metadata,playing,monkeypatch):
    import pytest
    import threading
    from app import station,announcer
    pid=playing(now=1000)
    play={'id':pid,'track_id':metadata['id'],'metadata':metadata,'starts':1000,'ends':1300}
    order=[]
    class Event:
        def set(self):order.append('notify')
    class Thread:
        def __init__(self,*args,**kwargs):pass
        def start(self):pass
    monkeypatch.setattr(threading,'Thread',Thread)
    monkeypatch.setattr(threading,'Event',Event)
    monkeypatch.setattr(station.audio_redis,'delete',lambda *a:None)
    monkeypatch.setattr(station,'publish',lambda *a:None)
    monkeypatch.setattr(station,'refill',lambda:order.append('refill'))
    monkeypatch.setattr(station,'peek',lambda:{'id':metadata['id'],'meta':metadata})
    monkeypatch.setattr(station,'select_next',lambda **kwargs:(play,'song.mp3'))
    monkeypatch.setattr(station,'ready_intro',lambda *a:{'duration':1,'path':'intro.mp3','script':'Intro','details':'{}','voice':'onyx'})
    monkeypatch.setattr(station,'start_music',lambda p:order.append('music_clock'))
    def transmit(path,*args):
        order.append(path)
        if path=='song.mp3':raise KeyboardInterrupt
    monkeypatch.setattr(station,'transmit',transmit)
    with pytest.raises(KeyboardInterrupt):station.run()
    assert order==['refill','intro.mp3','music_clock','notify','song.mp3']

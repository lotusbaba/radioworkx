import json
import uuid
from app import db
from app.requests import submit, history
from app.station import select_next
from app.downloads import process_job


def track(metadata, id, ready=True):
    m={**metadata,'id':id,'title':id,'artists':['Artist '+id],'album_id':id}
    with db.transaction() as c:
        c.execute('INSERT INTO tracks(id,metadata,status,duration,path,source,rights) VALUES(?,?,?,?,?,?,?)',
                  (id,json.dumps(m),'ready' if ready else 'available',100,id+'.mp3','https://example.org/a','CC BY'))
        if ready:c.execute('INSERT INTO playlist(track_id) VALUES(?)',(id,))
    return m


def ask(query,mode='auto',id=None):
    return submit(query,mode,'session',id or str(uuid.uuid4()))


def test_fifo_before_automatic_and_idempotent(metadata):
    for id in ('automatic','first','second'):track(metadata,id)
    id=str(uuid.uuid4())
    assert ask('first',id=id)==ask('first',id=id)
    ask('second')
    assert select_next(1000)[0]['track_id']=='first'
    assert select_next(1101)[0]['track_id']=='second'
    assert select_next(1202)[0]['track_id']=='automatic'
    assert len(history('session'))==2
    assert history('other')==[]


def test_unready_request_does_not_block_ready_request(metadata,monkeypatch):
    track(metadata,'first',False);track(metadata,'second');track(metadata,'automatic')
    ask('first');ask('second')
    assert select_next(1000)[0]['track_id']=='second'
    with db.connect() as c:
        row=c.execute("SELECT * FROM outbox WHERE queue='request-downloads'").fetchone()
    def acquire(id):
        with db.transaction() as c:c.execute("UPDATE tracks SET status='ready' WHERE id=?",(id,))
        return True
    monkeypatch.setattr('app.downloads.acquire',acquire)
    event={'id':row['id'],**json.loads(row['body'])}
    process_job(event);process_job(event)
    assert select_next(1101)[0]['track_id']=='first'


def test_matching_and_missing(metadata):
    track(metadata,'Song One')
    assert ask('something by Artist Song One')['track_id']=='Song One'
    assert ask('Album A','album')['track_id']=='Song One'
    assert ask('play SONG ONE')['track_id']=='Song One'
    assert ask('not a real song')['status']=='not_found'
    with db.connect() as c:assert c.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]==3


def test_policy_blocked_head_moves_behind_eligible_requests(metadata):
    first=track(metadata,'first');track(metadata,'second');track(metadata,'automatic')
    ask('first');ask('second')
    with db.transaction() as c:
        for i in range(2):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',(str(i),'first',json.dumps(first),i*100,i*100+90))
    from app.views import playlist_views
    with db.connect() as c:
        view=playlist_views(c,None,500)
        assert [r['metadata']['id'] for r in view['request_queue']]==['second','first']
        assert view['request_queue'][1]['status'].startswith('Deferred')
        assert view['up_next']['id']=='second'
    assert select_next(500)[0]['track_id']=='second'
    assert select_next(601)[0]['track_id']=='first'
    assert select_next(702)[0]['track_id']=='automatic'


def test_chat_api_session_validation_and_privacy(metadata):
    from fastapi.testclient import TestClient
    from app.api import app
    track(metadata,'Song')
    with TestClient(app) as client:
        assert client.get('/api/requests').status_code==401
        assert client.post('/api/requests',json={'query':'Song'}).status_code==401
        client.get('/')
        assert client.post('/api/requests',json={'query':'   '}).status_code==422
        result=client.post('/api/requests',json={'query':'Song'}).json()
        assert result['status']=='pending'
        assert len(client.get('/api/requests').json()['messages'])==1
        client.cookies.clear();client.get('/')
        assert client.get('/api/requests').json()['messages']==[]


def test_mood_confirmation_is_durable_and_downloads_only_after_yes(metadata):
    track(metadata,'Quiet Song',False)
    prompt=ask('I want something matching my mood right now')
    assert prompt['status']=='awaiting_confirmation'
    assert prompt['suggestions']==['jazz']
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==0
        assert c.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]==0
    db.init()  # Context survives initialization/restart and history refresh.
    assert history('session')[-1]['suggestions']==['jazz']
    refined=ask('I am feeling relaxed')
    assert refined['status']=='awaiting_confirmation'
    id=str(uuid.uuid4())
    confirmed=ask('yes please',id=id)
    assert confirmed['track_id']=='Quiet Song'
    assert ask('yes please',id=id)==confirmed
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==1
    assert ask('yes')['status']=='awaiting_confirmation'  # No stale double confirmation.


def test_genre_and_specific_conversation_requests(metadata):
    track(metadata,'Quiet Song')
    assert ask('I want some jazz')['track_id']=='Quiet Song'
    assert ask('jazz','genre')['track_id']=='Quiet Song'
    assert ask('Can you play something by Artist Quiet Song?')['track_id']=='Quiet Song'
    assert ask('I would like tracks from the album Album A')['track_id']=='Quiet Song'
    assert ask('I want to hear Quiet Song')['track_id']=='Quiet Song'
    assert ask('reggae','genre')['status']=='not_found'


def test_mood_cancel_session_isolation_and_specific_override(metadata):
    track(metadata,'Quiet Song')
    ask('I feel sad')
    other=submit('yes','auto','other',str(uuid.uuid4()))
    assert other['status']=='awaiting_confirmation'
    assert ask('no thanks')['status']=='cancelled'
    ask('I feel relaxed')
    assert ask('play track Quiet Song')['status']=='pending'
    assert ask('yes')['status']=='awaiting_confirmation'
    assert ask('the first one')['status']=='pending'


def test_natural_genre_requests_and_unavailable_alternative_confirmation(metadata):
    track({**metadata,'genre':'trip-hop'},'Alternative')
    track({**metadata,'genre':'funk'},'Funky Song')
    assert ask('get me a funk track')['track_id']=='Funky Song'
    reply=ask('get me a hip hop track')
    assert reply['status']=='awaiting_confirmation'
    assert "don't have playable hip-hop" in reply['response']
    assert reply['suggestions'][0]=='trip-hop'
    with db.connect() as c:assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==1
    assert ask('trip hop')['track_id']=='Alternative'
    assert ask('what genres do you have')['status']=='awaiting_confirmation'
    assert ask('Hip hop')['status']=='awaiting_confirmation'
    assert ask('hiphop')['status']=='awaiting_confirmation'


def test_genre_selects_eligible_undownloaded_alternative(metadata):
    import time
    blocked=track(metadata,'blocked')
    track(metadata,'fresh',False)
    now=time.time()
    with db.transaction() as c:
        for i in range(3):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',
                      (str(i),'blocked',json.dumps(blocked),now-600+i*100,now-510+i*100))
    result=ask('jazz')
    assert result['track_id']=='fresh'
    with db.connect() as c:
        event=json.loads(c.execute('SELECT body FROM outbox').fetchone()[0])
        assert event['track_id']=='fresh'
    assert ask('blocked')['track_id']=='blocked'


def test_blocked_genre_replacement_keeps_fifo(metadata):
    first=track(metadata,'first')
    request=ask('jazz')
    track(metadata,'fresh',False)
    track(metadata,'later')
    later=ask('later')
    with db.transaction() as c:
        for i in range(3):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',
                      (str(i),'first',json.dumps(first),i*100,i*100+90))
    assert select_next(500)[0]['track_id']=='later'
    with db.connect() as c:
        pending=c.execute("SELECT id,track_id FROM requests WHERE status='pending' ORDER BY sequence").fetchall()
        assert [(r['id'],r['track_id']) for r in pending]==[(request['id'],'fresh')]
        assert c.execute("SELECT COUNT(*) FROM outbox WHERE json_extract(body,'$.track_id')='fresh'").fetchone()[0]==1
    select_next(501)
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM outbox WHERE json_extract(body,'$.track_id')='fresh'").fetchone()[0]==1


def test_blocked_genre_discovers_then_schedules_new_album(metadata,monkeypatch):
    from app.requests import refresh_genre_head
    from app.downloads import plan_job
    first=track(metadata,'first')
    request=ask('jazz')
    with db.transaction() as c:
        for i in range(3):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',
                      (str(i),'first',json.dumps(first),i*100,i*100+90))
        refresh_genre_head(c,1000)
        refresh_genre_head(c,1001)
        rows=c.execute("SELECT * FROM outbox WHERE json_extract(body,'$.discover_genre')='jazz'").fetchall()
        assert len(rows)==1
    calls=[]
    def discover(genre):
        calls.append(genre)
        track(metadata,'new album track',False)
    monkeypatch.setattr('app.discovery.discover',discover)
    monkeypatch.setattr('app.downloads.time.time',lambda:1002)
    event={'id':rows[0]['id'],**json.loads(rows[0]['body'])}
    plan_job(event);plan_job(event)
    assert calls==['jazz']
    with db.connect() as c:
        row=c.execute('SELECT * FROM requests WHERE id=?',(request['id'],)).fetchone()
        assert row['track_id']=='new album track' and row['status']=='pending'
        assert c.execute("SELECT COUNT(*) FROM outbox WHERE json_extract(body,'$.track_id')='new album track'").fetchone()[0]==1

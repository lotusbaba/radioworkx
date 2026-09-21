import json
import queue
import sqlite3
import time
import uuid
from fastapi.testclient import TestClient
from app.api import app
from app import db,telemetry
from app.telemetry_api import _limits
from app.telemetry_collector import observe


def capture(monkeypatch):
    events=[]
    monkeypatch.setattr(telemetry,'emit',lambda action,**kw:events.append(telemetry.make_event(action,**kw)))
    return events


def test_browser_events_validate_and_never_accept_secrets(monkeypatch):
    events=capture(monkeypatch);_limits.clear();client=TestClient(app)
    event={'id':str(uuid.uuid4()),'timestamp':time.time(),'action':'playback.heartbeat','page':'album','mode':'personal','listened_ms':30000,'engaged':True}
    batch={'session_id':str(uuid.uuid4()),'events':[event]}
    assert client.post('/api/activity',json=batch).status_code==401
    client.get('/albums')
    assert client.post('/api/activity',json=batch,headers={'Origin':'https://evil.test'}).status_code==403
    assert client.post('/api/activity',json=batch).status_code==202
    first=events[-1]
    assert first['radioworkx']['listened_ms']==30000
    assert 'radio_listener' not in json.dumps(first)
    assert first['user']['id']!=client.cookies.get('radio_listener')
    assert client.post('/api/activity',json=batch).status_code==202
    assert events[-1]['event']['id']==first['event']['id']  # Index-level deduplication.
    for change in [{'action':'admin.token_created'},{'password':'secret'},{'listened_ms':40000},{'timestamp':0}]:
        assert client.post('/api/activity',json={**batch,'events':[{**event,**change}]}).status_code==422


def test_request_and_admin_audit_do_not_log_credentials_or_queries(monkeypatch):
    events=capture(monkeypatch);monkeypatch.setenv('ADMIN_PASSWORD','private-admin-password');client=TestClient(app);client.get('/')
    client.post('/api/requests',json={'query':'private user text','request_id':str(uuid.uuid4())})
    response=client.post('/api/admin/tokens',auth=('admin','private-admin-password'),headers={'X-Admin-Action':'tokens'},json={'name':'private app label'})
    assert response.status_code==201
    output=json.dumps(events)
    for secret in ['private-admin-password','private user text','private app label',response.json()['token']]:assert secret not in output
    assert any(e['event']['action']=='request.submitted' for e in events)
    assert any(e['event']['action']=='admin.token_created' for e in events)
    assert response.headers.get('x-request-id')


def test_buffer_overflow_is_nonblocking_and_counted(monkeypatch):
    class Running:
        def is_alive(self):return True
    monkeypatch.setenv('TELEMETRY_ENABLED','1');monkeypatch.setattr(telemetry,'_thread',Running());monkeypatch.setattr(telemetry,'_buffer',queue.Queue(maxsize=1));monkeypatch.setattr(telemetry,'_dropped',0)
    telemetry.emit('test.event',password='never retained')
    at=time.monotonic();telemetry.emit('test.event')
    assert time.monotonic()-at<.1 and telemetry._dropped==1
    event=telemetry._buffer.get_nowait();telemetry._buffer.task_done()
    assert 'password' not in json.dumps(event)


def test_observer_broadcast_deduplication_and_request_correlation(metadata,monkeypatch):
    events=capture(monkeypatch);now=time.time()
    with db.transaction() as c:
        c.execute('INSERT INTO tracks(id,metadata) VALUES(?,?)',('track-a',json.dumps(metadata)))
        c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) VALUES(?,?,?,?,?,?)',('p','track-a',json.dumps(metadata),now-100,now-1,now-1))
        c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created,play_id) VALUES('r','private-listener','private query','track','private response','track-a','played',?,'p')",(now-200,))
    state=sqlite3.connect(':memory:');state.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)');state.execute('INSERT INTO settings VALUES(?,?)',('start',str(now-300)));state.execute('CREATE TABLE seen(id TEXT PRIMARY KEY,created REAL)')
    observe(state);count=len(events);observe(state)
    assert len(events)==count
    assert sum(e['event']['action']=='broadcast.started' for e in events)==1
    fulfilled=next(e for e in events if e['event']['action']=='request.fulfilled')
    assert fulfilled['radioworkx']['queue_delay_ms']==100000
    assert 'private query' not in json.dumps(events) and 'private-listener' not in json.dumps(events)


def test_activity_search_is_admin_only_and_outage_is_contained(monkeypatch):
    import app.activity_admin as admin
    monkeypatch.setenv('ADMIN_PASSWORD','secret')
    client=TestClient(app)
    assert client.get('/api/admin/activity').status_code==401
    def fail(*a,**kw):raise OSError('private endpoint details')
    monkeypatch.setattr(admin.httpx,'post',fail)
    response=client.get('/api/admin/activity',auth=('admin','secret'))
    assert response.status_code==503 and 'private endpoint details' not in response.text
    assert client.get('/artists').status_code==200


def test_request_retry_does_not_duplicate_business_event(monkeypatch):
    events=capture(monkeypatch);client=TestClient(app);client.get('/')
    body={'request_id':str(uuid.uuid4()),'query':'No matching track','mode':'track'}
    for _ in range(2):assert client.post('/api/requests',json=body).status_code==200
    submitted=[e for e in events if e['event']['action']=='request.submitted']
    assert len(submitted)==2 and submitted[0]['event']['id']==submitted[1]['event']['id']
    assert submitted[0]['@timestamp']==submitted[1]['@timestamp']

import json
from fastapi.testclient import TestClient
from app.api import app
from app import db


def test_download_pages_sort_by_completion_and_include_all_kinds(metadata):
    with db.transaction() as c:
        for n in range(25):
            tid=f'track-{n:02}'
            c.execute("INSERT INTO tracks(id,metadata,status,downloaded_at,source) VALUES(?,?,'ready',?,'private-url')",(tid,json.dumps({**metadata,'id':tid}),1000+n))
            kind=['refill','boost','request'][n%3]
            queue={'refill':'downloads','boost':'priority-downloads','request':'request-downloads'}[kind]
            db.emit(c,tid,queue,{'kind':kind,'track_id':tid})
            c.execute('UPDATE outbox SET created=?,done=? WHERE id=?',(100-n,1100+n,tid))
            c.execute('INSERT INTO jobs VALUES(?,?,1)',(tid,json.dumps({'tracks':[tid],'completed':[tid]})))
    client=TestClient(app)
    pages=[client.get(f'/api/downloads?page={n}').json() for n in [1,2,3]]
    assert [len(p['items']) for p in pages]==[10,10,5]
    assert pages[0]['total']==25 and pages[0]['pages']==3
    items=[item for page in pages for item in page['items']]
    assert [i['metadata']['id'] for i in items]==[f'track-{n:02}' for n in reversed(range(25))]
    assert all(i['status']=='Downloaded' for i in items)
    assert 'private-url' not in json.dumps(pages)
    assert client.get('/api/downloads?page=99').json()['page']==3
    assert client.get('/api/downloads?page=0').status_code==422
    assert client.get('/api/downloads?page_size=101').status_code==422


def test_download_pages_keep_pending_and_collapse_empty_searches(metadata):
    with db.transaction() as c:
        for n in range(15):
            db.emit(c,str(n),'priority-downloads',{'kind':'recovery'})
            c.execute('UPDATE outbox SET done=1 WHERE id=?',(str(n),))
        db.emit(c,'request','request-downloads',{'kind':'request','discover_genre':'jazz'})
    data=TestClient(app).get('/api/downloads').json()
    assert data['total']==2
    assert any(i['label']=='Requested genre: jazz' and i['status']=='Selecting tracks' for i in data['items'])


def test_automatic_history_filters_before_pagination(metadata):
    with db.transaction() as c:
        for n in range(14):
            tid=str(n)
            c.execute("INSERT INTO tracks(id,metadata,status,downloaded_at) VALUES(?,?,'ready',?)",(tid,json.dumps(metadata),100+n))
            db.emit(c,tid,'downloads' if n<12 else 'priority-downloads',{'kind':'refill' if n<12 else 'boost'})
            c.execute('UPDATE outbox SET created=0,done=200 WHERE id=?',(tid,))
            c.execute('INSERT INTO jobs VALUES(?,?,1)',(tid,json.dumps({'tracks':[tid],'completed':[tid]})))
        db.emit(c,'pending','downloads',{'kind':'refill'})
    client=TestClient(app)
    first=client.get('/api/downloads?scope=automatic').json()
    second=client.get('/api/downloads?scope=automatic&page=2').json()
    assert first['total']==12 and first['pages']==2
    assert len(first['items'])==10 and len(second['items'])==2
    assert all(i['kind']=='refill' and i['status']=='Downloaded' for i in first['items']+second['items'])
    assert first['items'][0]['job_id']=='11'
    assert client.get('/api/downloads?scope=invalid').status_code==422


def test_community_request_history_pagination_and_privacy(metadata):
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata) VALUES('track',?)",(json.dumps(metadata),))
        for n in range(25):
            c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created) VALUES(?,'secret-listener','secret-query','track','secret-response','track',?,?)",(str(n),'pending' if n%2 else 'played',n))
        c.execute("INSERT INTO requests(id,listener,query,mode,response,status,created) VALUES('chat','secret-listener','secret-query','auto','secret-response','answered',1000)")
    client=TestClient(app)
    pages=[client.get(f'/api/community-requests?page={n}').json() for n in [1,2,3]]
    assert [len(p['items']) for p in pages]==[10,10,5]
    assert pages[0]['total']==25
    assert [i['request_id'] for p in pages for i in p['items']]==[str(n) for n in reversed(range(25))]
    assert 'secret-' not in json.dumps(pages)
    assert client.get('/api/community-requests?page=99').json()['page']==3
    assert client.get('/api/community-requests?page=0').status_code==422
    assert client.get('/api/community-requests?page_size=101').status_code==422

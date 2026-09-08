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

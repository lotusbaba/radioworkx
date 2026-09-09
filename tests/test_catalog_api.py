import json
import uuid
from fastapi.testclient import TestClient
from app.api import app
from app import db
from app.station import select_next


def seed(metadata):
    with db.transaction() as c:
        for tid,genre,status,source in [('a','jazz','ready',None),('b','funk','available','private-download'),('c','jazz','available',None)]:
            meta={**metadata,'id':tid,'title':'Song '+tid,'genre':genre,'artists':[tid],'album_id':tid}
            c.execute('INSERT INTO tracks(id,metadata,status,source,rights,duration,path) VALUES(?,?,?,?,?,100,?)',(tid,json.dumps(meta),status,source,'private-permission' if source else None,tid+'.mp3'))


def test_genre_selection_pagination_and_privacy(metadata):
    seed(metadata);client=TestClient(app)
    assert client.get('/api/catalog/genres').json()['items']==[{'genre':'funk','tracks':1,'downloaded':0},{'genre':'jazz','tracks':1,'downloaded':1}]
    data=client.get('/api/catalog/tracks?genre=jazz&genre=funk&page_size=1&page=2').json()
    assert data['total']==2 and data['items'][0]['id']=='b'
    assert 'private-' not in json.dumps(data)
    assert client.get('/api/catalog/tracks?genre=JAZZ&q=song').json()['items'][0]['id']=='a'
    assert client.get('/api/catalog/tracks?genre=unknown').json()['items']==[]
    with db.transaction() as c:db.set_setting(c,'download_cap_reached','1')
    assert client.get('/api/catalog/tracks').json()['total']==1
    assert client.get('/api/catalog/tracks?page_size=101').status_code==422


def test_exact_queue_session_fifo_idempotence_and_download(metadata):
    seed(metadata);client=TestClient(app);rid=str(uuid.uuid4())
    body={'track_id':'b','request_id':rid}
    assert client.post('/api/queue',json=body).status_code==401
    client.get('/')
    first=client.post('/api/queue',json=body)
    assert first.status_code==202 and first.json()['track_id']=='b'
    assert client.post('/api/queue',json=body).json()==first.json()
    assert client.post('/api/queue',json={**body,'track_id':'a'}).status_code==409
    assert client.post('/api/queue',json={'track_id':'a'}).status_code==202
    with db.connect() as c:
        assert [r[0] for r in c.execute('SELECT track_id FROM requests ORDER BY sequence')]==['b','a']
        event=c.execute('SELECT body FROM outbox WHERE id=?',('request:'+rid,)).fetchone()[0]
        assert json.loads(event)['track_id']=='b'
    # A download still pending never blocks a later ready request.
    assert select_next()[0]['track_id']=='a'
    assert client.post('/api/queue',json={'track_id':'missing'}).status_code==404
    assert client.post('/api/queue',json={'track_id':'c'}).status_code==409
    with db.transaction() as c:db.set_setting(c,'download_cap_reached','1')
    assert client.post('/api/queue',json={'track_id':'b'}).status_code==409


def test_queue_rate_limit_and_cross_listener_id_collision(metadata):
    seed(metadata);client=TestClient(app);client.get('/')
    rid=str(uuid.uuid4())
    assert client.post('/api/queue',json={'track_id':'a','request_id':rid}).status_code==202
    other=TestClient(app);other.get('/')
    assert other.post('/api/queue',json={'track_id':'a','request_id':rid}).status_code==409
    for _ in range(9):assert client.post('/api/queue',json={'track_id':'a'}).status_code==202
    assert client.post('/api/queue',json={'track_id':'a'}).status_code==429
    assert client.post('/api/queue',json={'track_id':'a','request_id':rid}).status_code==202

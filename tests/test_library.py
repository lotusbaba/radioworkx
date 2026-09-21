import json
import pytest
from fastapi.testclient import TestClient
from app.api import app
from app import db,downloads
from app.library import artist_ref,album_ref


def seed(metadata):
    audio=db.DATA/'audio';audio.mkdir();path=audio/'one.mp3';path.write_bytes(b'0123456789')
    with db.transaction() as c:
        for tid,status,artists,album in [('one','ready',['A & B','Guest'],'album-1'),('two','available',['A & B'],'album-2'),('bad','failed',['Guest'],'album-1')]:
            meta={**metadata,'id':tid,'artists':artists,'album_id':album,'album':'Same title','title':tid,'license_url':'https://creativecommons.org/licenses/by/4.0/'}
            c.execute('INSERT INTO tracks(id,metadata,status,source,rights,path,duration) VALUES(?,?,?,?,?,?,100)',(tid,json.dumps(meta),status,'https://private.example/secret','private-rights',str(path)))


def test_library_entities_privacy_and_navigation(metadata):
    seed(metadata);client=TestClient(app)
    assert client.get('/artists').status_code==200
    artists=client.get('/api/library/artists').json()
    assert artists['total']==2
    assert client.get('/api/library/albums').json()['total']==2  # Same title, different release IDs.
    assert client.get('/api/library/artists?q=A%20%26%20B').json()['total']==1
    aid=artist_ref('A & B')['id']
    detail=client.get('/api/library/artists/'+aid).json()
    assert detail['total']==2 and len(detail['albums'])==2
    assert 'private' not in json.dumps(detail) and str(db.DATA) not in json.dumps(detail)
    album=detail['albums'][0]['id']
    assert client.get('/albums/'+album).status_code==200
    assert client.get('/artists/'+aid).status_code==200
    assert client.get('/albums/missing').status_code==404
    assert client.get('/api/library/artists?page_size=1&page=2').json()['page']==2
    assert client.get('/api/library/artists?page_size=101').status_code==422
    assert client.get('/api/listen/bad').json()['status']=='unavailable'


def test_personal_preparation_deduplicated_and_does_not_queue_station(metadata,monkeypatch):
    seed(metadata);client=TestClient(app)
    assert client.post('/api/listen/two').status_code==401
    client.get('/albums')
    assert client.post('/api/listen/two',headers={'Origin':'https://evil.example'}).status_code==403
    for _ in range(2):assert client.post('/api/listen/two').json()['status']=='preparing'
    assert client.get('/api/listen/two').json()['status']=='preparing'
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM requests').fetchone()[0]==0
        event=dict(json.loads(c.execute('SELECT body FROM outbox').fetchone()[0]),id='listen:two')
    monkeypatch.setattr(downloads,'acquire',lambda tid:True)
    downloads.process_job(event)
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM playlist').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM plays').fetchone()[0]==0
        assert json.loads(c.execute('SELECT body FROM jobs').fetchone()[0])['completed']==['two']
    assert client.post('/api/listen/bad').status_code==409
    assert client.post('/api/listen/missing').status_code==404


def test_recording_range_and_path_confinement(metadata):
    seed(metadata);client=TestClient(app)
    assert client.get('/api/listen/one/audio').status_code==401
    client.get('/artists')
    response=client.get('/api/listen/one/audio',headers={'Range':'bytes=2-5'})
    assert response.status_code==206 and response.content==b'2345'
    assert response.headers['content-type']=='audio/mpeg'
    assert client.get('/api/listen/two/audio').status_code==409
    with db.transaction() as c:c.execute("UPDATE tracks SET path=? WHERE id='one'",(str(db.DATA/'radio.db'),))
    assert client.get('/api/listen/one/audio').status_code==404


def test_personal_cap_and_exact_failure(metadata,monkeypatch):
    seed(metadata);client=TestClient(app);client.get('/artists')
    with db.transaction() as c:db.set_setting(c,'download_cap_reached','1')
    assert client.post('/api/listen/two').status_code==409
    assert client.post('/api/listen/one').json()['status']=='ready'
    with db.transaction() as c:db.set_setting(c,'download_cap_reached','0')
    client.post('/api/listen/two')
    def fail(tid):raise ValueError('private failure URL')
    monkeypatch.setattr(downloads,'acquire',fail)
    downloads.process_job({'id':'listen:two','kind':'listen','track_id':'two'})
    assert client.get('/api/listen/two').json()['status']=='unavailable'
    assert 'private' not in json.dumps(client.get('/api/listen/two').json())
    with db.connect() as c:
        plan=json.loads(c.execute("SELECT body FROM jobs WHERE id='listen:two'").fetchone()[0])
        assert plan['tracks']==['two'] and plan['failed']==['two']


def test_concurrent_acquisition_is_not_quarantined(metadata):
    seed(metadata)
    with db.transaction() as c:c.execute("UPDATE tracks SET status='downloading' WHERE id='two'")
    with pytest.raises(downloads.TrackReserved):downloads.process_job({'id':'listen:two','kind':'listen','track_id':'two'})
    with db.connect() as c:
        assert c.execute("SELECT status FROM tracks WHERE id='two'").fetchone()[0]=='downloading'
        assert c.execute('SELECT COUNT(*) FROM failed_downloads').fetchone()[0]==0

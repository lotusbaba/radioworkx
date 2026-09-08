import json
from fastapi.testclient import TestClient
from app.api import app
from app import db, announcer, station
from app.views import playlist_views


def test_admin_auth_and_pagination(metadata,monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD','operator-secret')
    client=TestClient(app)
    for url in ['/admin','/admin/app.js','/api/admin/overview','/api/admin/repository/tracks','/api/sources']:
        assert client.get(url).status_code==401
        assert client.get(url,auth=('admin','wrong')).status_code==401
    with db.transaction() as c:
        for n in range(3):
            c.execute('INSERT INTO tracks(id,metadata,status) VALUES(?,?,?)',(str(n),json.dumps(metadata),'pending'))
    auth=('admin','operator-secret')
    assert client.get('/admin',auth=auth).status_code==200
    first=client.get('/api/admin/repository/tracks?page_size=2',auth=auth).json()
    second=client.get('/api/admin/repository/tracks?page_size=2&page=2',auth=auth).json()
    assert first['total']==3 and first['pages']==2 and len(second['items'])==1
    assert {r['id'] for r in first['items']}.isdisjoint(r['id'] for r in second['items'])
    assert client.get('/api/admin/overview?start=2&end=1',auth=auth).status_code==422


def test_activity_dates_and_public_request_privacy(metadata,monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD','secret')
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata,status) VALUES('track-a',?,'pending')",(json.dumps(metadata),))
        for n,at in enumerate([100,200,300]):
            c.execute("INSERT INTO reactions(id,play_id,listener,emoji,accepted,metadata) VALUES(?,'p','private','🔥',?,?)",(str(n),at,json.dumps(metadata)))
        for n,status in enumerate(['pending','played']):
            c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created) VALUES(?,?,'private chat','track','private reply','track-a',?,200)",(str(n),'secret-user-'+str(n),status))
        view=playlist_views(c,None,250)
    feed=view['community_requests']
    assert len(feed)==2 and {r['status'] for r in feed}=={'Queued','Played'}
    assert len({r['requested_by'] for r in feed})==2
    assert 'secret-user' not in json.dumps(feed) and 'private chat' not in json.dumps(feed)
    data=TestClient(app).get('/api/admin/overview?start=150&end=300',auth=('admin','secret')).json()
    assert data['metrics']['reactions']=={'current':1,'previous':1}
    assert data['metrics']['requests']['current']==2
    assert sum(r['reactions'] for r in data['series'])==1


def test_request_intro_is_play_specific_and_race_checked(metadata):
    assert 'requested by a listener' in announcer.script(metadata,{},requested=True)
    assert 'requested' not in announcer.script(metadata,{})
    assert announcer.cache_key(metadata,True)!=announcer.cache_key(metadata,False)
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES('track-a',?,'ready',100,'test.mp3')",(json.dumps(metadata),))
        c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created) VALUES('request-a','listener','q','track','r','track-a','pending',1)")
    assert station.select_next(1000,expected_track_id='track-a',expected_request_id=None) is None
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM plays').fetchone()[0]==0
    play=station.select_next(1000,expected_track_id='track-a',expected_request_id='request-a')
    assert play[0]['requested'] is True

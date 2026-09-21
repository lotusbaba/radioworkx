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


def test_track_playback_counts_filters_and_sorting(metadata,monkeypatch):
    import time
    monkeypatch.setenv('ADMIN_PASSWORD','secret')
    now=time.time()
    with db.transaction() as c:
        for track,count in [('a',0),('b',2),('c',10),('d',11)]:
            c.execute('INSERT INTO tracks(id,metadata,status) VALUES(?,?,?)',(track,json.dumps(dict(metadata,title=track)),'ready'))
            for n in range(count):
                c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) VALUES(?,?,?,?,?,?)',
                          (f'{track}-{n}',track,json.dumps(metadata),now-100,now-50,now-60))
        for pid,start,finish in [('future',now+100,None),('aborted',now-100,now-101),('intro',now-100,None)]:
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) VALUES(?,?,?,?,?,?)',
                      (pid,'a',json.dumps(metadata),start,start+200,finish))
        db.set_setting(c,'announcement_on_air',json.dumps({'play_id':'intro'}))
    client=TestClient(app)
    def query(**params):
        return client.get('/api/admin/repository/tracks',params=params,auth=('admin','secret'))
    data=query(sort='play_count',direction='asc',page_size=2).json()
    assert [(r['id'],r['play_count']) for r in data['items']]==[('a',0),('b',2)]
    assert data['total']==4 and data['pages']==2
    assert [r['id'] for r in query(sort='play_count',direction='asc',page_size=2,page=2).json()['items']]==['c','d']
    data=query(min_plays=2,max_plays=10,sort='play_count',direction='desc',start=1,end=2).json()
    assert [(r['id'],r['play_count']) for r in data['items']]==[('c',10),('b',2)]
    assert data['total']==2 and not data['date_filter_applied']
    assert query(max_plays=0).json()['items'][0]['id']=='a'
    assert query(min_plays=10,q='"title": "c"').json()['total']==1
    assert query(min_plays=12).json()['total']==0
    assert [r['id'] for r in query(sort='title',direction='asc').json()['items']]==['a','b','c','d']
    for params in [dict(min_plays=-1),dict(max_plays=1.5),dict(min_plays=10,max_plays=2),dict(sort='invalid'),dict(direction='invalid')]:
        assert query(**params).status_code==422
    with db.transaction() as c:
        db.set_setting(c,'announcement_on_air','null')
    assert query(q='"title": "a"',max_plays=1).json()['items'][0]['play_count']==1

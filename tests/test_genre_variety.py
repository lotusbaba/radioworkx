import json
from app import db
from app.requests import choose_genre_track,submit_local


def seed(metadata):
    with db.transaction() as c:
        for tid in ['cylinder','new-a','new-b']:
            m={**metadata,'id':tid,'title':'Cylinder One' if tid=='cylinder' else tid,'artists':[tid],'album_id':tid,'genre':'ambient'}
            c.execute("INSERT INTO tracks(id,metadata,status,duration,source,rights) VALUES(?,?,'ready',100,'https://example.org/music','licensed')",(tid,json.dumps(m)))
        c.execute("INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) SELECT 'old',id,metadata,100,200,200 FROM tracks WHERE id='cylinder'")


def test_genre_requests_rotate_but_exact_title_is_preserved(metadata):
    seed(metadata)
    first=submit_local('ambient','genre','listener','r1')
    second=submit_local('ambient','genre','listener','r2')
    assert {first['track_id'],second['track_id']}=={'new-a','new-b'}
    assert submit_local('Cylinder One','track','listener','r3')['track_id']=='cylinder'


def test_genre_uses_request_recency_after_every_track_used(metadata):
    seed(metadata)
    with db.transaction() as c:
        for tid,created in [('new-a',300),('new-b',400),('cylinder',500)]:
            c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created) VALUES(?,'listener','','genre','',?,'played',?)",(tid,tid,created))
        assert choose_genre_track(c,'ambient',10000)[0]['id']=='new-a'

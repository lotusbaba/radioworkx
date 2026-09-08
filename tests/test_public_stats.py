import json
import time
from fastapi.testclient import TestClient
from app.api import app
from app import db


def test_public_stats_periods_and_privacy(metadata):
    now=time.time()
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata,status) VALUES('a',?,'ready')",(json.dumps(metadata),))
        c.execute("INSERT INTO tracks(id,metadata,status) VALUES('b',?,'available')",(json.dumps(metadata),))
        for n,age in enumerate([10,2*86400,9*86400]):
            c.execute("INSERT INTO reactions(id,play_id,listener,emoji,accepted,metadata) VALUES(?,'p','private-listener','🔥',?,?)",(str(n),now-age,json.dumps(metadata)))
        c.execute("INSERT INTO host_downloads VALUES('a','example.org',NULL,?)",(now-10,))
        c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created) VALUES('r','private-listener','private-query','track','private-reply','a','pending',?)",(now-10,))
        c.execute("INSERT INTO requests(id,listener,query,mode,response,status,created) VALUES('chat','private-listener','private-query','auto','private-reply','answered',?)",(now-10,))
    client=TestClient(app)
    for period,likes in [('24h',1),('7d',2),('all',3)]:
        response=client.get('/api/stats',params={'period':period})
        assert response.status_code==200
        data=response.json()
        assert data['library']==1 and data['likes']==likes
        assert data['genres']==[{'genre':'jazz','likes':likes}]
        assert data['requests']==1 and data['downloads']==1
        assert 'private-' not in response.text
    assert client.get('/api/stats?period=invalid').status_code==422
    assert client.get('/api/admin/overview').status_code==401

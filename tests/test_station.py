import json
from app import db
from app.station import select_next

def test_boost_cannot_bypass_policy(metadata):
    with db.transaction() as c:
        for i in range(3):
            m={**metadata,'album_id':str(i)}
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) VALUES(?,?,?,?,?,?)',
                      (str(i),'track-a',json.dumps(m),i*100,i*100+90,i*100+90))
        for id,artists,priority in [('boost',['Artist A'],1),('safe',['Artist B'],0)]:
            m={**metadata,'id':id,'artists':artists}
            c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES(?,?,'ready',100,?)",(id,json.dumps(m),id+'.mp3'))
            c.execute('INSERT INTO playlist(track_id,priority) VALUES(?,?)',(id,priority))
    selected=select_next(now=500)
    assert selected[0]['track_id']=='safe'
    with db.connect() as c:
        assert c.execute('SELECT track_id FROM playlist').fetchone()[0]=='boost'

def test_station_waits_when_every_candidate_ineligible(metadata):
    with db.transaction() as c:
        for i in range(2):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',
                      (str(i),'track-a',json.dumps(metadata),i*100,i*100+90))
        c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES('track-a',?,'ready',100,'a.mp3')",(json.dumps(metadata),))
        c.execute("INSERT INTO playlist(track_id) VALUES('track-a')")
    assert select_next(now=500) is None


def test_blocked_queue_uses_eligible_cached_library(metadata):
    with db.transaction() as c:
        for i in range(2):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',(str(i),'blocked',json.dumps(metadata),i*100,i*100+90))
        c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES('blocked',?,'ready',100,'blocked.mp3')",(json.dumps(metadata),))
        c.execute("INSERT INTO playlist(track_id) VALUES('blocked')")
        safe={**metadata,'id':'cached','artists':['Other'],'album_id':'other'}
        c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES('cached',?,'ready',100,'cached.mp3')",(json.dumps(safe),))
    assert select_next(500)[0]['track_id']=='cached'

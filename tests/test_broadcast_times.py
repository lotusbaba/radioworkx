import json
from app import db,views


def test_request_uses_linked_broadcast_not_another_play(metadata,monkeypatch):
    monkeypatch.setattr(views.time,'time',lambda:500)
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata,status) VALUES('song',?,'ready')",(json.dumps(metadata),))
        for pid,start,end in [('requested',100,200),('replay',300,400)]:
            c.execute("INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) VALUES(?,'song',?,?,?,?)",(pid,json.dumps(metadata),start,end,end))
        c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created,play_id) VALUES('r','private','','track','','song','played',50,'requested')")
        item=views.community_request_page(c)['items'][0]
        assert item['requested_at']==50 and item['played_at']==100 and item['finished_at']==200
        db.set_setting(c,'announcement_on_air',json.dumps({'play_id':'requested'}))
        assert views.community_request_page(c)['items'][0]['played_at'] is None


def test_followup_ignores_earlier_and_future_broadcasts(metadata,monkeypatch):
    monkeypatch.setattr(views.time,'time',lambda:500)
    with db.transaction() as c:
        for tid in ['source','target']:
            c.execute("INSERT INTO tracks(id,metadata,status,downloaded_at) VALUES(?,?,'ready',10)",(tid,json.dumps({**metadata,'id':tid})))
        for pid,tid,start,end in [('original','source',100,200),('old','target',20,50),('future','target',600,700)]:
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) VALUES(?,?,?,?,?,?)',(pid,tid,json.dumps(metadata),start,end,end if end<500 else None))
        db.emit(c,'boost:original','priority-downloads',{'kind':'boost','exclude':'source','genre':'jazz'})
        c.execute("UPDATE outbox SET created=150,done=160 WHERE id='boost:original'")
        c.execute("INSERT INTO jobs(id,body,done) VALUES('boost:original',?,1)",(json.dumps({'tracks':['target'],'completed':['target']}),))
        follow=views.reaction_followup(c)
        assert follow['source_played_at']==100 and follow['played_at'] is None
        c.execute("INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) VALUES('new','target',?,250,350,350)",(json.dumps(metadata),))
        follow=views.reaction_followup(c)
        assert follow['played_at']==250 and follow['finished_at']==350

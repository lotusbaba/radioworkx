import json
from app import db
from app.views import playlist_views


def test_empty_recovery_history_is_not_a_download_queue(metadata):
    with db.transaction() as c:
        for n in range(15):
            id='recovery:'+str(n)
            db.emit(c,id,'priority-downloads',{'kind':'recovery'})
            c.execute('UPDATE outbox SET done=100 WHERE id=?',(id,))
            c.execute('INSERT INTO jobs VALUES(?,?,1)',(id,json.dumps({'tracks':[],'completed':[],'kind':'recovery'})))
        db.emit(c,'genre-search','request-downloads',{'kind':'request','discover_genre':'jazz','request_id':'r'})
        view=playlist_views(c,None,150)
        assert len(view['download_queue'])==1
        assert view['download_queue'][0]['label']=='Requested genre: jazz'
        assert len([r for r in view['download_activity'] if r['kind']=='recovery'])==1


def test_live_ten_track_preview_and_download_queue_excludes_completed(metadata):
    with db.transaction() as c:
        ids=[str(i) for i in range(10)]
        for i in ids:
            m={**metadata,'id':i,'artists':['artist-'+i],'album_id':'album-'+i}
            c.execute("INSERT INTO tracks(id,metadata,status,duration,source) VALUES(?,?,'ready',100,'https://private-source')",(i,json.dumps(m)))
        for i in ids[3:]:c.execute('INSERT INTO playlist(track_id) VALUES(?)',(i,))
        plan={'tracks':ids,'completed':ids,'kind':'refill'}
        db.emit(c,'batch','downloads',{'kind':'refill'})
        c.execute("UPDATE outbox SET created=0,done=1 WHERE id='batch'")
        c.execute('INSERT INTO jobs VALUES(?,?,1)',('batch',json.dumps(plan)))
        for i in ids[:3]:
            m=json.loads(c.execute('SELECT metadata FROM tracks WHERE id=?',(i,)).fetchone()[0])
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',(i,i,json.dumps(m),int(i)*100,int(i)*100+100))
        play={'track_id':'2','ends':300}
        result=playlist_views(c,play,250)
        assert len(result['playlist'])==10
        assert result['playlist'][0]['metadata']['id']=='3'
        assert all(r['status'] in ('Up next','Coming up') for r in result['playlist'])
        assert result['up_next']['id']=='3'
        db.emit(c,'download','downloads',{'kind':'refill'})
        c.execute('INSERT INTO jobs VALUES(?,?,0)',('download',json.dumps({'kind':'refill','tracks':['7','8','9'],'completed':['7']})))
        c.execute("UPDATE tracks SET status='downloading' WHERE id='8'")
        result=playlist_views(c,play,250)
        assert [i['metadata']['id'] for i in result['active_download_queue']]==['8','9']
        assert result['download_queue'][0]['status']=='Downloading'
        assert 'private-source' not in json.dumps(result)


def test_legacy_reactions_migration_preserves_history(metadata,playing):
    from app.service import accept_reaction
    play=playing()
    with db.transaction() as c:
        c.execute('DROP TABLE reactions')
        c.execute('CREATE TABLE reactions(id TEXT PRIMARY KEY,play_id TEXT,listener TEXT,emoji TEXT,accepted REAL,metadata TEXT,processed INTEGER DEFAULT 0,UNIQUE(play_id,listener,emoji))')
        c.execute('INSERT INTO reactions VALUES(?,?,?,?,?,?,?)',('old',play,'listener','🔥',1000,'{}',1))
    db.init()
    accept_reaction(play,'listener','🔥',now=1005)
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM reactions').fetchone()[0]==2
        assert c.execute("SELECT processed FROM reactions WHERE id='old'").fetchone()[0]==1
    db.init() # repeat initialization is safe


def test_download_history_distinguishes_downloads_reuse_and_empty_jobs(metadata):
    from app.views import acquisition_views
    with db.transaction() as c:
        for id,downloaded in [('fresh',110),('cached',50)]:
            c.execute("INSERT INTO tracks(id,metadata,status,downloaded_at) VALUES(?,?,'ready',?)",(id,json.dumps({**metadata,'id':id}),downloaded))
        db.emit(c,'batch','downloads',{'kind':'refill'})
        c.execute("UPDATE outbox SET created=100,done=120 WHERE id='batch'")
        c.execute('INSERT INTO jobs VALUES(?,?,1)',('batch',json.dumps({'tracks':['fresh','cached'],'completed':['fresh','cached'],'kind':'refill'})))
        result=acquisition_views(c,None,150)
        assert {r['metadata']['id']:r['status'] for r in result['download_activity']}=={'fresh':'Downloaded','cached':'Reused from library'}
        assert 'Refill due' in result['download_summary']
        db.emit(c,'boost','priority-downloads',{'kind':'boost'})
        c.execute("UPDATE outbox SET done=150 WHERE id='boost'")
        c.execute('INSERT INTO jobs VALUES(?,?,1)',('boost',json.dumps({'tracks':[],'completed':[],'kind':'boost'})))
        assert acquisition_views(c,None,160)['download_activity'][0]['status']=='No matching authorized tracks'


def test_reaction_followup_exposes_source_target_and_result(metadata):
    from app.views import reaction_followup
    with db.transaction() as c:
        for id,title in [('source','Original Song'),('target','Follow-up Song')]:
            c.execute("INSERT INTO tracks(id,metadata,status,downloaded_at) VALUES(?,?,'ready',110)",(id,json.dumps({**metadata,'id':id,'title':title})))
        db.emit(c,'boost:play','priority-downloads',{'kind':'boost','exclude':'source','genre':'jazz'})
        c.execute("UPDATE outbox SET created=100,done=120 WHERE id='boost:play'")
        c.execute('INSERT INTO jobs VALUES(?,?,1)',('boost:play',json.dumps({'tracks':['target'],'completed':['target']})))
        result=reaction_followup(c)
        assert result['source']['title']=='Original Song'
        assert result['target']['title']=='Follow-up Song'
        assert result['status']=='Downloaded'
        assert result['play_id']=='play'
        c.execute("UPDATE outbox SET failed='RuntimeError' WHERE id='boost:play'")
        assert reaction_followup(c)['status']=='Fetch failed after retries'


def test_completed_triggered_download_stays_in_queue(metadata):
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata,status,downloaded_at) VALUES('song',?,'ready',110)",(json.dumps(metadata),))
        db.emit(c,'boost:play','priority-downloads',{'kind':'boost','genre':'jazz'})
        c.execute("UPDATE outbox SET created=100,done=120 WHERE id='boost:play'")
        c.execute('INSERT INTO jobs VALUES(?,?,1)',('boost:play',json.dumps({'tracks':['song'],'completed':['song'],'kind':'boost'})))
        result=playlist_views(c,None,150)
        assert result['active_download_count']==0
        assert result['download_queue'][0]['status']=='Downloaded'
        assert result['download_queue'][0]['metadata']['title']==metadata['title']
        assert result['download_queue'][0]['kind']=='boost'


def test_next_airtime_includes_eligible_later_requests(metadata):
    from app.views import next_airtime
    from app.policy import WINDOW
    with db.transaction() as c:
        for i in range(3):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',(str(i),'head',json.dumps(metadata),i*100,i*100+90))
        other={**metadata,'artists':['Other'],'album_id':'other'}
        c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',('last','other',json.dumps(other),300,390))
        for id,meta in [('head',metadata),('later',other)]:
            c.execute("INSERT INTO tracks(id,metadata,status) VALUES(?,?,'ready')",(id,json.dumps(meta)))
            c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created) VALUES(?,'listener','','auto','',?,'pending',0)",(id,id))
        assert next_airtime(c,500)==500


def test_preview_matches_transmission_and_does_not_mutate_state(metadata):
    from app.scheduling import preview
    from app.station import select_next
    with db.transaction() as c:
        for i in range(12):
            id=str(i)
            meta={**metadata,'id':id,'title':id,'artists':['shared' if i<4 else id],
                  'album_id':'shared' if i<4 else id}
            c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES(?,?,'ready',100,'test.mp3')",(id,json.dumps(meta)))
            c.execute('INSERT INTO playlist(track_id) VALUES(?)',(id,))
        c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created) VALUES('req','listener','11','track','','11','pending',0)")
        c.execute("DELETE FROM playlist WHERE track_id='11'")
        expected=preview(c,[],1000)
        assert len(expected)==10
        assert expected[0]['metadata']['id']=='11'
        assert c.execute('SELECT COUNT(*) FROM plays').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM playlist').fetchone()[0]==11
    actual=[select_next(1000+i*100)[0]['track_id'] for i in range(10)]
    assert actual==[item['metadata']['id'] for item in expected]


def test_preview_changes_when_requested_download_becomes_ready(metadata):
    from app.scheduling import preview
    with db.transaction() as c:
        for id,status in [('request','available'),('automatic','ready')]:
            meta={**metadata,'id':id,'artists':[id],'album_id':id}
            c.execute('INSERT INTO tracks(id,metadata,status,duration) VALUES(?,?,?,100)',(id,json.dumps(meta),status))
        c.execute("INSERT INTO playlist(track_id) VALUES('automatic')")
        c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created) VALUES('req','listener','request','track','','request','pending',0)")
        assert preview(c,[],1000)[0]['metadata']['id']=='automatic'
        c.execute("UPDATE tracks SET status='ready' WHERE id='request'")
        assert preview(c,[],1000)[0]['metadata']['id']=='request'


def test_small_library_preview_never_pads_with_repeats(metadata):
    from app.scheduling import preview,choose,candidates
    with db.transaction() as c:
        for id in ['a','b']:
            meta={**metadata,'id':id,'artists':[id],'album_id':id}
            c.execute("INSERT INTO tracks(id,metadata,status,duration) VALUES(?,?,'ready',100)",(id,json.dumps(meta)))
        result=preview(c,[],1000)
        assert [r['metadata']['id'] for r in result]==['a','b']
        history=[{'metadata':r['metadata'],'starts':1000+i*100,'ends':1100+i*100} for i,r in enumerate(result)]
        assert choose(candidates(c),history,1200) is not None  # Small library may repeat instead of going silent.


def test_cached_selection_prefers_unplayed_track_over_oldest_download(metadata):
    from app.scheduling import candidates,choose
    with db.transaction() as c:
        metas={}
        for id in ['a','b','c']:
            metas[id]={**metadata,'id':id,'artists':[id],'album_id':id}
            c.execute("INSERT INTO tracks(id,metadata,status,duration) VALUES(?,?,'ready',100)",(id,json.dumps(metas[id])))
        history=[{'metadata':metas['a'],'starts':0,'ends':100}]
        assert choose(candidates(c),history,100)['id']=='b'

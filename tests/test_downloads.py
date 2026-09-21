import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from app import db, downloads
from app.station import refill

def add(id,meta,status='available',downloaded=None):
    with db.transaction() as c:
        c.execute('INSERT INTO tracks(id,metadata,source,rights,status,downloaded_at) VALUES(?,?,?,?,?,?)',
                  (id,json.dumps({**meta,'id':id}),'https://audio.example/'+id,'Permission',status,downloaded))

def test_hard_cap_reservations_and_latch(metadata,monkeypatch):
    monkeypatch.setattr(downloads,'MAX_TRACKS',3)
    add('ready',metadata,'ready',1)
    for i in range(8):add(str(i),metadata)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(downloads.reserve,map(str,range(8))))
    assert sum(r is not None for r in results)==2
    with db.transaction() as c:
        c.execute("UPDATE tracks SET downloaded_at=2,status='ready' WHERE status='downloading'")
        assert downloads.library_only(c)
        c.execute('DELETE FROM tracks WHERE id=?',('ready',))
    with db.connect() as c:
        remaining=c.execute("SELECT id FROM tracks WHERE status='available' LIMIT 1").fetchone()[0]
    assert downloads.reserve(remaining) is None

def test_refill_at_last_three_not_four(metadata,monkeypatch):
    for i in range(4):
        add(str(i),metadata,'ready',1)
        with db.transaction() as c:c.execute('INSERT INTO playlist(track_id) VALUES(?)',(str(i),))
    assert refill(now=1000) is None
    with db.transaction() as c:c.execute('DELETE FROM playlist WHERE track_id=?',('3',))
    assert refill(now=1000)
    assert refill(now=1100) is None # outstanding batch suppresses duplicate jobs

def test_refill_counts_current_track(metadata,playing,monkeypatch):
    monkeypatch.setattr('app.station.needs_recovery',lambda c,now:False)  # Isolate raw refill count from forecast recovery.
    playing(now=1000)
    for i in range(3):
        add(str(i),metadata,'ready',1)
        with db.transaction() as c:c.execute('INSERT INTO playlist(track_id) VALUES(?)',(str(i),))
    assert refill(now=1001) is None
    with db.transaction() as c:c.execute('DELETE FROM playlist WHERE track_id=?',('2',))
    assert refill(now=1001)


def test_short_playable_forecast_triggers_one_recovery(metadata,playing):
    playing(now=1000)
    for i in range(8):
        add(str(i),metadata,'ready',1)
    with db.transaction() as c:
        c.execute('UPDATE tracks SET duration=100')
    # Album limits leave only two forecast tracks despite eight cached files.
    id=refill(now=1001)
    assert id.startswith('recovery:')
    refill(now=1002)
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM outbox WHERE json_extract(body,'$.kind')='recovery'").fetchone()[0]==1

def test_ten_genres_and_artist_boost(metadata,monkeypatch):
    monkeypatch.setattr(downloads,'DEMO',False)
    for i in range(10):
        add(str(i),{**metadata,'genre':str(i),'artists':[str(i)]})
    plan,_=downloads.plan_job({'id':'batch','kind':'refill'})
    assert len(plan['tracks'])==10
    add('same-artist',{**metadata,'album_id':'different'})
    plan,_=downloads.plan_job(dict(id='boost',kind='boost',artists=metadata['artists'],genre='jazz',album_id='original',exclude='track-a'))
    assert plan['tracks']==['same-artist']

def test_cap_uses_only_downloaded(metadata,monkeypatch):
    monkeypatch.setattr(downloads,'DEMO',False)
    with db.transaction() as c:db.set_setting(c,'download_cap_reached','1')
    for i in range(10):
        add(str(i),{**metadata,'genre':str(i),'artists':[str(i)]},'ready',1)
    add('not-downloaded',metadata)
    plan,_=downloads.plan_job({'id':'batch','kind':'refill'})
    assert len(plan['tracks'])==10 and 'not-downloaded' not in plan['tracks']

def test_non_allowlisted_download_rejected(metadata,tmp_path,monkeypatch):
    monkeypatch.setenv('DOWNLOAD_HOSTS','authorized.example')
    with pytest.raises(ValueError):
        downloads.fetch_audio({'source':'http://localhost/private','metadata':json.dumps(metadata)},tmp_path/'x.mp3')

def test_partial_job_retry_never_requeues_already_played(metadata,monkeypatch):
    monkeypatch.setattr(downloads,'DEMO',False)
    for i in range(10):add(str(i),{**metadata,'genre':str(i),'artists':[str(i)]})
    event={'id':'retry','kind':'refill'}
    plan,_=downloads.plan_job(event)
    failed=plan['tracks'][-1]
    def acquire(id):
        if id==failed:raise RuntimeError('interrupted')
        return True
    monkeypatch.setattr(downloads,'acquire',acquire)
    downloads.process_job(event)
    with db.transaction() as c:
        assert c.execute('SELECT COUNT(*) FROM playlist').fetchone()[0]==9
        c.execute('DELETE FROM playlist')  # station already played all nine
    monkeypatch.setattr(downloads,'acquire',lambda id:True)
    downloads.process_job(event)
    with db.connect() as c:
        assert list(c.execute('SELECT track_id FROM playlist'))==[]
        assert c.execute('SELECT COUNT(*) FROM failed_downloads').fetchone()[0]==1

def test_prefers_ten_new_downloads_over_cached(metadata,monkeypatch):
    monkeypatch.setattr(downloads,'DEMO',False)
    for i in range(20):
        add(str(i),{**metadata,'genre':str(i%10),'artists':[str(i)]},'ready' if i<10 else 'available',1 if i<10 else None)
    plan,_=downloads.plan_job({'id':'new','kind':'refill'})
    assert len(plan['tracks'])==10
    assert all(int(t)>=10 for t in plan['tracks'])

def test_exact_ten_thousand_track_boundary(metadata):
    with db.transaction() as c:
        c.executemany("INSERT INTO tracks(id,metadata,status,downloaded_at) VALUES(?,?,'ready',1)",
                      ((f'cached-{i}',json.dumps(metadata)) for i in range(9999)))
    add('last-slot',metadata)
    add('overflow',metadata)
    assert downloads.reserve('last-slot') is not None
    assert downloads.reserve('overflow') is None
    with db.transaction() as c:
        c.execute("UPDATE tracks SET status='ready',downloaded_at=2 WHERE id='last-slot'")
        assert downloads.library_only(c)
        assert c.execute('SELECT COUNT(*) FROM tracks WHERE downloaded_at IS NOT NULL').fetchone()[0]==10000
    assert downloads.reserve('overflow') is None


def test_request_fetch_clears_genre_only_on_success_and_retry_is_safe(metadata,monkeypatch,isolated):
    add('requested',metadata)
    job={'id':'requested-job','kind':'request','request_id':'request','track_id':'requested'}
    isolated.zadd('radio:genres',{'jazz':21,'folk':8})
    def fail(id):raise RuntimeError('Download failed')
    monkeypatch.setattr(downloads,'acquire',fail)
    downloads.process_job(job)
    assert isolated.zscore('radio:genres','jazz')==21
    monkeypatch.setattr(downloads,'acquire',lambda id:True)
    add('alternative',metadata)
    job={**job,'id':'new-request-job','track_id':'alternative'}
    downloads.process_job(job)
    assert isolated.zscore('radio:genres','jazz') is None
    assert isolated.zscore('radio:genres','folk')==8
    isolated.zadd('radio:genres',{'jazz':3})
    downloads.process_job(job)
    assert isolated.zscore('radio:genres','jazz')==3


def test_recovery_triggers_with_full_but_ineligible_queue(metadata):
    with db.transaction() as c:
        for i in range(3):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',(str(i),'old',json.dumps(metadata),i*100,i*100+90))
    for i in range(9):
        add(str(i),metadata,'ready',1)
        with db.transaction() as c:c.execute('INSERT INTO playlist(track_id) VALUES(?)',(str(i),))
    id=refill(now=500)
    assert id.startswith('recovery:')
    assert refill(now=600) is None
    with db.connect() as c:
        row=c.execute('SELECT * FROM outbox WHERE id=?',(id,)).fetchone()
        assert json.loads(row['body'])['kind']=='recovery'
        assert row['queue']=='priority-downloads'


def test_recovery_selects_only_eligible_new_artists_without_waiting_for_ten(metadata,monkeypatch):
    monkeypatch.setattr(downloads.time,'time',lambda:500)
    monkeypatch.setattr(downloads,'DEMO',False)
    with db.transaction() as c:
        for i in range(4):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',(str(i),'old',json.dumps(metadata),i*100,i*100+90))
    add('blocked',metadata)
    add('new',{**metadata,'artists':['New Artist'],'album_id':'new'})
    monkeypatch.setattr('app.discovery.discover',lambda: (_ for _ in ()).throw(AssertionError('Existing eligible source should be used first')))
    plan,_=downloads.plan_job({'id':'recover','kind':'recovery'})
    assert plan['tracks']==['new']


def test_recovery_discovers_when_catalog_exhausted_and_stops_at_cap(metadata,monkeypatch):
    called=[]
    def discover():
        called.append(True)
        add('new',metadata)
    monkeypatch.setattr('app.discovery.discover',discover)
    monkeypatch.setattr(downloads,'DEMO',False)
    assert downloads.plan_job({'id':'recover','kind':'recovery'})[0]['tracks']==['new']
    downloads.plan_job({'id':'recover','kind':'recovery'})
    assert len(called)==1
    with db.transaction() as c:db.set_setting(c,'download_cap_reached','1')
    assert downloads.plan_job({'id':'capped','kind':'recovery'})[0]['tracks']==[]
    assert len(called)==1


def test_refill_search_does_not_hold_writer_lock(metadata,monkeypatch):
    for i in range(10):add(str(i),{**metadata,'genre':str(i),'artists':[str(i)]})
    real=downloads.balanced_sample
    def check(pool,*args):
        with db.connect() as c:
            c.execute('PRAGMA busy_timeout=50')
            c.execute('BEGIN IMMEDIATE')
            db.set_setting(c,'independent-writer','worked')
        return real(pool,*args)
    monkeypatch.setattr(downloads,'balanced_sample',check)
    plan,_=downloads.plan_job({'kind':'refill','id':'unlocked-refill'})
    assert len(plan['tracks'])==10
    with db.connect() as c:assert db.setting(c,'independent-writer')=='worked'


def test_refill_keeps_nine_fresh_genres_and_least_played_repeat(metadata):
    for i in range(9):
        meta={**metadata,'genre':str(i),'artists':[str(i)]}
        add('new-'+str(i),meta)
        add('old-'+str(i),meta,'ready',1)
    meta={**metadata,'genre':'tenth','artists':['tenth']}
    add('often',meta,'ready',1)
    add('rare',meta,'ready',1)
    with db.transaction() as c:
        for i in range(5):
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends,actual_end) VALUES(?,?,?,?,?,?)',
                      (str(i),'often',json.dumps(meta),i+1,i+2,i+2))
    plan,_=downloads.plan_job({'kind':'refill','id':'balanced'})
    assert set(plan['tracks'])=={'rare'}|{'new-'+str(i) for i in range(9)}
    assert downloads.plan_job({'kind':'refill','id':'balanced'})[0]==plan

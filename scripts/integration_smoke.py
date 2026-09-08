"""Run inside the demo API container: python scripts/integration_smoke.py.
Creates 21 synthetic listener reactions against a live demo track.
"""
import json
import time
import httpx
from app import db, queues
from app.events import r

base='http://api:8000'
with httpx.Client(base_url=base,timeout=10) as c:
    status=c.get('/api/status').json()
    assert status['demo'],'This smoke check must run only in demo mode'
    deadline=time.monotonic()+65
    while not status['play'] or status['play']['ends']-time.time()<15:
        assert time.monotonic()<deadline,'No live demo track'
        time.sleep(1)
        status=c.get('/api/status').json()
    play=status['play']
    genre=play['metadata']['genre']
    before=float(r.zscore('radio:genres',genre) or 0)
    for i in range(21):
        with httpx.Client(base_url=base,timeout=10) as listener:
            listener.get('/')
            result=listener.post('/api/reactions',json={'play_id':play['id'],'emoji':'🔥'})
            assert result.status_code==202,result.text
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        with db.connect() as sql:
            job=sql.execute('SELECT * FROM outbox WHERE id=?',('boost:'+play['id'],)).fetchone()
        if job and job['done']:
            break
        time.sleep(.25)
    assert job and job['done'] and not job['failed'],dict(job) if job else 'Missing threshold job'
    assert float(r.zscore('radio:genres',genre)) >= before+21
    with db.connect() as sql:
        plan=json.loads(sql.execute('SELECT body FROM jobs WHERE id=?',('boost:'+play['id'],)).fetchone()[0])
        assert len(plan['completed'])==1,plan
        source=sql.execute('SELECT metadata FROM tracks WHERE id=?',(plan['completed'][0],)).fetchone()[0]
        source=json.loads(source)
        assert set(source['artists']) & set(play['metadata']['artists']) or source['album_id']==play['metadata']['album_id']
        first=sql.execute("SELECT body FROM jobs WHERE json_extract(body,'$.kind')='refill' ORDER BY rowid LIMIT 1").fetchone()
        # Earlier empty authorized-catalog attempts may exist; inspect first populated refill.
        plans=[json.loads(row[0]) for row in sql.execute("SELECT body FROM jobs WHERE json_extract(body,'$.kind')='refill'")]
        batch=next(p for p in plans if len(p['tracks'])==10)
        metas=[json.loads(sql.execute('SELECT metadata FROM tracks WHERE id=?',(id,)).fetchone()[0]) for id in batch['tracks']]
        assert len({m['genre'] for m in metas})==10
        assert len({a for m in metas for a in m['artists']})==10
    assert any(fields['kind']=='reaction' for _,fields in r.xrevrange('radio:events',count=100))
    print(json.dumps({'sqs':queues.client().list_queues()['QueueUrls'],'play':play['id'],
                      'genre':genre,'reactions_added':21,'priority_download':plan['completed'][0],
                      'initial_batch_distinct_genres':10,'initial_batch_distinct_artists':10}))

import json
import redis
import time
from app.config import REDIS_URL

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def publish(kind, body):
    return r.xadd('radio:events', {'kind':kind,'body':json.dumps(body)},maxlen=2000,approximate=True)

# Atomic projection + SSE entry + idempotence: redelivery cannot add a second vote.
PROJECT = """
if redis.call('SADD', KEYS[1], ARGV[1]) == 0 then return 0 end
local cleared = tonumber(redis.call('HGET', KEYS[4], ARGV[2]) or '-1')
if tonumber(ARGV[4]) > cleared then redis.call('ZINCRBY', KEYS[2], 1, ARGV[2]) end
redis.call('XADD', KEYS[3], 'MAXLEN', '~', 2000, '*', 'kind', 'reaction', 'body', ARGV[3])
return 1
"""

def project(event):
    public = {k:event[k] for k in ('id','play_id','emoji','genre','artists')}
    return r.eval(PROJECT,4,'radio:projected','radio:genres','radio:events','radio:genre-cleared-at',
                  event['id'],event['genre'],json.dumps(public),event['accepted'])

def ranking():
    return [{'genre':g,'reactions':int(v)} for g,v in r.zrevrange('radio:genres',0,-1,withscores=True)]


FULFILL = """
if redis.call('SADD', KEYS[1], ARGV[1]) == 0 then return 0 end
redis.call('ZREM', KEYS[2], ARGV[2])
redis.call('HSET', KEYS[3], ARGV[2], ARGV[3])
redis.call('XADD', KEYS[4], 'MAXLEN', '~', 2000, '*', 'kind', 'genre_fulfilled', 'body', ARGV[4])
return 1
"""


def fulfill_genre(job_id, track_id, genre, now=None):
    now=time.time() if now is None else now
    return r.eval(FULFILL,4,'radio:fulfilled-fetches','radio:genres','radio:genre-cleared-at','radio:events',
                  job_id+':'+track_id,genre,now,json.dumps({'genre':genre,'track_id':track_id}))


def reconcile_fulfilled_genres():
    """Repair historical completed fetches without deleting post-fetch reactions."""
    from app import db
    latest={}
    with db.connect() as c:
        rows=c.execute("SELECT o.id,o.body,o.done,j.body AS plan FROM outbox o JOIN jobs j ON j.id=o.id WHERE o.done IS NOT NULL AND o.failed IS NULL AND json_extract(o.body,'$.kind') IN ('boost','request') ORDER BY o.done")
        for row in rows:
            event=json.loads(row['body']);plan=json.loads(row['plan'])
            for track_id in plan.get('completed',[]):
                track=c.execute('SELECT metadata FROM tracks WHERE id=?',(track_id,)).fetchone()
                if not track:continue
                genre=event.get('genre') or json.loads(track[0])['genre']
                latest[genre]=(row['done'],row['id']+':'+track_id)
    repaired=[]
    for genre,(cutoff,marker) in latest.items():
        for _ in range(5):
            try:
                with r.pipeline() as pipe:
                    # Concurrent votes/fulfillments invalidate this snapshot and retry.
                    pipe.watch('radio:projected','radio:genres','radio:genre-cleared-at','radio:fulfilled-fetches')
                    current=float(pipe.hget('radio:genre-cleared-at',genre) or -1)
                    if pipe.sismember('radio:fulfilled-fetches',marker) or current>=cutoff:break
                    with db.connect() as c:
                        ids=[row[0] for row in c.execute("SELECT id FROM reactions WHERE json_extract(metadata,'$.genre')=? AND accepted>?",(genre,cutoff))]
                    count=sum(bool(pipe.sismember('radio:projected',id)) for id in ids)
                    pipe.multi()
                    if count:pipe.zadd('radio:genres',{genre:count})
                    else:pipe.zrem('radio:genres',genre)
                    pipe.hset('radio:genre-cleared-at',genre,cutoff)
                    pipe.sadd('radio:fulfilled-fetches',marker)
                    pipe.xadd('radio:events',{'kind':'genre_fulfilled','body':json.dumps({'genre':genre,'reconciled':True})},maxlen=2000,approximate=True)
                    pipe.execute();repaired.append({'genre':genre,'remaining':count});break
            except redis.WatchError:continue
    return repaired

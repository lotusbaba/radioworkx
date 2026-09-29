"""Observe durable station outcomes without restarting the live transmitter."""
import hashlib
import json
import os
import time
from pathlib import Path
from app import db,telemetry as t


def observe(state):
    start=float(state.execute("SELECT value FROM observer_settings WHERE key='start'").fetchone()[0])
    def once(key,action,at=None,**fields):
        if state.execute('SELECT 1 FROM observer_seen WHERE id=%s',(key,)).fetchone():return
        t.emit(action,event_id=hashlib.sha256(key.encode()).hexdigest(),at=at,origin='observer',**fields)
        state.execute('INSERT INTO observer_seen VALUES(%s,%s)',(key,time.time()))
    start=max(start,time.time()-30*86400)
    for key in ('DEMO_MODE','VIDEOS_ENABLED','REACTION_THRESHOLD','CRAWLER_ENABLED','QUEUE_PREFIX'):
        value=os.getenv(key,'');digest=hashlib.sha256(value.encode()).hexdigest()
        previous=state.execute('SELECT value FROM observer_settings WHERE key=%s',('config:'+key,)).fetchone()
        if not previous or previous[0]!=digest:
            t.emit('configuration.changed' if previous else 'configuration.observed',config_key=key,config_digest=digest,origin='observer')
            state.execute('INSERT INTO observer_settings VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('config:'+key,digest))
    with db.connect() as c:
        intro=json.loads(db.setting(c,'announcement_on_air','null'))
        for p in c.execute('SELECT * FROM plays WHERE starts>=%s AND starts<=%s',(start,time.time())):
            if (intro and intro.get('play_id')==p['id']) or (p['actual_end'] is not None and p['actual_end']<=p['starts']):continue
            fields=dict(track_id=p['track_id'],broadcast_id=p['id'],mode='live')
            once('broadcast:'+p['id'],'broadcast.started',p['starts'],**fields)
            if p['actual_end']:
                duration=p['actual_end']-p['starts'];interrupted=p['actual_end']<p['ends']-3
                once('broadcast-end:'+p['id'],'broadcast.interrupted' if interrupted else 'broadcast.ended',p['actual_end'],duration=duration,outcome='failure' if interrupted else 'success',**fields)
        for r in c.execute('SELECT id,listener,created,track_id,status,play_id,query,mode FROM requests WHERE created>=%s',(start,)):
            fields=dict(request_id=r['id'],track_id=r['track_id'],who=r['listener'])
            once('request-state:'+r['id']+':'+r['status'],'request.'+{'pending':'queued','playing':'broadcast','played':'completed'}.get(r['status'],r['status']),outcome='failure' if r['status'] in {'not_found','failed'} else 'success',**fields)
            if r['track_id']:
                once('request-match:'+r['id'],'request.matched',r['created'],**fields)
                if r['play_id']:
                    p=c.execute('SELECT starts,actual_end FROM plays WHERE id=%s',(r['play_id'],)).fetchone()
                    if p and p['starts']<=time.time() and not (intro and intro.get('play_id')==r['play_id']) and (p['actual_end'] is None or p['actual_end']>p['starts']):
                        once('request-broadcast:'+r['id'],'request.fulfilled',p['starts'],queue_delay_ms=max(0,(p['starts']-r['created'])*1000),broadcast_id=r['play_id'],**fields)
        for r in c.execute('SELECT id,queue,body,created,sent,done,failed FROM outbox WHERE created>=%s',(start,)):
            body=json.loads(r['body']);fields=dict(job_id=r['id'],queue=r['queue'],track_id=body.get('track_id'),request_id=body.get('request_id'))
            once('job-queued:'+r['id'],'job.queued',r['created'],**fields)
            if body.get('kind')=='boost':once('boost:'+r['id'],'reaction.followup_triggered',r['created'],**fields)
            if r['sent']:once('job-sent:'+r['id'],'job.dispatched',r['sent'],queue_delay_ms=max(0,(r['sent']-r['created'])*1000),**fields)
            if r['done']:once('job-done:'+r['id'],'job.failed' if r['failed'] else 'job.completed',r['done'],outcome='failure' if r['failed'] else 'success',duration=max(0,r['done']-r['created']),**fields)
        for r in c.execute('SELECT track_id,error_type,created,id FROM failed_downloads WHERE created>=%s',(start,)):
            once('download-failed:'+r['id'],'download.failed',r['created'],track_id=r['track_id'],error_code=r['error_type'],outcome='failure')
        for r in c.execute('SELECT id,downloaded_at FROM tracks WHERE downloaded_at>=%s',(start,)):
            once('download-ready:'+r['id'],'download.ready',r['downloaded_at'],track_id=r['id'])
    state.execute('DELETE FROM observer_seen WHERE created<%s',(time.time()-35*86400,));state.commit()


def main():
    directory=Path(os.getenv('TELEMETRY_DIR','/telemetry'));directory.mkdir(parents=True,exist_ok=True)
    db.init()
    with db.connect() as state:
        state.execute("INSERT INTO observer_settings VALUES('start',%s) ON CONFLICT DO NOTHING", (str(time.time()),))
    t.install_errors()
    last_cleanup=0
    while True:
        try:
            with db.connect() as state:
                observe(state)
            if time.time()-last_cleanup>3600:
                for path in directory.glob('*.jsonl*'):
                    if path.stat().st_mtime<time.time()-7*86400:path.unlink()
                last_cleanup=time.time()
        except Exception as error:t.emit('observer.error',outcome='failure',error_code=type(error).__name__)
        time.sleep(2)

if __name__=='__main__':main()

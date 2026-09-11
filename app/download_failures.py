"""Durable private failure archive and bounded alternative selection."""
import json
import random
import time
import uuid
from app import db
from app.config import DEMO
from app.policy import eligible


def record(c,event,track_id,error):
    row=c.execute('SELECT * FROM tracks WHERE id=?',(track_id,)).fetchone()
    meta=json.loads(row['metadata']) if row else {}
    previous=c.execute('SELECT id FROM failed_downloads WHERE job_id=? AND track_id=?',(event['id'],track_id)).fetchone()
    failure_id=previous['id'] if previous else str(uuid.uuid4())
    detail=str(error)[:2000] or type(error).__name__
    c.execute('INSERT OR IGNORE INTO failed_downloads(id,job_id,track_id,kind,source_url,page_url,error_type,error_detail,created) VALUES(?,?,?,?,?,?,?,?,?)',
              (failure_id,event['id'],track_id,event['kind'],row['source'] if row else None,meta.get('bandcamp_url'),type(error).__name__,detail,time.time()))
    if row and row['status']!='ready':
        c.execute("UPDATE tracks SET status='failed',error=? WHERE id=?",(type(error).__name__,track_id))
        c.execute('DELETE FROM playlist WHERE track_id=?',(track_id,))
    db.emit(c,'failed-download:'+failure_id,'download-failures',{
        'failure_id':failure_id,'job_id':event['id'],'track_id':track_id,'kind':event['kind'],
        'source_url':row['source'] if row else None,'page_url':meta.get('bandcamp_url'),
        'error_type':type(error).__name__,'error_detail':detail})
    return failure_id,meta


def alternative(c,event,plan,meta):
    from app.downloads import library_only
    if event['kind']=='request':
        request=c.execute('SELECT requested_genre FROM requests WHERE id=?',(event.get('request_id'),)).fetchone()
        if not request or not request['requested_genre']:return None  # Preserve exact requested identity.
    if len(plan.get('failed',[]))>=4:return None  # At most three replacements per job.
    capped=library_only(c);now=time.time()
    history=[dict(r,metadata=json.loads(r['metadata'])) for r in c.execute('SELECT * FROM plays ORDER BY starts')]
    excluded=set(plan['tracks'])|set(plan.get('failed',[]))|{event.get('exclude')}
    excluded.update(r[0] for r in c.execute("SELECT track_id FROM requests WHERE status IN ('pending','playing')"))
    excluded.update(r[0] for r in c.execute('SELECT track_id FROM playlist'))
    genre=event.get('genre') or meta.get('genre')
    used_artists=set()
    if event['kind'] in {'refill','recovery'}:
        for tid in set(plan['tracks'])-set(plan.get('failed',[])):
            row=c.execute('SELECT metadata FROM tracks WHERE id=?',(tid,)).fetchone()
            if row:used_artists.update(json.loads(row['metadata'])['artists'])
    candidates=[]
    for row in c.execute("SELECT * FROM tracks WHERE status IN ('available','ready')"):
        m=json.loads(row['metadata'])
        if row['id'] in excluded or m.get('genre')!=genre or bool(m.get('demo'))!=DEMO:continue
        if row['status']!='ready' and (capped or not row['source'] or not row['rights']):continue
        if used_artists.intersection(m['artists']) or not eligible(m,history,now):continue
        candidates.append(row['id'])
    return random.choice(candidates) if candidates else None

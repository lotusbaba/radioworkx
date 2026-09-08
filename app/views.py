"""Public playlist and acquisition progress, without internal source URLs."""
import json
import hashlib
from app import db
from app.policy import eligible
from app.requests import head, ordered_pending


def playlist_views(c, play, now):
    from app.scheduling import preview
    history=[dict(p,metadata=json.loads(p['metadata'])) for p in c.execute('SELECT * FROM plays ORDER BY starts')]
    when=max(now,play['ends']) if play else now
    items=preview(c,history,when)
    requests=[]
    for row in ordered_pending(c, when):
        meta=json.loads(row['metadata'])
        label=('Downloading' if row['status']=='downloading' else 'Waiting for download' if row['status']!='ready' else
               'Waiting for artist / album limits' if not eligible(meta,history,when) else 'Ready')
        owner=c.execute('SELECT listener,created FROM requests WHERE id=?',(row['request_id'],)).fetchone()
        requests.append({'metadata':meta,'duration':row['duration'],'status':label if label=='Ready' else 'Deferred · '+label,
                         'requested_by':'Listener '+hashlib.sha256(owner['listener'].encode()).hexdigest()[:6],'requested_at':owner['created']})
    community=[]
    for row in c.execute("SELECT r.id,r.listener,r.created,r.status,t.metadata FROM requests r JOIN tracks t ON t.id=r.track_id WHERE r.track_id IS NOT NULL ORDER BY r.sequence DESC LIMIT 20"):
        community.append({'request_id':row['id'],'metadata':json.loads(row['metadata']),'requested_at':row['created'],
                          'requested_by':'Listener '+hashlib.sha256(row['listener'].encode()).hexdigest()[:6],
                          'status':{'pending':'Queued','playing':'Now playing','played':'Played','failed':'Unavailable'}.get(row['status'],row['status'])})
    downloads=[]
    for job in c.execute("SELECT o.id,o.body AS request,o.failed,j.body AS plan FROM outbox o LEFT JOIN jobs j ON j.id=o.id WHERE o.queue IN ('downloads','priority-downloads','request-downloads') AND o.done IS NULL ORDER BY CASE WHEN o.queue='priority-downloads' THEN 0 ELSE 1 END,o.created"):
        request=json.loads(job['request'])
        plan=json.loads(job['plan']) if job['plan'] else None
        if not plan and request['kind']=='request' and not request.get('discover_genre'):
            plan={'tracks':[request['track_id']],'completed':[]}
        if not plan:
            downloads.append({'job_id':job['id'],'kind':request['kind'],'metadata':None,'label':f"Requested genre: {request['discover_genre']}" if request.get('discover_genre') else None,'status':f"Finding eligible {request['discover_genre']} music from another album" if request.get('discover_genre') else 'Selecting tracks'})
            continue
        for id in plan['tracks']:
            if id in plan.get('completed',[]):continue
            row=c.execute('SELECT metadata,status,error FROM tracks WHERE id=?',(id,)).fetchone()
            if row:
                downloads.append({'job_id':job['id'],'kind':request['kind'],'metadata':json.loads(row['metadata']),
                                  'status':'Retry pending' if row['error'] else 'Downloading' if row['status']=='downloading' else 'Queued'})
    downloads.sort(key=lambda t:t['status']!='Downloading')
    acquisition=acquisition_views(c,play,now)
    completed=[item for item in acquisition['download_activity'] if item['kind'] in {'boost','request','recovery'} and item['metadata']]
    return {'reaction_followup':reaction_followup(c),**acquisition,'request_queue':requests,'community_requests':community,'playlist':items,
            'up_next':items[0]['metadata'] if items else None,
            'active_download_queue':downloads,'active_download_count':len(downloads),'download_queue':downloads+completed}


def acquisition_views(c, play, now):
    """Keep completed work visible without representing it as pending downloads."""
    automatic=c.execute('SELECT COUNT(*) FROM playlist').fetchone()[0]
    remaining=automatic+bool(play)
    active=c.execute("SELECT COUNT(*) FROM outbox WHERE queue='downloads' AND done IS NULL AND json_extract(body,'$.kind')='refill'").fetchone()[0]
    capped=db.setting(c,'download_cap_reached','0')=='1'
    last=float(db.setting(c,'last_refill','0'))
    wait=max(0,int(60-(now-last)))
    recovering=c.execute("SELECT 1 FROM outbox WHERE done IS NULL AND json_extract(body,'$.kind')='recovery'").fetchone()
    if recovering:
        summary='No eligible queued music: discovering and downloading new tracks now.'
    elif capped:
        summary='Library limit reached. New selections reuse downloaded audio.'
    elif active:
        summary='The next ten-track batch is being prepared.'
    elif remaining>3:
        summary=f'{automatic} automatic tracks queued + {int(bool(play))} playing. The next ten-track refill starts at 3 remaining.'
    else:
        summary=f'Refill due: {remaining} automatic tracks remaining.'
        if wait: summary+=f' Next check in up to {wait + 1}s.'
    activity=[]
    jobs=c.execute("SELECT o.id,o.body AS request,o.created,o.done,o.failed,j.body AS plan FROM outbox o LEFT JOIN jobs j ON j.id=o.id WHERE o.id IN (SELECT id FROM outbox WHERE queue IN ('priority-downloads','request-downloads') ORDER BY created DESC LIMIT 20) OR o.id IN (SELECT id FROM outbox WHERE queue='downloads' ORDER BY created DESC LIMIT 2) ORDER BY o.created DESC").fetchall()
    for job in jobs:
        request=json.loads(job['request'])
        plan=json.loads(job['plan']) if job['plan'] else None
        if job['failed']:
            activity.append({'job_id':job['id'],'kind':request['kind'],'metadata':None,'status':'Failed after retries'})
        if not plan:continue
        if not plan['tracks'] and job['done']:
            activity.append({'job_id':job['id'],'kind':request['kind'],'metadata':None,'label':f"Requested genre: {request['discover_genre']}" if request.get('discover_genre') else 'Recovery search completed','status':'Catalog checked for eligible genre alternatives' if request.get('discover_genre') else 'No matching authorized tracks'})
        for track_id in reversed(plan.get('completed',[])):
            row=c.execute('SELECT metadata,downloaded_at FROM tracks WHERE id=?',(track_id,)).fetchone()
            if not row:continue
            label=('Downloaded' if row['downloaded_at'] is not None and row['downloaded_at']>=job['created'] else 'Reused from library')
            activity.append({'job_id':job['id'],'kind':request['kind'],'metadata':json.loads(row['metadata']),'status':label})
    # Keep one diagnostic for repeated empty attempts; successful tracks stay visible.
    seen_empty=set()
    activity=[a for a in activity if a['metadata'] or not (a['kind'] in seen_empty or seen_empty.add(a['kind']))]
    return {'download_summary':summary,'download_activity':[a for a in activity if a['kind'] in {'boost','request','recovery'}][:20]+[a for a in activity if a['kind']=='refill'][:20]}


def reaction_followup(c):
    job=c.execute("SELECT o.id,o.body,o.created,o.done,o.failed,j.body AS plan FROM outbox o LEFT JOIN jobs j ON j.id=o.id WHERE o.queue='priority-downloads' AND json_extract(o.body,'$.kind')='boost' ORDER BY o.created DESC LIMIT 1").fetchone()
    if not job:return None
    event=json.loads(job['body'])
    source=c.execute('SELECT metadata FROM tracks WHERE id=?',(event.get('exclude'),)).fetchone()
    plan=json.loads(job['plan']) if job['plan'] else None
    target=None
    label='Selecting a follow-up'
    if plan and plan['tracks']:
        target=c.execute('SELECT metadata,status,error,downloaded_at FROM tracks WHERE id=?',(plan['tracks'][0],)).fetchone()
        if plan['tracks'][0] in plan.get('completed',[]):
            label='Downloaded' if target and target['downloaded_at'] is not None and target['downloaded_at']>=job['created'] else 'Reused from library'
        elif target:
            label='Retry pending' if target['error'] else 'Downloading' if target['status']=='downloading' else 'Queued for download'
    elif plan and job['done']:
        label='No matching authorized follow-up'
    if job['failed']:label='Fetch failed after retries'
    return {'play_id':job['id'].removeprefix('boost:'),'source':json.loads(source['metadata']) if source else None,
            'target':json.loads(target['metadata']) if target else None,'status':label,'genre':event.get('genre')}


def next_airtime(c, now):
    """Earliest policy-eligible cached selection, including deferred requests."""
    from app.config import DEMO
    from app.policy import WINDOW
    history=[dict(p,metadata=json.loads(p['metadata'])) for p in c.execute(
        'SELECT * FROM plays WHERE ends>? OR id IN (SELECT id FROM plays ORDER BY starts DESC LIMIT 3) ORDER BY starts',(now-WINDOW,))]
    rows=c.execute("SELECT * FROM tracks WHERE status='ready'").fetchall()
    tracks=[json.loads(row['metadata']) for row in rows if bool(json.loads(row['metadata']).get('demo'))==DEMO]
    for at in sorted({now}|{p['ends']+WINDOW for p in history if p['ends']+WINDOW>now}):
        if any(eligible(meta,history,at) for meta in tracks):return at
    return None


def download_page(c, page=1, page_size=10):
    """Browse all acquisition jobs by latest track activity, independent of playback order."""
    query="""
    WITH entries AS (
      SELECT o.id AS job_id,o.created,o.done,o.failed,
        json_extract(o.body,'$.kind') AS kind,
        json_extract(o.body,'$.discover_genre') AS genre,
        t.metadata,t.status AS track_status,t.error,t.downloaded_at,
        x.value AS track_id,
        EXISTS(SELECT 1 FROM json_each(j.body,'$.completed') z WHERE z.value=x.value) AS completed
      FROM outbox o LEFT JOIN jobs j ON j.id=o.id
      LEFT JOIN json_each(CASE WHEN j.body IS NOT NULL THEN json_extract(j.body,'$.tracks')
        WHEN json_extract(o.body,'$.track_id') IS NOT NULL THEN json_array(json_extract(o.body,'$.track_id'))
        ELSE '[]' END) x
      LEFT JOIN tracks t ON t.id=x.value
      WHERE o.queue IN ('downloads','priority-downloads','request-downloads')
    ), timed AS (
      SELECT *,CASE WHEN completed AND downloaded_at>=created THEN downloaded_at
        WHEN completed THEN COALESCE(done,created) ELSE COALESCE(done,created) END AS updated_at,
        ROW_NUMBER() OVER (PARTITION BY CASE WHEN track_id IS NULL THEN kind ELSE job_id||':'||track_id END ORDER BY created DESC,job_id DESC) AS diagnostic_rank
      FROM entries
    ), visible AS (SELECT * FROM timed WHERE track_id IS NOT NULL OR diagnostic_rank=1)
    """
    total=c.execute(query+'SELECT COUNT(*) FROM visible').fetchone()[0]
    pages=max(1,(total+page_size-1)//page_size)
    page=min(page,pages)
    rows=c.execute(query+'SELECT * FROM visible ORDER BY updated_at DESC,job_id DESC,track_id DESC LIMIT ? OFFSET ?',
                   (page_size,(page-1)*page_size))
    items=[]
    for row in rows:
        if row['failed']: status='Failed after retries'
        elif row['completed']: status='Downloaded' if row['downloaded_at'] is not None and row['downloaded_at']>=row['created'] else 'Reused from library'
        elif row['done']: status='No matching authorized tracks'
        elif row['error']: status='Retry pending'
        elif row['track_status']=='downloading': status='Downloading'
        else: status='Queued' if row['track_id'] else 'Selecting tracks'
        items.append(dict(job_id=row['job_id'],metadata=json.loads(row['metadata']) if row['metadata'] else None,
                          kind=row['kind'],status=status,updated_at=row['updated_at'],
                          label=f"Requested genre: {row['genre']}" if row['genre'] else None))
    return dict(items=items,total=total,page=page,pages=pages,page_size=page_size)

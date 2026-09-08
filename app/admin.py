"""Read-only operator dashboard, authenticated and paginated at the database."""
import hashlib
import math
import os
import secrets
import time
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app import db

security=HTTPBasic()


def authorize(credentials:HTTPBasicCredentials=Depends(security)):
    password=os.getenv('ADMIN_PASSWORD','')
    if not password: raise HTTPException(503,'Admin password is not configured')
    if not (secrets.compare_digest(credentials.username.encode(),b'admin') and secrets.compare_digest(credentials.password.encode(),password.encode())):
        raise HTTPException(401,'Invalid admin credentials',headers={'WWW-Authenticate':'Basic'})


router=APIRouter(dependencies=[Depends(authorize)])
FILES=Path(__file__).parent/'admin_assets'


@router.get('/admin',response_class=HTMLResponse)
def page():
    return HTMLResponse((FILES/'index.html').read_text(),headers={'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow'})


@router.get('/admin/app.js')
def javascript():
    return Response((FILES/'app.js').read_text(),media_type='application/javascript',headers={'Cache-Control':'no-store'})


def window(start,end):
    end=time.time() if end is None else end
    start=end-7*86400 if start is None else start
    if not all(math.isfinite(v) for v in (start,end)) or start>=end or end-start>366*86400:raise HTTPException(422,'Choose a date range of up to 366 days')
    return start,end


@router.get('/api/admin/overview')
def overview(start:float|None=None,end:float|None=None):
    start,end=window(start,end)
    bucket=3600 if end-start<=2*86400 else 86400
    with db.connect() as c:
        metrics={}
        for name,table,column,extra in [('reactions','reactions','accepted',''),('downloads','host_downloads','completed',''),
            ('requests','requests','created',' AND track_id IS NOT NULL'),('chat_messages','requests','created','')]:
            def count(a,b):return c.execute(f'SELECT COUNT(*) FROM {table} WHERE {column}>=? AND {column}<?'+extra,(a,b)).fetchone()[0]
            metrics[name]={'current':count(start,end),'previous':count(start-(end-start),start)}
        series={t:{'at':t,'reactions':0,'downloads':0,'requests':0} for t in range(int(start//bucket)*bucket,int(end//bucket)*bucket+1,bucket) if t<end}
        for name,table,column,extra in [('reactions','reactions','accepted',''),('downloads','host_downloads','completed',''),('requests','requests','created',' AND track_id IS NOT NULL')]:
            rows=c.execute(f'SELECT CAST({column}/? AS INTEGER)*? AS at,COUNT(*) AS n FROM {table} WHERE {column}>=? AND {column}<?'+extra+' GROUP BY at',(bucket,bucket,start,end))
            for row in rows:series[int(row['at'])][name]=row['n']
        genres=[dict(r) for r in c.execute("SELECT json_extract(metadata,'$.genre') AS genre,COUNT(*) AS reactions FROM reactions WHERE accepted>=? AND accepted<? GROUP BY genre ORDER BY reactions DESC LIMIT 20",(start,end))]
        library={r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) AS n FROM tracks GROUP BY status')}
        return {'start':start,'end':end,'bucket_seconds':bucket,'metrics':metrics,'series':list(series.values()),'genres':genres,'library':library,
                'hosts':c.execute('SELECT COUNT(*) FROM source_hosts').fetchone()[0],
                'crawler_status':db.setting(c,'crawler_status','Waiting'),'station_status':db.setting(c,'station_status','Starting')}


@router.get('/api/admin/repository/{kind}')
def repository(kind:Literal['tracks','hosts','requests','reactions','downloads','crawls','visuals','objects'],
               page:int=Query(1,ge=1,le=1000000),page_size:int=Query(25,ge=1,le=100),
               q:str=Query('',max_length=100),start:float|None=None,end:float|None=None):
    start,end=window(start,end)
    tables={
        'tracks':("tracks t","t.id,json_extract(t.metadata,'$.title') AS title,json_extract(t.metadata,'$.artists') AS artists,json_extract(t.metadata,'$.album') AS album,json_extract(t.metadata,'$.genre') AS genre,t.status,t.duration,t.downloaded_at,json_extract(t.metadata,'$.license_name') AS license,json_extract(t.metadata,'$.bandcamp_url') AS source",'t.metadata','t.id DESC',None),
        'hosts':('source_hosts h','h.hostname,h.provider,h.role,h.status,h.tracks_downloaded,h.notes,h.first_seen,h.last_seen','h.hostname','h.tracks_downloaded DESC,h.hostname',None),
        'requests':("requests r LEFT JOIN tracks t ON t.id=r.track_id","r.sequence,r.query,r.response,r.status,r.engine,r.created,json_extract(t.metadata,'$.title') AS title,r.listener",'r.query','r.sequence DESC','r.created'),
        'reactions':("reactions r LEFT JOIN plays p ON p.id=r.play_id","r.id,r.emoji,r.accepted,r.processed,json_extract(p.metadata,'$.title') AS title,json_extract(r.metadata,'$.genre') AS genre,json_extract(r.metadata,'$.artists') AS artists,r.play_id",'r.metadata','r.accepted DESC,r.id','r.accepted'),
        'downloads':("host_downloads d LEFT JOIN tracks t ON t.id=d.track_id","d.track_id,json_extract(t.metadata,'$.title') AS title,d.source_host,d.media_host,d.completed",'COALESCE(t.metadata,d.track_id)','d.completed DESC,d.track_id','d.completed'),
        'visuals':('track_visuals v LEFT JOIN tracks t ON t.id=v.track_id',"v.track_id,json_extract(t.metadata,'$.title') AS title,v.status,v.provider_id,v.created,v.completed,v.error",'COALESCE(t.metadata,v.track_id)','v.created DESC,v.track_id','v.created'),
        'objects':('media_objects m','m.object_key,m.track_id,m.kind,m.mime,m.checked','m.object_key','m.object_key',None),
        'crawls':('crawl_runs r','r.id,r.started,r.finished,r.pages,r.tracks,r.errors','r.id','r.started DESC,r.id','r.started')}
    table,columns,search,order,date=tables[kind]
    where=' WHERE '+search+' LIKE ?'
    values=['%'+q+'%']
    if date:where+=f' AND {date}>=? AND {date}<?';values.extend([start,end])
    with db.connect() as c:
        total=c.execute('SELECT COUNT(*) FROM '+table+where,values).fetchone()[0]
        rows=[dict(r) for r in c.execute('SELECT '+columns+' FROM '+table+where+' ORDER BY '+order+' LIMIT ? OFFSET ?',values+[page_size,(page-1)*page_size])]
    for row in rows:
        if 'listener' in row:row['listener']='Listener '+hashlib.sha256(row['listener'].encode()).hexdigest()[:6]
    return {'items':rows,'page':page,'page_size':page_size,'total':total,'pages':max(1,math.ceil(total/page_size)),
            'date_filter_applied':bool(date)}

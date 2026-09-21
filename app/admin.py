"""Authenticated operator dashboard, repository browsing and app-token management."""
import hashlib
import json
import math
import os
import secrets
import time
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
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


def token_mutation(request: Request):
    from urllib.parse import urlparse
    origin=request.headers.get('origin')
    if request.headers.get('x-admin-action')!='tokens' or (origin and urlparse(origin).netloc!=request.url.netloc):
        raise HTTPException(403,'Use the admin token controls on this site.')


class TokenName(BaseModel):
    name: str=Field(min_length=1,max_length=100)


@router.post('/api/admin/tokens',status_code=201,dependencies=[Depends(token_mutation)])
def create_token(body: TokenName,response: Response):
    from app.app_tokens import issue
    name=body.name.strip()
    if not name:raise HTTPException(422,'Enter an app name.')
    response.headers['Cache-Control']='no-store'
    return issue(name)


@router.get('/api/admin/tokens')
def list_tokens(response: Response,page:int=Query(1,ge=1),page_size:int=Query(10,ge=1,le=100)):
    response.headers['Cache-Control']='no-store'
    with db.connect() as c:
        total=c.execute('SELECT COUNT(*) FROM app_tokens').fetchone()[0]
        pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
        items=[dict(r,token='••••••••') for r in c.execute('SELECT id,name,created,last_used,revoked FROM app_tokens ORDER BY created DESC,id DESC LIMIT ? OFFSET ?',(page_size,(page-1)*page_size))]
    return dict(items=items,total=total,page=page,pages=pages)


@router.delete('/api/admin/tokens/{token_id}',dependencies=[Depends(token_mutation)])
def revoke_token(token_id:str,response:Response):
    response.headers['Cache-Control']='no-store'
    with db.transaction() as c:
        if not c.execute('SELECT 1 FROM app_tokens WHERE id=?',(token_id,)).fetchone():raise HTTPException(404,'Token not found.')
        c.execute('UPDATE app_tokens SET revoked=COALESCE(revoked,?) WHERE id=?',(time.time(),token_id))
    return {'status':'revoked'}


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
def repository(kind:Literal['tracks','hosts','requests','reactions','downloads','crawls','visuals','objects','failed-downloads'],
               page:int=Query(1,ge=1,le=1000000),page_size:int=Query(25,ge=1,le=100),
               q:str=Query('',max_length=100),start:float|None=None,end:float|None=None,
               sort:str|None=None,direction:Literal['asc','desc']='desc',
               min_plays:int|None=Query(None,ge=0),max_plays:int|None=Query(None,ge=0)):
    start,end=window(start,end)
    if min_plays is not None and max_plays is not None and min_plays>max_plays:
        raise HTTPException(422,'Minimum playbacks cannot exceed maximum playbacks.')
    tables={
        'tracks':("tracks t","t.id,json_extract(t.metadata,'$.title') AS title,json_extract(t.metadata,'$.artists') AS artists,json_extract(t.metadata,'$.album') AS album,json_extract(t.metadata,'$.genre') AS genre,t.status,t.duration,t.downloaded_at,json_extract(t.metadata,'$.license_name') AS license,json_extract(t.metadata,'$.bandcamp_url') AS source",'t.metadata','t.id DESC',None),
        'hosts':('source_hosts h','h.hostname,h.provider,h.role,h.status,h.tracks_downloaded,h.notes,h.first_seen,h.last_seen','h.hostname','h.tracks_downloaded DESC,h.hostname',None),
        'requests':("requests r LEFT JOIN tracks t ON t.id=r.track_id","r.sequence,r.query,r.response,r.status,r.engine,r.created,json_extract(t.metadata,'$.title') AS title,r.listener",'r.query','r.sequence DESC','r.created'),
        'reactions':("reactions r LEFT JOIN plays p ON p.id=r.play_id","r.id,r.emoji,r.accepted,r.processed,json_extract(p.metadata,'$.title') AS title,json_extract(r.metadata,'$.genre') AS genre,json_extract(r.metadata,'$.artists') AS artists,r.play_id",'r.metadata','r.accepted DESC,r.id','r.accepted'),
        'downloads':("host_downloads d LEFT JOIN tracks t ON t.id=d.track_id","d.track_id,json_extract(t.metadata,'$.title') AS title,d.source_host,d.media_host,d.completed",'COALESCE(t.metadata,d.track_id)','d.completed DESC,d.track_id','d.completed'),
        'failed-downloads':('failed_downloads f LEFT JOIN tracks t ON t.id=f.track_id',"f.id,f.job_id,f.track_id,json_extract(t.metadata,'$.title') AS title,f.kind,f.source_url,f.page_url,f.error_type,f.error_detail,f.created,f.replacement_id","COALESCE(t.metadata,'') || COALESCE(f.source_url,'') || f.error_detail",'f.created DESC,f.id','f.created'),
        'visuals':('track_visuals v LEFT JOIN tracks t ON t.id=v.track_id',"v.track_id,json_extract(t.metadata,'$.title') AS title,v.status,v.provider_id,v.created,v.completed,v.error",'COALESCE(t.metadata,v.track_id)','v.created DESC,v.track_id','v.created'),
        'objects':('media_objects m','m.object_key,m.track_id,m.kind,m.mime,m.checked','m.object_key','m.object_key',None),
        'crawls':('crawl_runs r','r.id,r.started,r.finished,r.pages,r.tracks,r.errors','r.id','r.started DESC,r.id','r.started')}
    table,columns,search,order,date=tables[kind]
    where=' WHERE '+search+' LIKE ?'
    values=['%'+q+'%']
    if date:where+=f' AND {date}>=? AND {date}<?';values.extend([start,end])
    with db.connect() as c:
        if kind=='tracks':
            intro=json.loads(db.setting(c,'announcement_on_air','null'))
            table+=""" LEFT JOIN (
                SELECT track_id,COUNT(*) AS play_count FROM plays
                WHERE starts<=? AND (actual_end IS NULL OR actual_end>starts)
                  AND id!=? GROUP BY track_id
            ) pc ON pc.track_id=t.id"""
            values=[time.time(),intro.get('play_id','') if intro else '']+values
            columns=columns.replace(' AS title,',' AS title,COALESCE(pc.play_count,0) AS play_count,',1)
            for bound,operator in [(min_plays,'>='),(max_plays,'<=')]:
                if bound is not None:
                    where+=f' AND COALESCE(pc.play_count,0){operator}?'
                    values.append(bound)
            allowed={'id','title','artists','album','genre','status','duration','downloaded_at','license','source','play_count'}
            if sort is not None:
                if sort not in allowed:raise HTTPException(422,'Unknown track sort column.')
                order=f'{sort} {direction.upper()},t.id ASC'
        elif sort is not None or min_plays is not None or max_plays is not None:
            raise HTTPException(422,'Playback filters and sorting apply to tracks only.')
        total=c.execute('SELECT COUNT(*) FROM '+table+where,values).fetchone()[0]
        rows=[dict(r) for r in c.execute('SELECT '+columns+' FROM '+table+where+' ORDER BY '+order+' LIMIT ? OFFSET ?',values+[page_size,(page-1)*page_size])]
    for row in rows:
        if 'listener' in row:row['listener']='Listener '+hashlib.sha256(row['listener'].encode()).hexdigest()[:6]
    return {'items':rows,'page':page,'page_size':page_size,'total':total,'pages':max(1,math.ceil(total/page_size)),
            'date_filter_applied':bool(date)}

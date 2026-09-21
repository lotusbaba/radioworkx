"""Artist/album browsing and personal playback, separate from station broadcasts."""
import hashlib
import json
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from app import db
from app.config import DEMO, MAX_TRACKS

router=APIRouter()
STATIC=Path(__file__).parent/'static'


def entity_id(value):
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def artist_ref(name):
    return {'id':entity_id(name),'name':name}


def album_ref(meta):
    identity=meta.get('album_id') or json.dumps([meta.get('album','Unknown album'),meta['artists']],ensure_ascii=False)
    return {'id':entity_id(identity),'name':meta.get('album') or 'Unknown album'}


def public_url(value):
    return value if isinstance(value,str) and urlparse(value).scheme in {'https','http'} else None


def capped(c):
    return db.setting(c,'download_cap_reached','0')=='1' or c.execute('SELECT COUNT(*) FROM tracks WHERE downloaded_at IS NOT NULL').fetchone()[0]>=MAX_TRACKS


def public_track(row,limit=False):
    meta=json.loads(row['metadata'])
    state=('ready' if row['status']=='ready' else 'unavailable' if row['status']=='failed' or limit or not row['source'] or not row['rights'] else 'preparing' if row['status']=='downloading' else 'available')
    return {'id':row['id'],'title':meta['title'],'artists':[artist_ref(a) for a in meta['artists']],
            'album':album_ref(meta),'genre':meta['genre'],'duration':row['duration'],'status':state,
            'source_page':public_url(meta.get('bandcamp_url')),'license_url':public_url(meta.get('license_url')),
            'license_name':meta.get('license_name'),'audio_changes':meta.get('audio_changes','MP3 format conversion only')}


def inventory(c):
    limit=capped(c)
    return [public_track(row,limit) for row in c.execute('SELECT * FROM tracks ORDER BY id') if bool(json.loads(row['metadata']).get('demo'))==DEMO]


def track_row(c,track_id):
    row=c.execute('SELECT * FROM tracks WHERE id=?',(track_id,)).fetchone()
    if row is None or bool(json.loads(row['metadata']).get('demo'))!=DEMO:raise HTTPException(404,'Track not found.')
    return row


def paginate(items,page,page_size):
    total=len(items);pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    return {'items':items[(page-1)*page_size:page*page_size],'total':total,'page':page,'pages':pages}


@router.get('/artists')
@router.get('/albums')
@router.get('/artists/{entity}')
@router.get('/albums/{entity}')
def library_page(request:Request,entity:str|None=None):
    from app.api import listener_page
    if entity:
        kind='artists' if request.url.path.startswith('/artists/') else 'albums'
        detail(kind,entity,1,50)  # Return a real 404 for missing pages.
    return listener_page(request,(STATIC/'library.html').read_text())


@router.get('/api/library/{kind}')
def directory(kind:Literal['artists','albums'],q:str=Query('',max_length=200),page:int=Query(1,ge=1),page_size:int=Query(24,ge=1,le=100)):
    with db.connect() as c:tracks=inventory(c)
    groups={}
    for track in tracks:
        for ref in track['artists'] if kind=='artists' else [track['album']]:
            group=groups.setdefault(ref['id'],dict(ref,tracks=0,ready=0,artists={},albums=set(),genres=set()))
            group['tracks']+=1;group['ready']+=track['status']=='ready'
            group['artists'].update({a['id']:a for a in track['artists']});group['albums'].add(track['album']['id']);group['genres'].add(track['genre'])
    items=[dict(g,artists=list(g['artists'].values()),albums=len(g['albums']),genres=sorted(g['genres'])) for g in groups.values() if q.casefold() in (g['name']+(' '+' '.join(a['name'] for a in g['artists'].values()) if kind=='albums' else '')).casefold()]
    items.sort(key=lambda g:(g['name'].casefold(),g['id']))
    return paginate(items,page,page_size)


@router.get('/api/library/{kind}/{entity}')
def detail(kind:Literal['artists','albums'],entity:str,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=100)):
    with db.connect() as c:tracks=inventory(c)
    selected=[t for t in tracks if entity in ([a['id'] for a in t['artists']] if kind=='artists' else [t['album']['id']])]
    if not selected:raise HTTPException(404,'Page not found.')
    ref=next(a for a in selected[0]['artists'] if a['id']==entity) if kind=='artists' else selected[0]['album']
    albums={t['album']['id']:t['album'] for t in selected};artists={a['id']:a for t in selected for a in t['artists']}
    selected.sort(key=lambda t:(t['album']['name'].casefold(),t['title'].casefold(),t['id']))
    return dict(paginate(selected,page,page_size),entity=ref,albums=sorted(albums.values(),key=lambda a:a['name'].casefold()),artists=list(artists.values()),ready=sum(t['status']=='ready' for t in selected))


@router.get('/api/listen/{track_id}')
def playback_status(track_id:str):
    with db.connect() as c:
        row=track_row(c,track_id)
        result=public_track(row,capped(c))
        job=c.execute('SELECT done,failed FROM outbox WHERE id=?',('listen:'+track_id,)).fetchone()
        if job and result['status']!='ready':
            if job['failed'] or job['done'] is not None:result['status']='unavailable'
            elif result['status']=='available':result['status']='preparing'
        return result


@router.post('/api/listen/{track_id}',status_code=202)
def prepare(track_id:str,request:Request):
    from app.api import listener
    who=listener(request)
    origin=request.headers.get('origin')
    if origin and urlparse(origin).netloc!=request.url.netloc:raise HTTPException(403,'Use the player on this site.')
    with db.transaction() as c:
        row=track_row(c,track_id);result=public_track(row,capped(c))
        if result['status']=='unavailable':raise HTTPException(409,'This recording is currently unavailable.')
        if result['status']=='ready':return result
        existing=c.execute('SELECT done,failed FROM outbox WHERE id=?',('listen:'+track_id,)).fetchone()
        if existing:
            if existing['done'] is not None or existing['failed']:raise HTTPException(409,'Audio preparation failed. Please try another track.')
            return dict(result,status='preparing')
        now=time.time()
        c.execute('DELETE FROM personal_downloads WHERE created<?',(now-3600,))
        if c.execute('SELECT COUNT(*) FROM personal_downloads WHERE listener=? AND created>?',(who,now-60)).fetchone()[0]>=10:
            raise HTTPException(429,'Please wait a minute before preparing more tracks.')
        c.execute('INSERT INTO personal_downloads(listener,created) VALUES(?,?)',(who,now))
        db.emit(c,'listen:'+track_id,'request-downloads',{'kind':'listen','track_id':track_id})
        return dict(result,status='preparing')


@router.get('/api/listen/{track_id}/audio')
def recording(track_id:str,request:Request):
    from app.api import listener
    listener(request)
    with db.connect() as c:row=track_row(c,track_id)
    if row['status']!='ready' or not row['path']:raise HTTPException(409,'Audio is not ready.')
    path=Path(row['path']).resolve()
    if not path.is_relative_to((db.DATA/'audio').resolve()) or not path.is_file():raise HTTPException(404,'Audio is currently unavailable.')
    return FileResponse(path,media_type='audio/mpeg',headers={'Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'})

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, Response, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel, Field
from redis import asyncio as aioredis
from app import db
from app.config import DEMO, EMOJIS, MAX_TRACKS, REDIS_URL, THRESHOLD
from app.events import ranking, r
from app.service import accept_reaction, now_playing, next_reaction_at, ReactionCooldown, COOLDOWN
from app.views import playlist_views, next_airtime
from app.app_tokens import authenticate as app_token

sessions = URLSafeSerializer(os.getenv('SESSION_SECRET','local-development-change-me'),salt='listener')
STATIC = Path(__file__).parent / 'static'

@asynccontextmanager
async def lifespan(app):
    db.init()
    yield

app = FastAPI(title='RadioWorkx',version='0.1.0',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=STATIC),name='static')
from app.admin import router as admin_router, authorize
app.include_router(admin_router)


def listener(request):
    try:
        return sessions.loads(request.cookies.get('radio_listener',''))
    except BadSignature:
        raise HTTPException(401,'Open the station page to start a listener session')

@app.get('/')
def index(request: Request):
    version=hashlib.sha256(b''.join((STATIC / name).read_bytes() for name in ('app.js','style.css','index.html'))).hexdigest()[:12]
    html=(STATIC / 'index.html').read_text().replace('/static/app.js',f'/static/app.js?v={version}').replace('/static/style.css',f'/static/style.css?v={version}')
    response = HTMLResponse(html,headers={'Cache-Control':'no-store'})
    cookie = request.cookies.get('radio_listener','')
    try:
        sessions.loads(cookie)
    except BadSignature:
        cookie = sessions.dumps(str(uuid.uuid4()))
    response.set_cookie('radio_listener',cookie,httponly=True,samesite='strict',
                        secure=os.getenv('COOKIE_SECURE','0')=='1' or request.url.scheme=='https',
                        max_age=365*86400)
    return response

@app.get('/health')
def health():
    try:
        r.ping()
        with db.connect() as c:
            c.execute('SELECT 1').fetchone()
        return {'status':'ok'}
    except Exception:
        raise HTTPException(503,'Storage is unavailable')

@app.get('/api/status')
def status():
    with db.connect() as c:
        play = now_playing(c)
        from app.announcer import on_air
        announcement = on_air(c,time.time())
        preview_play = play
        if announcement:
            reserved=c.execute('SELECT ends FROM plays WHERE id=?',(announcement['play_id'],)).fetchone()
            if reserved: preview_play={'ends':reserved['ends'],'track_id':announcement['metadata']['id']}
        counts = c.execute('SELECT emoji,COUNT(*) AS n FROM reactions WHERE play_id=? GROUP BY emoji',
                           (play['id'] if play else '',)).fetchall()
        count = c.execute('SELECT COUNT(*) FROM tracks WHERE downloaded_at IS NOT NULL').fetchone()[0]
        pending = c.execute('SELECT COUNT(*) FROM playlist').fetchone()[0]
        history = c.execute('SELECT metadata,starts FROM plays WHERE starts<=? ORDER BY starts DESC LIMIT 7',(time.time(),)).fetchall()
        from app.visuals import public as visual_status
        visual=visual_status(c,play['track_id'] if play else announcement['metadata']['id'] if announcement else None)
        return dict(visual=visual,**playlist_views(c,preview_play,time.time()),announcement=announcement,chat_engine='rag' if os.getenv('OPENAI_API_KEY') else 'basic',next_airtime=None if play or announcement else next_airtime(c,time.time()),reaction_cooldown=COOLDOWN,play=play,ranking=ranking(),emojis=EMOJIS,
                    reactions={row['emoji']:row['n'] for row in counts},
                    downloaded=count,cap=MAX_TRACKS,queued=pending,threshold=THRESHOLD,
                    library_only=db.setting(c,'download_cap_reached','0')=='1',demo=DEMO,
                    station_status=db.setting(c,'station_status','Starting station'),
                    download_status=db.setting(c,'download_status','Waiting for authorized audio'),
                    recent=[{'metadata':json.loads(p['metadata']),'starts':p['starts']} for p in history],
                    server_time=time.time())

@app.get('/api/downloads')
def downloads_page(page: int=Query(1,ge=1,le=1000000),page_size: int=Query(10,ge=1,le=100),scope: Literal['all','automatic']='all'):
    from app.views import download_page
    with db.connect() as c:
        c.execute('BEGIN')
        return download_page(c,page,page_size,automatic=scope=='automatic')

@app.get('/api/community-requests')
def community_requests_page(page: int=Query(1,ge=1,le=1000000),page_size: int=Query(10,ge=1,le=100)):
    from app.views import community_request_page
    with db.connect() as c:
        c.execute('BEGIN')
        return community_request_page(c,page,page_size)

@app.get('/api/stats')
def public_stats(response: Response, period: Literal['24h','7d','all']='7d'):
    """Aggregate station activity only; listener identities and chat stay private."""
    end=time.time()
    start={'24h':end-86400,'7d':end-7*86400,'all':0}[period]
    with db.connect() as c:
        c.execute('BEGIN')
        library=c.execute("SELECT COUNT(*) FROM tracks WHERE status='ready'").fetchone()[0]
        genres=[dict(row) for row in c.execute("SELECT COALESCE(json_extract(metadata,'$.genre'),'Unknown') AS genre,COUNT(*) AS likes FROM reactions WHERE accepted>=? AND accepted<? GROUP BY genre ORDER BY likes DESC,genre",(start,end))]
        downloads=c.execute('SELECT COUNT(*) FROM host_downloads WHERE completed>=? AND completed<?',(start,end)).fetchone()[0]
        requests=c.execute('SELECT COUNT(*) FROM requests WHERE track_id IS NOT NULL AND created>=? AND created<?',(start,end)).fetchone()[0]
    response.headers['Cache-Control']='public, max-age=15'
    return dict(period=period,library=library,likes=sum(row['likes'] for row in genres),downloads=downloads,requests=requests,genres=genres,updated_at=end)

@app.get('/api/session')
def session_status(request: Request):
    with db.connect() as c:
        return {'next_reaction_at':next_reaction_at(c,listener(request)),'server_time':time.time()}


@app.get('/api/sources',dependencies=[Depends(authorize)])
def sources():
    from app.hosts import repository
    with db.connect() as c:
        return {'hosts':repository(c),'crawler_status':db.setting(c,'crawler_status','Waiting for first crawl'),
                'runs':[dict(r) for r in c.execute('SELECT * FROM crawl_runs ORDER BY started DESC LIMIT 5')],
                'unique_downloads':c.execute('SELECT COUNT(*) FROM host_downloads').fetchone()[0]}

class Reaction(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    play_id: uuid.UUID
    emoji: Literal['❤️','🔥','🙌','😍','💃','🤯']

@app.post('/api/reactions',status_code=202)
def react(body: Reaction, request: Request):
    who = listener(request)
    try:
        id = accept_reaction(str(body.play_id),who,body.emoji,event_id=str(body.event_id))
    except ReactionCooldown as e:
        raise HTTPException(429,str(e),headers={'Retry-After':str(e.retry_after)})
    except ValueError as e:
        raise HTTPException(409,str(e))
    with db.connect() as c:
        return {'event_id':id,'status':'queued','next_reaction_at':next_reaction_at(c,who),'server_time':time.time()}

@app.get('/api/catalog/genres',dependencies=[Depends(app_token)])
def catalog_genres():
    from app.catalog_api import genre_counts
    return genre_counts()

@app.get('/api/catalog/tracks',dependencies=[Depends(app_token)])
def catalog_tracks(genre: list[str]=Query(default=[]),q: str=Query('',max_length=300),
                   page: int=Query(1,ge=1,le=1000000),page_size: int=Query(20,ge=1,le=100)):
    from app.catalog_api import catalog
    return catalog(genre,q,page,page_size)

class QueueTrack(BaseModel):
    track_id: str=Field(min_length=1,max_length=200)
    request_id: uuid.UUID=Field(default_factory=uuid.uuid4)

@app.post('/api/queue',status_code=202)
def queue_track(body: QueueTrack,identity: str=Depends(app_token)):
    from app.catalog_api import enqueue
    return enqueue(body.track_id,identity,str(body.request_id))

class TrackRequest(BaseModel):
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    query: str = Field(min_length=1,max_length=300)
    mode: Literal['auto','track','artist','album','genre'] = 'auto'

@app.get('/api/requests')
def request_history(request: Request):
    from app.requests import history
    return {'messages':history(listener(request))}

@app.post('/api/requests')
def request_track(body: TrackRequest, request: Request):
    from app.requests import submit
    if not body.query.strip():
        raise HTTPException(422,'Enter a track, artist, or album.')
    try:
        return submit(body.query.strip(),body.mode,listener(request),str(body.request_id))
    except ValueError as error:
        raise HTTPException(409,str(error))

@app.get('/api/events')
async def events(request: Request):
    raw = request.headers.get('last-event-id','')
    if raw and not re.fullmatch(r'\d+-\d+',raw):
        raise HTTPException(400,'Invalid event cursor')
    async def stream():
        client = aioredis.from_url(REDIS_URL,decode_responses=True)
        try:
            last = await client.xrevrange('radio:events',count=1)
            cursor = raw or (last[0][0] if last else '0-0')
            yield 'event: snapshot\ndata: '+json.dumps(await asyncio.to_thread(status))+'\n\n'
            while not await request.is_disconnected():
                rows = await client.xread({'radio:events':cursor},count=100,block=2000)
                if not rows:
                    yield 'event: snapshot\ndata: '+json.dumps(await asyncio.to_thread(status))+'\n\n'
                    continue
                for _,messages in rows:
                    for id,fields in messages:
                        cursor = id
                        yield f'id: {id}\nevent: {fields["kind"]}\ndata: {fields["body"]}\n\n'
                yield 'event: snapshot\ndata: '+json.dumps(await asyncio.to_thread(status))+'\n\n'
        finally:
            await client.aclose()
    return StreamingResponse(stream(),media_type='text/event-stream',headers={
        'Cache-Control':'no-cache','X-Accel-Buffering':'no','Connection':'keep-alive'})

@app.get('/api/live')
async def live(request: Request):
    listener(request)
    async def audio():
        client = aioredis.from_url(REDIS_URL)
        cursor = '$'
        try:
            # Start at the live edge. Only the server may choose tracks or their position.
            while not await request.is_disconnected():
                rows = await client.xread({'radio:audio':cursor},count=10,block=10000)
                if not rows:
                    continue
                for _,messages in rows:
                    for id,fields in messages:
                        cursor = id
                        yield fields[b'chunk']
                # Drop backlog for a slow connection instead of becoming an archive.
                latest = await client.xrevrange('radio:audio',count=1)
                if latest and int(latest[0][0].split(b'-')[0])-int(cursor.split(b'-')[0]) > 3000:
                    cursor = latest[0][0]
        finally:
            await client.aclose()
    return StreamingResponse(audio(),media_type='audio/mpeg',headers={
        'Cache-Control':'no-store','X-Accel-Buffering':'no','Accept-Ranges':'none'})


@app.get('/api/visuals/{track_id}/{kind}')
def visual_asset(track_id:str,kind:Literal['video','artwork']):
    from app import object_store
    from fastapi.responses import FileResponse
    with db.connect() as c:
        visual=c.execute('SELECT * FROM track_visuals WHERE track_id=?',(track_id,)).fetchone()
        if not visual or not visual[kind+'_key']:raise HTTPException(404,'Visual is not ready')
        row=c.execute('SELECT * FROM media_objects WHERE object_key=?',(visual[kind+'_key'],)).fetchone()
    if not row:raise HTTPException(404,'Visual is not ready')
    try:path=object_store.local_path(row)
    except Exception:raise HTTPException(503,'Visual is temporarily unavailable')
    return FileResponse(path,media_type=row['mime'],headers={'Cache-Control':'public, max-age=86400','X-Content-Type-Options':'nosniff'})

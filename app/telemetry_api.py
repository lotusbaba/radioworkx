"""Validated browser events and sanitized ASGI request/outcome instrumentation."""
import json
import time
import uuid
from collections import OrderedDict
from urllib.parse import urlparse
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal
from app import telemetry as t

router=APIRouter()
ACTIONS={'page.view','search.submitted','search.results','play.clicked','live.tune_in','live.tune_out','playback.started','playback.paused','playback.resumed','playback.seek','playback.stopped','playback.ended','playback.heartbeat','playback.buffering','playback.reconnect','playback.error','playback.blocked','preparation.waiting','preparation.ready','preparation.failed','browser.error'}

class BrowserEvent(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    timestamp:float
    latency_ms:float|None=Field(None,ge=0,le=600000)
    id:uuid.UUID
    action:str=Field(max_length=50)
    playback_id:uuid.UUID|None=None
    track_id:str|None=Field(None,max_length=200)
    mode:Literal['live','personal']|None=None
    page:Literal['station','artists','artist','albums','album']
    entity_id:str|None=Field(None,max_length=64)
    listened_ms:int=Field(0,ge=0,le=35000)
    position_seconds:float|None=Field(None,ge=0,le=86400)
    seek_from:float|None=Field(None,ge=0,le=86400)
    seek_to:float|None=Field(None,ge=0,le=86400)
    query_length:int|None=Field(None,ge=0,le=300)
    result_count:int|None=Field(None,ge=0,le=10000000)
    engaged:bool=False
    error_code:Literal['media','javascript','promise','network','preparation','autoplay']|None=None

class Batch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    session_id:uuid.UUID
    events:list[BrowserEvent]=Field(min_length=1,max_length=50)

_limits=OrderedDict()

@router.post('/api/activity',status_code=202)
async def activity(body:Batch,request:Request):
    from app.api import listener
    who=listener(request)
    origin=request.headers.get('origin')
    if origin and urlparse(origin).netloc!=request.url.netloc:raise HTTPException(403,'Invalid event origin')
    if any(e.timestamp<time.time()-86400 or e.timestamp>time.time()+120 for e in body.events):raise HTTPException(422,'Event timestamp outside collection window')
    if any(e.action not in ACTIONS for e in body.events):raise HTTPException(422,'Unsupported event action')
    now=time.monotonic();key=t.identity(who);entry=_limits.get(key,(now,0))
    if now-entry[0]>60:entry=(now,0)
    if entry[1]+len(body.events)>240:raise HTTPException(429,'Event rate exceeded')
    _limits[key]=(entry[0],entry[1]+len(body.events));_limits.move_to_end(key)
    while len(_limits)>10000:_limits.popitem(last=False)
    ua=request.headers.get('user-agent','').lower()
    browser='firefox' if 'firefox' in ua else 'edge' if 'edg/' in ua else 'chrome' if 'chrome' in ua else 'safari' if 'safari' in ua else 'other'
    for e in body.events:
        data=e.model_dump(exclude={'id','action','playback_id','timestamp'},exclude_none=True)
        t.emit(e.action,at=e.timestamp,who=who,session=str(body.session_id),event_id=t.identity(who+':'+str(e.id)),origin='browser',outcome='failure' if e.action.endswith(('.error','.failed','.blocked')) else 'success',playback_id=str(e.playback_id) if e.playback_id else None,browser=browser,device='mobile' if 'mobile' in ua else 'desktop',**data)
    return {'accepted':len(body.events)}


class ActivityMiddleware:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        path=scope.get('path','');method=scope['method']
        if path.startswith('/static/') or path in {'/health','/api/activity','/api/admin/activity'}:return await self.app(scope,receive,send)
        started=time.monotonic();trace_id=uuid.uuid4().hex;status=500;request_body=bytearray();response_body=bytearray();sent_headers=False
        capture=method in {'POST','DELETE'} and path.startswith(('/api/requests','/api/reactions','/api/queue','/api/listen','/api/admin/tokens'))
        async def recv():
            message=await receive()
            if capture and message['type']=='http.request' and len(request_body)<8192:request_body.extend(message.get('body',b'')[:8192-len(request_body)])
            return message
        def record(error=None):
            route=getattr(scope.get('route'),'path','unmatched')
            who=None
            try:
                from app.api import listener
                who=listener(Request(scope))
            except Exception:pass
            fields=dict(who=scope.get('app_identity') or who,trace_id=trace_id,route=route,method=method,status_code=status,latency_ms=round((time.monotonic()-started)*1000,2))
            t.emit('api.request',outcome='failure' if status>=400 else 'success',duration=time.monotonic()-started,**fields)
            if error:t.emit('api.error',outcome='failure',error_code=type(error).__name__,**fields)
            if path.startswith('/admin') or path.startswith('/api/admin/'):
                t.emit('admin.authentication_failed' if status==401 else 'admin.authentication_succeeded' if status<400 else 'admin.action_failed',outcome='failure' if status>=400 else 'success',**fields)
            if not capture:return
            try:body=json.loads(request_body or b'{}')
            except Exception:body={}
            try:result=json.loads(response_body or b'{}')
            except Exception:result={}
            if not isinstance(body,dict):body={}
            if not isinstance(result,dict):result={}
            action=('reaction.accepted' if status<400 else 'reaction.rejected') if path=='/api/reactions' else 'request.submitted' if path in {'/api/requests','/api/queue'} else 'preparation.requested' if path.startswith('/api/listen/') else 'admin.token_revoked' if method=='DELETE' else 'admin.token_created'
            tid=body.get('track_id') or result.get('track_id') or (scope.get('path_params',{}).get('track_id') if path.startswith('/api/listen/') else None)
            domain_id=(result.get('event_id') if action=='reaction.accepted' else result.get('id') if action=='request.submitted' and status<400 else None)
            t.emit(action,event_id=t.identity(action+':'+str(domain_id)) if domain_id else None,at=result.get('created') if action=='request.submitted' else None,outcome='success' if status<400 else 'failure',track_id=tid,request_id=body.get('request_id') or result.get('id'),broadcast_id=body.get('play_id'),query_length=len(str(body.get('query',''))),state=result.get('status'),emoji=body.get('emoji') if body.get('emoji') in {'❤️','🔥','🙌','😍','💃','🤯'} else None,token_id=result.get('id') if 'admin/tokens' in path else None,**fields)
        async def output(message):
            nonlocal status,sent_headers
            if message['type']=='http.response.start':
                status=message['status'];sent_headers=True
                message['headers']=list(message.get('headers',[]))+[(b'x-request-id',trace_id.encode())]
                # Log stream establishment now, not hours later when it disconnects.
                if path in {'/api/events','/api/live'}:record()
            if capture and message['type']=='http.response.body' and len(response_body)<32768:response_body.extend(message.get('body',b'')[:32768-len(response_body)])
            await send(message)
        try:
            await self.app(scope,recv,output)
        except Exception as error:
            record(error);raise
        else:
            if path not in {'/api/events','/api/live'}:record()

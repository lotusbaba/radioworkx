"""Bounded asynchronous telemetry. Only allowlisted structured fields leave the app."""
import atexit
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import threading
import time
import uuid
from datetime import datetime,timezone

FIELDS={'track_id','request_id','job_id','broadcast_id','playback_id','mode','page','entity_id','query_length','result_count','status_code','route','method','error_code','queue','attempt','queue_delay_ms','latency_ms','listened_ms','position_seconds','seek_from','seek_to','duration_seconds','emoji','token_id','config_key','config_digest','state','buffer_drops','browser','device','origin','engaged','matched_count'}
_buffer=queue.Queue(maxsize=10000)
_lock=threading.Lock();_thread=None;_dropped=0


def identity(value):
    return hmac.new(os.getenv('SESSION_SECRET','local-development-change-me').encode(),str(value).encode(),hashlib.sha256).hexdigest()[:32] if value else None


def make_event(action,*,who=None,session=None,outcome='success',origin='server',event_id=None,at=None,duration=None,trace_id=None,**fields):
    event={'@timestamp':datetime.fromtimestamp(at or time.time(),timezone.utc).isoformat(), 'ecs':{'version':'8.17.0'},
           'event':{'id':event_id or str(uuid.uuid4()),'action':action,'outcome':outcome,'kind':'event','dataset':'radioworkx.activity'},
           'service':{'name':os.getenv('SERVICE_NAME','radioworkx-api')},'radioworkx':{'origin':origin},'log':{'level':'error' if outcome=='failure' else 'info'}}
    if trace_id:event['trace']={'id':str(trace_id)[:64]}
    if who:event['user']={'id':identity(who)}
    if session:event['session']={'id':str(session)[:64]}
    if duration is not None:event['event']['duration']=max(0,int(duration*1e9))
    for k,v in fields.items():
        if k in FIELDS and v is not None and isinstance(v,(str,int,float,bool)):
            event['radioworkx'][k]=v[:200] if isinstance(v,str) else v
    return event


def enrich(event):
    tid=event['radioworkx'].get('track_id')
    from app import db
    with db.connect() as c:
        if not tid and event['radioworkx'].get('broadcast_id'):
            play=c.execute('SELECT track_id FROM plays WHERE id=?',(event['radioworkx']['broadcast_id'],)).fetchone()
            if play:tid=play['track_id'];event['radioworkx']['track_id']=tid
        if not tid:return
        row=c.execute('SELECT metadata FROM tracks WHERE id=?',(tid,)).fetchone()
    if row:
        m=json.loads(row['metadata']);event['radioworkx'].update(track_title=m.get('title'),artists=m.get('artists'),album=m.get('album'),album_id=m.get('album_id'),genre=m.get('genre'),provider=m.get('provider') or m.get('source_kind','catalog'))


def consume_and_write_events():
    global _dropped
    directory=Path(os.getenv('TELEMETRY_DIR','/data/telemetry'));directory.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(directory/(os.getenv('HOSTNAME','local')+'.jsonl'),maxBytes=20*1024*1024,backupCount=4)
    handler.setFormatter(logging.Formatter('%(message)s'))
    while True:
        event=_buffer.get()
        try:
            try:enrich(event)
            except Exception:pass
            if _dropped:event['radioworkx']['buffer_drops']=_dropped;_dropped=0
            handler.emit(logging.LogRecord('activity',logging.INFO,'',0,json.dumps(event,ensure_ascii=False),(),None))
        except Exception:_dropped+=1
        finally:_buffer.task_done()


def emit(action,**kwargs):
    global _thread,_dropped
    if os.getenv('TELEMETRY_ENABLED')!='1':return
    try:
        event=make_event(action,**kwargs)
        with _lock:
            if _thread is None or not _thread.is_alive():
                _thread=threading.Thread(target=consume_and_write_events,name='telemetry-writer',daemon=True);_thread.start()
        _buffer.put_nowait(event)
    except Exception:_dropped+=1


class ErrorHandler(logging.Handler):
    def emit(self,record):
        if record.levelno>=logging.ERROR:
            emit('worker.error',outcome='failure',error_code=record.exc_info[0].__name__ if record.exc_info else 'WorkerError',state=record.name)


def install_errors():
    logging.getLogger().addHandler(ErrorHandler())


@atexit.register
def flush():
    deadline=time.monotonic()+2
    while _buffer.unfinished_tasks and time.monotonic()<deadline:time.sleep(.01)

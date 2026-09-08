import json
import logging
import subprocess
import time
import uuid
import redis
from app import db
from app.config import REDIS_URL, DEMO
from app.events import publish
from app.policy import eligible, WINDOW
from app.service import now_playing
from app.requests import head, refresh_genre_head

log = logging.getLogger(__name__)
audio_redis = redis.Redis.from_url(REDIS_URL)


def refill(now=None):
    now = time.time() if now is None else now
    with db.transaction() as c:
        from app.downloads import library_only
        refresh_genre_head(c, now)
        if needs_recovery(c,now) and not library_only(c):
            recovering=c.execute("SELECT 1 FROM outbox WHERE done IS NULL AND json_extract(body,'$.kind')='recovery'").fetchone()
            last_recovery=float(db.setting(c,'last_recovery','0'))
            if not recovering and now-last_recovery>=300:
                id='recovery:'+str(uuid.uuid4())
                db.emit(c,id,'priority-downloads',{'kind':'recovery'})
                db.set_setting(c,'last_recovery',now)
                db.set_setting(c,'download_status','Finding eligible music to resume playback')
                return id
        count = c.execute('SELECT COUNT(*) FROM playlist').fetchone()[0] + bool(now_playing(c,now))
        pending = c.execute("SELECT COUNT(*) FROM outbox WHERE queue='downloads' AND done IS NULL AND json_extract(body,'$.kind')='refill'").fetchone()[0]
        last = float(db.setting(c,'last_refill','0'))
        if count <= 3 and not pending and now-last >= 60:
            id = 'refill:'+str(uuid.uuid4())
            db.emit(c,id,'downloads',{'kind':'refill'})
            db.set_setting(c,'last_refill',now)
            return id


def needs_recovery(c,now):
    active=now_playing(c,now)
    at=active['ends'] if active else now
    history=[dict(p,metadata=json.loads(p['metadata'])) for p in c.execute(
        'SELECT * FROM plays WHERE ends>? OR id IN (SELECT id FROM plays ORDER BY starts DESC LIMIT 3) ORDER BY starts',(at-WINDOW,))]
    if not history:return False  # Startup still uses the normal ten-genre batch.
    from app.scheduling import preview
    return len(preview(c,history,at,size=3)) < 3



def select_next(now=None, expected_track_id=None, start_delay=0, expected_request_id=...):
    now = time.time() if now is None else now
    with db.transaction() as c:
        refresh_genre_head(c, now)
        # Variety ranking needs older plays too. Match peek/preview exactly;
        # eligible() itself applies the three-hour performance window.
        history = [dict(p,metadata=json.loads(p['metadata'])) for p in c.execute('SELECT * FROM plays ORDER BY starts')]
        from app.scheduling import candidates, choose
        selected = choose(candidates(c), history, now)
        if expected_track_id is not None and (not selected or selected['id'] != expected_track_id):
            return None
        if expected_request_id is not ... and (not selected or selected.get('request_id') != expected_request_id):
            return None
        rows = [selected] if selected else []
        for row in rows:
            meta = json.loads(row['metadata'])
            if bool(meta.get('demo')) != DEMO:
                continue
            if not eligible(meta,history,now):
                continue
            play = dict(id=str(uuid.uuid4()),track_id=row['id'],metadata=meta,starts=now+start_delay,ends=now+start_delay+row['duration'],requested='request_id' in row)
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',
                      (play['id'],play['track_id'],json.dumps(meta),play['starts'],play['ends']))
            c.execute('DELETE FROM playlist WHERE track_id=?',(row['id'],))
            if 'request_id' in row.keys():
                c.execute("UPDATE requests SET status='playing',play_id=? WHERE id=?",(play['id'],row['request_id']))
            db.set_setting(c,'station_status','On air')
            return play,row['path']
        db.set_setting(c,'station_status','Waiting for eligible tracks' if rows else 'Waiting for audio')
        return None


def transmit(path, demo=False):
    codec = (['-af','volume=32','-c:a','libmp3lame','-ar','44100','-b:a','128k']
             if demo else ['-c:a','copy'])
    process = subprocess.Popen(['ffmpeg','-v','error','-re','-i',str(path),'-map_metadata','-1',
                                *codec,'-write_xing','0','-id3v2_version','0','-f','mp3','pipe:1'],
                               stdout=subprocess.PIPE)
    try:
        while block := process.stdout.read(2048):
            audio_redis.xadd('radio:audio',{'chunk':block},maxlen=160,approximate=True)
        if process.wait(timeout=10): raise RuntimeError('Audio transmission failed')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def peek(at=None):
    from app.scheduling import candidates, choose
    at = time.time() if at is None else at
    with db.connect() as c:
        history = [dict(p,metadata=json.loads(p['metadata'])) for p in c.execute('SELECT * FROM plays ORDER BY starts')]
        return choose(candidates(c),history,at)


def start_music(play):
    """Reaction and playback clocks begin with music, after the spoken introduction."""
    duration = play['ends']-play['starts']
    now = time.time()
    play.update(starts=now,ends=now+duration)
    with db.transaction() as c:
        c.execute('UPDATE plays SET starts=?,ends=? WHERE id=?',(play['starts'],play['ends'],play['id']))
        db.set_setting(c,'announcement_on_air','null')
        db.set_setting(c,'station_status','On air')
    publish('track',play)


def ready_intro(candidate, warm):
    """Use prepared speech only; provider latency must never hold the music loop."""
    from app import announcer
    if not announcer.enabled(): return None
    if warm and warm[0]==(candidate['id'],candidate.get('request_id')) and warm[1].done():
        try:
            intro=warm[1].result()
            if intro: return intro
        except Exception:
            log.warning('Prepared introduction unavailable; continuing with music')
    return announcer.cached(candidate['meta'],requested='request_id' in candidate)


def run():
    import threading
    from app import announcer
    with db.transaction() as c:
        c.execute('UPDATE plays SET actual_end=? WHERE actual_end IS NULL',(time.time(),))
        c.execute("UPDATE requests SET status='played' WHERE status='playing'")
        db.set_setting(c,'announcement_on_air','null')
    audio_redis.delete('radio:audio')
    def intro_loop():
        while True:
            try: announcer.prepare_upcoming_once()
            except Exception: log.exception('Upcoming introduction preparation failed')
            time.sleep(2)
    threading.Thread(target=intro_loop,name='announcer-queue',daemon=True).start()
    while True:
        refill()
        candidate = peek()
        if not candidate:
            with db.transaction() as c: db.set_setting(c,'station_status','Waiting for eligible tracks')
            time.sleep(1)
            continue
        intro = ready_intro(candidate,None)
        selected = select_next(expected_track_id=candidate['id'],start_delay=intro['duration'] if intro else 0,expected_request_id=candidate.get('request_id'))
        if not selected: continue  # Queue changed during preparation: never introduce the wrong track.
        play,path = selected
        try:
            if intro:
                now = time.time()
                duration = play['ends']-play['starts']
                play.update(starts=now+intro['duration'],ends=now+intro['duration']+duration)
                announcement = {'play_id':play['id'],'metadata':play['metadata'],'script':intro['script'],
                                'source':json.loads(intro['details']).get('source'),
                                'starts':now,'ends':play['starts'],'voice':intro['voice']}
                with db.transaction() as c:
                    c.execute('UPDATE plays SET starts=?,ends=? WHERE id=?',(play['starts'],play['ends'],play['id']))
                    db.set_setting(c,'announcement_on_air',json.dumps(announcement))
                    db.set_setting(c,'station_status','AI announcer on air')
                publish('announcement',announcement)
                try: transmit(intro['path'])
                except Exception: log.warning('Introduction playback failed; continuing with music')
            start_music(play)
            refill()
            transmit(path,bool(play['metadata'].get('demo')))
        except Exception:
            log.exception('Transmission interrupted')
        finally:
            with db.transaction() as c:
                c.execute('UPDATE plays SET actual_end=?,ends=MAX(ends,?) WHERE id=?',(time.time(),time.time(),play['id']))
                c.execute("UPDATE requests SET status='played' WHERE play_id=?",(play['id'],))
                db.set_setting(c,'announcement_on_air','null')
            publish('track_end',{'play_id':play['id']})

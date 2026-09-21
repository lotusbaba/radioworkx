import json
import logging
import os
import random
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx
from app import db
from app.config import DATA, DEMO, MAX_TRACKS
from app.policy import diverse_sample, balanced_sample, eligible, WINDOW

log = logging.getLogger(__name__)


def bootstrap():
    from app.catalog import import_catalog
    import_catalog('catalog/bandcamp.json',overwrite=False)
    with db.transaction() as c:
        c.execute("DELETE FROM playlist WHERE track_id IN (SELECT id FROM tracks WHERE COALESCE(json_extract(metadata,'$.demo'),0) != ?)",(int(DEMO),))
    if not DEMO:
        return
    genres = ['ambient','punk','soul','folk','techno','jazz','afrobeat','electronica','hip-hop','doom metal']
    with db.transaction() as c:
        for i in range(40):
            g = genres[i % 10]
            artist = f'Demo Ensemble {i % 20 + 1:02}'
            meta = dict(id=f'demo-{i:03}',title=f'Test transmission {i+1:02}',artists=[artist],
                        album=f'Synthetic Sessions {i//20+1}',album_id=f'demo-album-{i}',
                        genre=g,bandcamp_url=None,compilation_id=None,demo=True)
            c.execute('INSERT OR IGNORE INTO tracks(id,metadata,source,rights) VALUES(?,?,?,?)',
                      (meta['id'],json.dumps(meta),'demo://'+str(i),'Locally synthesized test tone; no artist recording'))


def library_only(c):
    count = c.execute('SELECT COUNT(*) FROM tracks WHERE downloaded_at IS NOT NULL').fetchone()[0]
    if count >= MAX_TRACKS:
        db.set_setting(c,'download_cap_reached','1')
    return db.setting(c,'download_cap_reached','0') == '1'


def plan_job(event):
    if event['kind']=='refill':return plan_refill(event)
    if event.get('discover_genre'):
        with db.connect() as c:
            existing=c.execute('SELECT body,done FROM jobs WHERE id=?',(event['id'],)).fetchone()
            request=c.execute("SELECT 1 FROM requests WHERE id=? AND status='pending'",(event['request_id'],)).fetchone()
        if existing: return json.loads(existing['body']),bool(existing['done'])
        if request:
            from app.discovery import discover
            discover(event['discover_genre'])
        with db.transaction() as c:
            from app.requests import refresh_genre_head
            if request: refresh_genre_head(c,time.time())
            plan={'tracks':[],'kind':'request','completed':[]}
            c.execute('INSERT OR IGNORE INTO jobs(id,body) VALUES(?,?)',(event['id'],json.dumps(plan)))
        return plan,False
    if event['kind']=='recovery':
        with db.transaction() as c:
            exists=c.execute('SELECT 1 FROM jobs WHERE id=?',(event['id'],)).fetchone()
            capped=library_only(c)
            now=time.time()
            history=[dict(p,metadata=json.loads(p['metadata'])) for p in c.execute(
                'SELECT * FROM plays WHERE ends>? OR id IN (SELECT id FROM plays ORDER BY starts DESC LIMIT 3) ORDER BY starts',(now-WINDOW,))]
            fresh_eligible=any(eligible(json.loads(t['metadata']),history,now) for t in c.execute(
                "SELECT metadata FROM tracks WHERE status='available' AND source IS NOT NULL AND rights IS NOT NULL "
                "AND id NOT IN (SELECT track_id FROM playlist) AND id NOT IN (SELECT track_id FROM requests WHERE status='pending')"))
        if not exists and not capped and not fresh_eligible and not DEMO:
            from app.discovery import discover
            discover()
    with db.transaction() as c:
        row = c.execute('SELECT body,done FROM jobs WHERE id=?',(event['id'],)).fetchone()
        if row:
            return json.loads(row['body']), bool(row['done'])
        if event['kind'] in {'request','listen'}:
            plan = {'tracks':[event['track_id']],'kind':event['kind'],'completed':[]}
            c.execute('INSERT INTO jobs(id,body) VALUES(?,?)',(event['id'],json.dumps(plan)))
            return plan, False
        capped = library_only(c)
        rows = c.execute("SELECT * FROM tracks WHERE status IN ('available','ready') AND id NOT IN (SELECT track_id FROM playlist)").fetchall()
        active = c.execute('SELECT track_id FROM plays WHERE actual_end IS NULL AND ends>?',(time.time(),)).fetchall()
        excluded = {x[0] for x in active} | {event.get('exclude')}
        candidates = []
        fresh = []
        for row in rows:
            t = json.loads(row['metadata'])
            if t['id'] in excluded or bool(t.get('demo')) != DEMO:
                continue
            if row['status'] != 'ready' and (capped or not row['source'] or not row['rights']):
                continue
            candidates.append(t)
            if row['status'] != 'ready':
                fresh.append(t)
        if event['kind']=='recovery':
            now=time.time()
            history=[dict(p,metadata=json.loads(p['metadata'])) for p in c.execute(
                'SELECT * FROM plays WHERE ends>? OR id IN (SELECT id FROM plays ORDER BY starts DESC LIMIT 3) ORDER BY starts',(now-WINDOW,))]
            requested={r[0] for r in c.execute("SELECT track_id FROM requests WHERE status='pending'")}
            pool=[t for t in fresh if t['id'] not in requested and eligible(t,history,now)]
            random.shuffle(pool)
            selected=[]
            artists=set()
            # Urgent recovery may be smaller than ten; never wait for a full diverse batch.
            for t in pool:
                if not artists.intersection(t['artists']):
                    selected.append(t)
                    artists.update(t['artists'])
                if len(selected)==10:break
        elif event['kind'] == 'boost':
            same = [t for t in candidates if set(t['artists']) & set(event['artists']) or t['album_id'] == event['album_id']]
            # Genre is a fallback if the current artist/album has no other authorized track.
            pool = same or [t for t in candidates if t['genre'] == event['genre']]
            selected = random.sample(pool,1) if pool else []
        else:
            selected = diverse_sample(fresh) or diverse_sample(candidates)
        plan = {'tracks':[t['id'] for t in selected],'kind':event['kind'],'completed':[]}
        c.execute('INSERT INTO jobs(id,body) VALUES(?,?)',(event['id'],json.dumps(plan)))
        if not selected:
            db.set_setting(c,'download_status','No eligible new tracks in reviewed sources; discovery will retry' if event['kind']=='recovery' else 'Waiting for a diverse authorized catalog' if event['kind'] != 'boost' else 'No authorized follow-up available')
        return plan, False


class TrackReserved(RuntimeError):
    pass


def reserve(track_id):
    with db.transaction() as c:
        row = c.execute('SELECT * FROM tracks WHERE id=?',(track_id,)).fetchone()
        if row is None or row['status']=='failed':
            raise ValueError('Track is quarantined after a failed download')
        if row['status'] == 'ready':
            return dict(row)
        if library_only(c):
            return None
        used = c.execute("SELECT COUNT(*) FROM tracks WHERE downloaded_at IS NOT NULL OR status='downloading'").fetchone()[0]
        if used >= MAX_TRACKS:
            return None
        if row['status'] == 'downloading':
            raise TrackReserved('Track already reserved')
        c.execute("UPDATE tracks SET status='downloading',error=NULL WHERE id=?",(track_id,))
        return dict(row)


def fetch_audio(row, target):
    source = row['source'] or ''
    if source.startswith('demo://') and DEMO and json.loads(row['metadata']).get('demo'):
        frequency = 130 + (int(source.split('://')[1]) % 20) * 16
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
                        f'sine=frequency={frequency}:duration=45:sample_rate=44100',
                        '-af','volume=0.08,tremolo=f=3:d=0.7','-ac','2','-b:a','128k',str(target)],check=True,timeout=120)
        return
    allowed = {h.strip().lower() for h in os.getenv('DOWNLOAD_HOSTS','').split(',') if h.strip()}
    metadata = json.loads(row['metadata'])
    if metadata.get('source_kind') == 'bandcamp_cc':
        from app.bandcamp import resolve_audio
        source = resolve_audio(source, metadata, allowed, dynamic=True)
        allowed.add(urlparse(source).hostname)
    if metadata.get('source_kind') == 'archive_cc':
        from app.crawler import fetch
        from app.archive_source import tracks
        from urllib.parse import quote
        document=json.loads(fetch('https://archive.org/metadata/'+quote(metadata['archive_identifier'],safe='')))
        verified=next((t for t in tracks(document,metadata['archive_identifier'],metadata['genre']) if t['id']==row['id']),None)
        if not verified or any(verified[k]!=metadata[k] for k in ('title','artists','album_id','license_url')):
            raise ValueError('Archive metadata or license changed')
        source=verified['source_url']
        allowed.add('archive.org')
    parsed = urlparse(source)
    if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username or parsed.password:
        raise ValueError('Audio URL must use HTTPS and an operator-allowlisted hostname')
    raw = target.with_suffix('.source')
    try:
        if metadata.get('source_kind')=='archive_cc':
            # Archive routes /download URLs to its own storage nodes. Validate every hop.
            from app.hosts import valid_url
            from urllib.parse import urljoin
            for _ in range(4):
                valid_url(source,'archive')
                with httpx.stream('GET',source,timeout=30,follow_redirects=False) as check:
                    if not check.is_redirect:break
                    source=urljoin(source,check.headers['location'])
            else:raise ValueError('Too many Archive redirects')
            valid_url(source,'archive')
            parsed=urlparse(source)
        # Redirects must be supplied as an explicit allowlisted final URL. No HTML/preview scraping.
        with httpx.stream('GET', source, timeout=30, follow_redirects=False) as response:
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError('Use the final authorized audio URL, redirects are disabled')
            total, started = 0, time.monotonic()
            with raw.open('wb') as f:
                for block in response.iter_bytes(65536):
                    total += len(block)
                    if total > 200 * 1024 * 1024 or time.monotonic()-started > 300:
                        raise ValueError('Download exceeded the 200 MiB / 300 second limit')
                    f.write(block)
        duration = probe(raw)
        if not 1 <= duration <= 1800:
            raise ValueError('Track duration must be 1–1800 seconds')
        subprocess.run(['ffmpeg','-v','error','-y','-protocol_whitelist','file,pipe','-i',str(raw),
                        '-vn','-map_metadata','-1','-ac','2','-ar','44100','-b:a','128k',str(target)],check=True,timeout=120)
        return parsed.hostname
    finally:
        raw.unlink(missing_ok=True)


def probe(path):
    result = subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_entries','format=duration',
                             '-of','default=noprint_wrappers=1:nokey=1',str(path)],capture_output=True,text=True,check=True,timeout=20)
    return float(result.stdout.strip())


def acquire(track_id):
    row = reserve(track_id)
    if row is None or row['status'] == 'ready':
        return row is not None
    from app import telemetry
    download_started=time.monotonic()
    telemetry.emit('download.started',track_id=track_id)
    audio_dir = DATA / 'audio'
    audio_dir.mkdir(parents=True,exist_ok=True)
    partial = audio_dir / f'{track_id}.part.mp3'
    final = audio_dir / f'{track_id}.mp3'
    try:
        media_host=fetch_audio(row,partial)
        duration = probe(partial)
        if not 1 <= duration <= 1800:
            raise ValueError('Invalid audio duration')
        partial.replace(final)
        with db.transaction() as c:
            c.execute("UPDATE tracks SET status='ready',path=?,duration=?,downloaded_at=?,error=NULL WHERE id=?",
                      (str(final),duration,time.time(),track_id))
            library_only(c)
            from app.hosts import completed
            completed(c,track_id,urlparse(json.loads(row['metadata']).get('bandcamp_url','')).hostname,media_host,time.time())
            db.set_setting(c,'download_status','Library only · 10,000 tracks' if library_only(c) else 'Standing by')
        telemetry.emit('download.completed',track_id=track_id,duration=time.monotonic()-download_started)
        return True
    except Exception as error:
        partial.unlink(missing_ok=True)
        with db.transaction() as c:
            # Do not persist source URLs or HTTP exceptions (signed URLs may contain secrets).
            c.execute("UPDATE tracks SET status='available',error=? WHERE id=?",(type(error).__name__,track_id))
            db.set_setting(c,'download_status',f'Download failed for {track_id}: {type(error).__name__}')
        raise


def process_job(event):
    plan, done = plan_job(event)
    if done:
        return
    for track_id in plan['tracks']:
        if track_id in plan.get('completed',[]) or track_id in plan.get('failed',[]):
            continue
        try:
            if acquire(track_id):
                with db.transaction() as c:
                    requested = c.execute("SELECT 1 FROM requests WHERE track_id=? AND status IN ('pending','playing')",(track_id,)).fetchone()
                    if plan['kind'] not in {'request','listen'} and not requested:
                        c.execute('INSERT OR IGNORE INTO playlist(track_id,priority) VALUES(?,?)',
                                  (track_id,1 if plan['kind'] in {'boost','recovery'} else 0))
                    plan.setdefault('completed',[]).append(track_id)
                    c.execute('UPDATE jobs SET body=? WHERE id=?',(json.dumps(plan),event['id']))
            elif plan['kind'] == 'request':
                with db.transaction() as c:
                    c.execute("UPDATE requests SET status='failed',response=response || ' Download unavailable: the library limit has been reached.' WHERE id=? AND status='pending'",(event['request_id'],))
        except TrackReserved:
            raise  # Another consumer is acquiring this recording; retry without quarantining it.
        except Exception as error:
            log.error('Download failed for %s (source URL omitted)',track_id)
            from app.download_failures import record,alternative
            with db.transaction() as c:
                failure_id,meta=record(c,event,track_id,error)
                plan.setdefault('failed',[]).append(track_id)
                replacement=alternative(c,event,plan,meta)
                if replacement:
                    plan['tracks'].append(replacement)
                    c.execute('UPDATE failed_downloads SET replacement_id=? WHERE id=?',(replacement,failure_id))
                if plan['kind']=='request':
                    if replacement:
                        c.execute("UPDATE requests SET track_id=?,response=response || ' Selecting another track in the requested genre after a download failure.' WHERE id=? AND status='pending'",(replacement,event.get('request_id')))
                    else:
                        c.execute("UPDATE requests SET status='failed',response=response || ' Download failed; please choose another track.' WHERE id=? AND status='pending'",(event.get('request_id'),))
                c.execute('UPDATE jobs SET body=? WHERE id=?',(json.dumps(plan),event['id']))
    if plan['kind']=='listen':
        from app import telemetry
        telemetry.emit('preparation.completed' if plan.get('completed') else 'preparation.failed',job_id=event['id'],track_id=event['track_id'],outcome='success' if plan.get('completed') else 'failure')
    if plan['kind'] in {'boost','request'}:
        from app.events import fulfill_genre
        for track_id in plan.get('completed',[]):
            with db.connect() as c:
                meta=json.loads(c.execute('SELECT metadata FROM tracks WHERE id=?',(track_id,)).fetchone()[0])
            fulfill_genre(event['id'],track_id,event.get('genre',meta['genre']))
    with db.transaction() as c:
        c.execute('UPDATE jobs SET done=1 WHERE id=?',(event['id'],))
        if plan.get('failed') and not plan.get('completed'):
            c.execute("UPDATE outbox SET failed='Download failed; no eligible replacement completed' WHERE id=?",(event['id'],))


def plan_refill(event):
    # Never hold SQLite's writer lock while searching artist/genre combinations.
    with db.transaction() as c:
        existing=c.execute('SELECT body,done FROM jobs WHERE id=?',(event['id'],)).fetchone()
        if existing:return json.loads(existing['body']),bool(existing['done'])
        capped=library_only(c)
        rows=c.execute("SELECT * FROM tracks WHERE status IN ('available','ready') AND id NOT IN (SELECT track_id FROM playlist)").fetchall()
        active={r[0] for r in c.execute('SELECT track_id FROM plays WHERE actual_end IS NULL AND ends>?',(time.time(),))}
        history=c.execute("SELECT track_id,json_extract(metadata,'$.genre') AS genre,COUNT(*) AS n,MAX(starts) AS last FROM plays WHERE starts<=? AND (actual_end IS NULL OR actual_end>starts) GROUP BY track_id,json_extract(metadata,'$.genre')",(time.time(),)).fetchall()
        counts={};last_played={};genre_last={}
        for play in history:
            counts[play['track_id']]=counts.get(play['track_id'],0)+play['n']
            last_played[play['track_id']]=max(last_played.get(play['track_id'],0),play['last'])
            genre_last[play['genre']]=max(genre_last.get(play['genre'],0),play['last'])
    fresh=[];candidates=[]
    for row in rows:
        meta=json.loads(row['metadata'])
        if meta['id'] in active or bool(meta.get('demo'))!=DEMO:continue
        if row['status']!='ready' and (capped or not row['source'] or not row['rights']):continue
        candidates.append(meta)
        if row['status']!='ready':fresh.append(meta)
    selected=balanced_sample(candidates,{t['id'] for t in fresh},counts,last_played,genre_last)
    plan={'tracks':[t['id'] for t in selected],'kind':'refill','completed':[]}
    with db.transaction() as c:
        existing=c.execute('SELECT body,done FROM jobs WHERE id=?',(event['id'],)).fetchone()
        if existing:return json.loads(existing['body']),bool(existing['done'])
        c.execute('INSERT INTO jobs(id,body) VALUES(?,?)',(event['id'],json.dumps(plan)))
        if not selected:db.set_setting(c,'download_status','Waiting for a diverse authorized catalog')
    return plan,False

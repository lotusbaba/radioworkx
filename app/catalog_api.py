"""Public, credential-free catalog views and exact-ID listener requests."""
import json
import time
from app import db
from app.config import DEMO, MAX_TRACKS
from app.downloads import library_only
from fastapi import HTTPException


def selectable(c):
    capped=db.setting(c,'download_cap_reached','0')=='1' or c.execute('SELECT COUNT(*) FROM tracks WHERE downloaded_at IS NOT NULL').fetchone()[0]>=MAX_TRACKS
    rows=[]
    for row in c.execute('SELECT * FROM tracks ORDER BY id'):
        meta=json.loads(row['metadata'])
        if bool(meta.get('demo'))!=DEMO or row['status']=='failed':continue
        if row['status']!='ready' and (capped or not row['source'] or not row['rights']):continue
        rows.append((row,meta))
    return rows


def public_track(row,meta):
    return {k:meta.get(k) for k in ('title','artists','album','genre','bandcamp_url','license_url','license_name')} | {
        'id':row['id'],'downloaded':row['status']=='ready','duration':row['duration']}


def catalog(genres,query,page,page_size):
    with db.connect() as c:
        rows=selectable(c)
    genres={g.casefold() for g in genres}
    query=query.casefold().strip()
    rows=[(r,m) for r,m in rows if (not genres or m['genre'].casefold() in genres) and
          (not query or query in ' '.join([m['title'],m.get('album',''),*m['artists']]).casefold())]
    rows.sort(key=lambda pair:(pair[1]['title'].casefold(),pair[0]['id']))
    total=len(rows);pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
    return dict(items=[public_track(r,m) for r,m in rows[(page-1)*page_size:page*page_size]],total=total,page=page,pages=pages,page_size=page_size)


def genre_counts():
    with db.connect() as c: rows=selectable(c)
    counts={}
    for row,meta in rows:
        entry=counts.setdefault(meta['genre'],{'genre':meta['genre'],'tracks':0,'downloaded':0})
        entry['tracks']+=1;entry['downloaded']+=row['status']=='ready'
    return {'items':sorted(counts.values(),key=lambda g:g['genre'])}


def enqueue(track_id,listener,request_id):
    from app.requests import public
    with db.transaction() as c:
        old=c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
        query='Catalog track: '+track_id
        if old:
            if (old['listener'],old['track_id'],old['query'])!=(listener,track_id,query):
                raise HTTPException(409,'Request ID already used for a different request.')
            return public(old)
        row=c.execute('SELECT * FROM tracks WHERE id=?',(track_id,)).fetchone()
        if row is None:raise HTTPException(404,'Track not found.')
        meta=json.loads(row['metadata'])
        if bool(meta.get('demo'))!=DEMO:raise HTTPException(404,'Track not found.')
        if row['status']=='failed' or (row['status']!='ready' and (library_only(c) or not row['source'] or not row['rights'])):
            raise HTTPException(409,'This track is not currently available to queue.')
        now=time.time()
        if c.execute('SELECT COUNT(*) FROM requests WHERE listener=? AND created>?',(listener,now-60)).fetchone()[0]>=10:
            raise HTTPException(429,'Too many requests. Try again in a minute.',headers={'Retry-After':'60'})
        c.execute("INSERT INTO requests(id,listener,query,mode,response,track_id,status,created) VALUES(?,?,?,'track',?,?,'pending',?)",
                  (request_id,listener,query,f'Queued “{meta["title"]}”. Requests play before automatic selections when eligible.',track_id,now))
        c.execute('DELETE FROM playlist WHERE track_id=?',(track_id,))
        db.emit(c,'request:'+request_id,'request-downloads',{'kind':'request','track_id':track_id,'request_id':request_id})
        return public(c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone())

"""Bounded SQS crawler: public provider pages, robots rules, durable frontier."""
import html
import ipaddress
import json
import os
import re
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse, urljoin, urlencode, quote
from urllib.robotparser import RobotFileParser
import httpx
from app import db, hosts

AGENT='RadioWorkxCrawler/1.0'


def fetch(url, max_bytes=2_000_000):
    host=hosts.valid_url(url)
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Provider resolved to a non-public address')
    with httpx.stream('GET',url,headers={'User-Agent':AGENT},timeout=15,follow_redirects=False) as response:
        response.raise_for_status()
        if response.is_redirect:raise ValueError('Crawler redirects are not followed')
        data=bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data)>max_bytes:raise ValueError('Crawler response too large')
        if not data:raise ValueError('Empty provider response')
    return data.decode('utf-8',errors='replace')


def permitted(url):
    host=hosts.valid_url(url)
    key='robots:'+host
    with db.connect() as c: old=json.loads(db.setting(c,key,'null'))
    if not old or old['at']<time.time()-86400:
        try: text=fetch('https://'+host+'/robots.txt',500_000)
        except httpx.HTTPStatusError as error:
            if error.response.status_code!=404: return False
            text='User-agent: *\nAllow: /'
        except Exception:return False
        old={'at':time.time(),'text':text}
        with db.transaction() as c:db.set_setting(c,key,json.dumps(old))
    parser=RobotFileParser()
    parser.parse(old['text'].splitlines())
    delay=max(2,parser.crawl_delay(AGENT) or parser.crawl_delay('*') or 0)
    with db.transaction() as c:
        last=float(db.setting(c,'crawl-host-next:'+host,'0'))
        if last>time.time():return False
        db.set_setting(c,'crawl-host-next:'+host,time.time()+delay)
    return parser.can_fetch(AGENT,url)


def enqueue(c,genre=None,force=False):
    from app.downloads import library_only
    if os.getenv('CRAWLER_ENABLED','1')!='1' or library_only(c):return None
    key='crawler-last:'+str(genre or 'all')
    if not force and time.time()-float(db.setting(c,key,'0'))<900:return None
    if c.execute("SELECT 1 FROM outbox WHERE queue='crawler' AND done IS NULL").fetchone():return None
    id='crawl:'+str(uuid.uuid4())
    db.emit(c,id,'crawler',{'kind':'crawl','genre':genre})
    db.set_setting(c,key,time.time())
    return id


def add_url(c,url,genre=None,depth=0,origin=None):
    try:
        host=hosts.valid_url(url,'bandcamp')
        p=urlparse(url)
        if not host.endswith('.bandcamp.com') or not re.fullmatch(r'/(album|track)/[a-zA-Z0-9_-]+',p.path):return
        url='https://'+host+p.path
    except ValueError:return
    hosts.register(c,host,origin=origin or url)
    if c.execute('SELECT COUNT(*) FROM crawl_frontier').fetchone()[0]>=5000:return
    c.execute('INSERT OR IGNORE INTO crawl_frontier(url,provider,genre,depth,discovered_from) VALUES(?,?,?,?,?)',
              (url,'bandcamp',genre,depth,origin))


def bandcamp_tracks(document,url,preferred=None):
    from app.bandcamp import parse_page
    from app.requests import KNOWN_GENRES, normalize
    data,license=parse_page(document)
    current=data['current']
    # Tags come from this release, never from the referring artist's genre.
    tags=[normalize(re.sub('<[^>]+>','',s)) for s in re.findall(r'<a[^>]*class="[^"]*\btag\b[^"]*"[^>]*>(.*?)</a>',document,re.S)]
    genres=[g for g in sorted(KNOWN_GENRES) if normalize(g) in tags]
    genre=preferred if preferred and (preferred in genres or not genres) else (genres[0] if genres else None)
    if not genre:return []
    album_id='bc-album-'+str(current.get('album_id') or current['id'])
    album=current.get('album_title') or current['title']
    # Track pages can contain album_title outside current; use the album page for stable identities.
    if '/track/' in url and current.get('album_id'):return []
    result=[]
    for t in data['trackinfo'][:100]:
        if t.get('private') or t.get('unreleased_track') or not (t.get('file') or {}).get('mp3-128'):continue
        artist=t.get('artist') or data.get('artist','')
        if not artist or re.search(r'\b(feat\.?|featuring|ft\.?|various artists)\b',artist+' '+t['title'],re.I):continue
        page=urljoin(url,t['title_link'])
        if urlparse(page).hostname!=urlparse(url).hostname:continue
        hosts.valid_url(t['file']['mp3-128'],'bandcamp')
        name='CC '+license.split('/licenses/')[1].strip('/').replace('/',' ').upper()
        result.append(dict(id='bc-'+str(t['track_id']),title=t['title'],artists=[artist],album=album,album_id=album_id,
            compilation_id='bc-compilation-'+str(current.get('album_id') or current['id']) if 'compilation' in album.lower() else None,
            genre=genre,bandcamp_url=page,bandcamp_track_id=t['track_id'],source_kind='bandcamp_cc',
            source_url=page,rights=name+' on '+page,license_url=license,license_name=name,
            audio_changes='MP3 format conversion only',attribution=f'{t["title"]} by {artist} — {album}. {name}. Source: {page}. MP3 format conversion only.'))
    return result


def import_items(items):
    from app.catalog import import_catalog
    if not items:return 0
    # Dedicated temporary file prevents collisions with discovery consumers.
    path=db.DATA/('crawl-import-'+uuid.uuid4().hex+'.json')
    try:
        with db.connect() as c: before=c.execute('SELECT COUNT(*) FROM tracks').fetchone()[0]
        path.write_text(json.dumps(items))
        import_catalog(path,overwrite=False)
        with db.connect() as c:return max(0,c.execute('SELECT COUNT(*) FROM tracks').fetchone()[0]-before)
    finally:path.unlink(missing_ok=True)


class ArchiveDeferred(ValueError):
    def __init__(self, imported):
        super().__init__('Archive metadata deferred; retain cursor for retry')
        self.imported=imported


def archive_discover(genre=None):
    from app.archive_source import tracks
    from app.bandcamp import LICENSES
    licenses=sorted(LICENSES | {u.replace('https://','http://') for u in LICENSES})
    q='mediatype:audio AND collection:netlabels AND ('+' OR '.join('licenseurl:"'+u+'"' for u in licenses)+')'
    if genre:q+=' AND subject:"'+re.sub(r'[^a-zA-Z0-9 -]','',genre)+'"'
    with db.transaction() as c:
        page=int(db.setting(c,'archive-page-v2:'+str(genre),1))
    url='https://archive.org/advancedsearch.php?'+urlencode({'q':q,'output':'json','rows':10,'page':page,'fl[]':'identifier','sort[]':'downloads desc'})
    if not permitted(url):return 0
    response=json.loads(fetch(url))
    if 'response' not in response:raise ValueError('Archive search returned an error')
    docs=response['response'].get('docs',[])
    added=0
    for item in docs:
        id=item['identifier']
        if not re.fullmatch('[a-zA-Z0-9_.-]+',id):continue
        url='https://archive.org/metadata/'+quote(id,safe='')
        time.sleep(2)
        try:
            if not permitted(url):raise ValueError('Archive item deferred; retry this search page')
            data=json.loads(fetch(url))
            added+=import_items(tracks(data,id,genre))
        except Exception as error:raise ArchiveDeferred(added) from error
    with db.transaction() as c:db.set_setting(c,'archive-page-v2:'+str(genre),page+1 if docs else 1)
    return added


def process(event):
    from app.downloads import library_only
    with db.transaction() as c:
        row=c.execute('SELECT finished FROM crawl_runs WHERE id=?',(event['id'],)).fetchone()
        if row and row['finished']:return
        if library_only(c):return
        hosts.bootstrap(c)
        c.execute('INSERT OR IGNORE INTO crawl_runs(id,started) VALUES(?,?)',(event['id'],time.time()))
        for feed in json.loads(Path('catalog/discovery-feeds.json').read_text()):
            add_url(c,feed['url'],feed['genre'],origin='seed feed')
        for row in c.execute('SELECT metadata FROM tracks WHERE source IS NOT NULL LIMIT 30').fetchall():
            m=json.loads(row['metadata']);add_url(c,m['bandcamp_url'],m['genre'],origin='existing catalog')
    pages=added=errors=0
    try:added+=archive_discover(event.get('genre'))
    except Exception as error:
        added+=getattr(error,'imported',0)
        errors+=1
    budget=max(1,min(50,int(os.getenv('CRAWLER_PAGE_BUDGET','20'))))
    for _ in range(budget):
        with db.transaction() as c:
            if library_only(c):break
            row=c.execute('SELECT * FROM crawl_frontier WHERE next_attempt<=? ORDER BY CASE WHEN genre=? THEN 0 ELSE 1 END,next_attempt,depth DESC LIMIT 1',
                          (time.time(),event.get('genre'))).fetchone()
            if not row:break
            c.execute("UPDATE crawl_frontier SET next_attempt=?,status='fetching' WHERE url=?",(time.time()+86400,row['url']))
        try:
            if not permitted(row['url']):raise ValueError('Robots restriction or host cooldown')
            document=fetch(row['url']);pages+=1
            links=re.findall(r'https://[a-zA-Z0-9-]+\.bandcamp\.com/(?:album|track)/[a-zA-Z0-9_-]+',html.unescape(document))
            # Relative album links let track pages lead to album metadata.
            links += [urljoin(row['url'],u) for u in re.findall(r'href="(/album/[a-zA-Z0-9_-]+)"',document)]
            with db.transaction() as c:
                if row['depth']<2:
                    for link in list(dict.fromkeys(links))[:30]:add_url(c,link,None,row['depth']+1,row['url'])
            try:items=bandcamp_tracks(document,row['url'],row['genre'])
            except (ValueError,KeyError):items=[]
            added+=import_items(items)
            with db.transaction() as c:c.execute("UPDATE crawl_frontier SET status=?,error=NULL WHERE url=?",('licensed' if items else 'no_eligible_tracks',row['url']))
        except Exception as error:
            errors+=1
            with db.transaction() as c:c.execute("UPDATE crawl_frontier SET status='deferred',error=? WHERE url=?",(type(error).__name__,row['url']))
        time.sleep(2)
    with db.transaction() as c:
        c.execute('UPDATE crawl_runs SET finished=?,pages=pages+?,tracks=tracks+?,errors=errors+? WHERE id=?',(time.time(),pages,added,errors,event['id']))
        from app.requests import refresh_genre_head
        refresh_genre_head(c,time.time())
        if added and not library_only(c):
            from app.station import needs_recovery
            if needs_recovery(c,time.time()) and not c.execute("SELECT 1 FROM outbox WHERE done IS NULL AND json_extract(body,'$.kind')='recovery'").fetchone():
                db.emit(c,'recovery:'+str(uuid.uuid4()),'priority-downloads',{'kind':'recovery'})
                db.set_setting(c,'last_recovery',time.time())
        db.set_setting(c,'crawler_status',f'Checked {pages} Bandcamp pages; added {added} tracks; {errors} deferred sources')

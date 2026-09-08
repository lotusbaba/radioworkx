"""On-demand metadata discovery from operator-reviewed Bandcamp releases."""
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin,urlparse
import httpx
from app import db
from app.bandcamp import parse_page

FEEDS=Path('catalog/discovery-feeds.json')


def discover(genre=None):
    from app.downloads import library_only
    from app.catalog import import_catalog
    with db.transaction() as c:
        if library_only(c):return 0
    added=0
    for feed in json.loads(FEEDS.read_text()):
        if genre is not None and feed['genre'] != genre: continue
        key='discovery:'+feed['url']
        with db.transaction() as c:
            if time.time()-float(db.setting(c,key,'0'))<300:continue
            db.set_setting(c,key,time.time())
        try:
            response=httpx.get(feed['url'],timeout=20,follow_redirects=False)
            response.raise_for_status()
            data,license_url=parse_page(response.text)
            current=data['current']
            album_id='bc-album-'+str(current.get('album_id') or current['id'])
            tracks=[]
            for t in data['trackinfo'][:100]:
                if t.get('private') or t.get('unreleased_track') or not (t.get('file') or {}).get('mp3-128'):continue
                if re.search(r'\b(feat\.?|featuring|ft\.)\s',t['title'],re.I):continue
                page=urljoin(feed['url'],t['title_link'])
                if urlparse(page).hostname!=urlparse(feed['url']).hostname:continue
                artist=t.get('artist') or data['artist']
                name='CC '+license_url.split('/licenses/')[1].strip('/').replace('/',' ').upper()
                tracks.append(dict(id='bc-'+str(t['track_id']),title=t['title'],artists=list(dict.fromkeys([artist,*feed.get('additional_artists',[])])),
                    album=current['title'],album_id=album_id,genre=feed['genre'],bandcamp_url=page,compilation_id=None,
                    bandcamp_track_id=t['track_id'],source_kind='bandcamp_cc',source_url=page,license_url=license_url,
                    license_name=name,audio_changes='MP3 format conversion only',rights=f'{name} on {page}; reverified at acquisition.',
                    attribution=f'{t["title"]} by {artist} — {current["title"]}. {name}. Source: {page}. MP3 format conversion only.'))
            target=db.DATA/'discovered-catalog.json'
            target.write_text(json.dumps(tracks))
            added+=import_catalog(target,overwrite=False)
        except Exception as error:
            with db.transaction() as c:db.set_setting(c,'discovery_status',f'Catalog source unavailable: {urlparse(feed["url"]).hostname} ({type(error).__name__})')
    with db.transaction() as c:
        from app.crawler import enqueue
        enqueue(c,genre)
    return added

"""Build an operator catalog from the explicitly reviewed, cached artist pages.
Refresh media URLs and verify the per-track license again at download time.
"""
import html
import json
import random
import re
import httpx
import sys
from pathlib import Path
from urllib.parse import urljoin,urlparse
from app.bandcamp import parse_page

pages=[
 ('hexxel','chiptune','https://hexxel.bandcamp.com/album/chromium'),
 ('stevia','vaporwave','https://steviasphere.bandcamp.com/album/collection'),
 ('justin','jazz','https://justinallanarnold.bandcamp.com/album/jazz-royalty-free-compilation'),
 ('alexander','metal','https://alexandernakarada.bandcamp.com/track/construction-3'),
 ('chris','ambient','https://chriszabriskie.bandcamp.com/track/cylinder-one'),
 ('leonard','orchestral','https://leonardrichter.bandcamp.com/track/the-hunt-begins'),
 ('storm','edm','https://thelionrecords.bandcamp.com/album/your-majesty-creative-commons-free-ep'),
 ('dan','folk','https://danwhalen.bandcamp.com/album/one-man-band'),
 ('broke','funk','https://brokeforfree.bandcamp.com/album/slam-funk'),
 ('tryad','trip-hop','https://tryad.bandcamp.com/album/listen'),
]
tracks=[]
hosts=set()
for key,genre,url in pages:
    cache=Path('/tmp/radio-cc-'+key+'.html')
    if '--refresh' in sys.argv or not cache.exists():
        response=httpx.get(url,timeout=30,follow_redirects=False)
        response.raise_for_status()
        cache.write_text(response.text)
    doc=cache.read_text()
    data,license_url=parse_page(doc)
    current=data['current']
    album_id=current.get('album_id') or current['id']
    album=current['title']
    parent=re.search(r'from\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',doc)
    if current['type']=='track' and parent:
        album=html.unescape(parent[2])
    candidates=[t for t in data['trackinfo'] if t.get('file') and not t.get('private') and not t.get('unreleased_track')
                and not re.search(r'\b(feat\.?|featuring|ft\.)\b',t['title'],re.I)]
    # Keep a useful follow-up pool; selection order is randomized again by the station.
    selected=random.SystemRandom().sample(candidates,min(4,len(candidates)))
    for t in selected:
        page=urljoin(url,t['title_link'])
        artist=t.get('artist') or data['artist']
        name='CC '+license_url.split('/licenses/')[1].strip('/').replace('/',' ').upper()
        meta=dict(id='bc-'+str(t['track_id']),title=t['title'],artists=[artist],album=album,
                  album_id='bc-album-'+str(album_id),genre=genre,bandcamp_url=page,
                  compilation_id='bc-compilation-'+str(album_id) if key=='justin' else None,
                  bandcamp_track_id=t['track_id'],source_kind='bandcamp_cc',source_url=page,
                  license_url=license_url,license_name=name,audio_changes='MP3 format conversion only',
                  rights=f'{name}, published by {artist} on {page}; license verified again at acquisition.',
                  attribution=f'{t["title"]} by {artist} — {album}. {name}. Source: {page}. MP3 format conversion only.')
        tracks.append(meta)
        hosts.add(urlparse(page).hostname)
        hosts.add(urlparse(t['file']['mp3-128']).hostname)
Path('catalog/open-license.json').write_text(json.dumps(tracks,indent=2,ensure_ascii=False)+'\n')
Path('/tmp/radio-cc-hosts.txt').write_text(','.join(sorted(hosts)))
print(json.dumps({'tracks':len(tracks),'genres':len({t['genre'] for t in tracks}),'artists':len({t['artists'][0] for t in tracks}),'licenses':sorted({t['license_name'] for t in tracks}),'hosts':sorted(hosts)}))

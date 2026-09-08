"""Internet Archive netlabel adapter. Metadata does not imply universal reuse permission."""
import hashlib
import re
from urllib.parse import quote
from app.bandcamp import LICENSES


def license_url(value):
    values=value if isinstance(value,list) else [value]
    if len(values)!=1:return None
    url=str(values[0] or '').replace('http://','https://').rstrip('/')+'/'
    return url if url in LICENSES else None


def tracks(data, identifier, preferred=None):
    meta=data.get('metadata',{})
    license=license_url(meta.get('licenseurl'))
    if not license or meta.get('mediatype')!='audio' or meta.get('access-restricted-item') in ('true',True):return []
    creator=meta.get('creator')
    if not isinstance(creator,str) or not creator.strip() or re.search(r'various|compilation',creator,re.I):return []
    subjects=meta.get('subject',[])
    subjects=subjects if isinstance(subjects,list) else re.split('[;,]',subjects)
    from app.requests import KNOWN_GENRES, normalize
    genres=[g for g in sorted(KNOWN_GENRES) if any(normalize(g)==normalize(s) for s in subjects)]
    if not genres:return []
    genre=preferred if preferred in genres else genres[0]
    album=meta.get('title')
    if not isinstance(album,str) or not album:return []
    items=[]
    for f in data.get('files',[]):
        name=f.get('name','')
        if f.get('source')!='original' or not name.lower().endswith('.mp3') or f.get('private') in ('true',True):continue
        if not f.get('title') or '/' in name or '\\' in name:continue
        artist=f.get('creator') or creator
        if not isinstance(artist,str) or re.search(r'\b(feat|ft|featuring|various)\b',artist+' '+f['title'],re.I):continue
        page='https://archive.org/details/'+quote(identifier,safe='')
        id='ia-'+hashlib.sha256((identifier+'/'+name).encode()).hexdigest()[:32]
        items.append(dict(id=id,title=f['title'],artists=[artist],album=album,album_id='ia-'+identifier,
            compilation_id='ia-compilation-'+identifier if 'compilation' in album.lower() else None,
            genre=genre,bandcamp_url=page,provider='archive',archive_identifier=identifier,archive_file=name,
            source_kind='archive_cc',source_url='https://archive.org/download/'+quote(identifier,safe='')+'/'+quote(name,safe=''),
            license_url=license,license_name='CC '+license.split('/licenses/')[1].strip('/').replace('/',' ').upper(),
            audio_changes='MP3 format conversion only',rights=license+' on '+page,
            attribution=f'{f["title"]} by {artist}. Source: {page}. License: {license}. MP3 format conversion only.'))
    return items[:100]

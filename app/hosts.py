"""Discovered host repository and idempotent successful-download accounting."""
import json
import re
import time
from urllib.parse import urlparse
from app import db


def provider(host):
    if re.fullmatch(r'[a-z0-9-]+\.bandcamp\.com',host) or host=='bandcamp.com': return 'bandcamp'
    if re.fullmatch(r't\d+\.bcbits\.com',host): return 'bandcamp'
    if host=='archive.org' or re.fullmatch(r'ia\d+\.(?:us\.)?archive.org',host): return 'archive'
    return 'manual'


def valid_url(url, expected=None):
    p=urlparse(url)
    host=p.hostname or ''
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443):
        raise ValueError('Expected public HTTPS provider URL without credentials')
    kind=provider(host)
    if kind=='manual' or expected and kind!=expected: raise ValueError('Unsupported provider host')
    return host


def register(c,host,kind=None,role='source',status='discovered',origin=None,notes=''):
    now=time.time()
    c.execute('INSERT INTO source_hosts(hostname,provider,role,status,discovered_from,notes,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?) '
              'ON CONFLICT(hostname) DO UPDATE SET last_seen=excluded.last_seen',
              (host,kind or provider(host),role,status,origin,notes,now,now))


def completed(c,track_id,source_host,media_host,at):
    if not source_host:return
    register(c,source_host,status='active')
    if media_host:register(c,media_host,role='media',status='active',origin=source_host)
    inserted=c.execute('INSERT OR IGNORE INTO host_downloads VALUES(?,?,?,?)',(track_id,source_host,media_host,at)).rowcount
    if inserted:
        for host in set(filter(None,(source_host,media_host))):
            c.execute("UPDATE source_hosts SET tracks_downloaded=tracks_downloaded+1,status='active' WHERE hostname=?",(host,))


def bootstrap(c):
    sites=[('bandcamp.com','bandcamp','active','Track-level CC BY/BY-SA checks; crawler follows public release and recommendation links.'),
           ('archive.org','archive','active','Netlabel metadata API; supported licenses and original MP3s only.'),
           ('ccmixter.org','ccmixter','adapter_pending','Free CC music; license varies per track. API adapter not enabled.'),
           ('www.jamendo.com','jamendo','credentials_required','API client ID and usage-terms review required; download permission varies per track.')]
    for host,kind,status,notes in sites:register(c,host,kind,'catalog',status,'research',notes)
    for row in c.execute('SELECT * FROM tracks'):
        meta=json.loads(row['metadata'])
        host=urlparse(meta.get('bandcamp_url','')).hostname
        if not host:continue
        register(c,host,origin=meta.get('bandcamp_url'))
        if row['downloaded_at'] is not None and not meta.get('demo'):
            # Historical media host was not recorded; do not invent its provenance.
            completed(c,row['id'],host,None,row['downloaded_at'])


def repository(c):
    return [dict(r) for r in c.execute('SELECT * FROM source_hosts ORDER BY tracks_downloaded DESC,hostname')]

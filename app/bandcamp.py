"""Public Bandcamp audio only when the recording explicitly grants CC BY/BY-SA reuse.
No login, purchase flow, private streams, paywall bypass, or general preview ripping.
"""
import html
import json
import re
from urllib.parse import urlparse
import httpx

LICENSES = {
    f'https://creativecommons.org/licenses/{kind}/{version}/'
    for kind in ('by','by-sa') for version in ('3.0','4.0')
}


def parse_page(document):
    match = re.search(r'data-tralbum="([^"]+)"',document)
    if not match:
        raise ValueError('Bandcamp public metadata is unavailable')
    data = json.loads(html.unescape(match[1]))
    section = re.search(r'<div id="license"[^>]*>(.*?)</div>',document,re.S)
    licenses = re.findall(r'https?://creativecommons.org/licenses/[^"<> ]+',section[1]) if section else []
    license_url = licenses[0].replace('http://','https://') if licenses else None
    if license_url not in LICENSES:
        raise ValueError('Recording must explicitly have a supported CC BY or CC BY-SA license')
    if data.get('is_private_stream') or data.get('is_preorder') or data.get('album_is_preorder'):
        raise ValueError('Only publicly released recordings may be acquired')
    return data,license_url


def resolve_audio(page_url, metadata, allowed_hosts, dynamic=False):
    from app.hosts import valid_url
    if dynamic:
        valid_url(page_url,'bandcamp')
        allowed_hosts=set(allowed_hosts)|{urlparse(page_url).hostname}
    parsed = urlparse(page_url)
    if parsed.scheme!='https' or parsed.hostname not in allowed_hosts or not parsed.hostname.endswith('.bandcamp.com'):
        raise ValueError('Bandcamp source hostname must be explicitly allowlisted')
    response=httpx.get(page_url,timeout=30,follow_redirects=False)
    response.raise_for_status()
    data,license_url=parse_page(response.text)
    if license_url != metadata['license_url']:
        raise ValueError('The recording license changed; review the catalog before acquisition')
    track=next((t for t in data['trackinfo'] if str(t['track_id'])==str(metadata['bandcamp_track_id'])),None)
    if not track or track.get('private') or track.get('unreleased_track') or not track.get('file'):
        raise ValueError('No publicly available licensed audio for this track')
    source=track['file'].get('mp3-128')
    if not source:
        raise ValueError('No supported public MP3 rendition')
    host=urlparse(source).hostname or ''
    if dynamic:
        valid_url(source,'bandcamp')
        allowed_hosts=set(allowed_hosts)|{host}
    if urlparse(source).scheme!='https' or not host.endswith('.bcbits.com') or host not in allowed_hosts:
        raise ValueError('Bandcamp media hostname must be explicitly allowlisted')
    return source

import html
import json
import httpx
import pytest
from app.bandcamp import parse_page, resolve_audio


def page(license='https://creativecommons.org/licenses/by/4.0/',private=False):
    data={'is_private_stream':private,'trackinfo':[{'track_id':123,'file':{'mp3-128':'https://t4.bcbits.com/stream/authorized.mp3'}}]}
    return '<script data-tralbum="'+html.escape(json.dumps(data),quote=True)+'"></script><div id="license"><a href="'+license+'">some rights reserved</a></div>'


def test_only_explicit_supported_open_licenses():
    assert parse_page(page())[1]=='https://creativecommons.org/licenses/by/4.0/'
    with pytest.raises(ValueError):parse_page('<div id="license">all rights reserved</div>')
    with pytest.raises(ValueError):parse_page(page('https://creativecommons.org/licenses/by-nc/4.0/'))
    with pytest.raises(ValueError):parse_page(page(private=True))


def test_license_reverified_and_hosts_enforced(monkeypatch):
    monkeypatch.setattr('app.bandcamp.httpx.get',lambda *a,**kw:httpx.Response(200,text=page(),request=httpx.Request('GET',a[0])))
    metadata={'bandcamp_track_id':123,'license_url':'https://creativecommons.org/licenses/by/4.0/'}
    allowed={'artist.bandcamp.com','t4.bcbits.com'}
    assert resolve_audio('https://artist.bandcamp.com/track/a',metadata,allowed).startswith('https://t4.bcbits.com/')
    with pytest.raises(ValueError):resolve_audio('https://artist.bandcamp.com/track/a',metadata,{'artist.bandcamp.com'})
    with pytest.raises(ValueError):resolve_audio('https://artist.bandcamp.com/track/a',{**metadata,'bandcamp_track_id':999},allowed)
    with pytest.raises(ValueError):resolve_audio('https://artist.bandcamp.com/track/a',{**metadata,'license_url':'https://creativecommons.org/licenses/by-sa/4.0/'},allowed)


def test_dynamic_provider_hosts_do_not_need_manual_allowlist(monkeypatch):
    monkeypatch.setattr('app.bandcamp.httpx.get',lambda *a,**kw:httpx.Response(200,text=page().replace('t4.bcbits.com','t9.bcbits.com'),request=httpx.Request('GET',a[0])))
    metadata={'bandcamp_track_id':123,'license_url':'https://creativecommons.org/licenses/by/4.0/'}
    assert resolve_audio('https://new-artist.bandcamp.com/track/a',metadata,set(),dynamic=True).startswith('https://t9.bcbits.com/')
    with pytest.raises(ValueError):resolve_audio('https://new-artist.bandcamp.com.evil.test/track/a',metadata,set(),dynamic=True)

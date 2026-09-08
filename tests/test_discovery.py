import html
import json
import httpx
from app import db,discovery


def test_discovery_imports_metadata_only_and_skips_unavailable_tracks(tmp_path,monkeypatch):
    feeds=tmp_path/'feeds.json'
    feeds.write_text(json.dumps([{'url':'https://new.bandcamp.com/album/release','genre':'jazz'}]))
    monkeypatch.setattr(discovery,'FEEDS',feeds)
    data={'artist':'New Artist','current':{'id':12,'title':'Release'},'trackinfo':[
        {'track_id':1,'title':'Available','title_link':'/track/available','file':{'mp3-128':'https://t4.bcbits.com/a.mp3'}},
        {'track_id':2,'title':'Unavailable','title_link':'/track/unavailable','file':None}]}
    page='<script data-tralbum="'+html.escape(json.dumps(data),quote=True)+'"></script><div id="license"><a href="https://creativecommons.org/licenses/by/4.0/">license</a></div>'
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        return httpx.Response(200,text=page,request=httpx.Request('GET',url))
    monkeypatch.setattr(discovery.httpx,'get',get)
    discovery.discover();discovery.discover()
    assert len(calls)==1
    with db.connect() as c:
        rows=c.execute('SELECT * FROM tracks').fetchall()
        assert len(rows)==1 and rows[0]['status']=='available'
        assert rows[0]['source']=='https://new.bandcamp.com/track/available'
        assert rows[0]['downloaded_at'] is None

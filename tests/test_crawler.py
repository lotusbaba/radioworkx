import json
import html
import time
import pytest
from app import db,hosts,crawler
from app.archive_source import tracks


def test_host_validation_and_distinct_completion_counts(metadata):
    for url in ['http://artist.bandcamp.com/a','https://bandcamp.com.evil.test/a','https://127.0.0.1/a','https://user@artist.bandcamp.com/a','https://artist.bandcamp.com:8000/a']:
        with pytest.raises(ValueError):hosts.valid_url(url)
    assert hosts.valid_url('https://new-artist.bandcamp.com/album/a')=='new-artist.bandcamp.com'
    assert hosts.valid_url('https://t9.bcbits.com/stream/a')=='t9.bcbits.com'
    with db.transaction() as c:
        hosts.completed(c,'a','new.bandcamp.com','t9.bcbits.com',100)
        hosts.completed(c,'a','new.bandcamp.com','t9.bcbits.com',101)
        counts={r['hostname']:r['tracks_downloaded'] for r in hosts.repository(c)}
        assert counts['new.bandcamp.com']==counts['t9.bcbits.com']==1


def test_historical_backfill_does_not_invent_cdn(metadata):
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata,status,downloaded_at) VALUES('a',?,'ready',100)",(json.dumps(metadata),))
        hosts.bootstrap(c);hosts.bootstrap(c)
        assert c.execute("SELECT tracks_downloaded FROM source_hosts WHERE hostname='example.bandcamp.com'").fetchone()[0]==1
        assert c.execute('SELECT media_host FROM host_downloads').fetchone()[0] is None


def test_job_deduplication_and_cap():
    with db.transaction() as c:
        assert crawler.enqueue(c)
        assert crawler.enqueue(c,force=True) is None
        c.execute('UPDATE outbox SET done=1')
        db.set_setting(c,'download_cap_reached','1')
        assert crawler.enqueue(c,force=True) is None


def test_frontier_only_admits_provider_release_pages():
    with db.transaction() as c:
        crawler.add_url(c,'https://new.bandcamp.com/album/a',origin='https://seed.bandcamp.com/album/x')
        crawler.add_url(c,'https://new.bandcamp.com/album/a')
        crawler.add_url(c,'https://evil.test/album/a')
        crawler.add_url(c,'https://new.bandcamp.com/checkout')
        assert c.execute('SELECT COUNT(*) FROM crawl_frontier').fetchone()[0]==1
        assert c.execute("SELECT COUNT(*) FROM source_hosts WHERE hostname='new.bandcamp.com'").fetchone()[0]==1


def test_bandcamp_license_genre_and_identity():
    data={'artist':'New Artist','current':{'id':123,'title':'New Album'},'trackinfo':[{'track_id':321,'title':'Song','title_link':'/track/song','file':{'mp3-128':'https://t9.bcbits.com/a.mp3'}}]}
    page='<script data-tralbum="'+html.escape(json.dumps(data),quote=True)+'"></script><a class="tag">jazz</a><div id="license"><a href="https://creativecommons.org/licenses/by/4.0/">CC</a></div>'
    items=crawler.bandcamp_tracks(page,'https://new.bandcamp.com/album/a')
    assert items[0]['genre']=='jazz' and items[0]['artists']==['New Artist']
    with pytest.raises(ValueError):crawler.bandcamp_tracks(page.replace('/by/','/by-nc/'),'https://new.bandcamp.com/album/a')


def test_archive_requires_supported_license_and_explicit_music_metadata():
    data={'metadata':{'mediatype':'audio','creator':'New Artist','title':'New Album','subject':['jazz'],'licenseurl':'https://creativecommons.org/licenses/by/4.0/'},
          'files':[{'name':'song.mp3','title':'Song','source':'original'},{'name':'derived.mp3','title':'Duplicate','source':'derivative'}]}
    result=tracks(data,'new-album','jazz')
    assert len(result)==1 and result[0]['source_kind']=='archive_cc'
    assert result[0]['source_url']=='https://archive.org/download/new-album/song.mp3'
    data['metadata']['licenseurl']='https://creativecommons.org/licenses/by-nc/4.0/'
    assert tracks(data,'new-album')==[]


def test_robot_disallow_is_respected(monkeypatch):
    monkeypatch.setattr(crawler,'fetch',lambda *args:'User-agent: *\nDisallow: /album/')
    assert not crawler.permitted('https://new.bandcamp.com/album/a')


def test_archive_query_matches_importer_licenses_and_keeps_failed_page(monkeypatch):
    from urllib.parse import urlparse,parse_qs
    urls=[]
    monkeypatch.setattr(crawler,'permitted',lambda url:True)
    monkeypatch.setattr(crawler.time,'sleep',lambda n:None)
    def fetch(url):
        urls.append(url)
        if 'advancedsearch' in url:return json.dumps({'response':{'docs':[{'identifier':'release'}]}})
        raise ValueError('Temporary metadata failure')
    monkeypatch.setattr(crawler,'fetch',fetch)
    with pytest.raises(ValueError):crawler.archive_discover()
    query=parse_qs(urlparse(urls[0]).query)['q'][0]
    assert 'http://creativecommons.org/licenses/by/3.0/' in query
    assert 'https://creativecommons.org/licenses/by-sa/4.0/' in query
    with db.connect() as c:assert db.setting(c,'archive-page-v2:None','1')=='1'
    monkeypatch.setattr(crawler,'fetch',lambda url:json.dumps({'response':{'docs':[{'identifier':'release'}]}}) if 'advancedsearch' in url else '{}')
    assert crawler.archive_discover()==0
    with db.connect() as c:assert db.setting(c,'archive-page-v2:None')=='2'


def test_archive_search_error_does_not_silently_reset_cursor(monkeypatch):
    monkeypatch.setattr(crawler,'permitted',lambda url:True)
    monkeypatch.setattr(crawler,'fetch',lambda url:json.dumps({'error':'Invalid query'}))
    with pytest.raises(ValueError,match='search returned an error'):crawler.archive_discover()


def test_new_crawl_imports_trigger_recovery_without_timer(monkeypatch):
    monkeypatch.setattr(crawler,'archive_discover',lambda genre:5)
    monkeypatch.setattr(crawler,'add_url',lambda *args,**kwargs:None)
    monkeypatch.setattr('app.station.needs_recovery',lambda c,now:True)
    crawler.process({'id':'crawl-new','genre':None})
    crawler.process({'id':'crawl-new','genre':None})
    with db.connect() as c:
        rows=c.execute("SELECT body FROM outbox WHERE json_extract(body,'$.kind')='recovery'").fetchall()
        assert len(rows)==1
        assert c.execute("SELECT tracks FROM crawl_runs WHERE id='crawl-new'").fetchone()[0]==5


def test_partial_archive_failure_preserves_import_count(monkeypatch):
    monkeypatch.setattr(crawler,'permitted',lambda url:True)
    monkeypatch.setattr(crawler.time,'sleep',lambda n:None)
    monkeypatch.setattr(crawler,'import_items',lambda items:5)
    def fetch(url):
        if 'advancedsearch' in url:return json.dumps({'response':{'docs':[{'identifier':'one'},{'identifier':'two'}]}})
        if url.endswith('/two'):raise ValueError('Temporary failure')
        return '{}'
    monkeypatch.setattr(crawler,'fetch',fetch)
    with pytest.raises(crawler.ArchiveDeferred) as error:crawler.archive_discover()
    assert error.value.imported==5
    with db.connect() as c:assert db.setting(c,'archive-page-v2:None','1')=='1'

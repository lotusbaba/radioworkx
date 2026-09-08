import json
import time
from types import SimpleNamespace
import pytest
from app import announcer, db, station
from app.service import now_playing


def test_supported_page_fact_is_added_without_generated_identity(metadata,monkeypatch):
    facts={'artist_about':'Artist A is based in Oaxaca and composes jazz music.'}
    def post(path,payload):
        assert payload['store'] is False
        assert 'untrusted' in payload['instructions']
        return {'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({
            'detail':'Based in Oaxaca, the artist composes jazz music.',
            'evidence':'based in Oaxaca and composes jazz music','source_field':'artist_about'})}]}]}
    monkeypatch.setattr('app.rag.post',post)
    text=announcer.script(metadata,facts)
    assert 'Track A by Artist A' in text
    assert 'Based in Oaxaca' in text
    assert announcer.script(metadata,{})=="You're listening to Radioworks. Up next, Track A by Artist A. From the album Album A."


def test_unsupported_evidence_is_not_announced(metadata,monkeypatch):
    monkeypatch.setattr('app.rag.post',lambda *args:{'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({
        'detail':'This artist won a Grammy.','evidence':'Grammy winner','source_field':'artist_about'})}]}]})
    assert 'Grammy' not in announcer.script(metadata,{'artist_about':'Independent musician.'})


def test_speech_request_cached_and_not_a_music_download(metadata,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-key')
    monkeypatch.setattr(announcer,'page_details',lambda m:{})
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append(kwargs['json'])
            return SimpleNamespace(content=b'mp3',raise_for_status=lambda:None)
    monkeypatch.setattr(announcer.httpx,'Client',Client)
    monkeypatch.setattr(announcer.subprocess,'run',lambda args,**kwargs:__import__('pathlib').Path(args[-1]).write_bytes(b'normalized mp3'))
    monkeypatch.setattr(announcer,'MP3',lambda path:SimpleNamespace(info=SimpleNamespace(length=12)))
    first=announcer.prepare(metadata)
    assert first['duration']==12 and first['voice']=='onyx'
    assert announcer.prepare(metadata)==first and len(calls)==1
    assert calls[0]['voice']=='onyx' and 'male radio announcer' in calls[0]['instructions']
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM tracks').fetchone()[0]==0


def test_music_clock_starts_after_intro(metadata,playing,monkeypatch):
    id=playing(now=1000)
    play={'id':id,'starts':1000,'ends':1300,'metadata':metadata}
    with db.transaction() as c:
        db.set_setting(c,'announcement_on_air',json.dumps({'play_id':id,'ends':1015}))
        assert now_playing(c,1010) is None
    monkeypatch.setattr(station.time,'time',lambda:1016)
    station.start_music(play)
    with db.connect() as c:
        live=now_playing(c,1016)
        assert live['starts']==1016 and live['ends']==1316
        assert db.setting(c,'announcement_on_air')=='null'


def test_changed_candidate_does_not_reserve_or_introduce_wrong_song(metadata):
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata,status,duration,path) VALUES('real',?,'ready',100,'test.mp3')",(json.dumps(metadata),))
    assert station.select_next(1000,expected_track_id='stale') is None
    with db.connect() as c:assert c.execute('SELECT COUNT(*) FROM plays').fetchone()[0]==0


def test_failed_speech_has_bounded_retry_and_music_can_continue(metadata,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-key')
    calls=[]
    def fail(*args,**kwargs): calls.append(1); raise RuntimeError('provider failed')
    monkeypatch.setattr(announcer,'page_details',fail)
    monkeypatch.setattr(announcer,'script',fail)
    assert announcer.prepare(metadata) is None
    assert announcer.prepare(metadata) is None
    assert len(calls)==3  # page fetch and both script attempts, then cooldown.


def test_unfinished_intro_never_blocks_music(metadata,monkeypatch):
    from concurrent.futures import Future
    monkeypatch.setattr(announcer,'enabled',lambda:True)
    monkeypatch.setattr(announcer,'cached',lambda *a,**k:None)
    def forbidden(*a,**k):raise AssertionError('Must not generate or wait in music loop')
    monkeypatch.setattr(announcer,'prepare',forbidden)
    future=Future()
    monkeypatch.setattr(future,'result',forbidden)
    candidate={'id':metadata['id'],'meta':metadata}
    assert station.ready_intro(candidate,((metadata['id'],None),future)) is None
    assert station.ready_intro(candidate,None) is None


def test_prepared_intro_matches_request_context(metadata,monkeypatch):
    from concurrent.futures import Future
    monkeypatch.setattr(announcer,'enabled',lambda:True)
    monkeypatch.setattr(announcer,'cached',lambda *a,**k:None)
    future=Future();future.set_result({'script':'Requested song'})
    warm=((metadata['id'],'request-1'),future)
    candidate={'id':metadata['id'],'meta':metadata,'request_id':'request-1'}
    assert station.ready_intro(candidate,warm)=={'script':'Requested song'}
    candidate.pop('request_id')
    assert station.ready_intro(candidate,warm) is None

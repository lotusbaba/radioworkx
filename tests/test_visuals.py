import json
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app import db, visuals, object_store
from app.api import app


def seed(metadata,status='queued'):
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata,status,duration) VALUES(?,?,'ready',180)",(metadata['id'],json.dumps(metadata)))
        c.execute('INSERT INTO track_visuals(track_id,status,created) VALUES(?,?,1)',(metadata['id'],status))


def test_schedule_once_and_disabled(metadata,monkeypatch):
    seed(metadata)
    with db.transaction() as c:
        c.execute('DELETE FROM track_visuals')
        monkeypatch.setenv('VIDEOS_ENABLED','0');visuals.schedule(c)
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==0
        monkeypatch.setenv('VIDEOS_ENABLED','1');visuals.schedule(c);visuals.schedule(c)
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==1


def test_generation_reuses_provider_and_cached_video(metadata,monkeypatch):
    seed(metadata);monkeypatch.setenv('OPENAI_API_KEY','test')
    calls=[];uploads=[]
    monkeypatch.setattr(visuals,'artwork',lambda m,p:p.write_bytes(b'image') or 'https://t4.bcbits.com/art.jpg')
    monkeypatch.setattr(object_store,'put',lambda tid,kind,path:uploads.append(kind) or object_store.key(tid,kind))
    monkeypatch.setattr(visuals.subprocess,'run',lambda args,**kwargs:Path(args[-1]).write_bytes(b'video'))
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def json(self):return {'id':'video_test','status':'completed'}
        def iter_bytes(self):yield b'generated-video'
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):calls.append(kwargs['data']);return Response()
        def get(self,*args,**kwargs):return Response()
        def stream(self,*args,**kwargs):return Response()
    monkeypatch.setattr(visuals.httpx,'Client',Client)
    event={'track_id':metadata['id']}
    visuals.process(event);visuals.process(event)
    assert len(calls)==1 and calls[0]['seconds']=='12' and uploads==['artwork','video']
    with db.transaction() as c:
        assert visuals.public(c,metadata['id'])['duration']==10
        c.execute("UPDATE track_visuals SET status='generating'")
    visuals.process(event)  # Restart after provider completion resumes its ID, never resubmits.
    assert len(calls)==1


def test_uncertain_submission_never_duplicates(metadata,monkeypatch):
    seed(metadata,'submitting');monkeypatch.setenv('OPENAI_API_KEY','test')
    visuals.process({'track_id':metadata['id']})
    with db.connect() as c:assert c.execute('SELECT status FROM track_visuals').fetchone()[0]=='submission_unknown'


def test_media_endpoint_range_and_missing(metadata,tmp_path):
    seed(metadata,'ready')
    path=tmp_path/'clip.mp4';path.write_bytes(b'0123456789')
    with db.transaction() as c:
        c.execute("UPDATE track_visuals SET video_key='video/test.mp4'")
        c.execute("INSERT INTO media_objects(object_key,track_id,kind,path,mime) VALUES('video/test.mp4',?,'video',?,'video/mp4')",(metadata['id'],str(path)))
    client=TestClient(app)
    response=client.get('/api/visuals/track-a/video',headers={'Range':'bytes=2-5'})
    assert response.status_code==206 and response.content==b'2345'
    assert client.get('/api/visuals/missing/video').status_code==404
    assert client.get('/api/visuals/track-a/audio').status_code==422


def test_object_sync_keeps_one_key_and_restores_missing_s3(metadata,tmp_path,monkeypatch):
    from botocore.exceptions import ClientError
    path=tmp_path/'audio.mp3';path.write_bytes(b'music')
    objects={};uploads=[]
    class S3:
        def head_bucket(self,**kwargs):pass
        def head_object(self,**kwargs):
            if kwargs['Key'] not in objects:raise ClientError({'Error':{'Code':'404'}},'HeadObject')
        def upload_file(self,path,bucket,key,**kwargs):objects[key]=Path(path).read_bytes();uploads.append(key)
    monkeypatch.setattr(object_store,'client',lambda:S3())
    key=object_store.put(metadata['id'],'audio',path)
    object_store.put(metadata['id'],'audio',path)
    assert len(uploads)==1
    objects.clear();object_store.upload(key)
    assert len(uploads)==2 and objects[key]==b'music'


def test_bandcamp_artwork_cdn_and_untrusted_destination(metadata,tmp_path,monkeypatch):
    fetched=[]
    def get(url,limit):
        fetched.append(url)
        return b'<meta property="og:image" content="https://f4.bcbits.com/img/a123.jpg">' if len(fetched)==1 else b'image'
    monkeypatch.setattr(visuals,'bounded_get',get)
    monkeypatch.setattr(visuals.subprocess,'run',lambda args,**kwargs:Path(args[-1]).write_bytes(b'jpg'))
    assert visuals.artwork(metadata,tmp_path/'art.jpg')=='https://f4.bcbits.com/img/a123.jpg'
    assert len(fetched)==2
    monkeypatch.setattr(visuals,'bounded_get',lambda *args:b'<meta property="og:image" content="https://internal.example/secret">')
    import pytest
    with pytest.raises(ValueError,match='Unsupported artwork host'):visuals.artwork(metadata,tmp_path/'other.jpg')


def test_disabled_flag_leaves_queue_unconsumed(monkeypatch):
    from app import workers
    monkeypatch.setenv('VIDEOS_ENABLED','0')
    monkeypatch.setattr(workers.queues,'queue',lambda name:(_ for _ in ()).throw(AssertionError('Must not consume paused queue')))
    assert workers.consume_once('visuals',wait=0)==0


def test_disabled_flag_prevents_new_submission(metadata,monkeypatch):
    import pytest
    seed(metadata)
    monkeypatch.setenv('VIDEOS_ENABLED','0')
    with pytest.raises(RuntimeError,match='paused'):visuals.process({'track_id':metadata['id']})

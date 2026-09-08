import json
import uuid
import httpx
from app import db, rag, requests


def setup(monkeypatch, metadata):
    monkeypatch.setenv('OPENAI_API_KEY','test-key')
    metadata['demo'] = rag.DEMO
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata,status) VALUES(?,?,'ready')",(metadata['id'],json.dumps(metadata)))
    monkeypatch.setattr(rag,'retrieve',lambda query,items:items)
    return metadata


def decision(action='request', intent='specific', track_id='track-a', genres=None):
    return dict(action=action,intent=intent,track_id=track_id,genres=genres or [],source_ids=['track-a'],reply='Let’s try jazz.')


def test_specific_fifo_and_idempotence(monkeypatch, metadata):
    setup(monkeypatch,metadata)
    calls=[]
    monkeypatch.setattr(rag,'decide',lambda *args: calls.append(args) or decision())
    id=str(uuid.uuid4())
    first=requests.submit('Play Track A','auto','listener',id)
    assert first['status']=='pending' and first['engine']=='rag'
    assert requests.submit('Play Track A','auto','listener',id)==first
    assert len(calls)==1
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]==1


def test_mood_requires_confirmation_and_is_private(monkeypatch, metadata):
    setup(monkeypatch,metadata)
    monkeypatch.setattr(rag,'decide',lambda *args:decision(intent='mood'))
    first=requests.submit('I need to unwind','auto','one',str(uuid.uuid4()))
    assert first['status']=='awaiting_confirmation'
    monkeypatch.setattr(rag,'decide',lambda *args:decision(intent='confirmation'))
    other=requests.submit('yes','auto','two',str(uuid.uuid4()))
    assert other['status']!='pending'
    confirmed=requests.submit('yes','auto','one',str(uuid.uuid4()))
    assert confirmed['status']=='pending'
    repeated=requests.submit('yes','auto','one',str(uuid.uuid4()))
    assert repeated['status']!='pending'


def test_fabricated_selection_cannot_queue(monkeypatch,metadata):
    setup(monkeypatch,metadata)
    monkeypatch.setattr(rag,'decide',lambda *args:decision(track_id='invented'))
    result=requests.submit('Play invented','auto','one',str(uuid.uuid4()))
    assert result['status']=='not_found'
    with db.connect() as c:
        assert not c.execute('SELECT * FROM outbox').fetchall()


def test_failure_falls_back_without_leaking_error(monkeypatch,metadata):
    setup(monkeypatch,metadata)
    def fail(*args): raise httpx.ConnectError('sensitive provider details')
    monkeypatch.setattr(rag,'decide',fail)
    result=requests.submit('Play Track A','auto','one',str(uuid.uuid4()))
    assert result['engine']=='basic' and result['status']=='pending'
    assert 'temporarily unavailable' in result['response']
    assert 'sensitive' not in result['response']


def test_embedding_cache_refresh(monkeypatch,metadata):
    calls=[]
    monkeypatch.setattr(rag,'embed',lambda texts: calls.append(texts) or [[1.0]+[0.0]*255 for _ in texts])
    rag.retrieve('jazz',[metadata])
    rag.retrieve('jazz',[metadata])
    assert [len(c) for c in calls]==[1,1,1]
    metadata['title']='New title'
    rag.retrieve('jazz',[metadata])
    assert len(calls)==5


def test_acknowledged_play_command_still_queues(monkeypatch,metadata):
    setup(monkeypatch,metadata)
    monkeypatch.setattr(rag,'decide',lambda *args:decision(action='answer',intent='question'))
    assert requests.submit('play Track A next','auto','one',str(uuid.uuid4()))['status']=='pending'


def test_offer_survives_question_and_yes_keeps_exact_track(monkeypatch,metadata):
    setup(monkeypatch,metadata)
    monkeypatch.setattr(rag,'decide',lambda *args:decision(action='answer'))
    offered=requests.submit('suggest something','auto','one',str(uuid.uuid4()))
    assert offered['status']=='awaiting_confirmation'
    monkeypatch.setattr(rag,'decide',lambda *args:decision(action='answer',intent='question'))
    requests.submit('what is playing now?','auto','one',str(uuid.uuid4()))
    result=requests.submit('yes play it','auto','one',str(uuid.uuid4()))
    assert result['status']=='pending' and result['track_id']==metadata['id']
    with db.connect() as c:
        assert c.execute("SELECT requested_genre FROM requests WHERE track_id IS NOT NULL").fetchone()[0]==''

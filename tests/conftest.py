import json
import uuid
import fakeredis
import pytest
from app import db, events

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path)
    db.init()
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(events,'r',fake)
    return fake

@pytest.fixture
def metadata():
    return dict(id='track-a',title='Track A',artists=['Artist A'],genre='jazz',album='Album A',
                album_id='album-a',compilation_id=None,bandcamp_url='https://example.bandcamp.com/track/a')

@pytest.fixture
def playing(metadata):
    def create(now=1000,duration=300):
        id=str(uuid.uuid4())
        with db.transaction() as c:
            c.execute('INSERT INTO plays(id,track_id,metadata,starts,ends) VALUES(?,?,?,?,?)',
                      (id,metadata['id'],json.dumps(metadata),now,now+duration))
        return id
    return create

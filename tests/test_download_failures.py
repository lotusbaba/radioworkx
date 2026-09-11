import json
from fastapi.testclient import TestClient
from app import db,downloads
from app.api import app


def seed(metadata):
    with db.transaction() as c:
        for tid in ['bad','good']:
            m={**metadata,'id':tid,'artists':[tid],'album_id':tid}
            c.execute("INSERT INTO tracks(id,metadata,status,source,rights) VALUES(?,?,'available','https://private.example/audio.mp3','licensed')",(tid,json.dumps(m)))
        event={'id':'boost:test','kind':'boost','genre':'jazz','artists':['original'],'album_id':'original'}
        db.emit(c,event['id'],'priority-downloads',event)
        c.execute('INSERT INTO jobs(id,body) VALUES(?,?)',(event['id'],json.dumps({'kind':'boost','tracks':['bad'],'completed':[]})))
    return event


def test_failed_boost_archived_replaced_and_idempotent(metadata,monkeypatch,isolated):
    event=seed(metadata);calls=[]
    def acquire(tid):
        calls.append(tid)
        if tid=='bad':raise ValueError('Archive metadata or license changed')
        return True
    monkeypatch.setattr(downloads,'acquire',acquire)
    isolated.zadd('radio:genres',{'jazz':28})
    downloads.process_job(event)
    assert calls==['bad','good'] and isolated.zscore('radio:genres','jazz') is None
    downloads.process_job(event)
    assert calls==['bad','good']
    with db.connect() as c:
        failure=dict(c.execute('SELECT * FROM failed_downloads').fetchone())
        assert failure['replacement_id']=='good' and failure['error_detail']=='Archive metadata or license changed'
        assert c.execute("SELECT status FROM tracks WHERE id='bad'").fetchone()[0]=='failed'
        assert c.execute("SELECT COUNT(*) FROM outbox WHERE queue='download-failures'").fetchone()[0]==1
        assert c.execute('SELECT track_id FROM playlist').fetchone()[0]=='good'
    monkeypatch.setenv('ADMIN_PASSWORD','test-password')
    client=TestClient(app)
    assert client.get('/api/admin/repository/failed-downloads').status_code==401
    response=client.get('/api/admin/repository/failed-downloads',auth=('admin','test-password'))
    assert response.json()['items'][0]['source_url']=='https://private.example/audio.mp3'
    assert 'private.example' not in client.get('/api/downloads').text


def test_all_replacements_fail_job_finishes_and_keeps_demand(metadata,monkeypatch,isolated):
    event=seed(metadata)
    monkeypatch.setattr(downloads,'acquire',lambda tid:(_ for _ in ()).throw(ValueError('bad audio')))
    isolated.zadd('radio:genres',{'jazz':28})
    downloads.process_job(event)
    with db.connect() as c:
        assert c.execute('SELECT done FROM jobs').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM failed_downloads').fetchone()[0]==2
        assert c.execute('SELECT failed FROM outbox WHERE id=?',(event['id'],)).fetchone()[0]
    assert isolated.zscore('radio:genres','jazz')==28


def test_replacements_bounded_and_wrong_genre_excluded(metadata,monkeypatch):
    event=seed(metadata)
    with db.transaction() as c:
        for n in range(8):
            tid=str(n);m={**metadata,'id':tid,'genre':'jazz' if n<7 else 'folk','artists':[tid],'album_id':tid}
            c.execute("INSERT INTO tracks(id,metadata,status,source,rights) VALUES(?,?,'available','https://example.org/a','licensed')",(tid,json.dumps(m)))
    calls=[]
    def fail(tid):calls.append(tid);raise ValueError('Invalid duration')
    monkeypatch.setattr(downloads,'acquire',fail)
    downloads.process_job(event)
    assert len(calls)==4 and len(set(calls))==4 and '7' not in calls


def test_completed_message_acknowledged_without_running_job(monkeypatch):
    from app import workers
    with db.transaction() as c:
        db.emit(c,'finished','priority-downloads',{'kind':'boost'})
        c.execute("UPDATE outbox SET done=1 WHERE id='finished'")
    ack=[]
    class SQS:
        def receive_message(self,**kwargs):return {'Messages':[{'Body':json.dumps({'id':'finished','kind':'boost'}),'ReceiptHandle':'receipt'}]}
        def delete_message(self,**kwargs):ack.append(kwargs['ReceiptHandle'])
    monkeypatch.setattr(workers.queues,'client',lambda:SQS())
    monkeypatch.setattr(workers.queues,'queue',lambda name:'queue-url')
    def forbidden(event):raise AssertionError('Completed job executed again')
    monkeypatch.setattr(downloads,'process_job',forbidden)
    assert workers.consume_once('priority-downloads',wait=0)==1 and ack==['receipt']

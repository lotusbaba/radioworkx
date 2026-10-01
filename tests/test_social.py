from fastapi.testclient import TestClient
from app.api import app
from app import db
from tests.test_accounts import register, seed, HEADERS


def test_sharing_privacy_following_and_revocation(metadata):
    seed(metadata)
    owner=register('owner@example.com'); follower=register('follower@example.com')
    guest=TestClient(app,headers=HEADERS)
    uid=owner.get('/api/account').json()['id']
    pid=owner.post('/api/me/playlists',json={'name':'Evening'}).json()['id']
    own='/api/me/playlists/'+pid
    public='/api/shared/playlists/'+pid
    follow='/api/me/following/playlists/'+pid
    owner.put(own+'/tracks/one')
    assert guest.get(public).status_code==404
    assert follower.put(follow).status_code==404
    assert guest.get('/api/people/'+uid).json()['playlists']==[]
    assert follower.put(own+'/sharing').status_code==404
    assert guest.put(own+'/sharing').status_code==401
    assert owner.put('/api/me/profile',json={'name':'Night listener'}).status_code==200
    assert owner.put(own+'/sharing').status_code==200
    data=guest.get(public)
    assert data.headers['cache-control']=='no-store'
    assert data.json()['owner']=={'id':uid,'name':'Night listener'}
    assert 'email' not in data.text and 'private.example' not in data.text
    assert guest.get('/api/people/'+uid).json()['playlists']==[{'id':pid,'name':'Evening'}]
    assert guest.put(follow).status_code==401
    assert owner.put(follow).status_code==400
    for _ in range(2):assert follower.put(follow).status_code==200
    assert len(follower.get('/api/me/social').json()['playlists'])==1
    assert follower.patch(own,json={'name':'stolen'}).status_code==404
    owner.put(own+'/tracks/two');owner.patch(own,json={'name':'Late evening'})
    followed=follower.get('/api/me/social').json()['playlists'][0]
    assert followed['name']=='Late evening'
    assert [t['id'] for t in followed['tracks']]==['one','two']
    owner.delete(own+'/tracks/one')
    assert [t['id'] for t in follower.get('/api/me/social').json()['playlists'][0]['tracks']]==['two']
    assert follower.delete(own+'/sharing').status_code==404
    assert owner.delete(own+'/sharing').status_code==200
    assert guest.get(public).status_code==404
    assert follower.get('/api/me/social').json()['playlists']==[]
    assert guest.get('/api/people/'+uid).json()['playlists']==[]
    owner.put(own+'/sharing')
    assert follower.get('/api/me/social').json()['playlists']==[]
    follower.put(follow);owner.delete(own)
    assert guest.get(public).status_code==404
    assert follower.get('/api/me/social').json()['playlists']==[]


def test_follow_people_profile_and_csrf():
    a=register();b=register('other@example.com');guest=TestClient(app)
    uid=a.get('/api/account').json()['id']
    path='/api/me/following/people/'+uid
    assert a.put(path).status_code==400
    assert b.put('/api/me/following/people/missing').status_code==404
    for _ in range(2):assert b.put(path).status_code==200
    social=b.get('/api/me/social').json()
    assert len(social['people'])==1
    assert social['people'][0]['name'].startswith('Listener ')
    assert a.put('/api/me/profile',json={'name':'  Radio friend  '}).status_code==200
    assert b.get('/api/me/social').json()['people'][0]['name']=='Radio friend'
    assert 'email' not in guest.get('/api/people/'+uid).text
    assert guest.get('/api/me/social').status_code==401
    for name in ['', ' '*3, 'x'*61]:assert a.put('/api/me/profile',json={'name':name}).status_code==400
    assert b.put(path,headers={'Origin':'https://evil.example'}).status_code==403
    assert b.delete(path).status_code==200
    assert b.get('/api/me/social').json()['people']==[]
    assert guest.get('/people/'+uid).status_code==200
    assert guest.get('/playlists/missing').status_code==200


def test_additive_migration_preserves_accounts():
    import hashlib
    from pathlib import Path
    from scripts.migrate_social import migrate
    a=register()
    uid=a.get('/api/account').json()['id']
    pid=a.post('/api/me/playlists',json={'name':'Existing private playlist'}).json()['id']
    previous=Path('app/schema.sql').read_text().split('-- Opt-in sharing:',1)[0]
    with db.transaction() as c:
        c.execute('DROP TABLE playlist_follows,listener_follows,shared_playlists,listener_profiles')
        db.set_setting(c,'database_schema_digest',hashlib.sha256(previous.encode()).hexdigest())
    migrate();migrate();db.init()
    assert a.get('/api/account').json()['id']==uid
    assert a.get('/api/me/music').json()['playlists'][0]['id']==pid
    assert a.get('/api/me/social').json()['shared']==[]

import json
import time
from fastapi.testclient import TestClient
from app.api import app
from app import db

HEADERS = {'X-RWX-Request': '1'}
PASSWORD = 'long enough password!'


def register(email='listener@example.com'):
    client = TestClient(app, headers=HEADERS)
    client.get('/my-music')
    response = client.post('/api/account/register', json={'email': email, 'password': PASSWORD})
    assert response.status_code == 201, response.text
    return client


def seed(metadata):
    with db.transaction() as c:
        for tid in ['one', 'two']:
            c.execute('INSERT INTO tracks(id,metadata,status,source,rights) VALUES(%s,%s,%s,%s,%s)',
                      (tid, json.dumps({**metadata, 'id': tid}), 'available', 'https://private.example/audio', 'private rights'))


def test_registration_sessions_login_logout_and_expiration():
    a = register(' Listener@Example.com ')
    assert a.get('/api/account').json()['email'] == 'listener@example.com'
    assert a.get('/api/account').headers['cache-control'] == 'no-store'
    old = a.cookies.get('rwx_account')
    with db.connect() as c:
        row = c.execute('SELECT * FROM users').fetchone()
        assert row['password_hash'] != PASSWORD and PASSWORD not in row['password_hash']
        assert c.execute('SELECT digest FROM user_sessions').fetchone()[0] != old
    assert a.post('/api/account/logout').status_code == 200
    assert a.get('/api/account').status_code == 401
    a.cookies.set('rwx_account', old)
    assert a.get('/api/account').status_code == 401
    a.cookies.clear()
    assert a.post('/api/account/login', json={'email':'listener@example.com','password':'incorrect password'}).status_code == 401
    assert a.post('/api/account/login', json={'email':'LISTENER@example.com','password':PASSWORD}).status_code == 200
    with db.transaction() as c: c.execute('UPDATE user_sessions SET expires=%s', (time.time()-1,))
    assert a.get('/api/account').status_code == 401


def test_csrf_cookie_flags_and_rate_limit():
    a = TestClient(app, base_url='https://testserver')
    body = {'email':'listener@example.com','password':PASSWORD}
    assert a.post('/api/account/register', json=body).status_code == 403
    assert a.post('/api/account/register', json=body, headers={**HEADERS,'Origin':'https://evil.example'}).status_code == 403
    response = a.post('/api/account/register', json=body, headers=HEADERS)
    assert response.status_code == 201
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    with db.transaction() as c:
        from app.accounts import digest
        c.cursor().executemany('INSERT INTO account_attempts VALUES(%s,%s)', [(digest('email:listener@example.com'),time.time())]*10)
    assert a.post('/api/account/login',json=body,headers=HEADERS).status_code == 429


def test_private_likes_playlists_ownership_order_and_persistence(metadata):
    seed(metadata)
    a = register(); b = register('second@example.com')
    guest = TestClient(app, headers=HEADERS)
    assert guest.get('/api/me/music').status_code == 401
    assert guest.put('/api/me/likes/one').status_code == 401
    for _ in range(2): assert a.put('/api/me/likes/one').status_code == 200
    assert len(a.get('/api/me/music').json()['likes']) == 1
    assert b.get('/api/me/music').json()['likes'] == []
    assert a.put('/api/me/likes/missing').status_code == 404
    p = a.post('/api/me/playlists',json={'name':' Road trip '}).json()
    assert p['name'] == 'Road trip'
    url = '/api/me/playlists/'+p['id']
    assert b.put(url+'/tracks/one').status_code == 404
    assert b.patch(url,json={'name':'stolen'}).status_code == 404
    assert b.delete(url).status_code == 404
    assert a.put(url+'/tracks/two').status_code == 200
    assert a.put(url+'/tracks/one').status_code == 200
    assert a.put(url+'/tracks/two').status_code == 200
    music = a.get('/api/me/music').json()
    assert [t['id'] for t in music['playlists'][0]['tracks']] == ['two','one']
    assert 'private' not in json.dumps(music)
    assert a.patch(url,json={'name':'Evening'}).status_code == 200
    db.init()  # Repeated initialization preserves collections.
    assert a.get('/api/me/music').json()['playlists'][0]['name'] == 'Evening'
    assert a.delete(url+'/tracks/two').status_code == 200
    assert a.delete('/api/me/likes/one').status_code == 200
    assert a.delete(url).status_code == 200
    assert a.get('/api/me/music').json() == {'likes': [], 'playlists': []}
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM user_playlist_tracks').fetchone()[0] == 0
        for table in ['plays','playlist','reactions','requests','outbox']:
            assert c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0


def test_credentials_and_playlist_validation():
    a=TestClient(app,headers=HEADERS)
    for email,password in [('not-email',PASSWORD),('a@example.com','short'),('a@example.com','x'*129)]:
        assert a.post('/api/account/register',json={'email':email,'password':password}).status_code == 400
    a=register()
    assert a.post('/api/account/register',json={'email':'LISTENER@EXAMPLE.COM','password':PASSWORD}).status_code == 409
    for name in ['', '  ', 'x'*81]:
        assert a.post('/api/me/playlists',json={'name':name}).status_code == 400

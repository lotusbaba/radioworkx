"""Private listener accounts and collections; independent of broadcast scheduling."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, SecretStr
from app import db
from app.library import STATIC, public_track, track_row, capped

router = APIRouter()
COOKIE = 'rwx_account'
LIFETIME = 30 * 86400


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000)
    return salt + ':' + key.hex()


DUMMY_HASH = password_hash('unused-dummy-password')


def same_site(request: Request):
    origin = request.headers.get('origin')
    if (request.headers.get('x-rwx-request') != '1'
            or request.headers.get('sec-fetch-site') == 'cross-site'
            or (origin and urlparse(origin).netloc != request.url.netloc)):
        raise HTTPException(403, 'Use your account on this site.')


def current_user(request: Request):
    token = request.cookies.get(COOKIE, '')
    with db.connect() as c:
        row = c.execute('SELECT u.id,u.email FROM users u JOIN user_sessions s ON s.user_id=u.id WHERE s.digest=? AND s.expires>?',
                        (digest(token), time.time())).fetchone()
    if not row:
        raise HTTPException(401, 'Sign in to save your music.')
    return dict(row)


def throttle(request, email):
    now = time.time()
    # Store hashes only. Do not trust caller-supplied forwarded IP headers.
    keys = [(digest('email:' + email), 10),
            (digest('ip:' + (request.client.host if request.client else 'unknown')), 60),
            ('global', 300)]
    limited = False
    with db.transaction() as c:
        c.execute('DELETE FROM account_attempts WHERE created<?', (now-900,))
        for key, limit in keys:
            if c.execute('SELECT COUNT(*) FROM account_attempts WHERE bucket=?', (key,)).fetchone()[0] >= limit:
                limited = True
        if not limited:
            c.executemany('INSERT INTO account_attempts VALUES(?,?)', [(key, now) for key, _ in keys])
    if limited:
        raise HTTPException(429, 'Too many sign-in attempts. Please try again in 15 minutes.')


def issue_session(c, user_id, request, response):
    token = secrets.token_urlsafe(32)
    c.execute('DELETE FROM user_sessions WHERE expires<? OR digest=?',
              (time.time(), digest(request.cookies.get(COOKIE, ''))))
    c.execute('INSERT INTO user_sessions VALUES(?,?,?)', (digest(token), user_id, time.time()+LIFETIME))
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict',
                        secure=request.url.scheme == 'https' or os.getenv('COOKIE_SECURE') == '1', max_age=LIFETIME)
    response.headers['Cache-Control'] = 'no-store'


class Credentials(BaseModel):
    email: str
    password: SecretStr


def credentials(body):
    email = body.email.strip().casefold()
    password = body.password.get_secret_value()
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise HTTPException(400, 'Enter a valid email address.')
    if not 12 <= len(password) <= 128:
        raise HTTPException(400, 'Use a password between 12 and 128 characters.')
    return email, password


@router.get('/my-music')
def account_page(request: Request):
    from app.api import listener_page
    return listener_page(request, (STATIC/'account.html').read_text())


@router.get('/api/account')
def profile(response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return user


@router.post('/api/account/register', status_code=201, dependencies=[Depends(same_site)])
def register(body: Credentials, request: Request, response: Response):
    email, password = credentials(body)
    throttle(request, email)
    encoded = password_hash(password)
    user_id = uuid.uuid4().hex
    try:
        with db.transaction() as c:
            c.execute('INSERT INTO users VALUES(?,?,?,?)', (user_id, email, encoded, time.time()))
            issue_session(c, user_id, request, response)
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'Unable to register this email. Try signing in.')
    return {'id': user_id, 'email': email}


@router.post('/api/account/login', dependencies=[Depends(same_site)])
def login(body: Credentials, request: Request, response: Response):
    email, password = credentials(body)
    throttle(request, email)
    with db.connect() as c:
        row = c.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    encoded = row['password_hash'] if row else DUMMY_HASH
    valid = hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)
    if not row or not valid:
        raise HTTPException(401, 'Email or password is incorrect.')
    with db.transaction() as c:
        issue_session(c, row['id'], request, response)
    return {'id': row['id'], 'email': row['email']}


@router.post('/api/account/logout', dependencies=[Depends(same_site)])
def logout(request: Request, response: Response):
    with db.transaction() as c:
        c.execute('DELETE FROM user_sessions WHERE digest=?', (digest(request.cookies.get(COOKIE, '')),))
    response.delete_cookie(COOKIE, httponly=True, samesite='strict')
    response.headers['Cache-Control'] = 'no-store'
    return {'ok': True}


@router.get('/api/me/music')
def music(response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    with db.connect() as c:
        limit = capped(c)
        likes = [public_track(r, limit) for r in c.execute('SELECT t.* FROM tracks t JOIN user_likes l ON l.track_id=t.id WHERE l.user_id=? ORDER BY l.created DESC,t.id', (user['id'],))]
        playlists = [dict(r) for r in c.execute('SELECT id,name FROM user_playlists WHERE user_id=? ORDER BY created,id', (user['id'],))]
        limit = capped(c)
        for playlist in playlists:
            playlist['tracks'] = [public_track(r, limit) for r in c.execute('SELECT t.* FROM tracks t JOIN user_playlist_tracks p ON p.track_id=t.id WHERE p.playlist_id=? ORDER BY p.position', (playlist['id'],))]
    return {'likes': likes, 'playlists': playlists}


@router.put('/api/me/likes/{track_id}', dependencies=[Depends(same_site)])
def like(track_id: str, user=Depends(current_user)):
    with db.transaction() as c:
        track_row(c, track_id)
        c.execute('INSERT OR IGNORE INTO user_likes VALUES(?,?,?)', (user['id'], track_id, time.time()))
    return {'ok': True}


@router.delete('/api/me/likes/{track_id}', dependencies=[Depends(same_site)])
def unlike(track_id: str, user=Depends(current_user)):
    with db.transaction() as c:
        c.execute('DELETE FROM user_likes WHERE user_id=? AND track_id=?', (user['id'], track_id))
    return {'ok': True}


class PlaylistName(BaseModel):
    name: str


def playlist_name(body):
    name = body.name.strip()
    if not 1 <= len(name) <= 80:
        raise HTTPException(400, 'Use a playlist name between 1 and 80 characters.')
    return name


def owned(c, playlist_id, user):
    if not c.execute('SELECT 1 FROM user_playlists WHERE id=? AND user_id=?', (playlist_id, user['id'])).fetchone():
        raise HTTPException(404, 'Playlist not found.')


@router.post('/api/me/playlists', status_code=201, dependencies=[Depends(same_site)])
def create_playlist(body: PlaylistName, user=Depends(current_user)):
    name = playlist_name(body)
    pid = uuid.uuid4().hex
    with db.transaction() as c:
        if c.execute('SELECT COUNT(*) FROM user_playlists WHERE user_id=?', (user['id'],)).fetchone()[0] >= 100:
            raise HTTPException(409, 'You can create up to 100 playlists.')
        c.execute('INSERT INTO user_playlists VALUES(?,?,?,?)', (pid, user['id'], name, time.time()))
    return {'id': pid, 'name': name, 'tracks': []}


@router.patch('/api/me/playlists/{playlist_id}', dependencies=[Depends(same_site)])
def rename_playlist(playlist_id: str, body: PlaylistName, user=Depends(current_user)):
    name = playlist_name(body)
    with db.transaction() as c:
        owned(c, playlist_id, user)
        c.execute('UPDATE user_playlists SET name=? WHERE id=?', (name, playlist_id))
    return {'ok': True}


@router.delete('/api/me/playlists/{playlist_id}', dependencies=[Depends(same_site)])
def delete_playlist(playlist_id: str, user=Depends(current_user)):
    with db.transaction() as c:
        owned(c, playlist_id, user)
        c.execute('DELETE FROM user_playlists WHERE id=?', (playlist_id,))
    return {'ok': True}


@router.put('/api/me/playlists/{playlist_id}/tracks/{track_id}', dependencies=[Depends(same_site)])
def add_track(playlist_id: str, track_id: str, user=Depends(current_user)):
    with db.transaction() as c:
        owned(c, playlist_id, user)
        track_row(c, track_id)
        count = c.execute('SELECT COUNT(*) FROM user_playlist_tracks WHERE playlist_id=?', (playlist_id,)).fetchone()[0]
        if count >= 500:
            raise HTTPException(409, 'A playlist can contain up to 500 tracks.')
        c.execute('INSERT OR IGNORE INTO user_playlist_tracks(playlist_id,track_id,position) SELECT ?,?,COALESCE(MAX(position),0)+1 FROM user_playlist_tracks WHERE playlist_id=?', (playlist_id, track_id, playlist_id))
    return {'ok': True}


@router.delete('/api/me/playlists/{playlist_id}/tracks/{track_id}', dependencies=[Depends(same_site)])
def remove_track(playlist_id: str, track_id: str, user=Depends(current_user)):
    with db.transaction() as c:
        owned(c, playlist_id, user)
        c.execute('DELETE FROM user_playlist_tracks WHERE playlist_id=? AND track_id=?', (playlist_id, track_id))
    return {'ok': True}

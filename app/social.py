"""Opt-in public playlists and private following lists."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from app import db
from app.accounts import current_user, same_site, owned
from app.library import STATIC, capped, public_track

router = APIRouter()


def person(c, user_id):
    row = c.execute('SELECT u.id,p.display_name FROM users u LEFT JOIN listener_profiles p ON p.user_id=u.id WHERE u.id=%s', (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Listener not found.')
    return {'id': row['id'], 'name': row['display_name'] or 'Listener ' + row['id'][:8]}


def shared_playlist(c, playlist_id):
    row = c.execute('SELECT p.id,p.name,p.user_id FROM user_playlists p JOIN shared_playlists s ON s.playlist_id=p.id WHERE p.id=%s', (playlist_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'This playlist is private or no longer available.')
    limit = capped(c)
    return {'id': row['id'], 'name': row['name'], 'owner': person(c, row['user_id']),
            'tracks': [public_track(t, limit) for t in c.execute('SELECT t.* FROM tracks t JOIN user_playlist_tracks p ON p.track_id=t.id WHERE p.playlist_id=%s ORDER BY p.position', (playlist_id,))]}


@router.get('/playlists/{playlist_id}')
@router.get('/people/{user_id}')
def social_page(request: Request):
    from app.api import listener_page
    return listener_page(request, (STATIC/'social.html').read_text())


@router.get('/api/shared/playlists/{playlist_id}')
def playlist(playlist_id: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with db.connect() as c:
        return shared_playlist(c, playlist_id)


@router.get('/api/people/{user_id}')
def profile(user_id: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with db.connect() as c:
        result = person(c, user_id)
        result['playlists'] = [dict(r) for r in c.execute('SELECT p.id,p.name FROM user_playlists p JOIN shared_playlists s ON s.playlist_id=p.id WHERE p.user_id=%s ORDER BY p.created,p.id', (user_id,))]
        return result


@router.get('/api/me/social')
def collection(response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    with db.connect() as c:
        playlists = []
        for row in c.execute('SELECT playlist_id FROM playlist_follows WHERE user_id=%s ORDER BY playlist_id', (user['id'],)).fetchall():
            try:
                playlists.append(shared_playlist(c, row[0]))
            except HTTPException as error:
                # READ COMMITTED: an owner can revoke/delete after we fetched the
                # follow IDs. Omit that item, rather than fail the whole collection.
                if error.status_code != 404:
                    raise
        return {'profile': person(c, user['id']),
                'shared': [r[0] for r in c.execute('SELECT s.playlist_id FROM shared_playlists s JOIN user_playlists p ON p.id=s.playlist_id WHERE p.user_id=%s', (user['id'],))],
                'people': [person(c, r[0]) for r in c.execute('SELECT followed_id FROM listener_follows WHERE user_id=%s ORDER BY followed_id', (user['id'],)).fetchall()],
                'playlists': playlists}


class ProfileName(BaseModel):
    name: str


@router.put('/api/me/profile', dependencies=[Depends(same_site)])
def update_profile(body: ProfileName, user=Depends(current_user)):
    name = body.name.strip()
    if not 1 <= len(name) <= 60:
        raise HTTPException(400, 'Use a public name between 1 and 60 characters.')
    with db.transaction() as c:
        c.execute('INSERT INTO listener_profiles VALUES(%s,%s) ON CONFLICT(user_id) DO UPDATE SET display_name=excluded.display_name', (user['id'], name))
    return {'ok': True}


@router.put('/api/me/playlists/{playlist_id}/sharing', dependencies=[Depends(same_site)])
def share(playlist_id: str, user=Depends(current_user)):
    with db.transaction() as c:
        owned(c, playlist_id, user)
        c.execute('INSERT INTO shared_playlists VALUES(%s) ON CONFLICT DO NOTHING', (playlist_id,))
    return {'url': '/playlists/' + playlist_id}


@router.delete('/api/me/playlists/{playlist_id}/sharing', dependencies=[Depends(same_site)])
def unshare(playlist_id: str, user=Depends(current_user)):
    with db.transaction() as c:
        owned(c, playlist_id, user)
        # Follows cascade away: republishing never silently re-subscribes listeners.
        c.execute('DELETE FROM shared_playlists WHERE playlist_id=%s', (playlist_id,))
    return {'ok': True}


@router.put('/api/me/following/people/{person_id}', dependencies=[Depends(same_site)])
def follow_person(person_id: str, user=Depends(current_user)):
    if person_id == user['id']:
        raise HTTPException(400, 'This is your own profile.')
    with db.transaction() as c:
        person(c, person_id)
        if not c.execute('SELECT 1 FROM listener_follows WHERE user_id=%s AND followed_id=%s', (user['id'], person_id)).fetchone():
            if c.execute('SELECT COUNT(*) FROM listener_follows WHERE user_id=%s', (user['id'],)).fetchone()[0] >= 100:
                raise HTTPException(409, 'You can follow up to 100 listeners.')
            c.execute('INSERT INTO listener_follows VALUES(%s,%s)', (user['id'], person_id))
    return {'ok': True}


@router.delete('/api/me/following/people/{person_id}', dependencies=[Depends(same_site)])
def unfollow_person(person_id: str, user=Depends(current_user)):
    with db.transaction() as c:
        c.execute('DELETE FROM listener_follows WHERE user_id=%s AND followed_id=%s', (user['id'], person_id))
    return {'ok': True}


@router.put('/api/me/following/playlists/{playlist_id}', dependencies=[Depends(same_site)])
def follow_playlist(playlist_id: str, user=Depends(current_user)):
    with db.transaction() as c:
        p = shared_playlist(c, playlist_id)
        if p['owner']['id'] == user['id']:
            raise HTTPException(400, 'This playlist is already in your collection.')
        if not c.execute('SELECT 1 FROM playlist_follows WHERE user_id=%s AND playlist_id=%s', (user['id'], playlist_id)).fetchone():
            if c.execute('SELECT COUNT(*) FROM playlist_follows WHERE user_id=%s', (user['id'],)).fetchone()[0] >= 100:
                raise HTTPException(409, 'You can follow up to 100 playlists.')
            c.execute('INSERT INTO playlist_follows VALUES(%s,%s)', (user['id'], playlist_id))
    return {'ok': True}


@router.delete('/api/me/following/playlists/{playlist_id}', dependencies=[Depends(same_site)])
def unfollow_playlist(playlist_id: str, user=Depends(current_user)):
    with db.transaction() as c:
        c.execute('DELETE FROM playlist_follows WHERE user_id=%s AND playlist_id=%s', (user['id'], playlist_id))
    return {'ok': True}

"""Shared, read-only candidate ordering for transmission and playlist previews."""
import json
from app.config import DEMO
from app.policy import eligible


def candidates(c):
    requests = [dict(r) for r in c.execute("SELECT t.*,r.id AS request_id FROM requests r JOIN tracks t ON t.id=r.track_id WHERE r.status='pending' ORDER BY r.sequence")]
    automatic = [dict(r) for r in c.execute("SELECT t.*,p.position FROM playlist p JOIN tracks t ON t.id=p.track_id ORDER BY p.priority DESC,p.position")]
    library = [dict(r) for r in c.execute("SELECT * FROM tracks WHERE status='ready' ORDER BY downloaded_at,id")]
    for rows in (requests, automatic, library):
        for row in rows: row['meta'] = json.loads(row['metadata'])
    return requests, automatic, library


def choose(groups, history, at):
    requests, automatic, library = groups
    requested = {r['id'] for r in requests}
    queued = {r['id'] for r in automatic}
    def playable(row):
        return row['status']=='ready' and bool(row['meta'].get('demo'))==DEMO and eligible(row['meta'],history,at)
    requested_row=next((r for r in requests if playable(r)),None)
    if requested_row:return requested_row
    last_played={p.get('track_id',p['metadata'].get('id')):p['ends'] for p in history}
    recent={p.get('track_id',p['metadata'].get('id')) for p in history[-9:]}
    cached=sorted(library,key=lambda r:last_played.get(r['id'],float('-inf')))
    rows = [r for r in automatic if r['id'] not in requested] + [r for r in cached if r['id'] not in requested and r['id'] not in queued]
    choices=[r for r in rows if playable(r)]
    # Prefer variety, but don't turn a small eligible library into silence.
    return next((r for r in choices if r['id'] not in recent),choices[0] if choices else None)


def preview(c, history, at, size=10):
    groups = candidates(c)
    history = list(history)
    result = []
    seen=set()
    for _ in range(size):
        row = choose(groups, history, at)
        if row is None or row['id'] in seen: break
        seen.add(row['id'])
        result.append({'metadata':row['meta'],'duration':row['duration'],
                       'status':'Up next' if not result else 'Coming up',
                       'selection':'Listener request' if 'request_id' in row else 'Automatic selection',
                       'estimated_start':at})
        if not row['duration'] or row['duration'] <= 0: break
        history.append({'metadata':row['meta'],'starts':at,'ends':at+row['duration']})
        at += row['duration']
        groups = ([r for r in groups[0] if r.get('request_id') != row.get('request_id')] if 'request_id' in row else groups[0],
                  [r for r in groups[1] if r['id'] != row['id']], groups[2])
    return result

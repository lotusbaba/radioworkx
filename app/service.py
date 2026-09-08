import json
import math
import time
import uuid
from app import db
from app.config import THRESHOLD


def now_playing(c, now=None):
    now = time.time() if now is None else now
    row = c.execute('SELECT * FROM plays WHERE starts<=? AND ends>? AND actual_end IS NULL ORDER BY starts DESC LIMIT 1',
                    (now,now)).fetchone()
    if not row:
        return None
    announcement=json.loads(db.setting(c,'announcement_on_air','null'))
    if announcement and announcement.get('play_id')==row['id']:
        return None
    requested=bool(c.execute("SELECT 1 FROM requests WHERE play_id=? AND status IN ('playing','played')",(row['id'],)).fetchone())
    return {**dict(row),'metadata':json.loads(row['metadata']),'requested':requested}

COOLDOWN = 1

class ReactionCooldown(ValueError):
    def __init__(self, next_at, now):
        self.next_at=next_at
        self.retry_after=max(1,math.ceil(next_at-now))
        super().__init__(f'You can react again in {self.retry_after}s')


def next_reaction_at(c, listener):
    row=c.execute('SELECT MAX(accepted) FROM reactions WHERE listener=?',(listener,)).fetchone()
    return (row[0]+COOLDOWN) if row[0] is not None else 0


def accept_reaction(play_id, listener, emoji, now=None, event_id=None):
    now = time.time() if now is None else now
    with db.transaction() as c:
        if event_id:
            previous=c.execute('SELECT * FROM reactions WHERE id=?',(event_id,)).fetchone()
            if previous:
                if (previous['play_id'],previous['listener'],previous['emoji']) != (play_id,listener,emoji):
                    raise ValueError('Reaction ID already used for a different event')
                return event_id
        play = now_playing(c,now)
        if not play or play['id'] != play_id:
            raise ValueError('That track has ended. React to the current track.')
        next_at=next_reaction_at(c,listener)
        if now < next_at:
            raise ReactionCooldown(next_at,now)
        meta = play['metadata']
        event = dict(id=event_id or str(uuid.uuid4()),play_id=play_id,listener=listener,emoji=emoji,
                     accepted=now,ends=play['ends'],track_id=play['track_id'],
                     artists=meta['artists'],genre=meta['genre'],album_id=meta['album_id'])
        c.execute('INSERT INTO reactions(id,play_id,listener,emoji,accepted,metadata) VALUES(?,?,?,?,?,?)',
                  (event['id'],play_id,listener,emoji,now,json.dumps(event)))
        db.emit(c,event['id'],'reactions',event)
        return event['id']

def process_reaction(event, now=None):
    now = time.time() if now is None else now
    with db.transaction() as c:
        row = c.execute('SELECT * FROM reactions WHERE id=?', (event['id'],)).fetchone()
        if not row:
            raise ValueError('Unknown reaction event')
        # Trust the durable server-authored event, not fields supplied on a queue.
        event = json.loads(row['metadata'])
        if not row['processed']:
            c.execute('UPDATE reactions SET processed=1 WHERE id=?',(event['id'],))
            count = c.execute('SELECT COUNT(*) FROM reactions WHERE play_id=? AND processed=1',
                              (event['play_id'],)).fetchone()[0]
            active = now_playing(c,now)
            # All accepted reactions on a play share its artist(s) and genre.
            # One job handles their simultaneous crossings, avoiding duplicate downloads.
            if count > THRESHOLD and event['accepted'] < event['ends'] and active and active['id'] == event['play_id']:
                job_id = 'boost:'+event['play_id']
                db.emit(c,job_id,'priority-downloads',dict(kind='boost',artists=event['artists'],
                          genre=event['genre'],album_id=event['album_id'],exclude=event['track_id']))
    return event

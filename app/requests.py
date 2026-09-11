"""Durable listener requests. SQL acceptance order, never SQS delivery order, defines FIFO."""
import json
import re
import random
import time
import unicodedata
import os
import httpx
from app import db
from app.config import DEMO
from app.downloads import library_only
from app.policy import eligible, WINDOW


def eligible_genre_tracks(c, genre, now=None):
    now = time.time() if now is None else now
    history = [dict(p, metadata=json.loads(p['metadata'])) for p in c.execute(
        'SELECT * FROM plays WHERE ends>? OR id IN (SELECT id FROM plays ORDER BY starts DESC LIMIT 3) ORDER BY starts', (now-WINDOW,))]
    capped = library_only(c)
    result = []
    for row in c.execute("SELECT * FROM tracks WHERE status IN ('ready','available') AND id NOT IN (SELECT track_id FROM requests WHERE status='pending')"):
        meta = json.loads(row['metadata'])
        if normalize(meta['genre']) != normalize(genre) or bool(meta.get('demo')) != DEMO: continue
        if row['status'] != 'ready' and (capped or not row['source'] or not row['rights']): continue
        if eligible(meta, history, now): result.append((row, meta))
    return result


def choose_genre_track(c, genre, now=None):
    """Favor discovery, then the least recently played/requested eligible track."""
    now=time.time() if now is None else now
    choices=eligible_genre_tracks(c,genre,now)
    if not choices:return None
    used={r['track_id']:r['last_used'] for r in c.execute(
        "SELECT track_id,MAX(at) AS last_used FROM (SELECT track_id,starts AS at FROM plays UNION ALL SELECT track_id,created AS at FROM requests WHERE track_id IS NOT NULL AND status!='failed') GROUP BY track_id")}
    # Do not choose a currently airing or already pending request track.
    active={r[0] for r in c.execute('SELECT track_id FROM plays WHERE starts<=? AND ends>? AND actual_end IS NULL',(now,now))}
    choices=[pair for pair in choices if pair[0]['id'] not in active]
    if not choices:return None
    oldest=min(used.get(row['id'],float('-inf')) for row,_ in choices)
    pool=[pair for pair in choices if used.get(pair[0]['id'],float('-inf'))==oldest]
    # Uniform artist groups avoid one prolific artist dominating the pool.
    artists={}
    for pair in pool:artists.setdefault(tuple(sorted(pair[1]['artists'])),[]).append(pair)
    return random.choice(random.choice(list(artists.values())))


def refresh_genre_head(c, now):
    """Continue discovery for deferred requests as well as the next request."""
    for request in c.execute("SELECT * FROM requests WHERE status='pending' ORDER BY sequence").fetchall():
        refresh_genre_request(c, now, request)


def refresh_genre_request(c, now, request):
    genre = request['requested_genre']
    # Upgrade old explicit genre requests without reinterpreting specific titles.
    if not genre:
        needle, mode = search_query(request['query'], request['mode'])
        if mode in {'auto','genre'}:
            genre = genre_intent(needle, [])
    if not genre: return
    history = [dict(p, metadata=json.loads(p['metadata'])) for p in c.execute('SELECT * FROM plays ORDER BY starts')]
    current = c.execute('SELECT metadata FROM tracks WHERE id=?',(request['track_id'],)).fetchone()
    if current and eligible(json.loads(current['metadata']), history, now): return
    choice = choose_genre_track(c, genre, now)
    if not choice:
        if library_only(c): return
        key = 'request-discovery:' + request['id']
        active = c.execute("SELECT 1 FROM outbox WHERE done IS NULL AND json_extract(body,'$.discover_genre')=?",(genre,)).fetchone()
        if not active and now-float(db.setting(c,key,'0')) >= 300:
            db.emit(c, key+':'+str(time.time_ns()), 'request-downloads',
                    {'kind':'request','discover_genre':genre,'request_id':request['id']})
            db.set_setting(c,key,now)
        return
    row, meta = choice
    response = f"Selected “{meta['title']}” by {' & '.join(meta['artists'])} for your {genre} request because the previous selection reached a playback limit. Your request keeps its FIFO position."
    c.execute('UPDATE requests SET track_id=?,response=?,requested_genre=?,sources=? WHERE id=?',
              (row['id'],response,genre,json.dumps([{k:meta.get(k) for k in ('id','title','bandcamp_url')}]),request['id']))
    c.execute('DELETE FROM playlist WHERE track_id=?',(row['id'],))
    db.emit(c, 'request:'+request['id']+':replacement:'+str(time.time_ns()), 'request-downloads',
            {'kind':'request','track_id':row['id'],'request_id':request['id']})


def normalize(value):
    value = unicodedata.normalize('NFKD', value.casefold())
    return ' '.join(re.sub(r'[^\w\s]', ' ', ''.join(c for c in value if not unicodedata.combining(c))).split())


def search_query(query, mode):
    query = query.strip().rstrip('.!?')
    query = re.sub(r"^(?:(?:please|can you|could you)\s+)*(?:(?:i want|i would like|i'd like|get me|give me|let me hear)\s+)?(?:(?:to hear|to listen to|listen to|play|queue|request)\s+)?", '', query, flags=re.I)
    for pattern, kind in [
        (r'^(?:(?:a track|tracks|songs|a song|something)\s+)?(?:from |off )?(?:the )?album\s+', 'album'),
        (r'^(?:a track|tracks|songs|a song|something)\s+(?:by|from)\s+(?:the artist\s+)?', 'artist'),
        (r'^(?:the )?artist\s+', 'artist'),
        (r'^(?:the )?(?:track|song)\s+', 'track'),
        (r'^(?:some |something in |music in |tracks in )?(?:the )?genre\s+', 'genre')]:
        if re.match(pattern, query, re.I):
            query = re.sub(pattern, '', query, flags=re.I)
            if mode == 'auto': mode = kind
            break
    return normalize(query), mode


MOODS = [
    ({'calm','relax','relaxed','stressed','anxious','chill','peaceful','sleep','quiet'}, ['ambient','jazz','folk','vaporwave']),
    ({'happy','upbeat','joyful','dance','party','energetic','workout','excited'}, ['funk','edm','chiptune','techno']),
    ({'sad','down','melancholy','lonely','reflective'}, ['folk','ambient','jazz','trip-hop']),
    ({'focus','focused','study','working','concentrate'}, ['ambient','jazz','orchestral','vaporwave']),
    ({'angry','intense','frustrated','heavy'}, ['metal','punk','doom metal','edm']),
    ({'nostalgic','dreamy'}, ['vaporwave','chiptune','trip-hop','ambient']),
]


KNOWN_GENRES = {'hip-hop','trip-hop','jazz','funk','ambient','folk','metal','rock','punk','pop','soul','r&b','reggae','classical','country','blues','techno','house','edm','electronic','chiptune','vaporwave','orchestral','afrobeat','doom metal'}


def genre_intent(needle, genres):
    # Only genre request grammar; don't extract a genre out of an arbitrary title/artist.
    needle=re.sub(r'\bhiphop\b','hip hop',needle)
    for genre in sorted(set(genres)|KNOWN_GENRES,key=len,reverse=True):
        name=normalize(genre)
        pattern=r'^(?:(?:yes|sure|okay|some|something|a|an|in|the|genre|music|tracks|songs|from|of|one|please)\s+)*'+re.escape(name)+r'(?:\s+(?:track|tracks|song|songs|music|genre|please|for|me|now))*$'
        if re.fullmatch(pattern,needle):return genre
    return None


def offer_genres(c,listener,genres,response):
    choices=genres[:3]
    c.execute('INSERT INTO conversations VALUES(?,?) ON CONFLICT(listener) DO UPDATE SET genres=excluded.genres',(listener,json.dumps(choices)))
    return {'response':response,'status':'awaiting_confirmation' if choices else 'not_found','suggestions':choices}


def conversation(c, listener, query, needle, mode, genres):
    """Return a genre to fetch, or a reply to save without any acquisition."""
    if mode != 'auto': return None
    saved = c.execute('SELECT genres FROM conversations WHERE listener=?',(listener,)).fetchone()
    offered = json.loads(saved['genres']) if saved else []
    if offered and needle in {'no','no thanks','cancel','never mind','nevermind'}:
        c.execute('DELETE FROM conversations WHERE listener=?',(listener,))
        return {'response':'No problem — I have not queued a song. Tell me another mood, genre, artist, album, or title.', 'status':'cancelled','suggestions':[]}
    if offered and needle in {'yes','yes please','sure','ok','okay','go ahead','sounds good','do it','surprise me'}:
        return {'genre':random.choice(offered)}
    needle = re.sub(r'^the (first|second|third)(?: one)?$', lambda m: m.group(1), needle)
    if offered and needle in {'first','second','third','1','2','3'}:
        index={'first':0,'second':1,'third':2,'1':0,'2':1,'3':2}[needle]
        if index < len(offered): return {'genre':offered[index]}
    if needle in {'what genres do you have','what genres are available','which genres do you have','show genres','list genres','genres'}:
        return offer_genres(c,listener,genres,'Available genres: '+', '.join(genres)+'. Which would you like?')
    requested_genre=genre_intent(needle,genres)
    if requested_genre:
        actual=next((g for g in genres if normalize(g)==normalize(requested_genre)),None)
        if actual:return {'genre':actual}
        preferred=['trip-hop','funk','edm'] if requested_genre=='hip-hop' else []
        choices=[g for wanted in preferred for g in genres if g==wanted]
        choices+=(g for g in genres if g not in choices)
        response=f"We don't have playable {requested_genre} tracks in our licensed catalog yet. "
        response+=('Would you like '+', '.join(choices[:3])+' instead? Tell me which one, or ask for a specific artist or song. I haven’t queued anything.' if choices else 'There are no playable alternatives right now.')
        return offer_genres(c,listener,choices,response)
    # Naming a genre directly is already a specific request (also confirms a suggestion).
    genre_query = re.sub(r'^(?:yes |sure |okay )', '', needle)
    genre_query = re.sub(r'^(?:some|something in|something|music in) ', '', genre_query)
    genre_query = re.sub(r' (?:music|tracks|songs)(?: please)?$', '', genre_query)
    genre_query = re.sub(r' please$', '', genre_query)
    for genre in genres:
        if genre_query == normalize(genre): return {'genre':genre}
    words=set(normalize(query).split())
    preferred=next((choices for cues,choices in MOODS if words & cues),None)
    vague = bool(words & {'mood','feeling','feel','vibe'}) or needle in {'hi','hello','hey','help','something','anything','surprise me','yes','yes please','sure','ok','okay'}
    if preferred or vague:
        choices=[g for wanted in (preferred or []) for g in genres if normalize(g)==normalize(wanted)][:3]
        choices=choices or genres[:3]
        if not choices:
            return {'response':"There are no playable genres in the catalog right now. Please try again once music is available.",'status':'not_found','suggestions':[]}
        c.execute('INSERT INTO conversations VALUES(?,?) ON CONFLICT(listener) DO UPDATE SET genres=excluded.genres',(listener,json.dumps(choices)))
        response=("For that mood, how about " if preferred else "How are you feeling — relaxed, upbeat, reflective, or something else? We could try ")
        response+=', '.join(choices)+'. Would one of those fit? Choose a genre, tell me more about your mood, or say yes and I’ll pick from these. I’ll wait before fetching a song.'
        return {'response':response,'status':'awaiting_confirmation','suggestions':choices}
    return None


def submit(query, mode, listener, request_id):
    if mode == 'auto' and os.getenv('OPENAI_API_KEY'):
        from app import rag
        try:
            return rag.submit(query, mode, listener, request_id)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError, rag.Unavailable):
            # No provider error bodies (which may contain sensitive context) reach clients.
            result = submit_local(query, mode, listener, request_id)
            with db.transaction() as c:
                c.execute("UPDATE requests SET response=? WHERE id=? AND engine='basic'",
                          ('AI chat is temporarily unavailable; using basic catalog search. ' + result['response'], request_id))
                return public(c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone())
    return submit_local(query, mode, listener, request_id)


def submit_local(query, mode, listener, request_id):
    with db.transaction() as c:
        old = c.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        if old:
            if (old['listener'], old['query'], old['mode']) != (listener, query, mode):
                raise ValueError('This request ID has already been used.')
            return public(old)
        needle, search_mode = search_query(query, mode)
        matches = []
        catalog = []
        capped = library_only(c)
        for row in c.execute('SELECT * FROM tracks ORDER BY id'):
            meta = json.loads(row['metadata'])
            if bool(meta.get('demo')) != DEMO or row['status']=='failed': continue
            if row['status'] != 'ready' and (capped or not row['source'] or not row['rights']): continue
            catalog.append((row,meta))
        genres=sorted({meta['genre'] for _,meta in catalog})
        # Exact catalog identities take precedence over mood words in titles/names.
        exact=any(needle==normalize(v) for _,m in catalog for v in [m['title'],m.get('album',''),*m['artists']])
        turn=None if exact else conversation(c,listener,query,needle,search_mode,genres)
        if turn and 'genre' not in turn:
            c.execute('INSERT INTO requests(id,listener,query,mode,response,status,created,suggestions) VALUES(?,?,?,?,?,?,?,?)',
                      (request_id,listener,query,mode,turn['response'],turn['status'],time.time(),json.dumps(turn['suggestions'])))
            return public(c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone())
        if turn:
            needle,search_mode=normalize(turn['genre']),'genre'
        c.execute('DELETE FROM conversations WHERE listener=?',(listener,))
        for row,meta in catalog:
            fields = {'genre':[meta['genre']], 'track': [meta['title']], 'artist': meta['artists'], 'album': [meta.get('album', '')]}
            values = fields.get(search_mode, sum(fields.values(), []) + [meta['title']+' by '+' & '.join(meta['artists'])])
            scores = [2 if needle == normalize(v) else 1 if needle and needle in normalize(v) else 0 for v in values]
            if max(scores): matches.append((max(scores), row, meta))
        matches.sort(key=lambda x: -x[0])
        if matches:
            top=[match for match in matches if match[0]==matches[0][0]]
            _, row, meta = random.choice(top) if search_mode in {'genre','artist','album'} else matches[0]
            if search_mode == 'genre':
                choice = choose_genre_track(c, meta['genre'])
                if choice: row, meta = choice
            track_id, status = row['id'], 'pending'
            position = c.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0] + 1
            response = f"Queued “{meta['title']}” by {' & '.join(meta['artists'])} at request position {position}, ahead of automatic selections when eligible. Blocked or downloading requests are deferred."
            if len(matches) > 1: response += ' I selected one matching track; use its full title for a specific song.'
        else:
            track_id, status = None, 'not_found'
            response = "I couldn't find a playable match in this station's licensed catalog. Try a song title, artist, album, or genre name" + (' from the downloaded library.' if capped else '.')
        c.execute('INSERT INTO requests(id,listener,query,mode,response,track_id,status,created) VALUES(?,?,?,?,?,?,?,?)',
                  (request_id,listener,query,mode,response,track_id,status,time.time()))
        if track_id:
            if search_mode == 'genre':
                c.execute('UPDATE requests SET requested_genre=? WHERE id=?',(meta['genre'],request_id))
            c.execute('DELETE FROM playlist WHERE track_id=?', (track_id,))
            db.emit(c,'request:'+request_id,'request-downloads',{'kind':'request','track_id':track_id,'request_id':request_id})
        return public(c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone())


def public(row):
    return {**{key: row[key] for key in ('id','query','response','status','track_id','created','engine')},'suggestions':json.loads(row['suggestions']), 'sources':json.loads(row['sources'])}


def history(listener):
    with db.connect() as c:
        rows = c.execute('SELECT * FROM requests WHERE listener=? ORDER BY sequence DESC LIMIT 50',(listener,)).fetchall()
        return [public(row) for row in reversed(rows)]


def ordered_pending(c, now=None):
    now = time.time() if now is None else now
    history = [dict(p,metadata=json.loads(p['metadata'])) for p in c.execute(
        'SELECT * FROM plays WHERE ends>? OR id IN (SELECT id FROM plays ORDER BY starts DESC LIMIT 3) ORDER BY starts',(now-WINDOW,))]
    rows = c.execute("SELECT t.*,r.id AS request_id FROM requests r JOIN tracks t ON t.id=r.track_id WHERE r.status='pending' ORDER BY r.sequence").fetchall()
    # Stable partition: ready eligible requests first, all deferred requests last.
    return sorted(rows, key=lambda r: not (r['status']=='ready' and bool(json.loads(r['metadata']).get('demo'))==DEMO and eligible(json.loads(r['metadata']),history,now)))


def head(c, now=None):
    rows = ordered_pending(c, now)
    return rows[0] if rows else None

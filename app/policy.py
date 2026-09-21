"""Conservative station-wide performance complement, rechecked at transmission."""
import random

WINDOW = 3 * 60 * 60

def eligible(candidate, history, now):
    # Include any performance overlapping the rolling window, not only starts.
    recent = [p for p in history if p['ends'] > now - WINDOW]
    for key, values, limit, consecutive in (
        ('artists', candidate['artists'], 4, 3),
        ('album_id', [candidate['album_id']], 3, 2),
        ('compilation_id', [candidate.get('compilation_id')], 4, 3),
    ):
        for value in filter(None, values):
            def matches(p):
                v = p['metadata'].get(key)
                return value in v if isinstance(v, list) else value == v
            if sum(matches(p) for p in recent) >= limit:
                return False
            # Consecutive counts survive silence and the rolling-window boundary.
            tail = history[-consecutive:]
            if len(tail) == consecutive and all(matches(p) for p in tail):
                return False
    return True

def diverse_sample(tracks, size=10, rng=None, max_states=5000):
    """Bounded search: many recordings by the same artists must not explode work."""
    rng = rng or random.SystemRandom()
    pool = list(tracks)
    rng.shuffle(pool)
    groups = {}
    for track in pool:
        # Equivalent artist/genre combinations need only one randomly chosen recording.
        groups.setdefault(track['genre'], {}).setdefault(frozenset(track['artists']), track)
    if len(groups)<size:return []
    genres=sorted(groups,key=lambda g:len(groups[g]))
    failed=set();visited=0
    def search(i, selected, artists):
        nonlocal visited
        if len(selected)==size:return selected
        if visited>=max_states:return None
        visited+=1
        remaining=size-len(selected)
        if len(genres)-i<remaining:return None
        state=(i,remaining,frozenset(artists))
        if state in failed:return None
        choices=[[(a,t) for a,t in groups[g].items() if not artists.intersection(a)] for g in genres[i:]]
        if sum(bool(c) for c in choices)<remaining:return None
        available=set().union(*(a for group in choices for a,t in group))
        if len(available)<remaining:return None
        for a,t in choices[0]:
            result=search(i+1,selected+[t],artists.union(a))
            if result:return result
        result=search(i+1,selected,artists)
        if result:return result
        failed.add(state)
        return None
    return search(0,[],set()) or []


def balanced_sample(tracks, fresh_ids, counts, last_played, genre_last, size=10, rng=None, max_states=50000):
    """Prefer the largest feasible fresh batch; rotate genres and rank repeat tracks.

    Search is bounded to keep large or conflicting catalogs from stalling workers.
    Equivalent artist/genre choices retain their best-ranked recording.
    """
    rng = rng or random.SystemRandom()
    pool = list(tracks)
    rng.shuffle(pool)
    pool.sort(key=lambda t:(t['id'] not in fresh_ids, counts.get(t['id'],0), last_played.get(t['id'],0)))
    groups = {}
    for track in pool:
        groups.setdefault(track['genre'], {}).setdefault(frozenset(track['artists']),track)
    genres = list(groups)
    rng.shuffle(genres)
    genres.sort(key=lambda g:(not any(t['id'] in fresh_ids for t in groups[g].values()),genre_last.get(g,0)))
    if len(genres)<size:return []
    fresh_genres={g for g in genres if any(t['id'] in fresh_ids for t in groups[g].values())}
    visited=0
    for target in range(min(size,len(fresh_genres)),-1,-1):
        failed=set()
        def search(i,selected,artists,fresh):
            nonlocal visited
            if len(selected)==size:return selected if fresh>=target else None
            if visited>=max_states:return None
            visited+=1
            remaining=size-len(selected)
            if len(genres)-i<remaining or fresh+min(remaining,sum(g in fresh_genres for g in genres[i:]))<target:return None
            state=(i,remaining,frozenset(artists),fresh)
            if state in failed:return None
            for a,t in groups[genres[i]].items():
                if artists.intersection(a):continue
                result=search(i+1,selected+[t],artists.union(a),fresh+int(t['id'] in fresh_ids))
                if result:return result
            result=search(i+1,selected,artists,fresh)
            if result:return result
            failed.add(state)
            return None
        result=search(0,[],set(),0)
        if result:return result
        if visited>=max_states:break
    # Retain a feasible batch if optimization exhausts its budget.
    return diverse_sample(tracks,size,rng)

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

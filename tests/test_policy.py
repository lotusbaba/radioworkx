import random
import pytest
from app.policy import eligible, diverse_sample, WINDOW

def play(meta,starts=0,ends=100):
    return dict(metadata=meta,starts=starts,ends=ends)

@pytest.mark.parametrize('field,limit,consecutive', [('artists',4,3),('album_id',3,2),('compilation_id',4,3)])
def test_limits(metadata,field,limit,consecutive):
    candidate = {**metadata,'compilation_id':'comp-a'}
    def matching(i):
        m={**candidate,'artists':[f'a-{i}'],'album_id':f'al-{i}','compilation_id':f'c-{i}'}
        m[field]=candidate[field]
        return play(m)
    def other():
        return play({**candidate,'artists':['other'],'album_id':'other','compilation_id':'other'})
    history=[]
    for i in range(limit-1):
        history.extend([matching(i),other()])
    assert eligible(candidate,history,500)
    history.extend([matching(99),other()])
    assert not eligible(candidate,history,500)
    history=[matching(i) for i in range(consecutive-1)]
    assert eligible(candidate,history,500)
    history.append(matching(99))
    assert not eligible(candidate,history,500)

def test_rolling_window_includes_overlapping_play(metadata):
    history=[play({**metadata,'album_id':f'album-{i}'},0,100) for i in range(4)]
    history.append(play({**metadata,'artists':['other'],'album_id':'other'},200,300))
    assert not eligible(metadata,history,WINDOW+99)
    assert eligible(metadata,history,WINDOW+100)

def test_all_featured_artists_checked(metadata):
    candidate={**metadata,'artists':['new','featured']}
    history=[play({**metadata,'artists':['featured'],'album_id':f'a{i}'}) for i in range(3)]
    assert not eligible(candidate,history,200)

def test_consecutive_survives_silence(metadata):
    history=[play({**metadata,'album_id':str(i)}) for i in range(3)]
    assert not eligible(metadata,history,WINDOW*2)

def test_diverse_random_sample(metadata):
    pool=[{**metadata,'id':str(i),'artists':[f'artist-{i}'],'genre':f'genre-{i%10}'} for i in range(30)]
    one=diverse_sample(pool,rng=random.Random(1))
    two=diverse_sample(pool,rng=random.Random(2))
    assert len(one)==10 and len({t['genre'] for t in one})==10
    assert len({a for t in one for a in t['artists']})==10
    assert one!=two
    assert diverse_sample(pool[:9])==[]

def test_diverse_sample_backtracks(metadata):
    pool=[{**metadata,'id':'1','genre':'a','artists':['same']},
          {**metadata,'id':'2','genre':'a','artists':['different']},
          {**metadata,'id':'3','genre':'b','artists':['same']}]
    for seed in range(20):
        assert len(diverse_sample(pool,2,random.Random(seed)))==2


def test_many_equivalent_tracks_with_impossible_diversity(metadata):
    pool=[{**metadata,'id':f'{g}-{a}-{n}','genre':f'genre-{g}','artists':[f'artist-{a}']} for g in range(10) for a in range(9) for n in range(20)]
    assert diverse_sample(pool)==[]
    assert diverse_sample(pool,max_states=1)==[]

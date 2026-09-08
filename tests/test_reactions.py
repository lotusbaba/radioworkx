import json
import pytest
from app import db, events
from app.service import accept_reaction, process_reaction, ReactionCooldown

def event(id):
    with db.connect() as c:
        return json.loads(c.execute('SELECT metadata FROM reactions WHERE id=?',(id,)).fetchone()[0])

def boosts():
    with db.connect() as c:
        return c.execute("SELECT * FROM outbox WHERE queue='priority-downloads'").fetchall()

def test_twenty_one_and_redelivery(playing,isolated):
    play_id=playing()
    for i in range(20):
        e=event(accept_reaction(play_id,f'user-{i}','🔥',now=1001))
        events.project(process_reaction(e,now=1002))
    assert not boosts()
    e=event(accept_reaction(play_id,'user-20','🔥',now=1001))
    for _ in range(3):
        events.project(process_reaction(e,now=1002))
    assert len(boosts())==1
    assert events.ranking()==[{'genre':'jazz','reactions':21}]
    assert isolated.xlen('radio:events')==21
    body=json.loads(boosts()[0]['body'])
    assert body['artists']==['Artist A'] and body['genre']=='jazz'

def test_repeat_reactions_after_one_second_and_idempotent_retry(playing):
    play_id=playing()
    one=accept_reaction(play_id,'listener','🔥',now=1001,event_id='one')
    assert accept_reaction(play_id,'listener','🔥',now=1002,event_id='one')==one
    with pytest.raises(ReactionCooldown):accept_reaction(play_id,'listener','🔥',now=1001.999)
    with pytest.raises(ReactionCooldown):accept_reaction(play_id,'listener','❤️',now=1001.5)
    two=accept_reaction(play_id,'listener','🔥',now=1002)
    assert two!=one
    assert accept_reaction(play_id,'listener','❤️',now=1003) not in (one,two)

def test_expired_and_stale_rejected(playing):
    play_id=playing()
    with pytest.raises(ValueError):accept_reaction(play_id,'listener','🔥',now=1300)
    with pytest.raises(ValueError):accept_reaction('stale','listener','🔥',now=1001)

def test_delayed_consumer_ranks_without_boost(playing):
    play_id=playing()
    for i in range(21):
        e=event(accept_reaction(play_id,str(i),'🔥',now=1299))
        events.project(process_reaction(e,now=1301))
    assert not boosts()
    assert events.ranking()[0]['reactions']==21

def test_queue_metadata_is_not_authoritative(playing):
    id=accept_reaction(playing(),'listener','🔥',now=1001)
    e=event(id)
    e['genre']='forged'
    assert process_reaction(e,now=1002)['genre']=='jazz'


def test_fulfilled_genre_clears_once_and_late_delivery_does_not_restore_old_votes(playing):
    play=playing()
    first=event(accept_reaction(play,'one','🔥',now=1001))
    late=event(accept_reaction(play,'two','🔥',now=1002))
    events.project(first)
    assert events.fulfill_genre('job','track','jazz',now=1003)==1
    assert events.ranking()==[]
    events.project(late)
    assert events.ranking()==[]
    fresh=event(accept_reaction(play,'three','🔥',now=1004))
    events.project(fresh)
    assert events.ranking()==[{'genre':'jazz','reactions':1}]
    assert events.fulfill_genre('job','track','jazz',now=1005)==0
    events.project(first)
    assert events.ranking()==[{'genre':'jazz','reactions':1}]

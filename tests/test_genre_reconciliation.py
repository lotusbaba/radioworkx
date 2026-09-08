import json
from app import db,events


def test_completed_fetch_repair_preserves_new_votes_and_is_idempotent(metadata):
    with db.transaction() as c:
        c.execute("INSERT INTO tracks(id,metadata,status) VALUES('track-a',?,'ready')",(json.dumps(metadata),))
        db.emit(c,'boost:old','priority-downloads',{'kind':'boost','genre':'jazz'})
        c.execute("UPDATE outbox SET done=100 WHERE id='boost:old'")
        c.execute('INSERT INTO jobs VALUES(?,?,1)',('boost:old',json.dumps({'completed':['track-a']})))
        for n,at in enumerate([90,95,101,102]):
            c.execute("INSERT INTO reactions(id,play_id,listener,emoji,accepted,metadata) VALUES(?,'p','u','🔥',?,?)",(str(n),at,json.dumps(metadata)))
            events.project(dict(id=str(n),play_id='p',emoji='🔥',genre='jazz',artists=['A'],accepted=at))
    assert events.ranking()==[{'genre':'jazz','reactions':4}]
    assert events.reconcile_fulfilled_genres()==[{'genre':'jazz','remaining':2}]
    assert events.reconcile_fulfilled_genres()==[]
    events.project(dict(id='delayed',play_id='p',emoji='🔥',genre='jazz',artists=['A'],accepted=99))
    assert events.ranking()==[{'genre':'jazz','reactions':2}]
    events.project(dict(id='new',play_id='p',emoji='🔥',genre='jazz',artists=['A'],accepted=110))
    assert events.ranking()==[{'genre':'jazz','reactions':3}]

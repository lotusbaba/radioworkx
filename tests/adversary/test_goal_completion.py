import asyncio
from types import SimpleNamespace
from adversary.engines.custom import run


def test_verified_goal_stops_without_model_call():
    class Adapter:
        def __init__(self):
            self.events=[]
            self.recorder=SimpleNamespace(write=lambda *a,**k:self.events.append((a,k)))
            self.actions=[]
        async def observe(self):return None
        def goal_complete(self):return True
        async def execute(self,action):self.actions.append(action)
    a=Adapter()
    assert asyncio.run(run(a,object(),'goal',(),6))=='completed'
    assert a.actions[0].type=='done'
    assert a.events[0][1]['reason']=='goal_verified'

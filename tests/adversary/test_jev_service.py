import asyncio
import json
import httpx
import pytest
from adversary.inference.jev_service import JevDecisionService
from adversary.inference.openai import BudgetExhausted
from tests.adversary.test_laya import request


def test_jev_hierarchy_budget_and_metadata():
    calls=[]
    def handle(req):
        body=json.loads(req.content);calls.append(body)
        choices=body['questions']['action']['criteria'];selected=next(iter(choices))
        return httpx.Response(200,json={'model':'jev-test','answers':{'action':{
            'type':'choice','choice':selected,'confidence':.7,
            'probabilities':{k:float(k==selected) for k in choices}}},'usage':{'input_tokens':10}})
    async def check():
        service=JevDecisionService('synthetic',max_calls=1,transport=httpx.MockTransport(handle))
        try:
            assert await service.choose(request(),[])=='a0'
            stage=service.take_metrics('r1')['stages'][0]
            assert stage['provider_confidence']==.7 and stage['answer_confidence']==1
            assert stage['model']=='jev-test'
            assert await service.choose(request(1),[])=='a0'
            assert service.take_metrics('r1')['stages'][0]['selection']=='deterministic'
            with pytest.raises(BudgetExhausted):await service.choose(request(),[])
            assert len(calls)==1
        finally:await service.aclose()
    asyncio.run(check())

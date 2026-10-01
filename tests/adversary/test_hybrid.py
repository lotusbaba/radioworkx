import asyncio
import pytest
from adversary.inference.hybrid import HybridDecisionService, RoutingBlocked
from adversary.inference.openai import BudgetExhausted
from adversary.models.decision import DecisionRequest
from tests.adversary.test_router import request_data


class Backend:
    model = 'fake'
    def __init__(self, limit=4):
        self.calls, self.max_calls = 0, limit
    async def choose(self, request, history):
        self.calls += 1
        return request.candidates[0].id


def request(**changes):
    data = request_data(**changes)
    data['agent']['strategy'] = 'custom-hybrid'
    return DecisionRequest(**data)


@pytest.mark.parametrize('history,coverage,expected', [
    ([], True, 'primary'), (['Reload','Reload'], True, 'generative'),
    ([], False, 'generative')])
def test_routing_and_evidence(history, coverage, expected):
    primary, fallback = Backend(), Backend()
    service = HybridDecisionService(primary, fallback)
    r = request(coverage={'complete_for_decision': coverage})
    assert asyncio.run(service.choose(r, history)) == 'empty-search'
    assert service.take_metrics(r.id)['backend'] == expected
    assert service.calls == 1
    assert (primary.calls, fallback.calls) == ((1,0) if expected=='primary' else (0,1))


def test_no_candidates_never_dispatches():
    service = HybridDecisionService(Backend(), Backend())
    with pytest.raises(RoutingBlocked):
        asyncio.run(service.choose(request(candidates=[]), []))
    assert service.calls == 0


def test_fallback_budget_is_shared_and_atomic():
    service = HybridDecisionService(Backend(), Backend(limit=1))
    async def run():
        r = request(coverage={})
        results = await asyncio.gather(service.choose(r,[]),service.choose(r,[]),return_exceptions=True)
        assert sum(isinstance(x, BudgetExhausted) for x in results)==1
    asyncio.run(run())
    assert service.calls==1


def test_many_candidates_use_fallback():
    service=HybridDecisionService(Backend(), Backend())
    asyncio.run(service.choose(request(candidates=[dict(id=f'a{i}',description='Reload',action={'type':'reload'}) for i in range(11)]),[]))
    assert service.fallback.calls==1


def test_real_openai_adapter_validates_structured_fallback():
    import json
    import httpx
    from adversary.inference.openai import DecisionService
    def response(http_request):
        payload=json.loads(http_request.content)
        assert payload['store'] is False
        assert payload['text']['format']['schema']['properties']['candidate_id']['enum']==['empty-search']
        return httpx.Response(200,json={'status':'completed','output':[{'type':'message',
            'content':[{'type':'output_text','text':'{"candidate_id":"empty-search"}'}]}]})
    fallback=DecisionService('synthetic-key','fake',1,transport=httpx.MockTransport(response))
    service=HybridDecisionService(Backend(),fallback)
    assert asyncio.run(service.choose(request(coverage={}),[]))=='empty-search'
    assert service.take_metrics('request-a')['stages'][0]['provider']=='openai'
    assert service.calls==1


def test_invalid_fallback_selection_never_reaches_executor():
    class Invalid(Backend):
        async def choose(self,request,history):return 'invented-action'
    service=HybridDecisionService(Backend(),Invalid())
    with pytest.raises(ValueError,match='unknown candidate'):
        asyncio.run(service.choose(request(coverage={}),[]))

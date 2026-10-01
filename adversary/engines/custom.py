from adversary.models.decision import AgentContext, DecisionRequest
from adversary.models.action import DoneAction


async def run(adapter, service, goal, values, max_steps):
    history = []
    for _ in range(max_steps):
        observation = await adapter.observe()
        goal_complete = getattr(adapter, 'goal_complete', None)
        if goal_complete is not None and goal_complete():
            adapter.recorder.write('completion', selection='deterministic', reason='goal_verified')
            await adapter.execute(DoneAction(reason='Framework verified goal completion'))
            return 'completed'
        candidates = adapter.candidates(values)
        # A bounded strategy may prove completion independently. Until then,
        # finishing is not a legal action; never trust a model's success claim.
        if goal_complete is not None and not goal_complete():
            candidates = tuple(c for c in candidates if not isinstance(c.action, DoneAction))
        request = DecisionRequest(id=f'{adapter.session_id}-request-{adapter.step}',
            agent=AgentContext(session_id=adapter.session_id, strategy=getattr(service, 'strategy', 'custom-laya'), goal=goal),
            observation=observation, candidates=candidates)
        cid = await service.choose(request, history)
        candidate = next(c for c in request.candidates if c.id == cid)
        adapter.recorder.write('decision', engine=getattr(service, 'strategy', 'custom-laya'), request_id=request.id,
                               observation_id=observation.id, candidate_id=cid,
                               inference=service.take_metrics(request.id))
        await adapter.execute(candidate.action)
        history.append(candidate.description)
        if adapter.done:
            return 'completed'
    return 'step_limit'

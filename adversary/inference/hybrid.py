"""Explicit, budgeted generative reasoning over observed browser candidates."""
import asyncio
from adversary.inference.router import DecisionRouter
from adversary.inference.openai import BudgetExhausted
from adversary.models.decision import (CandidateCoverage, DecisionBudget, DecisionPath,
    ModelAvailability, RouterConfig, StrategyRouting)


class RoutingBlocked(RuntimeError):
    pass


class HybridDecisionService:
    strategy = 'custom-hybrid'

    def __init__(self, primary, fallback, max_candidates=10):
        self.primary, self.fallback = primary, fallback
        self.model = primary.model
        self.lock = asyncio.Lock()
        self.metrics = {}
        self.router = DecisionRouter(RouterConfig(max_candidates=max_candidates,
            allow_hosted_llm=True, strategies=(StrategyRouting(strategy=self.strategy,
                bounded_operations=frozenset({'click', 'fill', 'select', 'key_press',
                    'reload', 'wait', 'scroll', 'done', 'navigate'})),)))

    @property
    def calls(self):
        return self.primary.calls + self.fallback.calls

    @property
    def call_counts(self):
        return {'primary': self.primary.calls, 'generative': self.fallback.calls}

    async def choose(self, request, history):
        async with self.lock:
            # Repeating the same action twice is evidence that routine selection
            # needs reasoning. No confidence threshold assumes calibrated scores.
            stalled = len(history) >= 2 and history[-1] == history[-2]
            if stalled:
                request = request.model_copy(update={'coverage': CandidateCoverage(complete_for_decision=False)})
            route = self.router.route(request, ModelAvailability(laya_available=True,
                llm_available=True, llm_is_local=False), DecisionBudget(
                    # The enclosing engine and asyncio timeout enforce these
                    # session budgets; this service only reserves model calls.
                    remaining_steps=1, remaining_ms=1,
                    laya_calls_remaining=max(0, self.primary.max_calls-self.primary.calls),
                    llm_calls_remaining=max(0, self.fallback.max_calls-self.fallback.calls)))
            self.metrics[request.id] = {'route': route.model_dump(mode='json'), 'stalled': stalled}
            if route.path == DecisionPath.BLOCKED:
                if 'budget' in route.blocked_by.value:
                    raise BudgetExhausted(route.blocked_by.value)
                raise RoutingBlocked(route.blocked_by.value)
            if not request.candidates:
                raise RoutingBlocked('No executable observed candidates; arbitrary actions are disabled')
            backend = self.primary if route.path == DecisionPath.LAYA else self.fallback
            selected = await backend.choose(request, history)
            if selected not in {c.id for c in request.candidates}:
                raise ValueError('Backend returned an unknown candidate')
            detail = backend.take_metrics(request.id) if hasattr(backend, 'take_metrics') else {
                'stages': [{'selection': 'model', 'provider': 'openai',
                    'choices': {c.id:c.description for c in request.candidates}, 'selected': selected}]}
            self.metrics[request.id].update(detail)
            self.metrics[request.id]['backend'] = 'primary' if backend is self.primary else 'generative'
            return selected

    def take_metrics(self, request_id):
        return self.metrics.pop(request_id, {})

    async def aclose(self):
        for backend in (self.primary, self.fallback):
            if hasattr(backend, 'aclose'):
                await backend.aclose()

"""Pure routing rules for the proposed hybrid engine, not an execution policy."""

from adversary.models.decision import (
    BlockReason, DecisionBudget, DecisionPath, DecisionRequest, ModelAvailability,
    RouteDecision, RouteReason, RouterConfig,
)


class DecisionRouter:
    def __init__(self, config: RouterConfig):
        self.config = config

    def route(
        self,
        request: DecisionRequest,
        availability: ModelAvailability,
        budget: DecisionBudget,
    ) -> RouteDecision:
        """Choose a backend without I/O, inference, execution or budget mutation.

        Malformed/stale candidates fail request validation, rather than becoming
        a reason to send invalid input to another model. Backend unavailability
        blocks the chosen route; implicit cross-backend fallback is not supported.
        """
        def result(path, reason, blocked_by=None):
            return RouteDecision(
                request_id=request.id,
                session_id=request.agent.session_id,
                observation_id=request.observation.id,
                step=request.observation.step,
                path=path, reason=reason, blocked_by=blocked_by,
            )

        if budget.remaining_steps == 0 or budget.remaining_ms == 0:
            return result(DecisionPath.BLOCKED, RouteReason.SESSION_BUDGET_EXHAUSTED,
                          BlockReason.SESSION_BUDGET_EXHAUSTED)

        strategy = next((s for s in self.config.strategies
                         if s.strategy == request.agent.strategy), None)
        if strategy is None:
            return result(DecisionPath.BLOCKED, RouteReason.STRATEGY_NOT_CONFIGURED,
                          BlockReason.STRATEGY_NOT_CONFIGURED)

        if not request.candidates:
            reason = RouteReason.NO_CANDIDATES
        elif len(request.candidates) > self.config.max_candidates:
            reason = RouteReason.TOO_MANY_CANDIDATES
        elif request.coverage.requires_unknown_widget:
            reason = RouteReason.UNKNOWN_WIDGET_REQUIRED
        elif not request.coverage.complete_for_decision:
            reason = RouteReason.INCOMPLETE_COVERAGE
        elif any(c.action.type not in strategy.bounded_operations for c in request.candidates):
            reason = RouteReason.OPERATION_NOT_COVERED
        else:
            reason = RouteReason.BOUNDED_CHOICES

        if reason == RouteReason.BOUNDED_CHOICES:
            if not availability.laya_available:
                return result(DecisionPath.BLOCKED, reason, BlockReason.LAYA_UNAVAILABLE)
            if budget.laya_calls_remaining == 0:
                return result(DecisionPath.BLOCKED, reason, BlockReason.LAYA_BUDGET_EXHAUSTED)
            return result(DecisionPath.LAYA, reason)

        if not availability.llm_available:
            return result(DecisionPath.BLOCKED, reason, BlockReason.LLM_UNAVAILABLE)
        if not availability.llm_is_local and not self.config.allow_hosted_llm:
            return result(DecisionPath.BLOCKED, reason, BlockReason.HOSTED_LLM_DISABLED)
        if budget.llm_calls_remaining == 0:
            return result(DecisionPath.BLOCKED, reason, BlockReason.LLM_CALL_BUDGET_EXHAUSTED)
        if budget.llm_call_cost > budget.llm_cost_remaining:
            return result(DecisionPath.BLOCKED, reason, BlockReason.LLM_COST_BUDGET_EXHAUSTED)
        return result(DecisionPath.LLM, reason)

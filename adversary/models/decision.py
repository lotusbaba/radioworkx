"""Requests, route outcomes and bounded model decisions with session identity."""

from enum import Enum
from typing import Annotated

from pydantic import Field, StrictBool, model_validator

from .action import ActionType, BrowserAction, CandidateAction, TargetAction
from .base import Contract, Identifier, Milliseconds, NonNegativeInt, ShortText
from .observation import BrowserObservation


class AgentContext(Contract):
    session_id: Identifier
    strategy: Identifier
    goal: Annotated[str, Field(min_length=1, max_length=4096)]


class CandidateCoverage(Contract):
    # The deterministic builder supplies these, never the model. Defaults do not
    # claim the builder has enumerated a sufficient set of choices.
    complete_for_decision: StrictBool = False
    requires_unknown_widget: StrictBool = False


class DecisionRequest(Contract):
    id: Identifier
    agent: AgentContext
    observation: BrowserObservation
    candidates: Annotated[tuple[CandidateAction, ...], Field(max_length=500)] = ()
    coverage: CandidateCoverage = CandidateCoverage()

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.agent.session_id != self.observation.session_id:
            raise ValueError("observation belongs to a different session")
        ids = [candidate.id for candidate in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate candidate IDs")
        elements = {e.locator.element_id: e.locator for e in self.observation.elements}
        for candidate in self.candidates:
            if isinstance(candidate.action, TargetAction):
                target = candidate.action.target
                if target.observation_id != self.observation.id:
                    raise ValueError("candidate target belongs to a stale observation")
                if elements.get(target.element_id) != target:
                    raise ValueError("candidate target is not in the observation snapshot")
        return self


class DecisionPath(str, Enum):
    LAYA = "laya"
    LLM = "llm"
    BLOCKED = "blocked"


class RouteReason(str, Enum):
    BOUNDED_CHOICES = "bounded_choices"
    NO_CANDIDATES = "no_candidates"
    TOO_MANY_CANDIDATES = "too_many_candidates"
    UNKNOWN_WIDGET_REQUIRED = "unknown_widget_required"
    INCOMPLETE_COVERAGE = "incomplete_coverage"
    OPERATION_NOT_COVERED = "operation_not_covered"
    STRATEGY_NOT_CONFIGURED = "strategy_not_configured"
    SESSION_BUDGET_EXHAUSTED = "session_budget_exhausted"


class BlockReason(str, Enum):
    SESSION_BUDGET_EXHAUSTED = "session_budget_exhausted"
    STRATEGY_NOT_CONFIGURED = "strategy_not_configured"
    LAYA_UNAVAILABLE = "laya_unavailable"
    LAYA_BUDGET_EXHAUSTED = "laya_budget_exhausted"
    LLM_UNAVAILABLE = "llm_unavailable"
    HOSTED_LLM_DISABLED = "hosted_llm_disabled"
    LLM_CALL_BUDGET_EXHAUSTED = "llm_call_budget_exhausted"
    LLM_COST_BUDGET_EXHAUSTED = "llm_cost_budget_exhausted"


class RouteDecision(Contract):
    request_id: Identifier
    session_id: Identifier
    observation_id: Identifier
    step: NonNegativeInt
    path: DecisionPath
    reason: RouteReason
    blocked_by: BlockReason | None = None

    @model_validator(mode="after")
    def blocked_reason_required(self):
        if (self.path == DecisionPath.BLOCKED) != (self.blocked_by is not None):
            raise ValueError("blocked_by is required only for blocked routes")
        return self


class StrategyRouting(Contract):
    strategy: Identifier
    bounded_operations: frozenset[ActionType]


class RouterConfig(Contract):
    max_candidates: Annotated[int, Field(strict=True, ge=1, le=20)] = 10
    strategies: tuple[StrategyRouting, ...]
    allow_hosted_llm: StrictBool = False

    @model_validator(mode="after")
    def unique_strategies(self):
        ids = [strategy.strategy for strategy in self.strategies]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate strategy routing configuration")
        return self


class ModelAvailability(Contract):
    laya_available: StrictBool = False
    llm_available: StrictBool = False
    llm_is_local: StrictBool = True


class DecisionBudget(Contract):
    # Remaining budgets are explicit snapshots. Router does not reserve/spend
    # them; the future service must atomically reserve before dispatch.
    remaining_steps: NonNegativeInt
    remaining_ms: Milliseconds
    laya_calls_remaining: NonNegativeInt = 0
    llm_calls_remaining: NonNegativeInt = 0
    llm_cost_remaining: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] = 0
    # A conservative reservation, supplied by provider configuration. Zero is
    # suitable for a free local model; never inferred from model output.
    llm_call_cost: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)] = 0


class Decision(Contract):
    request_id: Identifier
    session_id: Identifier
    observation_id: Identifier
    step: NonNegativeInt
    engine: Annotated[str, Field(pattern=r"^(scripted|laya)$")]
    candidate_id: Identifier
    queue_ms: Milliseconds = 0
    inference_ms: Milliseconds = 0
    total_ms: Milliseconds = 0

    def resolve(self, request: DecisionRequest) -> BrowserAction:
        """Resolve labels only against their original immutable request snapshot."""
        if (self.request_id, self.session_id, self.observation_id, self.step) != (
            request.id, request.agent.session_id, request.observation.id,
            request.observation.step,
        ):
            raise ValueError("decision does not match request/session/observation/step")
        for candidate in request.candidates:
            if candidate.id == self.candidate_id:
                return candidate.action
        raise ValueError("decision selected an unknown candidate")

"""Run with python -m adversary.inference.demo; no browser, network or model."""

from adversary.inference.router import DecisionRouter
from adversary.models.action import ActionType, BackAction, CandidateAction
from adversary.models.decision import (
    AgentContext, CandidateCoverage, DecisionBudget, DecisionRequest,
    ModelAvailability, RouterConfig, StrategyRouting,
)
from adversary.models.observation import BrowserObservation


def main():
    router = DecisionRouter(RouterConfig(strategies=(StrategyRouting(
        strategy="navigation_abuse", bounded_operations=frozenset({ActionType.BACK}),
    ),)))
    agent = AgentContext(session_id="agent-a", strategy="navigation_abuse",
                         goal="Explore navigation transitions")
    observation = BrowserObservation(id="obs-a", session_id=agent.session_id,
                                     step=0, url="http://127.0.0.1:8011/artists")
    budget = DecisionBudget(remaining_steps=5, remaining_ms=1000,
                            laya_calls_remaining=5, llm_calls_remaining=5)
    candidate = CandidateAction(id="go-back", description="Return to previous page",
                                action=BackAction())

    # Availability is illustrative input, not a claim that either model is loaded.
    for name, candidates, coverage, available in (
        ("bounded", (candidate,), True, True),
        ("uncovered", (), False, True),
        ("blocked", (), False, False),
    ):
        request = DecisionRequest(
            id=name, agent=agent, observation=observation, candidates=candidates,
            coverage=CandidateCoverage(complete_for_decision=coverage),
        )
        result = router.route(request, ModelAvailability(
            laya_available=available, llm_available=available,
        ), budget)
        print(result.model_dump_json())


if __name__ == "__main__":
    main()

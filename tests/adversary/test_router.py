import pytest
from pydantic import ValidationError

from adversary.inference.router import DecisionRouter
from adversary.models.action import ActionType
from adversary.models.decision import (
    BlockReason, Decision, DecisionBudget, DecisionPath, DecisionRequest,
    ModelAvailability, RouteDecision, RouteReason, RouterConfig,
)


def request_data(**changes):
    target = dict(observation_id="obs-a", element_id="search", alternatives=[
        dict(kind="role", value="textbox", accessible_name="Search"),
    ])
    data = dict(
        id="request-a",
        agent=dict(session_id="agent-a", strategy="malformed_input", goal="Test search"),
        observation=dict(id="obs-a", session_id="agent-a", step=3,
                         url="http://127.0.0.1:8011/artists",
                         elements=[dict(locator=target)]),
        candidates=[dict(id="empty-search", description="Fill empty search",
                         action=dict(type="fill", target=target, value=""))],
        coverage=dict(complete_for_decision=True),
    )
    data.update(changes)
    return data


def config(**changes):
    data = dict(strategies=[dict(strategy="malformed_input",
                                bounded_operations=[ActionType.FILL, ActionType.BACK])])
    data.update(changes)
    return RouterConfig(**data)


def budget(**changes):
    data = dict(remaining_steps=10, remaining_ms=1000, laya_calls_remaining=10,
                llm_calls_remaining=10, llm_cost_remaining=1, llm_call_cost=0.1)
    data.update(changes)
    return DecisionBudget(**data)


def route(data=None, *, models=None, limits=None, settings=None):
    return DecisionRouter(settings or config()).route(
        DecisionRequest(**(data if data is not None else request_data())),
        models or ModelAvailability(laya_available=True, llm_available=True),
        limits or budget(),
    )


def test_complete_empty_string_action_routes_to_laya_with_request_identity():
    result = route()
    assert result.path == DecisionPath.LAYA
    assert result.reason == RouteReason.BOUNDED_CHOICES
    assert (result.request_id, result.session_id, result.observation_id, result.step) == (
        "request-a", "agent-a", "obs-a", 3,
    )
    assert RouteDecision.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(("changes", "reason"), [
    ({"candidates": []}, RouteReason.NO_CANDIDATES),
    ({"candidates": [dict(id=f"back-{i}", description="Back", action=dict(type="back"))
                     for i in range(11)]}, RouteReason.TOO_MANY_CANDIDATES),
    ({"coverage": dict(complete_for_decision=True, requires_unknown_widget=True)},
     RouteReason.UNKNOWN_WIDGET_REQUIRED),
    ({"coverage": {}}, RouteReason.INCOMPLETE_COVERAGE),
    ({"candidates": [dict(id="reload", description="Reload", action=dict(type="reload"))]},
     RouteReason.OPERATION_NOT_COVERED),
])
def test_uncovered_decisions_require_llm(changes, reason):
    result = route(request_data(**changes))
    assert result.path == DecisionPath.LLM
    assert result.reason == reason


def test_candidate_limit_is_inclusive_and_configurable():
    data = request_data(candidates=[dict(id=f"back-{i}", description="Back",
                                        action=dict(type="back")) for i in range(10)])
    assert route(data).path == DecisionPath.LAYA
    assert route(data, settings=config(max_candidates=9)).path == DecisionPath.LLM


@pytest.mark.parametrize(("models", "limits", "expected"), [
    (dict(laya_available=False, llm_available=True), {}, BlockReason.LAYA_UNAVAILABLE),
    (dict(laya_available=True, llm_available=True), dict(laya_calls_remaining=0),
     BlockReason.LAYA_BUDGET_EXHAUSTED),
])
def test_unavailable_laya_does_not_silently_fallback(models, limits, expected):
    result = route(models=ModelAvailability(**models), limits=budget(**limits))
    assert result.path == DecisionPath.BLOCKED
    assert result.reason == RouteReason.BOUNDED_CHOICES
    assert result.blocked_by == expected


@pytest.mark.parametrize(("models", "limits", "expected"), [
    (dict(llm_available=False), {}, BlockReason.LLM_UNAVAILABLE),
    (dict(llm_available=True, llm_is_local=False), {}, BlockReason.HOSTED_LLM_DISABLED),
    (dict(llm_available=True), dict(llm_calls_remaining=0), BlockReason.LLM_CALL_BUDGET_EXHAUSTED),
    (dict(llm_available=True), dict(llm_cost_remaining=0.09), BlockReason.LLM_COST_BUDGET_EXHAUSTED),
])
def test_unavailable_or_exhausted_llm_blocks_without_using_laya(models, limits, expected):
    result = route(request_data(candidates=[]), models=ModelAvailability(laya_available=True, **models),
                   limits=budget(**limits))
    assert result.path == DecisionPath.BLOCKED
    assert result.reason == RouteReason.NO_CANDIDATES
    assert result.blocked_by == expected


def test_hosted_backend_requires_explicit_opt_in_and_sufficient_budget():
    result = route(request_data(candidates=[]), settings=config(allow_hosted_llm=True),
                   models=ModelAvailability(llm_available=True, llm_is_local=False),
                   limits=budget(llm_cost_remaining=0.1))
    assert result.path == DecisionPath.LLM


def test_free_local_model_requires_calls_but_no_cost_budget():
    assert route(request_data(candidates=[]),
                 limits=budget(llm_cost_remaining=0, llm_call_cost=0)).path == DecisionPath.LLM


@pytest.mark.parametrize("limits", [dict(remaining_steps=0), dict(remaining_ms=0)])
def test_expired_session_blocks_both_paths(limits):
    for data in (request_data(), request_data(candidates=[])):
        result = route(data, limits=budget(**limits))
        assert result.path == DecisionPath.BLOCKED
        assert result.blocked_by == BlockReason.SESSION_BUDGET_EXHAUSTED


def test_unknown_strategy_is_configuration_error_not_llm_escalation():
    result = route(settings=config(strategies=[]))
    assert result.path == DecisionPath.BLOCKED
    assert result.blocked_by == BlockReason.STRATEGY_NOT_CONFIGURED


def test_router_does_not_claim_policy_permission_or_mutate_budgets():
    # Model routing must not be mistaken for navigation authorization. A later
    # ActionPolicy is responsible for rejecting this production URL.
    data = request_data(candidates=[dict(id="navigate", description="Navigate",
        action=dict(type="navigate", url="https://radioworkx.tail060b33.ts.net/"))])
    settings = config(strategies=[dict(strategy="malformed_input", bounded_operations=["navigate"])])
    limits = budget()
    before = limits.model_dump_json()
    assert route(data, settings=settings, limits=limits).path == DecisionPath.LAYA
    assert limits.model_dump_json() == before


@pytest.mark.parametrize("mutation", ["missing_value", "missing_target", "duplicate_id",
                                     "stale_target", "unknown_target", "different_locator",
                                     "wrong_session"])
def test_invalid_request_is_rejected_not_escalated(mutation):
    data = request_data()
    action = data["candidates"][0]["action"]
    if mutation == "missing_value":
        del action["value"]
    elif mutation == "missing_target":
        del action["target"]
    elif mutation == "duplicate_id":
        data["candidates"] *= 2
    elif mutation == "stale_target":
        action["target"] = {**action["target"], "observation_id": "previous"}
    elif mutation == "unknown_target":
        action["target"] = {**action["target"], "element_id": "unknown"}
    elif mutation == "different_locator":
        action["target"] = {**action["target"], "alternatives": [dict(kind="css", value="body")]}
    elif mutation == "wrong_session":
        data["agent"]["session_id"] = "other-agent"
    with pytest.raises(ValidationError):
        route(data)


def decision_data(**changes):
    data = dict(request_id="request-a", session_id="agent-a", observation_id="obs-a",
                step=3, engine="laya", candidate_id="empty-search")
    data.update(changes)
    return data


def test_decision_resolves_only_original_candidate_and_round_trips():
    request = DecisionRequest(**request_data())
    request = DecisionRequest.model_validate_json(request.model_dump_json())
    decision = Decision(**decision_data())
    assert decision.resolve(request) == request.candidates[0].action
    assert decision.resolve(request).value == ""


@pytest.mark.parametrize("changes", [dict(request_id="other-request"), dict(session_id="agent-b"),
    dict(observation_id="obs-b"), dict(step=4), dict(candidate_id="invented")])
def test_response_cannot_cross_session_or_snapshot(changes):
    with pytest.raises(ValueError):
        Decision(**decision_data(**changes)).resolve(DecisionRequest(**request_data()))


@pytest.mark.parametrize("changes", [dict(max_candidates=0), dict(max_candidates=21),
    dict(max_candidates=True), dict(max_candidates="10"),
    dict(strategies=[dict(strategy="x", bounded_operations=[])] * 2)])
def test_invalid_router_configuration(changes):
    with pytest.raises(ValidationError):
        config(**changes)


@pytest.mark.parametrize("changes", [dict(remaining_ms=float("nan")), dict(remaining_ms=float("inf")),
    dict(remaining_steps=-1), dict(llm_cost_remaining=-1), dict(llm_call_cost=float("inf")),
    dict(llm_calls_remaining=True)])
def test_invalid_budget(changes):
    with pytest.raises(ValidationError):
        budget(**changes)


def test_snapshot_cannot_be_mutated_after_routing():
    request = DecisionRequest(**request_data())
    with pytest.raises(ValidationError):
        request.candidates[0].action.value = "changed"
    assert isinstance(request.candidates, tuple)
    assert isinstance(request.observation.elements, tuple)


@pytest.mark.parametrize("field", ["laya_available", "llm_available", "llm_is_local"])
def test_availability_requires_actual_booleans(field):
    with pytest.raises(ValidationError):
        ModelAvailability(**{field: "false"})


def test_empty_strategy_allowlist_never_routes_to_laya():
    settings = config(strategies=[dict(strategy="malformed_input", bounded_operations=[])])
    assert route(settings=settings).reason == RouteReason.OPERATION_NOT_COVERED


def test_extra_unknown_widget_flag_does_not_silently_change_routing():
    # The only supported flag concerns the current decision, not the whole page.
    with pytest.raises(ValidationError):
        route(request_data(coverage=dict(complete_for_decision=True, has_unknown_widget=True)))


def test_duplicate_and_foreign_observed_elements_rejected():
    data = request_data()
    data["observation"]["elements"] *= 2
    with pytest.raises(ValidationError):
        DecisionRequest(**data)
    data = request_data()
    data["observation"]["elements"][0]["locator"]["observation_id"] = "other"
    with pytest.raises(ValidationError):
        DecisionRequest(**data)


def test_demo_reports_three_paths_without_invoking_models(capsys):
    from adversary.inference.demo import main

    main()
    routes = [RouteDecision.model_validate_json(line) for line in capsys.readouterr().out.splitlines()]
    assert [result.path for result in routes] == [DecisionPath.LAYA, DecisionPath.LLM, DecisionPath.BLOCKED]

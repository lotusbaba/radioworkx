import subprocess
import sys

import pytest
from pydantic import ValidationError

from adversary.models.action import browser_action_adapter


TARGET = dict(observation_id="obs-1", element_id="field", alternatives=[
    dict(kind="test_id", value="search"),
    dict(kind="role", value="textbox", accessible_name="Search"),
    dict(kind="label", value="Search"),
    dict(kind="text", value="Search"),
    dict(kind="css", value="#search"),
])


@pytest.mark.parametrize("action", [
    dict(type="navigate", url="/artists"),
    dict(type="click", target=TARGET),
    dict(type="fill", target=TARGET, value=" \n雪🙂"),
    dict(type="fill", target=TARGET, value=""),
    dict(type="select", target=TARGET, values=[""]),
    dict(type="hover", target=TARGET),
    dict(type="scroll", delta_y=-300),
    dict(type="back"), dict(type="forward"), dict(type="reload"),
    dict(type="wait", duration_ms=250),
    dict(type="key_press", target=TARGET, key="Enter"),
    dict(type="submit", target=TARGET),
    dict(type="done", reason="Goal reached"),
])
def test_actions_preserve_exact_parameters_and_ordered_locators(action):
    validated = browser_action_adapter.validate_python(action)
    encoded = browser_action_adapter.dump_json(validated)
    decoded = browser_action_adapter.validate_json(encoded)
    assert decoded == validated
    if "target" in action:
        assert [loc.kind.value for loc in decoded.target.alternatives] == [
            "test_id", "role", "label", "text", "css",
        ]


@pytest.mark.parametrize("action", [
    dict(type="evaluate", script="alert(1)"),
    dict(type="click"),
    dict(type="fill", target=TARGET),
    dict(type="fill", target=TARGET, value=None),
    dict(type="fill", target=TARGET, value=123),
    dict(type="select", target=TARGET, values=[]),
    dict(type="scroll", delta_y=0),
    dict(type="scroll", delta_y=float("nan")),
    dict(type="scroll", delta_y=True),
    dict(type="navigate", url=""),
    dict(type="wait", duration_ms=-1),
    dict(type="wait", duration_ms=1001, timeout_ms=1000),
    dict(type="back", target=TARGET),
    dict(type="back", script="arbitrary code"),
    dict(type="back", schema_version=2),
    dict(type="back", schema_version=True),
    dict(type="back", schema_version=1.0),
    dict(type="back", timeout_ms=0),
    dict(type="done", reason=""),
    dict(type="click", target={**TARGET, "alternatives": []}),
    dict(type="click", target={**TARGET, "alternatives": [dict(kind="role", value="button")]}),
    dict(type="click", target={**TARGET, "alternatives": [dict(kind="css", value=" ")]}),
])
def test_invalid_actions_fail_at_the_contract_boundary(action):
    with pytest.raises(ValidationError):
        browser_action_adapter.validate_python(action)


def test_domain_imports_do_not_load_browser_model_or_radio_runtime():
    result = subprocess.run([sys.executable, "-c", """
import sys
import adversary.models.action
import adversary.models.observation
import adversary.models.decision
import adversary.inference.router
for name in ('playwright', 'browser_use', 'laya', 'torch', 'app'):
    assert not any(m == name or m.startswith(name + '.') for m in sys.modules), name
"""], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

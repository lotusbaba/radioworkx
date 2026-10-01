"""Concrete actions; a model chooses data, never executable Python/JavaScript."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from .base import Contract, Identifier, ShortText


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    HOVER = "hover"
    SCROLL = "scroll"
    BACK = "back"
    FORWARD = "forward"
    RELOAD = "reload"
    WAIT = "wait"
    KEY_PRESS = "key_press"
    SUBMIT = "submit"
    DONE = "done"


class LocatorKind(str, Enum):
    TEST_ID = "test_id"
    ROLE = "role"
    LABEL = "label"
    TEXT = "text"
    CSS = "css"


class LocatorAlternative(Contract):
    kind: LocatorKind
    value: ShortText
    accessible_name: ShortText | None = None
    exact: bool = True

    @model_validator(mode="after")
    def role_requires_name(self):
        if self.kind == LocatorKind.ROLE and self.accessible_name is None:
            raise ValueError("role locator requires an accessible name")
        if self.kind != LocatorKind.ROLE and self.accessible_name is not None:
            raise ValueError("accessible_name belongs only to role locators")
        if not self.value.strip():
            raise ValueError("locator value must not be blank")
        return self


class ElementLocator(Contract):
    observation_id: Identifier
    element_id: Identifier
    # Ordering is explicit and retained verbatim for replay.
    alternatives: Annotated[tuple[LocatorAlternative, ...], Field(min_length=1, max_length=5)]


class Action(Contract):
    timeout_ms: Annotated[int, Field(strict=True, ge=1, le=120_000)] = 10_000


class TargetAction(Action):
    target: ElementLocator


class NavigateAction(Action):
    type: Literal[ActionType.NAVIGATE] = ActionType.NAVIGATE
    # Relative paths and URLs are both representable. The execution policy must
    # resolve them against the QA origin and enforce redirect restrictions.
    url: Annotated[str, Field(min_length=1, max_length=4096)]


class ClickAction(TargetAction):
    type: Literal[ActionType.CLICK] = ActionType.CLICK


class FillAction(TargetAction):
    type: Literal[ActionType.FILL] = ActionType.FILL
    # Empty is intentional for boundary tests. Missing/None is not a value.
    value: Annotated[str, Field(max_length=65_536)]


class SelectAction(TargetAction):
    type: Literal[ActionType.SELECT] = ActionType.SELECT
    values: Annotated[tuple[Annotated[str, Field(max_length=4096)], ...], Field(min_length=1, max_length=100)]


class HoverAction(TargetAction):
    type: Literal[ActionType.HOVER] = ActionType.HOVER


class ScrollAction(Action):
    type: Literal[ActionType.SCROLL] = ActionType.SCROLL
    delta_x: Annotated[int, Field(strict=True, ge=-10_000, le=10_000)] = 0
    delta_y: Annotated[int, Field(strict=True, ge=-10_000, le=10_000)]

    @model_validator(mode="after")
    def nonzero_scroll(self):
        if self.delta_x == self.delta_y == 0:
            raise ValueError("scroll must move on at least one axis")
        return self


class BackAction(Action):
    type: Literal[ActionType.BACK] = ActionType.BACK


class ForwardAction(Action):
    type: Literal[ActionType.FORWARD] = ActionType.FORWARD


class ReloadAction(Action):
    type: Literal[ActionType.RELOAD] = ActionType.RELOAD


class WaitAction(Action):
    type: Literal[ActionType.WAIT] = ActionType.WAIT
    duration_ms: Annotated[int, Field(strict=True, ge=1, le=30_000)]

    @model_validator(mode="after")
    def wait_fits_timeout(self):
        if self.duration_ms > self.timeout_ms:
            raise ValueError("wait duration exceeds action timeout")
        return self


class KeyPressAction(TargetAction):
    type: Literal[ActionType.KEY_PRESS] = ActionType.KEY_PRESS
    key: ShortText


class SubmitAction(TargetAction):
    type: Literal[ActionType.SUBMIT] = ActionType.SUBMIT


class DoneAction(Action):
    type: Literal[ActionType.DONE] = ActionType.DONE
    reason: ShortText


BrowserAction = Annotated[
    NavigateAction | ClickAction | FillAction | SelectAction | HoverAction
    | ScrollAction | BackAction | ForwardAction | ReloadAction | WaitAction
    | KeyPressAction | SubmitAction | DoneAction,
    Field(discriminator="type"),
]
browser_action_adapter = TypeAdapter(BrowserAction)


class CandidateAction(Contract):
    id: Identifier
    description: ShortText
    action: BrowserAction

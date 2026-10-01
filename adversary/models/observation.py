"""Compact snapshots supplied by a future browser adapter, not raw DOM dumps."""

from typing import Annotated

from pydantic import Field, model_validator

from .action import ElementLocator
from .base import Contract, Identifier, NonNegativeInt


class BrowserElement(Contract):
    locator: ElementLocator
    role: Annotated[str, Field(max_length=128)] = ""
    accessible_name: Annotated[str, Field(max_length=512)] = ""
    disabled: bool = False


class BrowserObservation(Contract):
    id: Identifier
    session_id: Identifier
    step: NonNegativeInt
    url: Annotated[str, Field(min_length=1, max_length=4096)]
    title: Annotated[str, Field(max_length=512)] = ""
    visible_text: Annotated[str, Field(max_length=16_384)] = ""
    elements: Annotated[tuple[BrowserElement, ...], Field(max_length=500)] = ()

    @model_validator(mode="after")
    def validate_elements(self):
        ids = [element.locator.element_id for element in self.elements]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate element IDs in observation")
        if any(element.locator.observation_id != self.id for element in self.elements):
            raise ValueError("element belongs to a different observation")
        return self

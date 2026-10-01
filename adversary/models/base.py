"""Shared validation rules for serializable QA contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=512)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
Milliseconds = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class Contract(BaseModel):
    # Frozen snapshots prevent post-validation edits to candidates. Collections in
    # these models are tuples/frozensets so nested mutable containers cannot drift.
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

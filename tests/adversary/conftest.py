"""Domain tests do not need the parent suite's PostgreSQL/Redis fixture."""

import pytest


@pytest.fixture(autouse=True)
def isolated():
    # Override tests/conftest.py for full-suite runs; --confcutdir also allows
    # this slice to run without even importing application infrastructure.
    yield

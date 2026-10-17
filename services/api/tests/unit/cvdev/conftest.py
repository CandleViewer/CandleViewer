"""#2893 S9: a trip latches every account fixture transport in the process until a restart."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from cvdev.account_fixture import transport


@pytest.fixture(autouse=True)
def _unlatched() -> Iterator[None]:
    """The test-only reset: each test starts and ends with no transport tripped."""
    transport._TRIPPED.clear()
    yield
    transport._TRIPPED.clear()

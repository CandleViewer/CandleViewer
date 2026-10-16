"""Shared fixtures for the E09-X02 HTTP/WS abuse cases (#2144). Modules that define their own
`stack` (e.g. `test_csrf_double_submit.py`) keep it: a module fixture overrides this one. The
harness is imported lazily, so collecting the service-level modules here never imports the app."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from ._stack import Grants, Stack


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    """`create_app()` over the in-memory auth stack of `_stack.py`."""
    from ._stack import open_stack

    with open_stack(monkeypatch) as s:
        yield s


@pytest.fixture
def ws_world(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Stack, Grants]]:
    """The same stack with a WS principal source whose account grant a test can revoke. Not named
    `world`: `test_role_revoked_mid_step_up.py` defines a different `world` of its own."""
    from ._stack import Grants, open_stack

    grants = Grants()
    with open_stack(monkeypatch, snapshot_loader=grants.load) as s:
        yield s, grants

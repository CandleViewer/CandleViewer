"""E14-Q04 (#431): one real `create_app()` world per test module (the RBAC pack's `build_world`,
patches undone at teardown as in `tests/contract/rbac/conftest.py`, C-13.7) and a fresh in-memory
E14-T01 drawings repository per test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from _drawings_contract import Api

from tests.contract.rbac.rbac_harness import World, build_world
from tests.drawings._drawings_api_env import FakeDrawingRepo


@pytest.fixture(scope="module")
def _drawings_world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        yield build_world(mp)
    finally:
        mp.undo()


@pytest.fixture
def api(_drawings_world: World) -> Api:
    _drawings_world.audit.records.clear()
    _drawings_world.app.state.drawings_repository = repo = FakeDrawingRepo()
    return Api(_drawings_world, repo)

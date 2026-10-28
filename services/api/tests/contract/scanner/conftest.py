"""E08-T09 (#4708): one real `create_app()` world per test module (the RBAC pack's `build_world`,
patches undone at teardown, C-13.7) and a fresh in-memory scanner-preset repository per test, as
the indicator-presets contract pack does."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from _scanner_contract import Api

from tests.contract.rbac.rbac_harness import World, build_world
from tests.scanner_presets._scanner_env import FakeScannerRepo


@pytest.fixture(scope="module")
def _scanner_world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        yield build_world(mp)
    finally:
        mp.undo()


@pytest.fixture
def api(_scanner_world: World) -> Api:
    _scanner_world.audit.records.clear()
    _scanner_world.app.state.scanner_presets_repository = repo = FakeScannerRepo()
    return Api(_scanner_world, repo)

"""E13-T03 (#427): one real `create_app()` world per test module (the RBAC pack's `build_world`,
patches undone at teardown, C-13.7) and a fresh in-memory preset repository per test, as the
drawings contract pack does."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from _presets_contract import Api

from tests.contract.rbac.rbac_harness import World, build_world
from tests.indicator_presets._presets_env import FakePresetRepo


@pytest.fixture(scope="module")
def _presets_world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        yield build_world(mp)
    finally:
        mp.undo()


@pytest.fixture
def api(_presets_world: World) -> Api:
    _presets_world.audit.records.clear()
    _presets_world.app.state.indicator_presets_repository = repo = FakePresetRepo()
    return Api(_presets_world, repo)

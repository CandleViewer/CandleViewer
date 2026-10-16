"""Regression guard (E09-Q03 fix round 2): the matrix pack must leave no global state behind.

The pack patches `candleviewer.app.build_identity_provider`, `SqlAlchemyAlertRepository` and
`build_retention_manager` to build a real-app world without Postgres, and sets the `WORLD_ENV`
variables (bars on, its state root in tmp). A session-lifetime patch once leaked into later
`create_app()` callers (the telemetry fail-closed 501 test saw a fake identity provider and
returned 401). The `zz` prefix runs this module AFTER the other pack modules, whose module-scoped
world fixtures have been torn down by then.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import candleviewer.app as appmod
from candleviewer.retention_wiring import build_retention_manager as _original_retention_builder
from candleviewer.settings import get_settings
from candleviewer.storage.repositories.alerts_sqlalchemy import (
    SqlAlchemyAlertRepository as OriginalAlertRepository,
)
from tests.contract.rbac.rbac_harness import WORLD_ENV, build_world

#: Baselines, captured at collection time before any fixture of this pack has run (not at test
#: start), so a leak is caught whatever the test order. `app.py` imports the alert repository
#: without re-exporting it, so it is read reflectively (no `type: ignore`).
_ORIGINAL_IDENTITY = appmod.build_identity_provider
_ORIGINAL_ENV = {name: os.environ.get(name) for name in WORLD_ENV}


def _alert_repository() -> object:
    return getattr(appmod, "SqlAlchemyAlertRepository")  # noqa: B009 - non-exported name


def _retention_builder() -> object:
    return getattr(appmod, "build_retention_manager")  # noqa: B009 - non-exported name


def _world_env() -> dict[str, str | None]:
    return {name: os.environ.get(name) for name in WORLD_ENV}


def test_pack_left_no_patch_behind() -> None:
    assert appmod.build_identity_provider is _ORIGINAL_IDENTITY, "identity patch leaked"
    assert _alert_repository() is OriginalAlertRepository, "alert patch leaked"
    assert _retention_builder() is _original_retention_builder, "retention patch leaked"
    assert _world_env() == _ORIGINAL_ENV, "env patch leaked"


def test_a_fresh_create_app_still_fails_closed_without_an_identity_provider() -> None:
    assert appmod.build_identity_provider(get_settings()) is None


def test_world_patches_are_undone_by_the_monkeypatch_teardown(tmp_path: Path) -> None:
    """Order-independent proof of the teardown path itself, env patches included. A failure while
    the world is live still reaches `mp.undo()`, so it cannot leak into the tests after it."""
    mp = pytest.MonkeyPatch()
    try:
        build_world(mp, bars_state_root=tmp_path)
        assert appmod.build_identity_provider is not _ORIGINAL_IDENTITY, "world must patch"
        assert _retention_builder() is not _original_retention_builder
        settings = get_settings()
        assert settings.bars_enabled is True, "world must enable bars while live"
        assert settings.bars_state_root == str(tmp_path.resolve()), "world must root bars in tmp"
    finally:
        mp.undo()
    assert appmod.build_identity_provider is _ORIGINAL_IDENTITY
    assert _alert_repository() is OriginalAlertRepository
    assert _retention_builder() is _original_retention_builder
    assert _world_env() == _ORIGINAL_ENV, "env patch leaked"

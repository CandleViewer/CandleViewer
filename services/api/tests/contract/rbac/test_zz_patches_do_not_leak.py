"""Regression guard (E09-Q03 fix round 2): the matrix pack must leave no global state behind.

The pack patches `candleviewer.app.build_identity_provider`, `SqlAlchemyAlertRepository` and
`build_retention_manager` to build a real-app world without Postgres. A session-lifetime patch once
leaked into later `create_app()` callers (the telemetry fail-closed 501 test saw a fake identity
provider and returned 401). The `zz` prefix runs this module AFTER the other pack modules, whose
module-scoped world fixtures have been torn down by then.
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
from tests.contract.rbac.rbac_harness import build_world

#: Captured at collection time, before any fixture of this pack has run. `app.py` imports the
#: alert repository without re-exporting it, so it is read reflectively (no `type: ignore`).
_ORIGINAL_IDENTITY = appmod.build_identity_provider
#: Environment variables `build_world` sets; all must be back to their outside values afterwards.
_WORLD_ENV = ("CV_ALLOWED_ORIGINS", "CV_BARS_ENABLED", "CV_BARS_STATE_ROOT")


def _alert_repository() -> object:
    return getattr(appmod, "SqlAlchemyAlertRepository")  # noqa: B009 - non-exported name


def _retention_builder() -> object:
    return getattr(appmod, "build_retention_manager")  # noqa: B009 - non-exported name


def test_pack_left_the_original_identity_provider_and_alert_repository_in_place() -> None:
    assert appmod.build_identity_provider is _ORIGINAL_IDENTITY, "identity patch leaked"
    assert _alert_repository() is OriginalAlertRepository, "alert patch leaked"
    assert _retention_builder() is _original_retention_builder, "retention patch leaked"


def test_a_fresh_create_app_still_fails_closed_without_an_identity_provider() -> None:
    assert appmod.build_identity_provider(get_settings()) is None


def test_world_patches_are_undone_by_the_monkeypatch_teardown(tmp_path: Path) -> None:
    """Order-independent proof of the teardown path itself, env patches included."""
    before = {k: os.environ.get(k) for k in _WORLD_ENV}
    mp = pytest.MonkeyPatch()
    build_world(mp, bars_state_root=tmp_path)
    assert appmod.build_identity_provider is not _ORIGINAL_IDENTITY, "world must patch while live"
    assert _retention_builder() is not _original_retention_builder
    assert os.environ.get("CV_BARS_ENABLED") == "true", "world must enable bars while live"
    mp.undo()
    assert appmod.build_identity_provider is _ORIGINAL_IDENTITY
    assert _alert_repository() is OriginalAlertRepository
    assert _retention_builder() is _original_retention_builder
    assert {k: os.environ.get(k) for k in _WORLD_ENV} == before, "env patch leaked"

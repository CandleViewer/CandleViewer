"""`create_app` passes the M1 settings to the audit limiter, record budget and flush task."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest
from pydantic import ValidationError

import candleviewer.app as app_mod
from candleviewer.audit.service import AuditService
from candleviewer.audit_lane_wiring import LaneKeyRefused
from candleviewer.settings import Environment, Settings


def test_create_app_wires_audit_settings_into_limiter_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}
    real = app_mod.make_audit_router

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(app_mod, "make_audit_router", spy)
    app = app_mod.create_app(
        Settings(
            environment=Environment.DEMO,
            metrics_enabled=False,
            bars_state_root=str(tmp_path / "bars"),
            audit_query_rate_per_minute=7,
            audit_query_max_concurrent=3,
            audit_query_timeout_ms=1500,
            audit_record_budget_per_hour=11,
            audit_record_budget_owner_per_hour=13,
            audit_read_flush_pages=17,
            audit_read_flush_seconds=19.0,
            audit_budget_tracked_users=71,
            audit_inflight_writes=29,
            audit_verify_max_span=31,
            audit_verify_rate_per_hour=37,
            audit_verify_deadline_s=41.0,
        )
    )
    lim, bud = seen["limiter"], seen["budget"]
    assert (lim._rate, lim._max_concurrent, lim._cap) == (7, 3, 71)
    assert (seen["query_timeout_ms"], seen["verify_max_span"]) == (1500, 31)
    assert (seen["verify_limiter"]._rate, seen["verify_limiter"]._cap) == (37, 71)
    assert seen["verify_deadline_s"] == 41.0
    assert seen["verify_events"] is None  # the fake backend wires no `system_events` writer
    assert (bud._per_hour, bud._owner_per_hour) == (11, 13)
    assert (bud._flush_pages, bud._flush_s) == (17, 19.0)
    assert (bud._tracked, bud._inflight_cap) == (71, 29)
    flush = app.state.audit_budget_flush
    assert flush._budget is bud and flush._interval_s == 19.0  # one budget, ticked by the task
    assert app.state.audit_query_metrics is not None  # served on the scraped registry


def test_real_audit_backend_caps_reads_with_the_global_setting() -> None:
    svc = app_mod._build_audit(
        Settings(
            storage_backend="real",
            audit_query_global_max_concurrent=3,
            audit_verify_statement_timeout_ms=4321,
            audit_verify_max_entry_bytes=65_536,
        )
    )
    assert svc._repository._read_slots == 3  # constructed only; nothing connects
    assert svc._repository._verify_timeout_ms == 4321
    assert svc._repository._entry_bytes == 65_536


@pytest.mark.parametrize("value", [65_535, 8_388_609])
def test_the_verify_entry_cap_is_a_bounded_setting(value: int) -> None:
    assert Settings().audit_verify_max_entry_bytes == 4 * 1024 * 1024
    with pytest.raises(ValidationError):
        Settings(audit_verify_max_entry_bytes=value)  # below 64 KiB, or above the 8 MiB budget


@pytest.mark.parametrize("backend", ["fake", "real"])
async def test_the_audit_module_runs_the_lane_key_loader_first_on_either_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: Literal["fake", "real"]
) -> None:
    """ADR-0037 decision 6: `start()` runs S2b-1's loader before anything else, so the environment
    form refuses boot on either backend and no lock or writer is taken."""
    monkeypatch.setenv("CV_AUDIT_LANE_KEY_HEX", "")
    settings = Settings(storage_backend=backend, audit_wal_path=str(tmp_path / "a.wal"))
    svc = app_mod._build_audit(settings)
    with pytest.raises(LaneKeyRefused, match=r"^CV_AUDIT_LANE_KEY_HEX is refused"):
        await svc.start(cast(Any, SimpleNamespace(settings=settings)))
    assert not svc.is_active and not (tmp_path / "breakglass").exists()


def test_create_app_hands_the_audit_module_the_lane_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0037 decision 12: the composition root hands over the flag runtime's cached read."""
    reads: list[Callable[[], bool]] = []
    monkeypatch.setattr(AuditService, "use_lane_flag", lambda _svc, read: reads.append(read))
    app = app_mod.create_app(
        Settings(metrics_enabled=False, bars_state_root=str(tmp_path / "bars"))
    )
    assert reads == [app.state.feature_flags.lane_flag]

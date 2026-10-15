"""`create_app` passes the M1 settings to the audit limiter, record budget and flush task."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import candleviewer.app as app_mod
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
        )
    )
    lim, bud = seen["limiter"], seen["budget"]
    assert (lim._rate, lim._max_concurrent, lim._cap) == (7, 3, 71)
    assert (seen["query_timeout_ms"], seen["verify_max_span"]) == (1500, 31)
    assert (seen["verify_limiter"]._rate, seen["verify_limiter"]._cap) == (37, 71)
    assert (bud._per_hour, bud._owner_per_hour) == (11, 13)
    assert (bud._flush_pages, bud._flush_s) == (17, 19.0)
    assert (bud._tracked, bud._inflight_cap) == (71, 29)
    flush = app.state.audit_budget_flush
    assert flush._budget is bud and flush._interval_s == 19.0  # one budget, ticked by the task
    assert app.state.audit_query_metrics is not None  # served on the scraped registry


def test_real_audit_backend_caps_reads_with_the_global_setting() -> None:
    svc = app_mod._build_audit(
        Settings(storage_backend="real", audit_query_global_max_concurrent=3)
    )
    assert svc._repository._read_slots == 3  # constructed only; nothing connects

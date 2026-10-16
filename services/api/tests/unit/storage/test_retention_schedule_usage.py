"""Schedule flag, policy seed/resolution, permission and StorageUsage shape (E07-T05)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.storage.models import StreamKind
from candleviewer.storage.retention.policy import (
    RETENTION_CHANGE_PERMISSION,
    RetentionPermissionDenied,
    RetentionPolicy,
    RetentionRule,
    load_defaults,
    require_retention_change,
)
from candleviewer.storage.retention.schedule import RetentionSchedule
from candleviewer.storage.retention.usage import build_storage_usage


def test_schedule_off_by_default_and_on_with_flag() -> None:
    assert RetentionSchedule.from_env({}).jobs() == {}
    on = RetentionSchedule.from_env({"CV_RETENTION_ENABLED": "true"}).jobs()
    assert on == {"export": "15 2 * * *", "retention": "0 3 * * *", "compact": "0 3 * * 0"}


def test_seed_matches_section7_defaults() -> None:
    rules = {r.stream: r for r in load_defaults()}
    assert rules[StreamKind.TRADES].hot_days == 30
    assert rules[StreamKind.ORDERBOOK_DELTA].hot_days == 7
    assert rules[StreamKind.KLINES].cold_days is None


def test_per_symbol_beats_global() -> None:
    p = RetentionPolicy(
        [RetentionRule(StreamKind.TRADES, 10, 100, symbol="ETHUSDT")], load_defaults()
    )
    assert p.resolve("ETHUSDT", StreamKind.TRADES).hot_days == 10  # type: ignore[union-attr]  # justified: rule present
    assert p.resolve("BTCUSDT", StreamKind.TRADES).hot_days == 30  # type: ignore[union-attr]  # justified: rule present


def test_retention_change_requires_permission() -> None:
    require_retention_change([Permission.RECORDING_WRITE])
    with pytest.raises(RetentionPermissionDenied):
        require_retention_change([Permission.RECORDING_READ, Permission.ORDERS_READ])


def test_retention_change_is_the_seeded_recording_write_code_not_the_audit_action() -> None:
    # #2699: `retention.change` is an audit action no role holds; the gate is the seeded code.
    assert RETENTION_CHANGE_PERMISSION == Permission.RECORDING_WRITE
    with pytest.raises(RetentionPermissionDenied):
        require_retention_change(["retention.change"])


def test_storage_usage_keys_match_openapi() -> None:
    out = build_storage_usage(
        total=100,
        used=50,
        daily_growth=5,
        tiers=[],
        symbols=[],
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert set(out) == {
        "disk_total_bytes",
        "disk_used_bytes",
        "disk_free_bytes",
        "projected_full_at",
        "daily_growth_bytes",
        "tiers",
        "symbols",
        "generated_at",
    }
    assert out["disk_free_bytes"] == 50 and out["projected_full_at"] is not None


def test_schedule_from_settings_reads_settings_object() -> None:
    from candleviewer.settings import Settings

    s = Settings(retention_enabled=True, retention_cron="1 1 * * *")
    jobs = RetentionSchedule.from_settings(s).jobs()
    assert jobs["retention"] == "1 1 * * *"
    assert RetentionSchedule.from_settings(Settings()).jobs() == {}

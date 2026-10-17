"""The limiter/budget/verify defaults must match the merged contract text (#2392)."""

from __future__ import annotations

from pathlib import Path

from candleviewer.settings import Settings

_SPEC = Path(__file__).resolve().parents[4] / "docs" / "plan" / "22-api-openapi.yaml"


def test_settings_defaults_are_named_in_the_contract() -> None:
    text = _SPEC.read_text(encoding="utf-8")
    missing = [
        name
        for name in (
            "audit_query_rate_per_minute",
            "audit_query_max_concurrent",
            "audit_query_timeout_ms",
            "audit_record_budget_per_hour",
            "audit_record_budget_owner_per_hour",
            "audit_read_flush_pages",
            "audit_read_flush_seconds",
            "audit_budget_tracked_users",
            "audit_inflight_writes",
            "audit_verify_max_span",
        )
        if name not in text
    ]
    assert not missing, (
        f"contract PR #2392 is not in this base: {missing} absent from 22-api-openapi.yaml; "
        "merge #2392 first (contract-first)"
    )
    s = Settings()
    assert (s.audit_query_rate_per_minute, s.audit_query_max_concurrent) == (60, 2)
    assert (s.audit_query_timeout_ms, s.audit_record_budget_per_hour) == (4000, 120)
    assert (s.audit_record_budget_owner_per_hour, s.audit_read_flush_pages) == (600, 50)
    assert (s.audit_read_flush_seconds, s.audit_budget_tracked_users) == (300.0, 1024)
    assert (s.audit_inflight_writes, s.audit_verify_max_span) == (64, 1_000_000)

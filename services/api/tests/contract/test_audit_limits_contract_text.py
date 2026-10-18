"""The limiter/budget/verify defaults must match the merged contract text (#2392)."""

from __future__ import annotations

import re
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
            "audit_verify_rate_per_hour",
            "audit_verify_deadline_s",
            "audit_verify_statement_timeout_ms",
            "audit_verify_max_entry_bytes",
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
    assert s.audit_verify_rate_per_hour == 30
    assert (s.audit_verify_deadline_s, s.audit_verify_statement_timeout_ms) == (60.0, 10_000)
    assert s.audit_verify_max_entry_bytes == 4_194_304  # 4 MiB


def _verify_limits() -> str:
    """The `**Limits.**` paragraph of `verifyAuditChain`, on one line."""
    text = _SPEC.read_text(encoding="utf-8")
    section = text.split("operationId: verifyAuditChain", 1)[1].split("x-rbac:", 1)[0]
    assert "**Limits.**" in section, "the verify section no longer has a Limits paragraph"
    return " ".join(section.split("**Limits.**", 1)[1].split())


def test_verify_limit_defaults_are_the_ones_the_contract_states() -> None:
    """F14-1: the verify section states a default for each of the three limits, in its own
    unit, and each is the `Settings` default: a drift on either side fails here."""
    limits, unit = _verify_limits(), {None: 1, " s": 1, " MiB": 1024 * 1024}
    for name in (
        "audit_verify_deadline_s",
        "audit_verify_statement_timeout_ms",
        "audit_verify_max_entry_bytes",
    ):
        stated = re.search(rf"`{name}`,? \(?default (\d+)( s| MiB)?\)", limits)
        assert stated, f"the verify section no longer states a default for {name}"
        assert Settings.model_fields[name].default == int(stated[1]) * unit[stated[2]]

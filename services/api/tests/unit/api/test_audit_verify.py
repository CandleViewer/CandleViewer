"""`api/audit_verify.py`: the gauge rule, the result record and the bounded record write."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.api import audit_verify as mod
from candleviewer.audit.models import AuditOutcome, ChainBreakKind, Severity, VerifyResult


def _result(*, verified: bool, full: bool = False) -> VerifyResult:
    return VerifyResult(
        verified=verified,
        entries_checked=4,
        first_bad_id=None if verified else 4,
        checked_at=datetime(2026, 10, 15, tzinfo=UTC),
        from_id=1,
        to_id=4,
        anchor_hash="0" * 64,
        last_hash="a" * 64,
        kind=None if verified else ChainBreakKind.PREV_HASH_MISMATCH,
        full_chain=full,
    )


def _state() -> float | None:
    return REGISTRY.get_sample_value("cv_audit_chain_verified_state")


def test_gauge_rule_only_a_genesis_to_head_run_sets_one() -> None:
    mod.observe_verify(_result(verified=False))
    assert _state() == 0
    mod.observe_verify(_result(verified=True))
    assert _state() == 0  # a passing partial range never hides the break
    mod.observe_verify(_result(verified=True, full=True))
    assert _state() == 1
    mod.observe_verify(_result(verified=True))
    assert _state() == 1
    mod.observe_verify(_result(verified=False, full=True))
    assert _state() == 0


def test_gauge_rule_a_full_range_run_that_stops_is_unknown() -> None:
    """Review of #2462: a stop must not leave an old 1 standing."""
    mod.observe_verify(_result(verified=True, full=True))
    mod.observe_stop(full_chain=False)  # a partial range leaves the gauge as it is
    assert _state() == 1
    mod.observe_stop(full_chain=True)
    state = _state()
    assert state is not None and math.isnan(state)


def test_result_record_is_critical_with_kind_at_id_on_a_break() -> None:
    outcome, severity, reason, after = mod.result_record(_result(verified=False))
    assert (outcome, severity, reason) == (
        AuditOutcome.FAILURE,
        Severity.CRITICAL,
        "prev_hash_mismatch@4",
    )
    assert after == {
        "from_id": 1,
        "to_id": 4,
        "entries_checked": 4,
        "verified": False,
        "first_bad_id": 4,
        "kind": "prev_hash_mismatch",
    }
    ok = mod.result_record(_result(verified=True))
    assert ok[:3] == (AuditOutcome.SUCCESS, Severity.INFO, "verified")


async def test_a_record_write_past_its_timeout_counts_as_not_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mod, "WRITE_TIMEOUT_S", 0.01)

    async def stalled(*_a: Any, **_kw: Any) -> None:
        await asyncio.Event().wait()

    written = await mod.write_verify_record(
        stalled,
        {"actor_label": "owner"},
        outcome=AuditOutcome.SUCCESS,
        severity=Severity.INFO,
        reason="started",
        after_state={"from_id": 1, "to_id": 2},
    )
    assert written is False

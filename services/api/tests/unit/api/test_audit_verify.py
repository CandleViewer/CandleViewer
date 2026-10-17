"""`api/audit_verify.py`: the gauge rule, the result record and the bounded record write."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import Any

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api import audit_verify as mod
from candleviewer.audit.models import AuditOutcome, ChainBreakKind, Severity, VerifyResult
from candleviewer.observability.audit_query_metrics import cv_audit_chain_verified_state
from candleviewer.observability.health_probes import SystemEvent


def _result(
    *,
    verified: bool,
    full: bool = False,
    kind: ChainBreakKind = ChainBreakKind.PREV_HASH_MISMATCH,
) -> VerifyResult:
    return VerifyResult(
        verified=verified,
        entries_checked=4,
        first_bad_id=None if verified else 4,
        checked_at=datetime(2026, 10, 15, tzinfo=UTC),
        from_id=1,
        to_id=4,
        anchor_hash="0" * 64,
        last_hash="a" * 64,
        kind=None if verified else kind,
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


@pytest.mark.parametrize(
    ("before", "full", "after"),
    [
        (1.0, True, math.nan),  # verified, then a full run stops: unknown
        (0.0, True, 0.0),  # a known break is kept, so its alert keeps firing
        (math.nan, True, math.nan),
        (1.0, False, 1.0),  # a partial range that stops changes nothing
        (0.0, False, 0.0),
    ],
)
def test_gauge_rule_a_stop_takes_only_a_one_to_unknown(
    before: float, full: bool, after: float
) -> None:
    """Reviews of #2462: a stop must not leave an old 1 standing, and must never clear a 0."""
    cv_audit_chain_verified_state.set(before)
    mod.observe_stop(full_chain=full)
    state = _state()
    assert state is not None
    assert math.isnan(state) if math.isnan(after) else state == after


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


class _Events:
    """A `SystemEventWriter` that keeps what it is given, or fails, or never answers."""

    def __init__(self, fail: Exception | None = None, hang: bool = False) -> None:
        self.written: list[SystemEvent] = []
        self.fail, self.hang = fail, hang

    async def write(self, event: SystemEvent) -> None:
        if self.hang:
            await asyncio.Event().wait()
        if self.fail is not None:
            raise self.fail
        self.written.append(event)


@pytest.mark.parametrize("kind", list(ChainBreakKind))
async def test_a_break_of_each_kind_raises_one_critical_db_event(kind: ChainBreakKind) -> None:
    events = _Events()
    await mod.raise_break_event(events, _result(verified=False, kind=kind), "req-1")
    [event] = events.written
    assert (event.component, event.kind, event.severity) == ("db", "audit_chain_break", "critical")
    assert (event.message, event.correlation_id) == ("audit chain break at id 4", "req-1")
    assert event.details == {"first_bad_id": "4", "kind": kind.value, "from_id": "1", "to_id": "4"}


async def test_a_verified_run_or_no_writer_raises_nothing() -> None:
    events = _Events()
    await mod.raise_break_event(events, _result(verified=True), None)
    await mod.raise_break_event(None, _result(verified=False), None)  # not wired
    assert events.written == []


@pytest.mark.parametrize(
    ("events", "error"),
    [
        (_Events(fail=OSError("pg down at 10.0.0.9")), "OSError"),
        (_Events(hang=True), "TimeoutError"),
    ],
)
async def test_an_event_that_cannot_be_written_is_logged_by_class_only(
    events: _Events, error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mod, "EVENT_TIMEOUT_S", 0.01)
    with capture_logs() as logs:
        await mod.raise_break_event(events, _result(verified=False), None)  # never raises
    assert [(e["event"], e["error"]) for e in logs] == [("audit.verify.event_write_failed", error)]
    assert "10.0.0.9" not in repr(logs)

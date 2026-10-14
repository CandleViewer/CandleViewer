"""PR #1674 finding 3: `StepUpService` drives the B16 `session` chart.

Sync code enforces first; each path then asserts the chart's state and the
audit record its action wrote (with before/after state, C-12.8)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from candleviewer.auth.errors import SessionReadOnly, StepUpCodeInvalid, StepUpRequired
from candleviewer.auth.session_chart import SessionChart, SessionChartError
from candleviewer.auth.step_up import StepUpService
from candleviewer.statechart.bindings import b16_session
from tests.conftest import RecordingAuditSink

from .test_step_up import PASSWORD, _code, _Positions, _session, _setup


def _sid(svc: StepUpService, sessions: object, alias: str = "s1") -> str:
    return str(sessions.sessions[alias].id)  # type: ignore[attr-defined]


async def test_challenge_issued_records_action_request_and_audits_required(
    b16_audit: RecordingAuditSink,
) -> None:
    svc, _clock, _seed, user, sessions = await _setup()
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", "keys")
    await svc.record_pending("s1", "keys")
    sid = _sid(svc, sessions)
    assert svc.chart.in_state(sid, "normal") and svc.chart.in_state(sid, "active")
    (call,) = b16_audit.calls
    assert call["action"] == "auth.step_up_required" and call["outcome"] == "denied"
    assert call["session_id"] == sid and call["actor_user_id"] == str(user)
    assert call["reason"] == "keys" and call["after_state"]["step_up_failures"] == 0


async def test_step_up_ok_elevates_chart_and_audits_granted(
    b16_audit: RecordingAuditSink,
) -> None:
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    sid = _sid(svc, sessions)
    assert svc.chart.in_state(sid, "elevated")
    (call,) = b16_audit.calls
    assert call["action"] == "auth.step_up_granted" and call["reason"] == "keys"
    assert call["before_state"]["elevated_classes"] == []
    assert call["after_state"]["elevated_classes"] == ["keys"]


async def test_grace_use_audits_grace_used(b16_audit: RecordingAuditSink) -> None:
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    clock.now += timedelta(minutes=1)
    await svc.require_elevation("s1", "keys")
    assert b16_audit.actions()[-1] == "auth.step_up_grace_used"
    assert svc.chart.in_state(_sid(svc, sessions), "elevated")


async def test_grace_expiry_sends_elevation_deadline_back_to_normal(
    b16_audit: RecordingAuditSink,
) -> None:
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    clock.now += timedelta(minutes=5, seconds=1)
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", "keys")
    await svc.record_pending("s1", "keys")
    sid = _sid(svc, sessions)
    assert svc.chart.in_state(sid, "normal")
    assert b16_audit.actions()[-1] == "auth.step_up_required"


async def test_strikes_then_readonly_downgrade_then_expiry(
    b16_audit: RecordingAuditSink,
) -> None:
    svc, clock, _seed, user, sessions = await _setup()
    sid = _sid(svc, sessions)
    for remaining in (2, 1):
        with pytest.raises(StepUpCodeInvalid):
            await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
        assert b16_audit.calls[-1]["reason"] == f"keys:remaining={remaining}"
    assert svc.chart.in_state(sid, "normal")
    with pytest.raises(SessionReadOnly):
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    assert svc.chart.in_state(sid, "readonly_downgrade")
    assert b16_audit.actions() == [
        "auth.step_up_failed",
        "auth.step_up_failed",
        "auth.step_up_failed",
        "auth.session_readonly_downgrade",
    ]
    down = b16_audit.calls[-1]
    assert down["severity"] == "error" and down["after_state"]["step_up_failures"] == 3
    assert down["before_state"]["step_up_failures"] == 2
    clock.now += timedelta(minutes=5, seconds=1)
    await svc.assert_writable("s1")
    assert svc.chart.in_state(sid, "normal")


async def test_owner_reset_revokes_target_charts_and_audits_revocation(
    b16_audit: RecordingAuditSink,
) -> None:
    svc, clock, seed, user, sessions = await _setup()
    target = uuid.uuid4()
    sessions.sessions["t1"] = _session(target)
    await svc.record_pending("t1", "keys")  # target has a live chart
    target_sid = _sid(svc, sessions, "t1")
    chart = svc.chart.interpreter(target_sid)
    assert chart is not None
    await svc.step_up(str(user), "o1", "users", _code(seed, clock), PASSWORD)
    await svc.preview_reset(str(target), _Positions(0))
    await svc.reset_totp(actor_session_id="o1", actor_user_id=str(user), target_user_id=str(target))
    assert svc.chart.interpreter(target_sid) is None  # dropped after REVOKE
    revoked = [c for c in b16_audit.calls if c["action"] == "auth.session_revoked"]
    assert [c["session_id"] for c in revoked] == [target_sid]
    assert revoked[0]["reason"] == "mfa_reset_by_owner"


async def test_hydration_from_row_is_not_re_audited(b16_audit: RecordingAuditSink) -> None:
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    rebuilt = StepUpService(
        svc._mfa, sessions, svc._encryptor, svc._users, svc._hasher, clock=clock
    )
    before = len(b16_audit.calls)
    await rebuilt.require_elevation("s1", "keys")  # chart rebuilt from the row
    assert rebuilt.chart.in_state(_sid(svc, sessions), "elevated")
    assert b16_audit.actions()[before:] == ["auth.step_up_grace_used"]
    await rebuilt.stop()


async def test_audit_sink_missing_fails_loud_after_enforcement() -> None:
    svc, clock, seed, user, sessions = await _setup()
    b16_session.set_audit_sink(None)
    with pytest.raises(SessionChartError):
        await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    # Enforcement already happened and persisted (sync code enforces, C-2.21).
    assert "keys" in sessions.sessions["s1"].step_up_elevations


async def test_locked_row_is_recorded_as_idle_lock_before_the_next_event(
    b16_audit: RecordingAuditSink,
) -> None:
    """#2301 / INV-B16-e: the idle deadline is evaluated on access. The chart
    records the lock once (dropping elevation), ignores activity, and an unlock
    recorded against the still-locked row lands in `auth.idle_locked`."""
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    sid = _sid(svc, sessions)
    clock.now += timedelta(minutes=16)  # past the default 15-minute idle timeout
    row = sessions.sessions["s1"]
    assert row.is_idle_locked(now=clock.now)
    for _ in range(2):
        await svc.chart.record(row, clock.now, "REQUEST")
    assert svc.chart.in_state(sid, "idle_locked") and svc.chart.in_state(sid, "normal")
    assert b16_audit.actions()[-3:] == [
        "auth.idle_locked",
        "auth.request_ignored",
        "auth.request_ignored",
    ]
    await svc.chart.record(row, clock.now, "UNLOCK_OK")
    assert svc.chart.in_state(sid, "active")
    assert b16_audit.actions()[-1] == "auth.session_unlocked"
    assert b16_audit.actions().count("auth.idle_locked") == 1


async def test_chart_rebuilt_for_a_locked_row_comes_back_locked_without_elevation(
    b16_audit: RecordingAuditSink,
) -> None:
    """Snapshot note (#2301): no lock state is persisted; the row re-evaluates it."""
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    row = sessions.sessions["s1"].model_copy(
        update={"last_seen_at": clock.now - timedelta(minutes=16)}
    )
    assert row.is_idle_locked(now=clock.now) and row.step_up_elevations["keys"] > clock.now
    chart = SessionChart()
    try:
        await chart.record(row, clock.now, "REQUEST", replay=True)
        assert chart.in_state(str(row.id), "idle_locked")
        assert not chart.in_state(str(row.id), "elevated")
        assert b16_audit.actions()[-1] == "auth.idle_locked"
    finally:
        await chart.stop()

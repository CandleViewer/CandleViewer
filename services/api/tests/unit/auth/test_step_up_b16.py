"""PR #1674 finding 3: `StepUpService` drives the B16 `session` chart.

Sync code enforces first; each path then asserts the chart's state and the
audit record its action wrote (with before/after state, C-12.8)."""

from __future__ import annotations

import ast
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.auth.errors import SessionReadOnly, StepUpCodeInvalid, StepUpRequired
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_chart import SessionChart, SessionChartError
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import StepUpService, grace_expires_at
from candleviewer.statechart.bindings import b16_session
from tests.conftest import RecordingAuditSink

from .session_fakes import FakeSessionRepository
from .test_step_up import (
    _HASHER,
    _T0,
    PASSWORD,
    _Clock,
    _code,
    _Positions,
    _pw_hash,
    _session,
    _setup,
)


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
    mark = len(b16_audit.calls)
    await svc.chart.record(row, clock.now, "UNLOCK_OK")
    assert svc.chart.in_state(sid, "active")
    # `POST /auth/unlock` writes the unlock row write-ahead; the chart writes none (B16.7).
    assert b16_audit.actions()[mark:] == []
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


# -- B16.7 (#2301): one fail-closed writer per record; unlock drops elevation ----


class _FailingSink(RecordingAuditSink):
    """The M19 writer refusing one action: that row is never written (C-2.9)."""

    def __init__(self, action: str) -> None:
        super().__init__()
        self.failing: str | None = action

    async def emit(self, action: str, **kwargs: Any) -> None:
        if action == self.failing:
            raise RuntimeError(f"audit down: {action}")
        await super().emit(action, **kwargs)


_LATER = _T0 + timedelta(minutes=5)


@pytest.mark.parametrize(
    ("leaf", "step_up"),
    [
        ("elevated", {"step_up_elevations": {"keys": _LATER}}),
        ("normal", {}),
        ("readonly_downgrade", {"readonly_until": _LATER, "step_up_failures": 3}),
    ],
)
async def test_failed_lock_write_raises_and_the_retry_records_the_lock(
    leaf: str, step_up: dict[str, Any]
) -> None:
    """With the sink failing on `auth.idle_locked`, recording the lock raises and
    writes no row, also from `[active, elevated]`, where the step moves both
    regions and the receipt reads clean (CV-C06). The retry locks the chart."""
    sink = _FailingSink("auth.idle_locked")
    b16_session.set_audit_sink(sink)
    # The default 15-minute idle timeout locks this row one minute before _T0.
    row = _session(uuid.uuid4()).model_copy(
        update={"last_seen_at": _T0 - timedelta(minutes=16), **step_up}
    )
    sid = str(row.id)
    chart = SessionChart()
    try:
        await chart.record(row, _T0 - timedelta(minutes=2), "REQUEST", replay=True)
        assert chart.in_state(sid, "active") and chart.in_state(sid, leaf)
        with pytest.raises(SessionChartError):
            await chart.record(row, _T0, "REQUEST", replay=True)
        assert not chart.in_state(sid, "idle_locked") and sink.actions() == []
        sink.failing = None
        await chart.record(row, _T0, "REQUEST", replay=True)
        assert chart.in_state(sid, "idle_locked") and not chart.in_state(sid, "elevated")
        assert sink.actions() == ["auth.idle_locked"]
    finally:
        await chart.stop()


async def test_failed_revocation_write_makes_revoke_raise() -> None:
    """A kill event moves both regions, so a failed `auth.session_revoked` write
    can leave a clean receipt; `SessionChart.revoke` still raises (B16.7)."""
    sink = _FailingSink("auth.session_revoked")
    b16_session.set_audit_sink(sink)
    row = _session(uuid.uuid4())
    chart = SessionChart()
    try:
        with pytest.raises(SessionChartError):
            await chart.revoke(row, _T0, "admin")
        assert not chart.in_state(str(row.id), "revoked") and sink.actions() == []
    finally:
        await chart.stop()


def test_every_audit_action_the_chart_writes_is_registered() -> None:
    """The M19 writer refuses an unregistered action, which would fail every
    record that writes it (C-2.9). Reads the literal `_emit` actions."""
    tree = ast.parse(Path(b16_session.__file__).read_text(encoding="utf-8"))
    written = {
        node.args[2].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "_emit"
        and len(node.args) > 2
        and isinstance(node.args[2], ast.Constant)
    }
    assert {"auth.idle_locked", "auth.request_ignored"} <= written
    assert written <= AUDIT_ACTIONS


async def _lock_and_unlock(
    svc: StepUpService, clock: _Clock, sessions: FakeSessionRepository
) -> SessionRecord:
    """Let the idle deadline `_last_seen_14_minutes_ago` set pass, then unlock
    `s1` with the password; returns the row as it was while locked."""
    clock.now += timedelta(minutes=2)
    locked = sessions.sessions["s1"]
    assert locked.is_idle_locked(now=clock.now)
    service = SessionService(sessions, _HASHER, clock=clock)
    await service.unlock("s1", password=PASSWORD, password_hash=await _pw_hash())
    return locked


def _last_seen_14_minutes_ago(sessions: FakeSessionRepository, clock: _Clock) -> None:
    """`s1` idle-locks one minute from now (default 15-minute timeout)."""
    row = sessions.sessions["s1"]
    sessions.sessions["s1"] = row.model_copy(
        update={"last_seen_at": clock.now - timedelta(minutes=14)}
    )


async def test_unlock_of_an_idle_locked_row_drops_every_step_up_elevation() -> None:
    """Step up, idle-lock, unlock: no grace window, one-shot grant or pending
    challenge taken before the lock survives the password-only unlock
    (PR #2290 ruling rule 4d); `step_up_failures` and `readonly_until` stay."""
    svc, clock, seed, user, sessions = await _setup()
    _last_seen_14_minutes_ago(sessions, clock)
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    clock.now += timedelta(seconds=30)  # a fresh TOTP time step
    await svc.step_up(str(user), "s1", "killswitch", _code(seed, clock), PASSWORD)
    await svc.record_pending("s1", "users")
    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    elevations = set(sessions.sessions["s1"].step_up_elevations)
    assert elevations == {"keys", "once:killswitch", "pending:users"}
    locked = await _lock_and_unlock(svc, clock, sessions)
    row = sessions.sessions["s1"]
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", "keys")
    with pytest.raises(StepUpRequired):
        await svc.consume_single_use("s1", "killswitch")
    assert await svc.pending_action_class("s1") is None
    assert grace_expires_at(row.step_up_elevations, clock.now) is None  # step_up_expires_at
    assert (row.step_up_failures, row.readonly_until) == (1, None)
    assert (locked.step_up_failures, locked.readonly_until) == (1, None)


async def test_unlock_of_an_idle_locked_row_keeps_the_readonly_downgrade() -> None:
    svc, clock, _seed, user, sessions = await _setup()
    _last_seen_14_minutes_ago(sessions, clock)
    for _ in range(2):
        with pytest.raises(StepUpCodeInvalid):
            await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    with pytest.raises(SessionReadOnly):
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    await svc.record_pending("s1", "keys")
    locked = await _lock_and_unlock(svc, clock, sessions)
    row = sessions.sessions["s1"]
    assert set(locked.step_up_elevations) == {"pending:keys"} and row.step_up_elevations == {}
    assert locked.readonly_until is not None
    assert (row.step_up_failures, row.readonly_until) == (3, locked.readonly_until)
    with pytest.raises(SessionReadOnly):
        await svc.assert_writable("s1")


async def test_unlock_of_a_row_that_is_not_locked_only_re_stamps_it() -> None:
    """B16.7 clears on the unlock of a row idle-locked at that instant only."""
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    clock.now += timedelta(minutes=1)
    service = SessionService(sessions, _HASHER, clock=clock)
    await service.unlock("s1", password=PASSWORD, password_hash=await _pw_hash())
    row = sessions.sessions["s1"]
    assert row.last_seen_at == clock.now and set(row.step_up_elevations) == {"keys"}

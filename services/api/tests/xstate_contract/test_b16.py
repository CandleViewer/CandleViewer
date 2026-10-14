"""tests/xstate_contract/test_b16.py — B16 `session` golden traces (E09-S03, QA #1634; #2301).

Drives the B16 contract (`machines/B16.session.machine.json`) only through
`cv.statechart.factory.build` (C-2.19). Transition names follow
28-statechart-catalogue.md B16.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from xstate_statemachine import Interpreter, SimulatedClock

from candleviewer.statechart import build
from candleviewer.statechart.bindings import b16_session
from candleviewer.statechart.registry import Registry
from tests.conftest import RecordingAuditSink
from tests.xstate_contract._harness import all_events, settle
from tests.xstate_contract.membership import _CATALOGUE


async def _start(lane: str = "platform") -> Interpreter:
    result = await build("session", clock=SimulatedClock(), lane=lane)  # type: ignore[arg-type]
    return result.interpreter


async def _active() -> Interpreter:
    interp = await _start()
    await interp.send("MFA_OK", wait=True)
    await interp.drain_pending()
    return interp


async def _send(interp: Interpreter[Any], event: str, **payload: Any) -> None:
    await interp.send(event, wait=True, **payload)
    await settle()


def _leaves(interp: Interpreter[Any]) -> frozenset[str]:
    """One active leaf per region, e.g. `{"auth.idle_locked", "elevation.normal"}`."""
    return frozenset(s.split(".", 1)[1] for s in interp.current_state_ids if s.count(".") == 2)


_LOCKED = frozenset({"auth.idle_locked", "elevation.normal"})


async def test_b16_starts_pending_mfa_and_normal() -> None:
    interp = await _start()
    try:
        assert interp.matches("auth.pending_mfa")
        assert interp.matches("elevation.normal")
    finally:
        await interp.stop()


async def test_b16_mfa_ok_activates() -> None:
    interp = await _active()
    try:
        assert interp.matches("auth.active")
        assert interp.context["mfa_satisfied"] is True
    finally:
        await interp.stop()


async def test_b16_mfa_timeout_revokes_with_timeout_reason() -> None:
    interp = await _start()
    try:
        await interp.send("MFA_TIMEOUT", wait=True)
        await interp.drain_pending()
        assert interp.matches("auth.revoked")
        assert interp.context["revoke_reason"] == "timeout"
    finally:
        await interp.stop()


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize(
    ("event", "reason"),
    [("ABSOLUTE_DEADLINE", "expired"), ("REVOKE", "admin"), ("LOGOUT", "logout")],
)
async def test_b16_terminal_events_revoke_with_reason_and_kill_elevation(
    event: str, reason: str, locked: bool
) -> None:
    """#2301: IDLE_DEADLINE is the idle lock, no longer a revocation; the three
    revocations end the session from `active` and from `idle_locked` alike."""
    interp = await _active()
    try:
        if locked:
            await _send(interp, "IDLE_DEADLINE")
        await interp.send(event, wait=True)
        await interp.drain_pending()
        assert interp.matches("auth.revoked")
        assert interp.matches("elevation.dead")
        assert interp.context["revoke_reason"] == reason
    finally:
        await interp.stop()


async def test_b16_mfa_attempts_exhausted_locks_after_cap() -> None:
    from candleviewer.statechart.bindings.b16_session import MFA_ATTEMPT_CAP

    interp = await _start()
    try:
        for _ in range(MFA_ATTEMPT_CAP + 1):
            await interp.send("MFA_FAILED", wait=True)
            await interp.drain_pending()
            if interp.matches("auth.revoked"):
                break
        assert interp.matches("auth.revoked")
        assert interp.context["revoke_reason"] == "locked"
    finally:
        await interp.stop()


async def test_b16_step_up_toggles_elevation() -> None:
    interp = await _active()
    try:
        await interp.send("STEP_UP_OK", wait=True)
        await interp.drain_pending()
        assert interp.matches("elevation.elevated")
        await interp.send("ELEVATION_DEADLINE", wait=True)
        await interp.drain_pending()
        assert interp.matches("elevation.normal")
    finally:
        await interp.stop()


async def test_b16_built_with_mandatory_strict_config() -> None:
    interp = await _start()
    try:
        assert interp.strict is True
    finally:
        await interp.stop()


# -- E09-S04 step-up sub-states ------------------------------------------------

_US = 1_000_000


async def _step_up(interp: Interpreter, cls: str) -> None:
    await interp.send(
        "STEP_UP_OK",
        wait=True,
        elevated_until_us=300 * _US,
        action_class=cls,
    )
    await interp.drain_pending()


async def test_b16_grace_guard_per_class_and_no_grace_list() -> None:
    from candleviewer.statechart.bindings.b16_session import grace_window_valid

    interp = await _active()
    try:
        await _step_up(interp, "keys")
        await _step_up(interp, "live_enablement")
        ctx = interp.context
        assert ctx["elevated_classes"] == {"keys": 300 * _US}
        assert grace_window_valid(ctx, {"action_class": "keys", "now_us": 100 * _US})
        assert not grace_window_valid(ctx, {"action_class": "keys", "now_us": 301 * _US})
        assert not grace_window_valid(ctx, {"action_class": "users", "now_us": 100 * _US})
        for cls in ("live_enablement", "killswitch"):
            assert not grace_window_valid(ctx, {"action_class": cls, "now_us": 1})
    finally:
        await interp.stop()


async def test_b16_three_step_up_failures_downgrade_to_readonly() -> None:
    interp = await _active()
    try:
        await _step_up(interp, "keys")
        for _ in range(3):
            assert not interp.matches("elevation.readonly_downgrade")
            await interp.send("STEP_UP_FAILED", wait=True, now_us=10 * _US)
            await interp.drain_pending()
        assert interp.matches("elevation.readonly_downgrade")
        assert interp.context["readonly_until_us"] == 310 * _US
        assert interp.context["elevated_until_us"] is None
        await interp.send("READONLY_EXPIRED", wait=True)
        await interp.drain_pending()
        assert interp.matches("elevation.normal")
        assert interp.context["step_up_failures"] == 0
    finally:
        await interp.stop()


def test_b16_policy_constants_match_service() -> None:
    from candleviewer.auth import step_up as svc
    from candleviewer.auth.session_service import MAX_UNLOCK_ATTEMPTS
    from candleviewer.statechart.bindings import b16_session as b

    assert b.NO_GRACE_ACTION_CLASSES == svc.NO_GRACE_ACTION_CLASSES
    assert b.ACTION_CLASSES == svc.ACTION_CLASSES
    assert b.STEP_UP_FAILURE_CAP == svc.FAILURE_CAP
    assert b.STEP_UP_GRACE_US == svc.GRACE_WINDOW // timedelta(microseconds=1)
    assert b.READONLY_DOWNGRADE_US == svc.READONLY_WINDOW // timedelta(microseconds=1)
    assert b.UNLOCK_ATTEMPT_CAP == MAX_UNLOCK_ATTEMPTS


# §B16.6 ledger (E50-T31 membership): pinned to 28-statechart-catalogue.md.
INVARIANTS: dict[str, str] = {
    "INV-B16-a": "test_b16_terminal_events_revoke_with_reason_and_kill_elevation",
    "INV-B16-b": "test_b16_terminal_events_revoke_with_reason_and_kill_elevation",
    "INV-B16-c": "deferred:E09",
    "INV-B16-d": "test_b16_revoked_is_terminal",
    "INV-B16-e": "deferred:E09",
    "INV-B16-f": "test_b16_unlock_never_unrevokes_or_reelevates",
    "INV-B16-g": "test_b16_only_an_audited_unlock_ok_lifts_the_lock",
}


def test_b16_revoked_is_terminal() -> None:
    from candleviewer.statechart.registry import Registry
    from tests.xstate_contract._harness import is_terminal

    assert is_terminal(Registry().get("session"), "auth.revoked")


def test_b16_invariant_ledger_matches_catalogue() -> None:
    from tests.xstate_contract.membership import check_ledger

    check_ledger(16, INVARIANTS, globals())


# -- #2301: the idle lock is the non-terminal `auth.idle_locked` ---------------


async def test_b16_lock_is_not_revocation_and_drops_elevation(
    b16_audit: RecordingAuditSink,
) -> None:
    interp = await _active()
    try:
        await _step_up(interp, "keys")
        await _send(interp, "IDLE_DEADLINE")
        assert _leaves(interp) == _LOCKED
        ctx = interp.context
        assert ctx["revoke_reason"] is None and ctx["idle_locked"] is True
        assert ctx["elevated_until_us"] is None and ctx["elevated_classes"] == {}
        assert ctx["one_click_armed"] is False
        assert b16_audit.actions()[-1] == "auth.idle_locked"
        assert "auth.session_revoked" not in b16_audit.actions()
    finally:
        await interp.stop()


async def test_b16_unlock_restores_active_without_elevation(
    b16_audit: RecordingAuditSink,
) -> None:
    interp = await _active()
    try:
        await _step_up(interp, "keys")
        await _send(interp, "IDLE_DEADLINE")
        await _send(interp, "UNLOCK_OK", idle_expires_at_us=900 * _US)
        assert _leaves(interp) == {"auth.active", "elevation.normal"}
        assert interp.context["idle_expires_at_us"] == 900 * _US
        assert interp.context["one_click_armed"] is False  # unlock never re-arms
        assert b16_audit.actions()[-1] == "auth.session_unlocked"
        assert b16_audit.actions().count("auth.login") == 1  # MFA_OK only: unlock is no login
    finally:
        await interp.stop()


async def test_b16_fifth_unlock_failure_revokes_with_reason_locked(
    b16_audit: RecordingAuditSink,
) -> None:
    cap = b16_session.UNLOCK_ATTEMPT_CAP
    interp = await _active()
    try:
        await _send(interp, "IDLE_DEADLINE")
        for n in range(1, cap):
            await _send(interp, "UNLOCK_FAILED")
            assert _leaves(interp) == _LOCKED and interp.context["unlock_attempts"] == n
        assert b16_audit.actions().count("auth.unlock_failed") == cap - 1
        await _send(interp, "UNLOCK_FAILED")
        assert _leaves(interp) == {"auth.revoked", "elevation.dead"}
        assert interp.context["revoke_reason"] == "locked"
        assert b16_audit.actions()[-1] == "auth.session_revoked"
    finally:
        await interp.stop()


@pytest.mark.parametrize("event", ["REQUEST", "STEP_UP_OK"])
async def test_b16_activity_while_locked_is_ignored_and_audited(
    event: str, b16_audit: RecordingAuditSink
) -> None:
    interp = await _active()
    try:
        await _send(interp, "IDLE_DEADLINE")
        await _send(interp, event, idle_expires_at_us=9 * _US, elevated_until_us=9 * _US)
        assert _leaves(interp) == _LOCKED and interp.deferred_count == 0
        assert interp.context["idle_expires_at_us"] == 0  # activity never re-stamps a lock
        assert interp.context["elevated_classes"] == {}
        call = b16_audit.calls[-1]
        assert call["action"] == "auth.request_ignored" and call["reason"] == event
    finally:
        await interp.stop()


async def test_b16_readonly_downgrade_survives_lock_and_unlock() -> None:
    interp = await _active()
    try:
        for _ in range(3):
            await _send(interp, "STEP_UP_FAILED", now_us=10 * _US)
        for event in ("IDLE_DEADLINE", "IDLE_DEADLINE"):  # a repeated lock signal is inert
            await _send(interp, event)
            assert _leaves(interp) == {"auth.idle_locked", "elevation.readonly_downgrade"}
        await _send(interp, "UNLOCK_OK")
        assert _leaves(interp) == {"auth.active", "elevation.readonly_downgrade"}
        assert interp.context["readonly_until_us"] == 310 * _US
        await _send(interp, "READONLY_EXPIRED")
        assert _leaves(interp) == {"auth.active", "elevation.normal"}
    finally:
        await interp.stop()


async def test_b16_lock_signal_after_revocation_never_reopens_elevation() -> None:
    """A literal root hoist `IDLE_DEADLINE -> elevation.normal` left `dead` for
    `normal`, and `STEP_UP_OK` then re-elevated a revoked session (C-04 class)."""
    interp = await _active()
    try:
        await _send(interp, "LOGOUT")
        await _send(interp, "IDLE_DEADLINE")
        assert _leaves(interp) == {"auth.revoked", "elevation.dead"}
        assert not interp.can("STEP_UP_OK")
    finally:
        await interp.stop()


@pytest.mark.parametrize("event", ["UNLOCK_OK", "UNLOCK_FAILED"])
async def test_b16_unlock_outside_a_lock_is_absorbed_never_replayed(
    event: str, b16_audit: RecordingAuditSink
) -> None:
    """Deferred (`onUnhandled: defer`), a stray unlock would replay into the next
    lock and lift it without a password."""
    interp = await _active()
    try:
        await _send(interp, event)
        assert interp.deferred_count == 0
        assert b16_audit.calls[-1]["action"] == "auth.request_ignored"
        await _send(interp, "IDLE_DEADLINE")
        assert _leaves(interp) == _LOCKED and interp.context["unlock_attempts"] == 0
    finally:
        await interp.stop()


async def test_b16_each_lock_starts_a_fresh_unlock_count() -> None:
    interp = await _active()
    try:
        for event in ("IDLE_DEADLINE", "UNLOCK_FAILED", "UNLOCK_FAILED", "UNLOCK_OK"):
            await _send(interp, event)
        assert interp.context["unlock_attempts"] == 0
        await _send(interp, "IDLE_DEADLINE")
        assert _leaves(interp) == _LOCKED and interp.context["unlock_attempts"] == 0
    finally:
        await interp.stop()


async def test_b16_lock_publishes_the_one_click_disarm_flag() -> None:
    published: list[tuple[str, bool]] = []

    class _Arm:
        async def publish(self, session_id: str, *, armed: bool) -> None:
            published.append((session_id, armed))

    b16_session.set_one_click_publisher(_Arm())
    try:
        result = await build(
            "session", ctx={"session_id": "s-1"}, clock=SimulatedClock(), lane="platform"
        )
        interp = result.interpreter
        for event in ("MFA_OK", "IDLE_DEADLINE", "UNLOCK_OK"):
            await _send(interp, event)
        assert published == [("s-1", False)]
        await interp.stop()
    finally:
        b16_session.set_one_click_publisher(None)


def test_b16_catalogue_contract_matches_machine_json() -> None:
    """C-2.19: catalogue B16.1 is the machine JSON minus the keys no entry repeats."""
    text = _CATALOGUE.read_text(encoding="utf-8")
    block = re.search(r"### B16\.1 Contract \(normative\)\s*```json\n(.*?)\n```", text, re.S)
    assert block is not None
    chart = dict(Registry().get("session"))
    for key in ("version", "strictConfig", "maxIterations"):
        chart.pop(key)
    assert json.loads(block.group(1)) == chart


# -- properties over any event sequence (#2301, INV-B16-f/g) --------------------

_ALPHABET = sorted(all_events(Registry().get("session")))
#: Every event stays drawable; half the draws come from the lock vocabulary so
#: short sequences reach (and leave) `auth.idle_locked` often.
_LOCK_EVENTS = ("IDLE_DEADLINE", "UNLOCK_OK", "UNLOCK_FAILED", "STEP_UP_OK", "REQUEST")
_PROPS = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
_SEQ = st.lists(st.one_of(st.sampled_from(_ALPHABET), st.sampled_from(_LOCK_EVENTS)), max_size=20)
Step = tuple[str, frozenset[str], frozenset[str], list[str]]


async def _walk(seq: list[str]) -> list[Step]:
    """From `auth.active`: `(event, leaves before, leaves after, audit actions)` per step."""
    sink = RecordingAuditSink()
    b16_session.set_audit_sink(sink)
    interp = await _active()
    steps: list[Step] = []
    try:
        for event in seq:
            before, mark = _leaves(interp), len(sink.calls)
            await _send(interp, event)
            steps.append((event, before, _leaves(interp), sink.actions()[mark:]))
            assert interp.error is None and interp.is_running, seq
    finally:
        await interp.stop()
    return steps


@_PROPS
@given(seq=_SEQ)
async def test_b16_elevated_and_idle_locked_are_never_both_active(seq: list[str]) -> None:
    for _event, _before, after, _audit in await _walk(seq):
        assert not {"auth.idle_locked", "elevation.elevated"} <= after, seq


@_PROPS
@given(seq=_SEQ)
async def test_b16_unlock_never_unrevokes_or_reelevates(seq: list[str]) -> None:
    for event, before, after, _audit in await _walk([*seq, "UNLOCK_OK"]):
        if event == "UNLOCK_OK":
            assert "auth.revoked" not in before or "auth.revoked" in after, seq
            assert "elevation.elevated" in before or "elevation.elevated" not in after, seq


@_PROPS
@given(seq=_SEQ)
async def test_b16_only_an_audited_unlock_ok_lifts_the_lock(seq: list[str]) -> None:
    for event, before, after, audit in await _walk(seq):
        if "auth.idle_locked" in before and "auth.idle_locked" not in after:
            assert event == "UNLOCK_OK" or "auth.revoked" in after, seq
        if "auth.idle_locked" in before and "auth.active" in after:
            assert audit.count("auth.session_unlocked") == 1, seq

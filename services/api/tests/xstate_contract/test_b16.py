"""tests/xstate_contract/test_b16.py — B16 `session` golden traces (E09-S03, QA #1634).

Drives the B16 contract (`machines/B16.session.machine.json`) only through
`cv.statechart.factory.build` (C-2.19). Transition names follow
28-statechart-catalogue.md B16.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from xstate_statemachine import Interpreter, SimulatedClock

from candleviewer.statechart import build
from candleviewer.statechart.bindings import b16_session  # noqa: F401  (registers "session")


async def _start(lane: str = "platform") -> Interpreter:
    result = await build("session", clock=SimulatedClock(), lane=lane)  # type: ignore[arg-type]
    return result.interpreter


async def _active() -> Interpreter:
    interp = await _start()
    await interp.send("MFA_OK", wait=True)
    await interp.drain_pending()
    return interp


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


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        ("IDLE_DEADLINE", "idle"),
        ("ABSOLUTE_DEADLINE", "expired"),
        ("REVOKE", "admin"),
        ("LOGOUT", "logout"),
    ],
)
async def test_b16_terminal_events_revoke_with_reason_and_kill_elevation(
    event: str, reason: str
) -> None:
    interp = await _active()
    try:
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
    from candleviewer.statechart.bindings import b16_session as b

    assert b.NO_GRACE_ACTION_CLASSES == svc.NO_GRACE_ACTION_CLASSES
    assert b.ACTION_CLASSES == svc.ACTION_CLASSES
    assert b.STEP_UP_FAILURE_CAP == svc.FAILURE_CAP
    assert b.STEP_UP_GRACE_US == svc.GRACE_WINDOW // timedelta(microseconds=1)
    assert b.READONLY_DOWNGRADE_US == svc.READONLY_WINDOW // timedelta(microseconds=1)


# §B16.7 ledger (E50-T31 membership): pinned to 28-statechart-catalogue.md.
INVARIANTS: dict[str, str] = {
    "INV-B16-a": "test_b16_terminal_events_revoke_with_reason_and_kill_elevation",
    "INV-B16-b": "test_b16_terminal_events_revoke_with_reason_and_kill_elevation",
    "INV-B16-c": "deferred:E09",
    "INV-B16-d": "test_b16_revoked_is_terminal",
    "INV-B16-e": "deferred:E09",
    # #2301 contract-first: the idle-lock chart and its property tests land in slice 2/2.
    "INV-B16-f": "deferred:E09",
    "INV-B16-g": "deferred:E09",
}


def test_b16_revoked_is_terminal() -> None:
    from candleviewer.statechart.registry import Registry
    from tests.xstate_contract._harness import is_terminal

    assert is_terminal(Registry().get("session"), "auth.revoked")


def test_b16_invariant_ledger_matches_catalogue() -> None:
    from tests.xstate_contract.membership import check_ledger

    check_ledger(16, INVARIANTS, globals())

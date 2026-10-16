"""E27-T04 per-account health FSM (US-ACCT-010): AC Healthy, Degraded, Down within 30 s; suspend
and resume; wall-clock steps; positive evidence only, derived on every read (ticket Security
notes: health is never asserted optimistically)."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError
from structlog.testing import capture_logs

from candleviewer.accounts.health import (
    CONNECTION_STATE,
    DMS_RETRY_MIN_S,
    AccountHealthMonitor,
    HealthState,
    HealthThresholds,
    SystemClock,
)
from candleviewer.accounts.order_gate import AccountHealthCheck, KeyStanding
from candleviewer.observability.context import bind_context, get_context
from candleviewer.settings import Settings
from tests.unit.accounts._fakes import ACC, ACC_B, T0, Dms, FakeClock, Sizing, Standings


def _monitor() -> tuple[AccountHealthMonitor, FakeClock, Dms]:
    clock, dms = FakeClock(), Dms()
    monitor = AccountHealthMonitor(clock, dms)
    monitor.track(ACC)
    return monitor, clock, dms


def test_tracked_account_starts_down_without_invoking_the_dead_mans_switch() -> None:
    monitor, _, dms = _monitor()
    view = monitor.view(ACC)
    assert view is not None and (view.state, view.reason) == (HealthState.DOWN, "never_connected")
    assert view.heartbeat_age_ms is None and dms.calls == [] and monitor.tick() == []
    monitor.untrack(ACC)
    assert monitor.current(ACC) is None and monitor.view(ACC) is None


def test_authenticated_heartbeat_is_healthy_and_reports_its_age() -> None:
    monitor, clock, _ = _monitor()
    transition = monitor.ws_heartbeat(ACC)
    clock.advance(2.5)
    view = monitor.view(ACC)
    assert transition is not None and transition.to_state is HealthState.HEALTHY
    assert view is not None and view.state is HealthState.HEALTHY
    assert (view.reason, view.heartbeat_age_ms, view.rest_only) == ("ws_heartbeat", 2500, False)
    assert CONNECTION_STATE[view.state] == "connected"


def test_ws_drop_with_rest_polling_is_degraded_and_flags_rest_only() -> None:
    monitor, clock, _ = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(1)
    monitor.ws_dropped(ACC)
    monitor.rest_ok(ACC)
    view = monitor.view(ACC)
    assert view is not None and (view.state, view.reason) == (HealthState.DEGRADED, "rest_only")
    assert view.rest_only and CONNECTION_STATE[view.state] == "degraded"


def test_late_heartbeat_without_rest_is_degraded_ws_silent() -> None:
    monitor, clock, _ = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(10)
    assert monitor.tick() == []
    clock.advance(0.001)
    (transition,) = monitor.tick()
    assert (transition.to_state, transition.reason) == (HealthState.DEGRADED, "ws_silent")


async def test_down_exactly_at_the_down_window_invokes_the_dead_mans_switch_once() -> None:
    monitor, clock, dms = _monitor()
    monitor.rest_ok(ACC)
    clock.advance(29.999)
    monitor.tick()
    await monitor.drain()
    assert monitor.current(ACC) is HealthState.DEGRADED and dms.calls == []
    clock.advance(0.001)
    with capture_logs() as logs:
        (transition,) = monitor.tick()
        await monitor.drain()
    assert (transition.from_state, transition.to_state) == (HealthState.DEGRADED, HealthState.DOWN)
    assert transition.at == clock.wall and dms.transitions == [transition]
    assert logs[0]["event"] == "account.health_changed" and logs[0]["to_state"] == "down"
    clock.advance(5)
    assert monitor.tick() == []
    await monitor.drain()
    assert len(dms.calls) == 1


async def test_suspend_past_the_down_window_resumes_down_not_healthy() -> None:
    monitor, clock, dms = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.mono += 600  # the boot-time clock counted the suspend; no event ran meanwhile
    (transition,) = monitor.tick()
    await monitor.drain()
    assert transition.to_state is HealthState.DOWN and dms.calls == [(ACC, "no_success")]


@pytest.mark.parametrize("step", [timedelta(minutes=5), timedelta(minutes=-5)])
def test_a_wall_clock_step_changes_no_state(step: timedelta) -> None:
    monitor, clock, _ = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.wall += step
    assert monitor.tick() == [] and monitor.current(ACC) is HealthState.HEALTHY


def test_thresholds_come_from_settings_and_must_be_ordered() -> None:
    settings_ = Settings(account_heartbeat_s=5, account_down_s=20)
    assert HealthThresholds.from_settings(settings_) == HealthThresholds(5, 20)
    with pytest.raises(ValueError, match="heartbeat_s < down_s"):
        HealthThresholds(10, 10)


@pytest.mark.parametrize(
    "bad",
    [
        {"account_heartbeat_s": 10.001},
        {"account_down_s": 30.001},
        {"account_heartbeat_s": 0},
        {"account_down_s": 0},
    ],
)
def test_health_windows_cannot_exceed_the_us_acct_010_nfr(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(**bad)


def test_the_us_acct_010_limits_themselves_are_accepted() -> None:
    settings_ = Settings(account_heartbeat_s=10, account_down_s=30)
    assert HealthThresholds.from_settings(settings_) == HealthThresholds(10, 30)


@pytest.mark.parametrize("cadence", [5.0, 9.9, 10.0])
def test_a_heartbeat_at_least_every_window_keeps_an_idle_account_healthy(cadence: float) -> None:
    monitor, clock, _ = _monitor()
    monitor.ws_heartbeat(ACC)
    for _ in range(12):  # two minutes of pongs on an account with no other traffic
        clock.advance(cadence)
        assert monitor.tick() == [] and monitor.ws_heartbeat(ACC) is None
    assert monitor.current(ACC) is HealthState.HEALTHY


def test_system_clock_is_tz_aware_and_monotonic_off_linux_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = SystemClock()
    assert clock.now().tzinfo is not None and clock.monotonic() <= clock.monotonic()
    monkeypatch.setattr(sys, "platform", "darwin")
    assert clock.monotonic() > 0


def test_a_read_before_tick_and_the_commit_after_it_agree() -> None:
    monitor, clock, _ = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(12)
    view = monitor.view(ACC)
    (transition,) = monitor.tick()
    assert view is not None and (view.state, view.reason) == (HealthState.DEGRADED, "ws_silent")
    assert view.changed_at == transition.at == T0 + timedelta(seconds=10)


async def test_evidence_after_an_unticked_lapse_still_records_the_down_episode() -> None:
    monitor, clock, dms = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(600)  # resumed from suspend; the socket re-authenticates before any tick
    with capture_logs() as logs:
        transition = monitor.ws_heartbeat(ACC)
        await monitor.drain()
    assert transition is not None and transition.to_state is HealthState.HEALTHY
    assert [e["to_state"] for e in logs] == ["down", "healthy"]
    assert dms.calls == [(ACC, "no_success")]


async def test_a_raising_hook_is_logged_per_account_and_stops_no_other_account() -> None:
    clock, dms = FakeClock(), Dms(ACC)
    monitor = AccountHealthMonitor(clock, dms)
    for account in (ACC, ACC_B):
        monitor.track(account)
        monitor.ws_heartbeat(account)
    clock.advance(31)
    with capture_logs() as logs:
        moved = monitor.tick()
        await monitor.drain()
    assert [(t.account_id, t.to_state) for t in moved] == [
        (ACC, HealthState.DOWN),
        (ACC_B, HealthState.DOWN),
    ]
    assert dms.calls == [(ACC, "no_success"), (ACC_B, "no_success")]
    failed = [e for e in logs if e["event"] == "account.dms_hook_failed"]
    assert failed == [
        {
            "event": "account.dms_hook_failed",
            "log_level": "error",
            "account_id": str(ACC),
            "reason": "no_success",
            "error": "RuntimeError",
        }
    ]
    assert "retMsg" not in repr(logs)


async def test_the_hook_runs_as_a_named_task_under_the_account_and_caller_context() -> None:
    monitor, clock, dms = _monitor()
    monitor.rest_ok(ACC)
    clock.advance(30)
    with bind_context(conn_id="ws-1"):
        monitor.tick()
        assert get_context() == {"conn_id": "ws-1"}  # the account binding stays with the call
    await monitor.drain()
    assert dms.contexts == [{"conn_id": "ws-1", "account_id": str(ACC)}]
    assert dms.task_names == [f"account-dms:{ACC}"]


_EVALUATIONS: dict[str, Callable[[AccountHealthMonitor], object]] = {
    "tick": lambda monitor: monitor.tick(),
    "ws_heartbeat": lambda monitor: monitor.ws_heartbeat(ACC),
    "ws_dropped": lambda monitor: monitor.ws_dropped(ACC),
    "rest_ok": lambda monitor: monitor.rest_ok(ACC),
}


@pytest.mark.parametrize("evaluate", list(_EVALUATIONS.values()), ids=list(_EVALUATIONS))
async def test_a_failed_hook_call_is_made_again_by_the_first_evaluation_after_its_delay(
    evaluate: Callable[[AccountHealthMonitor], object],
) -> None:
    clock, dms = FakeClock(), Dms(ACC)
    monitor = AccountHealthMonitor(clock, dms)
    monitor.track(ACC)
    monitor.rest_ok(ACC)
    clock.advance(30)
    (down,) = monitor.tick()
    await monitor.drain()
    dms.failing.clear()
    evaluate(monitor)  # inside the retry delay: no call
    await monitor.drain()
    assert dms.transitions == [down]
    clock.advance(DMS_RETRY_MIN_S)
    evaluate(monitor)
    await monitor.drain()
    evaluate(monitor)
    await monitor.drain()
    assert dms.transitions == [down, down]


async def test_a_failing_hook_is_retried_at_doubling_delays_capped_at_the_down_window() -> None:
    clock = FakeClock()
    dms = Dms(ACC, clock=clock)
    monitor = AccountHealthMonitor(clock, dms)
    monitor.track(ACC)
    monitor.rest_ok(ACC)
    clock.advance(30)
    down_at = clock.mono
    for _ in range(121):  # two minutes of ticks at the 1 s cadence
        monitor.tick()
        await monitor.drain()
        clock.advance(1)
    assert [at - down_at for at in dms.called_at] == [0, 1, 3, 7, 15, 31, 61, 91]


async def test_a_new_down_episode_restarts_the_retry_delay_from_the_shortest() -> None:
    clock = FakeClock()
    dms = Dms(ACC, clock=clock)
    monitor = AccountHealthMonitor(clock, dms)
    monitor.track(ACC)
    monitor.rest_ok(ACC)
    for step in (30, 1, 2):  # down, then two failed retries: the next delay is 4 s
        clock.advance(step)
        monitor.tick()
        await monitor.drain()
    monitor.rest_ok(ACC)  # recovered while the old episode backs off
    for step in (30, 1):  # silent for the down window: a new episode, then 1 s later
        clock.advance(step)
        monitor.tick()
        await monitor.drain()
    assert [at - dms.called_at[0] for at in dms.called_at] == [0, 1, 3, 33, 34]
    episodes = [t.at - T0 for t in dms.transitions]
    assert episodes == [timedelta(seconds=30)] * 3 + [timedelta(seconds=63)] * 2


async def test_a_slow_hook_blocks_neither_evidence_nor_tick_and_is_never_doubled() -> None:
    monitor, clock, dms = _monitor()
    dms.hold = asyncio.Event()
    monitor.rest_ok(ACC)
    clock.advance(30)
    (down,) = monitor.tick()
    await dms.entered.wait()  # the hook is now mid-call, and stays there
    recovered = monitor.ws_heartbeat(ACC)
    clock.advance(1)
    assert monitor.tick() == [] and dms.transitions == [down]
    assert recovered is not None and recovered.to_state is HealthState.HEALTHY
    dms.hold.set()
    await monitor.drain()
    monitor.tick()
    await monitor.drain()
    assert dms.transitions == [down]


async def test_a_hook_call_that_outlives_its_timeout_is_logged_and_made_again() -> None:
    clock, dms = FakeClock(), Dms()
    monitor = AccountHealthMonitor(clock, dms, dms_timeout_s=0.001)
    monitor.track(ACC)
    dms.hold = asyncio.Event()  # never set: the call hangs until its timeout cancels it
    monitor.rest_ok(ACC)
    clock.advance(30)
    with capture_logs() as logs:
        (down,) = monitor.tick()
        async with asyncio.timeout(5):  # fails fast, not hangs, if the hook timeout is lost
            await monitor.drain()
    errors = [(e["event"], e["error"]) for e in logs if e["log_level"] == "error"]
    assert errors == [("account.dms_hook_failed", "TimeoutError")]
    dms.hold = None
    clock.advance(DMS_RETRY_MIN_S)
    for _ in range(2):
        monitor.tick()
        await monitor.drain()
    assert dms.transitions == [down, down]


@pytest.mark.parametrize("fails", [False, True], ids=["returns", "raises"])
async def test_a_down_episode_during_a_call_in_flight_is_delivered_after_it(fails: bool) -> None:
    monitor, clock, dms = _monitor()
    dms.failing = {ACC} if fails else set()
    dms.hold = asyncio.Event()
    monitor.rest_ok(ACC)
    clock.advance(30)
    (first,) = monitor.tick()
    await dms.entered.wait()
    monitor.rest_ok(ACC)
    clock.advance(30)
    (second,) = monitor.tick()  # down again while the first call is still in flight
    dms.hold.set()
    await monitor.drain()
    monitor.tick()  # the first call's failure does not delay the newer episode
    await monitor.drain()
    assert dms.transitions == [first, second]


async def test_untracking_an_account_that_is_owed_a_call_logs_the_drop() -> None:
    clock, dms = FakeClock(), Dms(ACC)
    monitor = AccountHealthMonitor(clock, dms)
    monitor.track(ACC)
    monitor.rest_ok(ACC)
    clock.advance(30)
    monitor.tick()
    await monitor.drain()
    with capture_logs() as logs:
        monitor.untrack(ACC)
        monitor.untrack(ACC)
    monitor.tick()
    await monitor.drain()
    assert logs == [
        {
            "event": "account.dms_hook_dropped",
            "log_level": "warning",
            "account_id": str(ACC),
            "reason": "no_success",
        }
    ]
    assert len(dms.calls) == 1


async def test_draining_with_a_call_still_owed_logs_the_drop() -> None:
    clock, dms = FakeClock(), Dms(ACC)
    monitor = AccountHealthMonitor(clock, dms)
    for account in (ACC, ACC_B):
        monitor.track(account)
        monitor.rest_ok(account)
    clock.advance(30)
    owed, _ = monitor.tick()  # ACC's hook call fails, ACC_B's returns
    with capture_logs() as logs:
        await monitor.drain()
    assert [e for e in logs if e["event"] == "account.dms_hook_dropped"] == [
        {
            "event": "account.dms_hook_dropped",
            "log_level": "warning",
            "account_id": str(ACC),
            "reason": "no_success",
        }
    ]
    assert monitor.owed() == [owed]


@pytest.mark.parametrize("evidence", ["ws_heartbeat", "ws_dropped", "rest_ok"])
def test_evidence_for_an_untracked_account_is_ignored(evidence: str) -> None:
    monitor, _, dms = _monitor()
    monitor.untrack(ACC)
    assert getattr(monitor, evidence)(ACC) is None
    assert monitor.current(ACC) is None and monitor.view(ACC) is None and dms.calls == []


def test_tracking_an_account_again_keeps_its_evidence() -> None:
    monitor, _, _ = _monitor()
    monitor.ws_heartbeat(ACC)
    monitor.track(ACC)
    assert monitor.current(ACC) is HealthState.HEALTHY


#: Steps in whole milliseconds, so the fake's wall clock (timedelta, microseconds) and monotonic
#: clock (float seconds) agree exactly and `changed_at` can be compared with the wall clock.
_STEP = st.integers(0, 40_000).map(lambda ms: ms / 1000)
_EVENTS = st.lists(st.tuples(_STEP, st.sampled_from(["hb", "drop", "rest", "tick", "read"])))


@settings(max_examples=200, deadline=None, derandomize=True)
@given(_EVENTS)
async def test_health_never_outlives_its_evidence(events: list[tuple[float, str]]) -> None:
    monitor, clock, dms = _monitor()
    gate = AccountHealthCheck(monitor, Standings({ACC: KeyStanding(True)}), Sizing({ACC: True}))
    act = {"hb": monitor.ws_heartbeat, "drop": monitor.ws_dropped, "rest": monitor.rest_ok}
    seen: dict[str, float] = {}
    live, changed = False, T0
    with capture_logs() as logs:
        for dt, kind in events:
            clock.advance(dt)
            if kind in act:
                seen[kind], live = clock.mono, (live or kind == "hb") and kind != "drop"
                act[kind](ACC)
            elif kind == "tick":
                monitor.tick()
            await monitor.drain()
            state, view, refusal = monitor.current(ACC), monitor.view(ACC), gate.refusal(ACC)
            last = max(seen.get(k, -1e9) for k in ("hb", "rest"))
            if state is HealthState.HEALTHY:
                assert live and clock.mono - seen["hb"] <= 10
            assert (state is HealthState.DOWN) == (clock.mono - last >= 30)
            assert (refusal is not None) == (state is HealthState.DOWN)
            assert view is not None and view.state is state
            assert changed <= view.changed_at <= clock.wall
            changed = view.changed_at
    downs = [e for e in logs if e.get("to_state") == "down"]
    assert dms.calls == [(ACC, "no_success")] * len(downs)

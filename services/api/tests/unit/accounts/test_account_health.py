"""E27-T04 per-account health FSM (US-ACCT-010): AC Healthy, Degraded, Down within 30 s; suspend
and resume, whether or not the boot-time clock counts it; wall-clock steps; positive evidence only,
derived on every read (ticket Security notes: health is never asserted optimistically). The
dead-man's-switch hook is owed a call for every transition into `down` and gets it, retried with
jittered backoff until one returns."""

from __future__ import annotations

import asyncio
import inspect
import math
import sys
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.accounts.health import (
    CONNECTION_STATE,
    DMS_HOOK_TIMEOUT_S,
    DMS_RETRY_MIN_S,
    AccountHealthMonitor,
    HealthState,
    HealthThresholds,
    SystemClock,
    epoch_ms,
)
from candleviewer.observability.context import bind_context, get_context
from candleviewer.settings import ACCOUNT_DOWN_MAX_S, ACCOUNT_HEARTBEAT_MAX_S, Settings
from tests.unit.accounts._fakes import ACC, ACC_B, T0, Dms, FakeClock, Jitter


def _monitor() -> tuple[AccountHealthMonitor, FakeClock]:
    clock = FakeClock()
    monitor = AccountHealthMonitor(clock, Dms())
    monitor.track(ACC)
    return monitor, clock


def _hooked(
    *failing: UUID, rng: Jitter | None = None
) -> tuple[AccountHealthMonitor, FakeClock, Dms]:
    """A monitor whose hook fails for the `failing` accounts and records when it is called; the
    retry jitter is `rng`, by default none, so retry times are exact."""
    clock = FakeClock()
    dms = Dms(*failing, clock=clock)
    monitor = AccountHealthMonitor(clock, dms, rng=rng or Jitter())
    monitor.track(ACC)
    return monitor, clock, dms


def test_tracked_account_starts_down_without_invoking_the_dead_mans_switch() -> None:
    monitor, _, dms = _hooked()
    view = monitor.view(ACC)
    assert view is not None and (view.state, view.reason) == (HealthState.DOWN, "never_connected")
    assert view.heartbeat_age_ms is None and dms.calls == [] and monitor.tick() == []
    monitor.untrack(ACC)
    assert monitor.current(ACC) is None and monitor.view(ACC) is None


def test_authenticated_heartbeat_is_healthy_and_reports_its_age() -> None:
    monitor, clock = _monitor()
    transition = monitor.ws_heartbeat(ACC)
    clock.advance(2.5)
    view = monitor.view(ACC)
    assert transition is not None and transition.to_state is HealthState.HEALTHY
    assert view is not None and view.state is HealthState.HEALTHY
    assert (view.reason, view.heartbeat_age_ms, view.rest_only) == ("ws_heartbeat", 2500, False)
    assert CONNECTION_STATE[view.state] == "connected"


def test_ws_drop_with_rest_polling_is_degraded_and_flags_rest_only() -> None:
    monitor, clock = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(1)
    monitor.ws_dropped(ACC)
    monitor.rest_ok(ACC)
    view = monitor.view(ACC)
    assert view is not None and (view.state, view.reason) == (HealthState.DEGRADED, "rest_only")
    assert view.rest_only and CONNECTION_STATE[view.state] == "degraded"


def test_a_rest_success_one_down_window_old_no_longer_counts_as_polling() -> None:
    monitor, clock = _monitor()
    monitor.rest_ok(ACC)
    clock.advance(5)
    monitor.ws_heartbeat(ACC)
    monitor.ws_dropped(ACC)
    clock.advance(25)  # the REST success is exactly `down_s` old, the WS one 25 s
    view = monitor.view(ACC)
    assert view is not None and (view.state, view.reason) == (HealthState.DEGRADED, "ws_silent")


def test_late_heartbeat_without_rest_is_degraded_ws_silent() -> None:
    monitor, clock = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(10)
    assert monitor.tick() == []
    clock.advance(0.001)
    (transition,) = monitor.tick()
    assert (transition.to_state, transition.reason) == (HealthState.DEGRADED, "ws_silent")
    view = monitor.view(ACC)
    assert view is not None and view.rest_only is True


async def test_down_exactly_at_the_down_window_invokes_the_dead_mans_switch_once() -> None:
    monitor, clock, dms = _hooked()
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


async def test_a_suspend_the_boot_clock_counts_resumes_down_not_healthy() -> None:
    monitor, clock, dms = _hooked()
    monitor.ws_heartbeat(ACC)
    clock.mono += 600  # the boot-time clock counted the suspend; no event ran meanwhile
    (transition,) = monitor.tick()
    await monitor.drain()
    assert (transition.to_state, transition.reason) == (HealthState.DOWN, "no_success")
    assert transition.at == T0 + timedelta(seconds=30)  # when the down window lapsed
    assert dms.calls == [(ACC, "no_success")]


def test_a_suspend_the_boot_clock_misses_reads_healthy_one_heartbeat_window_at_most() -> None:
    monitor, clock = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.wall += timedelta(hours=1)  # the host slept, unseen by the boot-time clock (WSL2)
    assert monitor.current(ACC) is HealthState.HEALTHY
    clock.mono += 10.001  # no evidence follows the resume
    assert monitor.current(ACC) is HealthState.DEGRADED


@pytest.mark.parametrize("step", [timedelta(minutes=5), timedelta(minutes=-5)])
def test_a_wall_clock_step_changes_no_state(step: timedelta) -> None:
    monitor, clock = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.wall += step
    assert monitor.tick() == [] and monitor.current(ACC) is HealthState.HEALTHY


def test_thresholds_come_from_settings() -> None:
    settings_ = Settings(account_heartbeat_s=5, account_down_s=20)
    assert HealthThresholds.from_settings(settings_) == HealthThresholds(5, 20)


@pytest.mark.parametrize(("heartbeat", "down"), [(10, 10), (0, 5), (-1, 5)])
def test_thresholds_must_be_positive_and_ordered(heartbeat: float, down: float) -> None:
    with pytest.raises(ValueError, match="0 < heartbeat_s < down_s"):
        HealthThresholds(heartbeat, down)


@pytest.mark.parametrize(("heartbeat", "down"), [(10.001, 30), (10, 30.001), (11, 31)])
def test_thresholds_cannot_exceed_the_us_acct_010_caps(heartbeat: float, down: float) -> None:
    with pytest.raises(ValueError, match="capped at"):
        HealthThresholds(heartbeat, down)


def test_thresholds_at_the_us_acct_010_caps_are_accepted() -> None:
    assert HealthThresholds(10, 30) == HealthThresholds(ACCOUNT_HEARTBEAT_MAX_S, ACCOUNT_DOWN_MAX_S)


def test_the_defaults_are_the_us_acct_010_caps_in_thresholds_and_settings() -> None:
    assert HealthThresholds() == HealthThresholds(10, 30)
    assert HealthThresholds.from_settings(Settings()) == HealthThresholds()


def test_the_us_acct_010_limits_themselves_are_accepted() -> None:
    settings_ = Settings(account_heartbeat_s=10, account_down_s=30)
    assert HealthThresholds.from_settings(settings_) == HealthThresholds(10, 30)


@pytest.mark.parametrize("cadence", [5.0, 9.9, 10.0])
def test_a_heartbeat_at_least_every_window_keeps_an_idle_account_healthy(cadence: float) -> None:
    monitor, clock = _monitor()
    monitor.ws_heartbeat(ACC)
    for _ in range(12):  # two minutes of pongs on an account with no other traffic
        clock.advance(cadence)
        assert monitor.tick() == [] and monitor.ws_heartbeat(ACC) is None
    assert monitor.current(ACC) is HealthState.HEALTHY


def test_system_clock_now_is_tz_aware() -> None:
    assert SystemClock().now().tzinfo is not None


def test_system_clock_monotonic_never_runs_backwards() -> None:
    clock = SystemClock()
    assert clock.monotonic() <= clock.monotonic()


def test_system_clock_monotonic_works_off_linux_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    assert SystemClock().monotonic() > 0


def test_wire_timestamps_are_epoch_milliseconds() -> None:
    monitor, clock = _monitor()
    clock.advance(1.5)
    monitor.ws_heartbeat(ACC)
    view = monitor.view(ACC)
    assert view is not None and epoch_ms(T0) == 1_792_065_600_000
    assert view.ws_entry(ACC)["changed_at_ms"] == epoch_ms(T0) + 1_500


def test_a_read_before_tick_and_the_commit_after_it_agree() -> None:
    monitor, clock = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(12)
    view = monitor.view(ACC)
    (transition,) = monitor.tick()
    assert view is not None and (view.state, view.reason) == (HealthState.DEGRADED, "ws_silent")
    assert view.changed_at == transition.at == T0 + timedelta(seconds=10)


async def test_each_of_two_lapses_a_late_tick_finds_is_dated_when_it_lapsed() -> None:
    monitor, clock = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(12)
    (degraded,) = monitor.tick()
    clock.advance(28)
    (down,) = monitor.tick()
    await monitor.drain()
    assert (degraded.to_state, degraded.at) == (HealthState.DEGRADED, T0 + timedelta(seconds=10))
    assert (down.to_state, down.at) == (HealthState.DOWN, T0 + timedelta(seconds=30))


async def test_evidence_after_an_unticked_lapse_still_records_the_down_episode() -> None:
    monitor, clock, dms = _hooked()
    monitor.ws_heartbeat(ACC)
    clock.advance(600)  # resumed from suspend; the socket re-authenticates before any tick
    with capture_logs() as logs:
        transition = monitor.ws_heartbeat(ACC)
        await monitor.drain()
    assert transition is not None and transition.to_state is HealthState.HEALTHY
    assert [e["to_state"] for e in logs] == ["down", "healthy"]
    assert dms.calls == [(ACC, "no_success")]


@pytest.mark.parametrize("first", ["ws_heartbeat", "rest_ok"])
async def test_a_rest_success_after_an_unticked_lapse_still_records_the_down_episode(
    first: str,
) -> None:
    monitor, clock, dms = _hooked()
    getattr(monitor, first)(ACC)
    clock.advance(600)  # resumed from suspend; the next REST poll succeeds before any tick
    with capture_logs() as logs:
        transition = monitor.rest_ok(ACC)
        await monitor.drain()
    assert transition is not None and transition.to_state is HealthState.DEGRADED
    assert (transition.from_state, transition.reason) == (HealthState.DOWN, "rest_only")
    assert [e["to_state"] for e in logs] == ["down", "degraded"]
    assert dms.calls == [(ACC, "no_success")]


@pytest.mark.parametrize("evidence", ["ws_heartbeat", "ws_dropped", "rest_ok"])
def test_evidence_for_an_untracked_account_is_ignored(evidence: str) -> None:
    monitor, _ = _monitor()
    monitor.untrack(ACC)
    assert getattr(monitor, evidence)(ACC) is None
    assert monitor.current(ACC) is None and monitor.view(ACC) is None


def test_tracking_an_account_again_keeps_its_evidence() -> None:
    monitor, _ = _monitor()
    monitor.ws_heartbeat(ACC)
    monitor.track(ACC)
    assert monitor.current(ACC) is HealthState.HEALTHY


async def test_a_raising_hook_is_logged_per_account_and_stops_no_other_account() -> None:
    monitor, clock, dms = _hooked(ACC)
    monitor.track(ACC_B)
    for account in (ACC, ACC_B):
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
    assert "echoed exchange text" not in repr(logs)


async def test_the_hook_runs_as_a_named_task_under_the_account_and_caller_context() -> None:
    monitor, clock, dms = _hooked()
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
    monitor, clock, dms = _hooked(ACC)
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
    monitor, clock, dms = _hooked(ACC)
    monitor.rest_ok(ACC)
    clock.advance(30)
    down_at = clock.mono
    for _ in range(121):  # two minutes of ticks at the 1 s cadence
        monitor.tick()
        await monitor.drain()
        clock.advance(1)
    assert [at - down_at for at in dms.called_at] == [0, 1, 3, 7, 15, 31, 61, 91]


async def test_each_retry_waits_a_draw_from_the_upper_half_of_its_backoff() -> None:
    rng = Jitter(0.0)  # every draw at the low end of its range: half the backoff
    monitor, clock, dms = _hooked(ACC, rng=rng)
    monitor.rest_ok(ACC)
    clock.advance(30)
    down_at = clock.mono
    for _ in range(61):
        monitor.tick()
        await monitor.drain()
        clock.advance(1)
    assert rng.ranges == [(0.5, 1), (1, 2), (2, 4), (4, 8), (8, 16), (15, 30), (15, 30), (15, 30)]
    assert [at - down_at for at in dms.called_at] == [0, 1, 2, 4, 8, 16, 31, 46]


async def test_a_new_down_episode_restarts_the_retry_delay_from_the_shortest() -> None:
    monitor, clock, dms = _hooked(ACC)
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


async def test_a_new_down_episode_is_called_at_once_inside_the_old_retry_delay() -> None:
    monitor, clock, dms = _hooked(ACC)
    monitor.rest_ok(ACC)
    clock.advance(30)
    for second in range(33):  # the old episode keeps failing after the account recovers at 2 s
        if second == 2:
            monitor.rest_ok(ACC)
        monitor.tick()
        await monitor.drain()
        clock.advance(1)
    # Its call at 31 s backed off to 61 s; the new episode, down at 32 s, does not wait for that.
    assert [at - dms.called_at[0] for at in dms.called_at] == [0, 1, 3, 7, 15, 31, 32]
    episodes = [t.at - T0 for t in dms.transitions]
    assert episodes == [timedelta(seconds=30)] * 6 + [timedelta(seconds=62)]


async def test_a_slow_hook_blocks_neither_evidence_nor_tick_and_is_never_doubled() -> None:
    monitor, clock, dms = _hooked()
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
    monitor = AccountHealthMonitor(clock, dms, dms_timeout_s=0.001, rng=Jitter())
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


@pytest.mark.parametrize("timeout", [0, -1.0, math.inf, math.nan])
def test_the_hook_timeout_must_be_finite_and_positive(timeout: float) -> None:
    with pytest.raises(ValueError, match="dms_timeout_s"):
        AccountHealthMonitor(FakeClock(), Dms(), dms_timeout_s=timeout)


def test_the_default_hook_timeout_is_five_seconds_inside_the_down_window() -> None:
    default = inspect.signature(AccountHealthMonitor).parameters["dms_timeout_s"].default
    assert DMS_HOOK_TIMEOUT_S == default == 5.0
    assert DMS_HOOK_TIMEOUT_S < HealthThresholds().down_s


async def test_a_hook_that_swallows_its_cancellation_is_abandoned_and_holds_nothing_up() -> None:
    clock, dms = FakeClock(), Dms()
    dms.stubborn, dms.hold = True, asyncio.Event()  # held, and it swallows every cancellation
    monitor = AccountHealthMonitor(clock, dms, dms_timeout_s=0.001, rng=Jitter())
    monitor.track(ACC)
    monitor.rest_ok(ACC)
    clock.advance(30)
    try:
        with capture_logs() as logs:
            (first,) = monitor.tick()
            async with asyncio.timeout(5):  # fails fast, not hangs, if the post-cancel wait is lost
                await monitor.drain()
        errors = [(e["event"], e["account_id"]) for e in logs if e["log_level"] == "error"]
        stuck, failed = ("account.dms_hook_stuck", str(ACC)), ("account.dms_hook_failed", str(ACC))
        assert errors == [stuck, failed]
        assert monitor.owed() == [first]  # no call returned: still owed, and listed for the wiring
        monitor.rest_ok(ACC)  # recovered, then down again: the stuck call does not hold the account
        clock.advance(30)
        (second,) = monitor.tick()
        async with asyncio.timeout(5):
            await monitor.drain()
        assert dms.transitions == [first, second] and dms.active == 2  # both hooks still running
        dms.failing.add(ACC)  # released, each abandoned hook raises: counted once already
        with capture_logs() as late:
            dms.hold.set()
            async with asyncio.timeout(5):
                await dms.idle.wait()
        assert late == []
    finally:
        dms.hold.set()  # a failed assertion must not leave a hook that never ends


@pytest.mark.parametrize("fails", [False, True], ids=["returns", "raises"])
async def test_a_down_episode_during_a_call_in_flight_is_delivered_after_it(fails: bool) -> None:
    monitor, clock, dms = _hooked(*([ACC] if fails else []))
    dms.hold = asyncio.Event()
    monitor.rest_ok(ACC)
    clock.advance(30)
    (first,) = monitor.tick()
    await dms.entered.wait()
    monitor.rest_ok(ACC)
    clock.advance(30)
    with capture_logs() as logs:
        (second,) = monitor.tick()  # down again while the first call is still in flight
        dms.hold.set()
        await dms.exited.wait()  # the first call has returned or raised
    dms.failing.clear()
    monitor.tick()  # the first call's failure does not delay the newer episode
    await monitor.drain()
    assert dms.transitions == [first, second] and monitor.owed() == []
    dropped = [e for e in logs if e["event"] == "account.dms_hook_dropped"]
    assert len(dropped) == int(fails)  # the replaced first episode, only if its call failed


async def test_an_undelivered_episode_a_new_one_replaces_is_logged_as_dropped() -> None:
    monitor, clock, dms = _hooked(ACC)
    monitor.rest_ok(ACC)
    clock.advance(30)
    (old,) = monitor.tick()
    await monitor.drain()  # its call failed, so it is still owed
    monitor.rest_ok(ACC)
    clock.advance(30)
    dms.failing.clear()
    with capture_logs() as logs:
        (new,) = monitor.tick()
        await monitor.drain()
    assert [e for e in logs if e["event"] == "account.dms_hook_dropped"] == [
        {
            "event": "account.dms_hook_dropped",
            "log_level": "warning",
            "account_id": str(ACC),
            "reason": "no_success",
        }
    ]
    assert dms.transitions == [old, new] and monitor.owed() == []


async def test_an_episode_replaced_before_its_call_started_is_logged_as_dropped() -> None:
    monitor, clock, dms = _hooked()
    dms.hold = asyncio.Event()
    monitor.rest_ok(ACC)
    clock.advance(30)
    episodes = monitor.tick()
    await dms.entered.wait()  # the first episode's call is in flight, and stays there
    with capture_logs() as logs:
        for _ in range(2):  # recover, then down again, twice, while that call runs
            monitor.rest_ok(ACC)
            clock.advance(30)
            episodes += monitor.tick()
        dms.hold.set()
        await dms.exited.wait()  # the first call has returned
    monitor.tick()
    await monitor.drain()
    dropped = [e for e in logs if e["event"] == "account.dms_hook_dropped"]
    assert len(dropped) == 1  # the second episode: never called, and replaced by the third
    assert dms.transitions == [episodes[0], episodes[2]] and monitor.owed() == []


async def test_untracking_an_account_that_is_owed_a_call_logs_the_drop() -> None:
    monitor, clock, dms = _hooked(ACC)
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


@pytest.mark.parametrize("fails", [False, True], ids=["returns", "raises"])
async def test_untracking_with_a_call_in_flight_logs_the_drop_only_if_that_call_fails(
    fails: bool,
) -> None:
    monitor, clock, dms = _hooked(*([ACC] if fails else []))
    dms.hold = asyncio.Event()
    monitor.rest_ok(ACC)
    clock.advance(30)
    monitor.tick()
    await dms.entered.wait()
    with capture_logs() as logs:
        monitor.untrack(ACC)
        assert [e for e in logs if e["event"] == "account.dms_hook_dropped"] == []  # not yet
        dms.hold.set()
        await monitor.drain()
    dropped = [e for e in logs if e["event"] == "account.dms_hook_dropped"]
    assert len(dropped) == int(fails) and len(dms.calls) == 1


async def test_a_re_tracked_account_starts_no_second_call_while_the_old_one_is_in_flight() -> None:
    monitor, clock, dms = _hooked()
    dms.hold = asyncio.Event()
    monitor.rest_ok(ACC)
    clock.advance(30)
    (first,) = monitor.tick()
    await dms.entered.wait()  # the first tracking's call is in flight, and stays there
    monitor.untrack(ACC)
    monitor.track(ACC)
    monitor.rest_ok(ACC)
    clock.advance(30)
    (second,) = monitor.tick()  # down again under the second tracking: owed, not yet called
    assert monitor.owed() == [second]
    dms.hold.set()
    await dms.exited.wait()
    monitor.tick()  # the first call has returned: the second tracking's call starts now
    await monitor.drain()
    assert dms.transitions == [first, second] and dms.peak == 1 and monitor.owed() == []


async def test_draining_with_a_call_still_owed_logs_the_drop() -> None:
    monitor, clock, _ = _hooked(ACC)
    monitor.track(ACC_B)
    for account in (ACC, ACC_B):
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


async def test_drain_also_waits_for_a_call_that_starts_while_it_waits() -> None:
    monitor, clock, dms = _hooked()
    monitor.track(ACC_B)
    first_hold = dms.hold = asyncio.Event()
    monitor.rest_ok(ACC)
    clock.advance(5)
    monitor.rest_ok(ACC_B)
    clock.advance(25)
    (first,) = monitor.tick()  # ACC is down, its call held; ACC_B follows 5 s later
    await dms.entered.wait()
    draining = asyncio.ensure_future(monitor.drain())
    await asyncio.sleep(0)  # drain is waiting on the first call alone
    second_hold = dms.hold = asyncio.Event()
    clock.advance(5)
    (second,) = monitor.tick()  # another account goes down while drain waits
    first_hold.set()
    for _ in range(5):  # loop turns: the first call ends; a drain that ignored the second returns
        await asyncio.sleep(0)
    assert not draining.done() and monitor.owed() == [second]
    second_hold.set()
    await draining
    assert dms.transitions == [first, second] and monitor.owed() == []


#: Steps in whole milliseconds, so the fake's wall clock (timedelta, microseconds) and monotonic
#: clock (float seconds) agree exactly and `changed_at` can be compared with the wall clock.
_STEP = st.integers(0, 40_000).map(lambda ms: ms / 1000)
_EVENTS = st.lists(st.tuples(_STEP, st.sampled_from(["hb", "drop", "rest", "tick", "read"])))


@settings(max_examples=200, deadline=None, derandomize=True)
@given(_EVENTS)
async def test_health_never_outlives_its_evidence(events: list[tuple[float, str]]) -> None:
    monitor, clock, dms = _hooked()
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
            state, view = monitor.current(ACC), monitor.view(ACC)
            last = max(seen.get(k, -1e9) for k in ("hb", "rest"))
            if state is HealthState.HEALTHY:
                assert live and clock.mono - seen["hb"] <= 10
            assert (state is HealthState.DOWN) == (clock.mono - last >= 30)
            assert view is not None and view.state is state
            assert changed <= view.changed_at <= clock.wall
            changed = view.changed_at
    downs = [e for e in logs if e.get("to_state") == "down"]
    assert dms.calls == [(ACC, "no_success")] * len(downs)

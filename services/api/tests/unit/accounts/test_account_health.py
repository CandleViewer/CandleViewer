"""E27-T04 per-account health FSM (US-ACCT-010): AC Healthy, Degraded, Down within 30 s; suspend
and resume, whether or not the boot-time clock counts it; wall-clock steps; positive evidence only,
derived on every read (ticket Security notes: health is never asserted optimistically)."""

from __future__ import annotations

import sys
from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.accounts.health import (
    CONNECTION_STATE,
    DOWN_MAX_S,
    HEARTBEAT_MAX_S,
    AccountHealthMonitor,
    HealthState,
    HealthThresholds,
    SystemClock,
    epoch_ms,
)
from candleviewer.settings import ACCOUNT_DOWN_MAX_S, ACCOUNT_HEARTBEAT_MAX_S, Settings
from tests.unit.accounts._fakes import ACC, T0, FakeClock


def _monitor() -> tuple[AccountHealthMonitor, FakeClock]:
    clock = FakeClock()
    monitor = AccountHealthMonitor(clock)
    monitor.track(ACC)
    return monitor, clock


def test_tracked_account_starts_down_until_its_first_success() -> None:
    monitor, _ = _monitor()
    view = monitor.view(ACC)
    assert view is not None and (view.state, view.reason) == (HealthState.DOWN, "never_connected")
    assert view.heartbeat_age_ms is None and monitor.tick() == []
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


def test_down_exactly_at_the_down_window_commits_one_transition() -> None:
    monitor, clock = _monitor()
    monitor.rest_ok(ACC)
    clock.advance(29.999)
    monitor.tick()
    assert monitor.current(ACC) is HealthState.DEGRADED
    clock.advance(0.001)
    with capture_logs() as logs:
        (transition,) = monitor.tick()
    assert (transition.from_state, transition.to_state) == (HealthState.DEGRADED, HealthState.DOWN)
    assert transition.at == clock.wall
    assert logs[0]["event"] == "account.health_changed" and logs[0]["to_state"] == "down"
    clock.advance(5)
    assert monitor.tick() == []


def test_a_suspend_the_boot_clock_counts_resumes_down_not_healthy() -> None:
    monitor, clock = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.mono += 600  # the boot-time clock counted the suspend; no event ran meanwhile
    (transition,) = monitor.tick()
    assert (transition.to_state, transition.reason) == (HealthState.DOWN, "no_success")
    assert transition.at == T0 + timedelta(seconds=30)  # when the down window lapsed


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


def test_thresholds_come_from_settings_and_must_be_ordered() -> None:
    settings_ = Settings(account_heartbeat_s=5, account_down_s=20)
    assert HealthThresholds.from_settings(settings_) == HealthThresholds(5, 20)
    with pytest.raises(ValueError, match="heartbeat_s < down_s"):
        HealthThresholds(10, 10)


@pytest.mark.parametrize(("heartbeat", "down"), [(10.001, 30), (10, 30.001), (11, 31)])
def test_thresholds_cannot_exceed_the_us_acct_010_caps(heartbeat: float, down: float) -> None:
    with pytest.raises(ValueError, match="capped at"):
        HealthThresholds(heartbeat, down)


def test_thresholds_at_the_us_acct_010_caps_are_accepted() -> None:
    assert HealthThresholds(10, 30) == HealthThresholds(HEARTBEAT_MAX_S, DOWN_MAX_S)


def test_the_defaults_are_the_us_acct_010_caps_in_thresholds_and_settings() -> None:
    assert HealthThresholds() == HealthThresholds(10, 30)
    assert HealthThresholds.from_settings(Settings()) == HealthThresholds()


def test_settings_carry_the_same_caps_as_the_health_module() -> None:
    """M1 may not import `accounts`, so `Settings` mirrors the caps; the pair must not drift."""
    assert (ACCOUNT_HEARTBEAT_MAX_S, ACCOUNT_DOWN_MAX_S) == (HEARTBEAT_MAX_S, DOWN_MAX_S)


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


def test_system_clock_is_tz_aware_and_monotonic_off_linux_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = SystemClock()
    assert clock.now().tzinfo is not None and clock.monotonic() <= clock.monotonic()
    monkeypatch.setattr(sys, "platform", "darwin")
    assert clock.monotonic() > 0


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


def test_evidence_after_an_unticked_lapse_still_records_the_down_episode() -> None:
    monitor, clock = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(600)  # resumed from suspend; the socket re-authenticates before any tick
    with capture_logs() as logs:
        transition = monitor.ws_heartbeat(ACC)
    assert transition is not None and transition.to_state is HealthState.HEALTHY
    assert [e["to_state"] for e in logs] == ["down", "healthy"]


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


#: Steps in whole milliseconds, so the fake's wall clock (timedelta, microseconds) and monotonic
#: clock (float seconds) agree exactly and `changed_at` can be compared with the wall clock.
_STEP = st.integers(0, 40_000).map(lambda ms: ms / 1000)
_EVENTS = st.lists(st.tuples(_STEP, st.sampled_from(["hb", "drop", "rest", "tick", "read"])))


@settings(max_examples=200, deadline=None, derandomize=True)
@given(_EVENTS)
def test_health_never_outlives_its_evidence(events: list[tuple[float, str]]) -> None:
    monitor, clock = _monitor()
    act = {"hb": monitor.ws_heartbeat, "drop": monitor.ws_dropped, "rest": monitor.rest_ok}
    seen: dict[str, float] = {}
    live, changed = False, T0
    for dt, kind in events:
        clock.advance(dt)
        if kind in act:
            seen[kind], live = clock.mono, (live or kind == "hb") and kind != "drop"
            act[kind](ACC)
        elif kind == "tick":
            monitor.tick()
        state, view = monitor.current(ACC), monitor.view(ACC)
        last = max(seen.get(k, -1e9) for k in ("hb", "rest"))
        if state is HealthState.HEALTHY:
            assert live and clock.mono - seen["hb"] <= 10
        assert (state is HealthState.DOWN) == (clock.mono - last >= 30)
        assert view is not None and view.state is state
        assert changed <= view.changed_at <= clock.wall
        changed = view.changed_at

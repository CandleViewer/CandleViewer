"""E27-T04 per-account health FSM (US-ACCT-010): AC Healthy, Degraded, Down within 30 s; suspend
and resume; wall-clock steps; positive evidence only (ticket Security notes)."""

from __future__ import annotations

import sys
from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.accounts.health import (
    CONNECTION_STATE,
    AccountHealthMonitor,
    HealthState,
    HealthThresholds,
    SystemClock,
)
from candleviewer.settings import Settings
from tests.unit.accounts._fakes import ACC, Dms, FakeClock


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
    assert monitor.state(ACC) is None and monitor.view(ACC) is None


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


def test_down_exactly_at_the_down_window_invokes_the_dead_mans_switch_once() -> None:
    monitor, clock, dms = _monitor()
    monitor.rest_ok(ACC)
    clock.advance(29.999)
    monitor.tick()
    assert monitor.state(ACC) is HealthState.DEGRADED and dms.calls == []
    clock.advance(0.001)
    with capture_logs() as logs:
        (transition,) = monitor.tick()
    assert (transition.from_state, transition.to_state) == (HealthState.DEGRADED, HealthState.DOWN)
    assert transition.at == clock.wall and dms.calls == [(ACC, "no_success")]
    assert logs[0]["event"] == "account.health_changed" and logs[0]["to_state"] == "down"
    clock.advance(5)
    assert monitor.tick() == [] and len(dms.calls) == 1


def test_suspend_past_the_down_window_resumes_down_not_healthy() -> None:
    monitor, clock, dms = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.mono += 600  # the boot-time clock counted the suspend; no event ran meanwhile
    (transition,) = monitor.tick()
    assert transition.to_state is HealthState.DOWN and dms.calls == [(ACC, "no_success")]


@pytest.mark.parametrize("step", [timedelta(minutes=5), timedelta(minutes=-5)])
def test_a_wall_clock_step_changes_no_state(step: timedelta) -> None:
    monitor, clock, _ = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.wall += step
    assert monitor.tick() == [] and monitor.state(ACC) is HealthState.HEALTHY


def test_thresholds_come_from_settings_and_must_be_ordered() -> None:
    settings_ = Settings(account_heartbeat_s=5, account_down_s=20)
    assert HealthThresholds.from_settings(settings_) == HealthThresholds(5, 20)
    with pytest.raises(ValueError, match="heartbeat_s < down_s"):
        HealthThresholds(10, 10)


def test_system_clock_is_tz_aware_and_monotonic_off_linux_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = SystemClock()
    assert clock.now().tzinfo is not None and clock.monotonic() <= clock.monotonic()
    monkeypatch.setattr(sys, "platform", "darwin")
    assert clock.monotonic() > 0


_EVENTS = st.lists(st.tuples(st.floats(0, 40), st.sampled_from(["hb", "drop", "rest", "tick"])))


@settings(max_examples=200, deadline=None, derandomize=True)
@given(_EVENTS)
def test_health_never_outlives_its_evidence(events: list[tuple[float, str]]) -> None:
    monitor, clock, dms = _monitor()
    act = {"hb": monitor.ws_heartbeat, "drop": monitor.ws_dropped, "rest": monitor.rest_ok}
    seen: dict[str, float] = {}
    live, downs = False, 0
    for dt, kind in events:
        clock.advance(dt)
        seen[kind], live = clock.mono, (live or kind == "hb") and kind != "drop"
        got = act[kind](ACC) if kind in act else next(iter(monitor.tick()), None)
        downs += got is not None and got.to_state is HealthState.DOWN
        state, last = monitor.state(ACC), max(seen.get(k, -1e9) for k in ("hb", "rest"))
        if state is HealthState.HEALTHY:
            assert live and clock.mono - seen["hb"] <= 10
        assert (state is HealthState.DOWN) == (clock.mono - last >= 30)
    assert len(dms.calls) == downs

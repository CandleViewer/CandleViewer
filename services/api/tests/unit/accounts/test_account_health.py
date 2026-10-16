"""E27-T04 per-account health FSM (US-ACCT-010): AC Healthy, Degraded, Down within 30 s; suspend
and resume; wall-clock steps; positive evidence only, derived on every read (ticket Security
notes: health is never asserted optimistically)."""

from __future__ import annotations

import sys
from datetime import timedelta
from uuid import UUID

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
from candleviewer.accounts.order_gate import AccountHealthCheck, KeyStanding
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


def test_down_exactly_at_the_down_window_invokes_the_dead_mans_switch_once() -> None:
    monitor, clock, dms = _monitor()
    monitor.rest_ok(ACC)
    clock.advance(29.999)
    monitor.tick()
    assert monitor.current(ACC) is HealthState.DEGRADED and dms.calls == []
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
    assert monitor.tick() == [] and monitor.current(ACC) is HealthState.HEALTHY


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


def test_a_read_before_tick_and_the_commit_after_it_agree() -> None:
    monitor, clock, _ = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(12)
    view = monitor.view(ACC)
    (transition,) = monitor.tick()
    assert view is not None and (view.state, view.reason) == (HealthState.DEGRADED, "ws_silent")
    assert view.changed_at == transition.at == T0 + timedelta(seconds=10)


def test_evidence_after_an_unticked_lapse_still_records_the_down_episode() -> None:
    monitor, clock, dms = _monitor()
    monitor.ws_heartbeat(ACC)
    clock.advance(600)  # resumed from suspend; the socket re-authenticates before any tick
    with capture_logs() as logs:
        transition = monitor.ws_heartbeat(ACC)
    assert transition is not None and transition.to_state is HealthState.HEALTHY
    assert [e["to_state"] for e in logs] == ["down", "healthy"]
    assert dms.calls == [(ACC, "no_success")]


class _FailsFor(Dms):
    def __init__(self, failing: UUID) -> None:
        super().__init__()
        self.failing = failing

    def account_down(self, account_id: UUID, reason: str) -> None:
        super().account_down(account_id, reason)
        if account_id == self.failing:
            raise RuntimeError("policy store said: retMsg=invalid api_key")


def test_a_failing_dead_mans_switch_hook_does_not_stop_the_other_accounts() -> None:
    clock, dms = FakeClock(), _FailsFor(ACC)
    monitor = AccountHealthMonitor(clock, dms)
    for account in (ACC, ACC_B):
        monitor.track(account)
        monitor.ws_heartbeat(account)
    clock.advance(31)
    with capture_logs() as logs:
        moved = monitor.tick()
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
def test_health_never_outlives_its_evidence(events: list[tuple[float, str]]) -> None:
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

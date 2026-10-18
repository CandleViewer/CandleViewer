"""E27-T04 (#837): the account health runtime and its wiring in the app: the stand-in bindings,
the loops, their faults and the stop, the private-WS consumer's feed, the thresholds from the
settings and the composition `create_app` builds. Fake clock, sleeper and ports: no Docker, no
network and no wall-clock wait but the 0.1 s a cut-off step takes. The lifespan's order is in
`test_main_lifespan_stop_order.py`."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, cast
from unittest.mock import Mock

import pytest
from structlog.testing import capture_logs

import candleviewer.account_health_wiring as wiring
import candleviewer.app as appmod
from candleviewer.account_health_wiring import TICK_S, LoggingDeadMansSwitch, UnavailableWalletRest
from candleviewer.accounts.health import DMS_HOOK_TIMEOUT_S, HealthState, HealthTransition
from candleviewer.accounts.verification import KeyRefused, Refusal
from candleviewer.accounts.wallet import WalletThresholds, WalletUnavailable
from candleviewer.app import AppContext
from candleviewer.observability.health import HealthStatus
from candleviewer.settings import Environment, Settings
from tests.unit.accounts._fakes import ACC, ACC_B, T0, FakeClock
from tests.unit.accounts._runtime_rig import Rig, snapshot

_ECHO = "echoed exchange text: key abc123"  # what a failing collaborator's message may carry
#: A cut-off bound in a test, in real time: a lapse that is no hair's breadth on a starved runner.
_BOUND_S = 0.1


def _loops() -> list[str]:
    names = (t.get_name() for t in asyncio.all_tasks())
    return sorted(n for n in names if n.startswith("account-health"))


def _task(name: str) -> asyncio.Task[Any]:
    [task] = [t for t in asyncio.all_tasks() if t.get_name() == name]
    return task


def _failed_steps(logs: Sequence[Mapping[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (e["task"], e["error"], e["consecutive"])
        for e in logs
        if e["event"] == "account_health.step_failed"
    ]


def _stop_failures(logs: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    return [
        (e["step"], e["error"]) for e in logs if e["event"] == "account_health.stop_step_failed"
    ]


async def test_the_stand_ins_log_what_is_unbound_and_the_wallet_read_is_unavailable() -> None:
    episode = HealthTransition(ACC, HealthState.DEGRADED, HealthState.DOWN, "no_success", T0)
    with capture_logs() as logs:
        await LoggingDeadMansSwitch().account_down(episode)
    assert [(e["event"], e["log_level"], e["account_id"], e["reason"]) for e in logs] == [
        ("account.dms_policy_unbound", "error", str(ACC), "no_success")
    ]
    with pytest.raises(WalletUnavailable):
        await UnavailableWalletRest().wallet(ACC)


async def test_a_rejected_credential_reaches_the_logging_binding_the_app_wires() -> None:
    rig = Rig(rest=True)
    rig.rest.error = KeyRefused(Refusal.IP_NOT_ALLOWED)  # the exchange refuses the key
    await rig.boot()
    with capture_logs() as logs:
        await rig.run(10)  # the first read is due at 10 s
    await rig.close()
    [line] = [e for e in logs if e["event"] == "account.credential_rejection_unbound"]
    want = {"log_level": "error", "account_id": str(ACC), "reason": "ip_not_allowed"}
    assert want.items() <= line.items()


async def test_two_loops_run_once_each_and_a_stop_ends_them() -> None:
    assert TICK_S <= 1.0  # `tick()` is owed at least once a second (health.py)
    assert wiring.STOP_TIMEOUT_S > 2 * DMS_HOOK_TIMEOUT_S  # `drain()` ends within twice the timeout
    rig = Rig()
    rig.runtime.start()
    rig.runtime.start()  # a second start changes nothing
    await rig.run(0)
    assert _loops() == ["account-health-reconcile", "account-health-tick"]
    with capture_logs() as logs:
        await rig.close()
        await rig.runtime.stop()  # a second stop does nothing
    rig.runtime.start()  # a stopped runtime is not restarted
    assert _loops() == [] and logs == []  # a stop is not a loop that ended


# --- supervision


def _tick_that_fails(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> Mock:
    """`monitor.tick()` raising until the mock's `side_effect` is cleared."""
    tick = Mock(side_effect=RuntimeError(_ECHO), return_value=[])
    monkeypatch.setattr(rig.runtime.monitor, "tick", tick)
    return tick


@pytest.mark.parametrize(
    ("span_s", "every_s", "passes"),
    [(5.0, 2.0, 3), (5.0, 0.5, 10), (60.0, 0.5, 120), (0.1, 5.0, 1), (0.0, 5.0, 1)],
)
def test_a_span_of_seconds_is_the_passes_that_cover_it_and_at_least_one(
    span_s: float, every_s: float, passes: int
) -> None:
    assert wiring._passes(span_s, every_s) == passes


async def test_a_loop_whose_passes_fail_for_5_s_is_a_fault(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig()
    _tick_that_fails(rig, monkeypatch)
    await rig.boot()  # the first pass is at once
    await rig.run(4)
    assert rig.runtime.fault is None  # 9 passes have failed in a row
    await rig.run(0.5)
    assert rig.runtime.fault == "the account-health-tick loop fails: 10 passes in a row"
    await rig.close()


async def test_a_failing_loop_logs_its_first_failure_and_then_once_a_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig()
    _tick_that_fails(rig, monkeypatch)
    with capture_logs() as logs:
        await rig.boot()
        await rig.run(60.5)
    await rig.close()
    # the first pass, then the 120th: a minute at `TICK_S`
    assert [consecutive for *_, consecutive in _failed_steps(logs)] == [1, 120]


async def test_a_pass_that_works_clears_the_fault(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig()
    tick = _tick_that_fails(rig, monkeypatch)
    await rig.boot()
    await rig.run(5)
    assert rig.runtime.fault is not None
    tick.side_effect = None  # the next pass works
    await rig.run(0.5)
    assert rig.runtime.fault is None
    await rig.close()


async def test_a_stop_clears_the_fault_of_a_failing_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig()
    _tick_that_fails(rig, monkeypatch)
    await rig.boot()
    await rig.run(5)
    assert rig.runtime.fault is not None
    await rig.close()
    assert rig.runtime.fault is None  # nothing is running


async def test_a_loop_that_ends_is_a_fault_the_accounts_check_reports() -> None:
    rig = Rig()
    await rig.accounts.start(cast(AppContext, object()))  # the supervisor's call
    await rig.boot()
    assert rig.runtime.fault is None and rig.accounts.health().status is HealthStatus.OK
    with capture_logs() as logs:
        _task("account-health-tick").cancel()  # whatever ends the task, it is not a stop
        await rig.run(1)
    report = rig.accounts.health()
    await rig.close()
    assert report.status is HealthStatus.DEGRADED
    assert report.detail == "the account-health-tick loop ended"
    ended = [e for e in logs if e["event"] == "account_health.loop_ended"]
    assert [(e["log_level"], e["task"]) for e in ended] == [("critical", "account-health-tick")]


async def test_a_loop_that_ends_anyway_is_logged_critical_by_its_error_type() -> None:
    rig = Rig()
    await rig.boot()
    with capture_logs() as logs:
        [tick] = [t for t in asyncio.all_tasks() if t.get_name() == "account-health-tick"]
        tick.cancel()  # whatever ends the task, it is not a stop
        rig.sleeper.fail = RuntimeError(_ECHO)  # and the other loop's next sleep raises
        await rig.run(1)
    await rig.close()
    assert sorted((e["event"], e["log_level"], e["task"], e["error"]) for e in logs) == [
        ("account_health.loop_ended", "critical", "account-health-reconcile", "RuntimeError"),
        ("account_health.loop_ended", "critical", "account-health-tick", None),
    ]
    assert _ECHO not in repr(logs)


async def test_a_step_that_raises_is_logged_by_type_and_the_loop_carries_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig()
    tick = Mock(side_effect=[[], RuntimeError(_ECHO), *[[]] * 10])  # the second pass fails
    monkeypatch.setattr(rig.runtime.monitor, "tick", tick)
    await rig.boot()
    with capture_logs() as logs:
        await rig.run(3)
    await rig.close()
    failed = [(e["event"], e["task"], e["error"]) for e in logs]
    assert failed == [("account_health.step_failed", "account-health-tick", "RuntimeError")]
    assert tick.call_count >= 6 and _ECHO not in repr(logs)  # it kept ticking, twice a second


async def _down_with_a_hook_in_flight(rig: Rig) -> asyncio.Event:
    """A slow dead-man's-switch hook, called once the account has gone down."""
    await rig.boot()
    rig.dms.hold = rig.dms.hold or asyncio.Event()
    rig.ws.connect()
    await rig.run(1)
    rig.ws.go_silent()
    await rig.run(35)  # down at 30 s: the hook call started and waits
    assert rig.dms.active == 1
    return rig.dms.hold


async def test_a_stop_waits_for_a_dead_mans_switch_call_in_flight() -> None:
    rig = Rig()
    hold = await _down_with_a_hook_in_flight(rig)
    stopping = asyncio.create_task(rig.runtime.stop())
    await rig.run(0)
    assert not stopping.done()  # it waits for the hook
    hold.set()
    await stopping
    assert rig.dms.active == 0 and _loops() == []


async def test_a_cancelled_stop_propagates_the_cancellation() -> None:
    rig = Rig()
    hold = await _down_with_a_hook_in_flight(rig)
    stopping = asyncio.create_task(rig.runtime.stop())
    await rig.run(0)  # it waits for the hook
    stopping.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    hold.set()  # frees the hook


async def test_each_stop_step_is_bounded_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(rest=True)
    monkeypatch.setattr(wiring, "STOP_TIMEOUT_S", 0.01)
    rig.dms.stubborn = rig.rest.stubborn = True  # a hook and a read that swallow their cancellation
    freed = rig.rest.hold = rig.dms.hold = asyncio.Event()  # and never return: the drain still runs
    try:
        await _down_with_a_hook_in_flight(rig)
        with capture_logs() as logs:
            await rig.runtime.stop()
        failed = [(e["event"], e["step"], e["error"]) for e in logs]
        assert failed == [
            ("account_health.stop_step_failed", "loops", "TimeoutError"),
            ("account_health.stop_step_failed", "drain", "TimeoutError"),
        ]
    finally:
        freed.set()  # frees the hook and the read, whatever the outcome
        await rig.run(0)


async def test_a_read_that_outlives_a_cut_off_stop_gives_no_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig(rest=True)
    monkeypatch.setattr(wiring, "STOP_TIMEOUT_S", _BOUND_S)
    await rig.boot()
    rig.ws.connect()  # the one pong is at 0 s: the down window ends at 30 s
    await rig.run(0)
    rig.ws.go_silent()
    rig.rest.hold = asyncio.Event()
    rig.rest.stubborn = True  # the read due at 10.5 s, once the heartbeat lapses, swallows a cancel
    try:
        await rig.run(11)
        assert rig.rest.calls == [10.5]
        with capture_logs() as logs:
            async with asyncio.timeout(1):  # a deadline, so that a missing bound fails, not hangs
                await rig.runtime.stop()
            rig.clock.advance(60)  # the lapse passes with no tick left to commit it
            rig.rest.hold.set()  # the read returns after the stop
            await rig.run(0)
        assert _stop_failures(logs) == [("loops", "TimeoutError")]
        assert rig.dms.calls == []  # a lapse that evidence would have committed is not one
        assert [e for e in logs if e["event"] == "account.health_changed"] == []
    finally:
        rig.rest.hold.set()  # frees the read, whatever the outcome
        await rig.run(0)


async def test_a_loop_whose_sleep_swallows_the_cancel_ends_with_the_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig()
    monkeypatch.setattr(wiring, "STOP_TIMEOUT_S", _BOUND_S)
    rig.sleeper.stubborn = True  # a cancelled sleep wakes early: one that breaks its contract
    await rig.boot()
    rig.runtime.ws_heartbeat(ACC)  # the last evidence, at 0 s: the account is down from 30 s
    await rig.run(1)
    try:
        async with asyncio.timeout(1):  # a deadline, so that a loop that runs on fails, not hangs
            await rig.runtime.stop()
        await rig.run(31)  # a loop that ran on would commit the lapse and call the hook
        assert rig.dms.calls == [] and _loops() == []
    finally:
        rig.sleeper.stubborn = False  # so that a loop that ran on can be cancelled
        for name in _loops():
            _task(name).cancel()
        await rig.run(0)


async def test_the_feed_reaches_the_monitor_and_the_cache_and_skips_an_untracked_account() -> None:
    rig = Rig()
    rig.track()
    feed = rig.accounts.account_health  # what the private-WS consumer gets from `ctx.accounts`
    polled = feed.rest_ok(ACC)  # a REST success is evidence for a tracked account
    assert polled is not None and polled.to_state is HealthState.DEGRADED
    up = feed.ws_heartbeat(ACC)
    assert up is not None and up.to_state is HealthState.HEALTHY
    down = feed.ws_dropped(ACC)
    assert down is not None and down.to_state is HealthState.DEGRADED
    assert feed.wallet_pushed(ACC, snapshot(T0)) is True
    view = rig.runtime.wallets.view(ACC)
    assert view is not None and view.snapshot is not None and view.snapshot.updated_at == T0
    assert feed.ws_heartbeat(ACC_B) is None and feed.ws_dropped(ACC_B) is None
    assert feed.rest_ok(ACC_B) is None and feed.wallet_pushed(ACC_B, snapshot(T0)) is False


async def test_the_feed_is_not_the_runtime_and_gives_no_way_to_it() -> None:
    rig = Rig()
    feed = rig.accounts.account_health
    assert feed is not rig.runtime
    for name in "monitor wallets current start stop runtime feed".split():
        assert not hasattr(feed, name)


@pytest.mark.parametrize("evidence", ["ws_heartbeat", "ws_dropped", "rest_ok", "wallet_pushed"])
async def test_evidence_after_a_stop_changes_nothing_and_starts_no_hook_call(
    evidence: str,
) -> None:
    rig = Rig()
    await rig.boot()
    rig.ws.connect()
    await rig.run(1)
    rig.ws.go_silent()
    await rig.close()
    rig.clock.advance(60)  # the down window passes with no tick to commit it
    args = (ACC, snapshot(rig.clock.now())) if evidence == "wallet_pushed" else (ACC,)
    assert not getattr(rig.accounts.account_health, evidence)(*args)  # None or False
    await rig.run(0)
    assert rig.dms.calls == []  # a lapse that evidence would have committed is not one
    view = rig.runtime.wallets.view(ACC)
    assert view is not None and view.snapshot is None  # nor was a frame applied


async def test_the_windows_come_from_the_settings() -> None:
    rig = Rig(settings=Settings(account_heartbeat_s=4, account_down_s=20, wallet_stale_s=5))
    rig.track()
    rig.runtime.ws_heartbeat(ACC)
    rig.clock.advance(4)
    assert rig.runtime.monitor.current(ACC) is HealthState.HEALTHY
    rig.clock.advance(0.001)
    assert rig.runtime.monitor.current(ACC) is HealthState.DEGRADED  # heartbeat window of 4 s
    assert rig.runtime.wallets.thresholds == WalletThresholds(5, 60, 4)  # stale 5 s, down poll 4 s


async def test_create_app_wires_the_runtime_and_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(wiring, "SystemClock", lambda: clock)
    app = appmod.create_app(Settings(environment=Environment.TESTNET))
    runtime = app.state.account_health
    assert runtime.monitor.current(ACC) is None  # nothing is tracked yet
    runtime.wallets.track(ACC)
    runtime.wallets.apply(ACC, snapshot(T0))
    clock.advance(61)  # past the reconciliation period with no refresh
    assert runtime.wallets.risk_sizing_available(ACC) is False
    metric, labels = "cv_wallet_sizing_old_snapshot_total", {"env": "testnet"}
    assert app.state.metrics_facade.registry.get_sample_value(metric, labels) == 1.0


def test_create_app_hands_the_accounts_service_the_runtimes_feed() -> None:
    app = appmod.create_app(Settings(environment=Environment.TESTNET))
    runtime = app.state.account_health
    feed = app.state.app_context.accounts.account_health
    assert feed is runtime.feed
    runtime.monitor.track(ACC)
    assert feed.ws_heartbeat(ACC) is not None  # the feed reaches the monitor the app built

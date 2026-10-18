"""E27-T04 (#837): the account health runtime and its wiring in the app: the stand-in bindings,
the loops and the stop, the private-WS consumer's feed, the thresholds from the settings and the
composition `create_app` builds. Fake clock, sleeper and ports: no Docker, no network, no wait."""

from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest
from structlog.testing import capture_logs

import candleviewer.account_health_wiring as wiring
import candleviewer.app as appmod
from candleviewer.account_health_wiring import TICK_S, LoggingDeadMansSwitch, UnavailableWalletRest
from candleviewer.accounts.health import DMS_HOOK_TIMEOUT_S, HealthState, HealthTransition
from candleviewer.accounts.verification import KeyRefused, Refusal
from candleviewer.accounts.wallet import WalletThresholds, WalletUnavailable
from candleviewer.settings import Environment, Settings
from tests.unit.accounts._fakes import ACC, ACC_B, T0, FakeClock
from tests.unit.accounts._runtime_rig import Rig, snapshot

_ECHO = "echoed exchange text: key abc123"  # what a failing collaborator's message may carry


def _loops() -> list[str]:
    names = (t.get_name() for t in asyncio.all_tasks())
    return sorted(n for n in names if n.startswith("account-health"))


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


async def test_the_feed_reaches_the_monitor_and_the_cache_and_skips_an_untracked_account() -> None:
    rig = Rig()
    rig.track()
    feed = rig.runtime
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

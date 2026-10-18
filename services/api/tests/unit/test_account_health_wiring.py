"""E27-T04 (#837): the account health runtime and its wiring in the app: tracking from the
repository, the stand-in bindings, the loops and the stop, the private-WS consumer's feed, the
thresholds from the settings and the composition `create_app` builds on both backends. Fake clock,
sleeper and ports: no Docker, no network and no wall-clock wait but the 0.1 s a cut-off step takes.
The lifespan's order is in `test_main_lifespan_stop_order.py`."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping, Sequence
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from uuid import UUID

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

import candleviewer.account_health_wiring as wiring
import candleviewer.app as appmod
from candleviewer.account_health_wiring import (
    TICK_S,
    TRACKING_REFRESH_S,
    LoggingDeadMansSwitch,
    UnavailableWalletRest,
    wire_account_health,
)
from candleviewer.accounts.health import DMS_HOOK_TIMEOUT_S, HealthState, HealthTransition
from candleviewer.accounts.verification import KeyRefused, Refusal
from candleviewer.accounts.wallet import WalletThresholds, WalletUnavailable
from candleviewer.accounts.wallet_topic import WalletTopic
from candleviewer.app import AppContext
from candleviewer.observability.health import HealthStatus
from candleviewer.observability.metrics import Metrics
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.accounts import ExchangeAccountRow, SelfCheckTargetRow
from candleviewer.storage.repositories.key_selfcheck_sqlalchemy import SqlAlchemyKeySelfCheckStore
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from tests.unit.accounts._fakes import ACC, ACC_B, T0, FakeClock, key_row
from tests.unit.accounts._runtime_rig import Rig, snapshot

_ECHO = "echoed exchange text: key abc123"  # what a failing collaborator's message may carry
_ACC_C = UUID(int=3)
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


async def test_a_rejected_wallet_read_refuses_at_once_and_only_a_later_pass_clears_it() -> None:
    """24-internal-schemas.md section 8.6 through the reconciler (Option A on #837): the rejection
    reaches the key standing, which the runtime's order-entry check reads at once. It is never
    health evidence, and no evidence clears it: not an accepted read, nor the socket's pongs."""
    rig = Rig(rest=True)
    rig.runtime.standings.observe([key_row(ACC, verified_at=rig.clock.now())])
    check = rig.runtime.order_entry_check
    rig.rest.error = KeyRefused(Refusal.IP_NOT_ALLOWED)  # the exchange refuses the key
    await rig.boot()
    with capture_logs() as logs:
        await rig.run(10)  # the first read is due at 10 s
    view, refused = rig.runtime.monitor.view(ACC), check.refusal(ACC)
    rig.rest.error = None  # the next read, at 20 s, is accepted: `rest_ok`
    await rig.run(10)
    rig.ws.connect()
    await rig.run(1)
    healthy, still = rig.runtime.monitor.current(ACC), check.refusal(ACC)
    rig.runtime.standings.observe([key_row(ACC, verified_at=rig.clock.now())])  # a later pass
    cleared = check.refusal(ACC)
    await rig.close()
    assert view is not None and view.reason == "never_connected"  # no evidence from a rejection
    assert refused is not None and refused.reason == "account_disabled_by_policy"
    assert rig.rest.calls == [10.0, 20.0] and healthy is HealthState.HEALTHY
    assert still == refused and cleared is None
    [line] = [e for e in logs if e["event"] == "account.credential_rejected"]
    want = {"log_level": "error", "account_id": str(ACC), "reason": "ip_not_allowed"}
    assert want.items() <= line.items()


async def test_two_loops_run_once_each_and_a_stop_ends_them() -> None:
    assert TICK_S <= 1.0  # `tick()` is owed at least once a second (health.py)
    assert wiring.STOP_TIMEOUT_S > 2 * DMS_HOOK_TIMEOUT_S  # `drain()` ends within twice the timeout
    rig = Rig(source=False)  # the fake backend: no repository to read, so no tracking loop
    rig.runtime.start()
    rig.runtime.start()  # a second start changes nothing
    await rig.run(0)
    assert _loops() == ["account-health-reconcile", "account-health-tick"]
    with capture_logs() as logs:
        await rig.close()
        await rig.runtime.stop()  # a second stop does nothing
    rig.runtime.start()  # a stopped runtime is not restarted
    assert _loops() == [] and logs == []  # a stop is not a loop that ended


async def test_with_a_repository_a_tracking_loop_runs_too_and_a_stop_ends_all_three() -> None:
    rig = Rig()
    await rig.boot()
    rig.runtime.start()  # a second start changes nothing
    assert _loops() == [
        "account-health-reconcile",
        "account-health-tick",
        "account-health-tracking",
    ]
    with capture_logs() as logs:
        await rig.close()
    assert _loops() == [] and rig.runtime.fault is None and logs == []


# --- tracking


async def test_an_account_the_repository_reports_is_tracked_and_one_it_drops_is_untracked() -> None:
    rig = Rig(ACC)
    runtime = rig.runtime
    await runtime.refresh_tracking()
    assert runtime.monitor.current(ACC) is HealthState.DOWN  # tracked: down until a success
    assert runtime.wallets.view(ACC) is not None
    rig.wanted = frozenset({ACC_B})  # ACC is disabled or loses its key, ACC_B is added
    await runtime.refresh_tracking()
    assert runtime.monitor.current(ACC) is None and runtime.wallets.view(ACC) is None
    assert runtime.monitor.current(ACC_B) is HealthState.DOWN
    assert runtime.wallets.view(ACC_B) is not None


async def test_an_account_that_leaves_and_comes_back_is_tracked_again() -> None:
    rig = Rig()
    for wanted in (frozenset({ACC}), frozenset(), frozenset({ACC})):  # disabled, then enabled
        rig.wanted = wanted
        await rig.runtime.refresh_tracking()
    assert rig.runtime.monitor.current(ACC) is HealthState.DOWN
    assert rig.runtime.wallets.view(ACC) is not None


async def test_a_change_of_the_tracked_set_is_logged_with_its_counts_and_no_change_is_not() -> None:
    rig = Rig()
    with capture_logs() as logs:
        await rig.runtime.refresh_tracking()  # ACC is added
        await rig.runtime.refresh_tracking()  # nothing changes
        rig.wanted = frozenset({ACC_B, _ACC_C})  # two added, ACC removed
        await rig.runtime.refresh_tracking()
    changes = [(e["log_level"], e["tracked"], e["added"], e["removed"]) for e in logs]
    assert changes == [("info", 1, 1, 0), ("info", 2, 2, 1)]  # and the second refresh said nothing
    assert {e["event"] for e in logs} == {"account_health.tracking_changed"}


@pytest.mark.parametrize("failure", ["raises", "hangs"])
async def test_a_failed_or_hung_read_keeps_the_tracked_set_and_raises_its_error_type(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(ACC)
    await rig.runtime.refresh_tracking()
    monkeypatch.setattr(wiring, "READ_TIMEOUT_S", _BOUND_S)
    rig.wanted = frozenset({ACC_B})
    rig.read_error = RuntimeError(_ECHO) if failure == "raises" else None
    rig.read_hangs = failure == "hangs"
    with pytest.raises(RuntimeError if failure == "raises" else TimeoutError):
        async with asyncio.timeout(1) as deadline:  # so that a missing bound fails, not hangs
            await rig.runtime.refresh_tracking()
    assert not deadline.expired()  # the read's own bound cut it, not this deadline
    assert rig.runtime.monitor.current(ACC) is HealthState.DOWN  # still tracked: nothing untracked
    assert rig.runtime.monitor.current(ACC_B) is None


async def test_an_account_owing_a_dead_mans_switch_call_stays_tracked_until_it_returns() -> None:
    rig = Rig()
    hold = await _down_with_a_hook_in_flight(rig)  # ACC is down and its hook call is owed
    rig.wanted = frozenset({ACC_B})  # the owner switches the account for another
    with capture_logs() as logs:
        await rig.runtime.refresh_tracking()
        assert rig.runtime.monitor.current(ACC) is HealthState.DOWN  # the call is still owed
        hold.set()  # the hook returns
        await rig.run(0)
        await rig.runtime.refresh_tracking()
    await rig.close()
    assert rig.runtime.monitor.current(ACC) is None  # nothing is owed now: untracked
    assert rig.runtime.wallets.view(ACC) is None
    assert rig.runtime.monitor.current(ACC_B) is HealthState.DOWN
    assert [e for e in logs if e["event"] == "account.dms_hook_dropped"] == []
    changes = [(e["tracked"], e["added"], e["removed"]) for e in logs if "tracked" in e]
    assert changes == [(2, 1, 0), (1, 0, 1)]  # the held account counts as tracked until it goes


async def test_the_tracking_loop_reads_at_start_and_then_every_refresh_interval() -> None:
    assert TRACKING_REFRESH_S <= 60  # a new account is monitored within a minute
    rig = Rig(ACC)
    rig.runtime.start()
    await rig.run(0)
    assert rig.runtime.monitor.current(ACC) is HealthState.DOWN  # the first read is at once
    rig.wanted = frozenset({ACC, ACC_B})
    await rig.run(TRACKING_REFRESH_S - 0.5)
    assert rig.runtime.monitor.current(ACC_B) is None
    await rig.run(1)
    assert rig.runtime.monitor.current(ACC_B) is HealthState.DOWN
    await rig.close()


async def test_without_a_repository_a_refresh_tracks_nothing() -> None:
    rig = Rig(source=False)
    await rig.runtime.refresh_tracking()
    assert rig.runtime.monitor.current(ACC) is None


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


async def test_a_failed_tracking_read_is_logged_by_its_error_type_and_then_once_a_minute() -> None:
    rig = Rig()
    rig.read_error = RuntimeError(_ECHO)
    with capture_logs() as logs:
        await rig.boot()
        await rig.run(150)  # reads at 0, 15, ... 150 s
    await rig.close()
    tracking = "account-health-tracking"
    # the first read, then the 4th and the 8th: a minute apart at `TRACKING_REFRESH_S`
    assert _failed_steps(logs) == [(tracking, "RuntimeError", n) for n in (1, 4, 8)]
    assert _ECHO not in repr(logs)


async def test_a_minute_of_failed_tracking_reads_is_a_fault_the_accounts_check_reports() -> None:
    rig = Rig()
    await rig.accounts.start(cast(AppContext, object()))  # the supervisor's call
    rig.read_error = RuntimeError(_ECHO)  # the repository cannot be read
    await rig.boot()
    await rig.run(44)  # reads at 0, 15 and 30 s have failed
    assert rig.runtime.fault is None and rig.accounts.health().status is HealthStatus.OK
    await rig.run(1)  # the 4th, at 45 s
    report = rig.accounts.health()
    await rig.close()
    assert report.status is HealthStatus.DEGRADED
    assert report.detail == "the account-health-tracking loop fails: 4 passes in a row"
    assert rig.runtime.monitor.current(ACC) is None  # and nothing is tracked


async def test_a_tracking_read_that_works_clears_the_fault_and_tracks() -> None:
    rig = Rig()
    rig.read_error = RuntimeError(_ECHO)
    await rig.boot()
    await rig.run(45)
    assert rig.runtime.fault is not None
    rig.read_error = None
    await rig.run(15)  # the next read, at 60 s, works
    assert rig.runtime.fault is None
    assert rig.runtime.monitor.current(ACC) is HealthState.DOWN  # and tracks what it reports
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


async def test_a_stop_releases_the_pool_once_the_calls_have_drained() -> None:
    rig = Rig()
    hold = await _down_with_a_hook_in_flight(rig)
    stopping = asyncio.create_task(rig.runtime.stop())
    await rig.run(0)
    assert rig.released == []  # the drain is waiting for the hook
    hold.set()
    await stopping
    assert rig.released == ["pool"]


async def test_a_stop_without_a_start_releases_once_and_a_second_stop_does_nothing() -> None:
    rig = Rig()
    await rig.runtime.stop()
    await rig.runtime.stop()
    assert _loops() == [] and rig.released == ["pool"]


async def test_a_pool_release_that_hangs_is_cut_off_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig()
    monkeypatch.setattr(wiring, "RELEASE_TIMEOUT_S", _BOUND_S)
    rig.release_hangs = True
    await rig.boot()
    with capture_logs() as logs:
        async with asyncio.timeout(1):  # a deadline, so that a missing bound fails, not hangs
            await rig.runtime.stop()
    assert _stop_failures(logs) == [("release", "TimeoutError")]


async def test_a_loop_that_will_not_stop_does_not_keep_the_drain_and_the_release_from_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig(rest=True)
    monkeypatch.setattr(wiring, "STOP_TIMEOUT_S", _BOUND_S)
    await rig.boot()
    rig.rest.hold = asyncio.Event()
    rig.rest.stubborn = True  # the read due at 10 s (the socket never connected) swallows a cancel
    try:
        await rig.run(11)
        assert rig.rest.calls == [10.0]
        with capture_logs() as logs:
            async with asyncio.timeout(1):  # a deadline, so that a missing bound fails, not hangs
                await rig.runtime.stop()
        assert _stop_failures(logs) == [("loops", "TimeoutError")]
        assert rig.released == ["pool"]  # the drain and the release still ran
    finally:
        rig.rest.hold.set()  # frees the read, whatever the outcome
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


def test_the_three_stop_steps_fit_the_default_stop_budget() -> None:
    worst_s = 2 * wiring.STOP_TIMEOUT_S + wiring.RELEASE_TIMEOUT_S  # the loops, the drain, the pool
    assert worst_s < Settings().api_stop_budget_s


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
    for name in "monitor wallets current start stop refresh_tracking runtime feed".split():
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


def _real() -> Settings:
    return Settings(
        storage_backend="real",
        environment=Environment.TESTNET,
        auth_pepper=SecretStr("test-pepper"),
        auth_totp_key_hex=SecretStr("11" * 32),
        auth_recovery_hmac_key_hex=SecretStr("22" * 32),
        auth_csrf_key_hex=SecretStr("33" * 32),
    )


def _account_row(
    account: UUID, *, env: str = "testnet", enabled: bool = True
) -> SelfCheckTargetRow:
    # A dict literal, not keywords: ruff S106 reads `colour_token=` as a password.
    fields: dict[str, Any] = {
        "id": account, "exchange": "bybit", "env": env, "kind": "main", "exchange_uid": "1000001",
        "parent_account_id": None, "label": "fx", "colour_token": "accent.neutral",
        "is_enabled": enabled, "trading_enabled": False, "position_mode": "one_way",
        "margin_mode": "cross", "account_type": "UNIFIED", "quote_ccy": "USDT",
        "equity_cached_usd": None, "equity_cached_at": None, "max_sub_accounts_hint": 5,
        "last_reconciled_at": None, "created_at": T0, "updated_at": T0, "deleted_at": None,
    }  # fmt: skip
    return SelfCheckTargetRow(UUID(int=account.int + 100), False, T0, ExchangeAccountRow(**fields))


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    """The real-backend `create_app` with the usable-key read faked at its SQL edge, which also
    records the environment its store was bound to."""
    edges = SimpleNamespace(rows=[], envs=[], disposed=0)

    async def targets(store: SqlAlchemyKeySelfCheckStore) -> tuple[SelfCheckTargetRow, ...]:
        edges.envs.append(store._env)
        return tuple(edges.rows)

    async def dispose(_repository: SqlAlchemyRelationalRepository) -> None:
        edges.disposed += 1

    monkeypatch.setattr(SqlAlchemyKeySelfCheckStore, "targets", targets)
    monkeypatch.setattr(SqlAlchemyRelationalRepository, "dispose", dispose)
    monkeypatch.setattr(appmod, "_build_accounts_counts", lambda _settings: None)
    yield edges


async def test_the_real_backend_tracks_only_the_enabled_accounts_of_its_environment(
    stored: SimpleNamespace,
) -> None:
    stored.rows = [
        _account_row(ACC),
        _account_row(ACC_B, enabled=False),  # an account the owner switched off
        _account_row(_ACC_C, env="live"),  # a row of another environment: never tracked
    ]
    runtime = appmod.create_app(_real()).state.account_health
    await runtime.refresh_tracking()
    assert runtime.monitor.current(ACC) is HealthState.DOWN  # tracked, never connected
    assert runtime.monitor.current(ACC_B) is None and runtime.monitor.current(_ACC_C) is None


async def test_the_real_backend_binds_the_store_it_reads_to_the_process_environment(
    stored: SimpleNamespace,
) -> None:
    runtime = appmod.create_app(_real()).state.account_health
    await runtime.refresh_tracking()
    assert stored.envs == ["testnet"]


async def test_a_row_of_another_environment_is_logged_once_for_as_long_as_it_stays(
    stored: SimpleNamespace,
) -> None:
    runtime = appmod.create_app(_real()).state.account_health
    foreign = _account_row(_ACC_C, env="live")  # the store filters on `env`: a bug worth a line
    with capture_logs() as logs:
        for rows in ([foreign], [foreign], [], [foreign]):  # it stays, goes, then returns
            stored.rows = rows
            await runtime.refresh_tracking()
    mismatches = [(e["event"], e["log_level"], e["rows"]) for e in logs]
    assert mismatches == [("account_health.env_mismatch", "error", 1)] * 2


async def test_a_stop_releases_the_pool_of_the_runtimes_own_store_and_only_that_one(
    stored: SimpleNamespace,
) -> None:
    runtime = appmod.create_app(_real()).state.account_health
    await runtime.stop()
    assert stored.disposed == 1


def test_the_fake_backend_wires_the_runtime_with_no_repository_to_read() -> None:
    runtime = appmod.create_app(Settings(environment=Environment.TESTNET)).state.account_health
    assert runtime.monitor.current(ACC) is None  # nothing is tracked and no loop reads for it


def test_create_app_hands_the_accounts_service_the_runtimes_feed() -> None:
    app = appmod.create_app(Settings(environment=Environment.TESTNET))
    runtime = app.state.account_health
    feed = app.state.app_context.accounts.account_health
    assert feed is runtime.feed
    runtime.monitor.track(ACC)
    assert feed.ws_heartbeat(ACC) is not None  # the feed reaches the monitor the app built


def test_create_app_serves_the_wallet_topic_from_the_runtime_through_the_gateway_hub() -> None:
    app = appmod.create_app(Settings(environment=Environment.TESTNET))
    runtime, services = app.state.account_health, app.state.ws_registry.services
    topic: Any = services.snapshots._sources["wallet"]
    assert topic is runtime.topic and topic._publish == services.sequencing.publish
    runtime.monitor.track(ACC)
    body = topic.build(SimpleNamespace(accounts=frozenset({ACC, ACC_B})))
    assert [entry["exchange_account_id"] for entry in body.structured["health"]] == [str(ACC)]


def test_a_release_without_the_read_it_frees_is_refused() -> None:
    async def release() -> None:
        return None

    topic = WalletTopic(SequencingHub().publish, SnapshotBody)
    with pytest.raises(ValueError, match="release"):
        wire_account_health(Settings(), Metrics("demo"), topic, release=release)

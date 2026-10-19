"""E27-T04 W5 (#837): dead-man's-switch episodes across restarts (AC Down within 30 s; C-13.6
scenario 12): the row written before the hook call and resolved after it, the replay, the boot
episode. Fakes, no sleeps; the SQL: `tests/integration/storage/test_dms_episode_journal_pg.py`."""

from __future__ import annotations

import asyncio
import gc
import inspect
import math
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

import pytest
from structlog.testing import capture_logs

import candleviewer.account_health_wiring as wiring
from candleviewer.accounts.health import (
    DMS_HOOK_TIMEOUT_S,
    DMS_JOURNAL_TIMEOUT_S,
    AccountHealthMonitor,
    HealthState,
    HealthTransition,
)
from tests.unit.accounts._fakes import ACC, ACC_B, T0, Dms, Episode, FakeClock, Jitter, Journal
from tests.unit.accounts._runtime_rig import START, Rig
from tests.unit.accounts._wallet_ws import Conn, owner

_ECHO = "echoed exchange text: key abc123"  # what a failing journal's message may carry
_OPEN = Episode(ACC, "degraded", "no_success", T0)  # a row a killed process left open
_HOOK_TROUBLE = {"account.dms_hook_stuck", "account.dms_hook_failed", "account.dms_hook_dropped"}


def _journaled(journal: Journal, **kwargs: Any) -> tuple[AccountHealthMonitor, FakeClock, Dms]:
    clock = FakeClock()
    dms = Dms(clock=clock)
    monitor = AccountHealthMonitor(clock, dms, journal=journal, rng=Jitter(), **kwargs)
    monitor.track(ACC)
    return monitor, clock, dms


def _down(monitor: AccountHealthMonitor, clock: FakeClock) -> HealthTransition:
    monitor.rest_ok(ACC)
    clock.advance(30)
    (down,) = monitor.tick()
    return down


def _journal_failures(logs: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    failed = (e for e in logs if e["event"] == "account.dms_journal_failed")
    return [(e["log_level"], e["step"], e["error"]) for e in failed]


def _writes() -> set[asyncio.Task[Any]]:
    """The journal writes still running, those a call left to unwind included."""
    return {t for t in asyncio.all_tasks() if t.get_name().startswith("account-dms-journal")}


async def _silent_down(rig: Rig) -> None:
    """Boot, one heartbeat at 0 s, then silence: down at 30 s, and its hook call starts."""
    await rig.boot()
    rig.runtime.ws_heartbeat(ACC)
    await rig.run(31)


async def _kill() -> None:
    """A SIGKILL as far as one event loop allows: the runtime's tasks end where they stand."""
    for task in asyncio.all_tasks():
        if task.get_name().startswith(("account-health", "account-dms")):
            task.cancel()
    await asyncio.sleep(0)


async def _restart(journal: Journal) -> Rig:
    rig = Rig(journal=journal)
    await rig.boot()
    await rig.run(1)
    await rig.close()
    return rig


async def test_an_episode_is_recorded_before_its_hook_call_and_resolved_once_it_returns() -> None:
    journal = Journal()
    monitor, clock, dms = _journaled(journal)
    dms.hold = asyncio.Event()
    down = _down(monitor, clock)
    await dms.entered.wait()  # the hook is mid-call: its row must already be written
    assert journal.open() == [ACC]
    assert [(e.from_state, e.reason, e.at) for e in journal.rows.values()] == [
        ("degraded", "no_success", down.at)
    ]
    dms.hold.set()
    await monitor.drain()
    assert journal.open() == [] and monitor.owed() == []


async def test_a_retried_call_reuses_its_row_and_its_success_resolves_it() -> None:
    journal = Journal()
    monitor, clock, dms = _journaled(journal)
    dms.failing.add(ACC)
    _down(monitor, clock)
    await monitor.drain()
    assert journal.open() == [ACC]  # the failed call leaves it open
    dms.failing.clear()
    clock.advance(1)  # the retry delay
    monitor.tick()
    await monitor.drain()
    assert len(dms.transitions) == 2 and len(journal.rows) == 1 and journal.open() == []


@pytest.mark.parametrize("error", [RuntimeError(_ECHO), asyncio.CancelledError()])  # its driver's
async def test_a_failed_advance_write_still_calls_the_hook_logs_critical_and_counts(
    error: BaseException,
) -> None:
    journal = Journal()
    journal.fail["record"] = error
    monitor, clock, dms = _journaled(journal)
    with capture_logs() as logs:
        down = _down(monitor, clock)
        await monitor.drain()
    assert dms.transitions == [down] and monitor.owed() == []  # the policy ran: delivered
    assert _journal_failures(logs) == [("critical", "record", type(error).__name__)]
    assert monitor.journal_failures == 1 and journal.rows == {} and _ECHO not in repr(logs)


async def test_a_record_stuck_past_its_cancellation_never_holds_the_hook_nor_a_retry() -> None:
    journal = Journal()
    journal.hold["record"] = stuck = asyncio.Event()
    monitor, clock, dms = _journaled(journal, journal_timeout_s=0.001)
    dms.failing.add(ACC)  # so the call is retried
    try:
        with capture_logs() as logs:
            down = _down(monitor, clock)
            async with asyncio.timeout(5):  # fails fast, not hangs, if the bound is lost
                await monitor.drain()
                clock.advance(1)  # the retry delay
                monitor.tick()
                await monitor.drain()
        assert dms.transitions == [down, down] and len(_writes()) == 1  # the first, still stuck
    finally:
        stuck.set()  # the server answers: the stuck write ends
        await asyncio.gather(*_writes(), return_exceptions=True)
    assert _journal_failures(logs) == [("critical", "record", "TimeoutError")] * 2
    assert monitor.journal_failures == 2 and "account.dms_hook_stuck" not in repr(logs)
    dms.failing.clear()
    clock.advance(2)  # the next retry writes the record again
    monitor.tick()
    await monitor.drain()
    assert journal.open() == [] and len(journal.rows) == 1


async def test_a_call_cancelled_during_its_record_cancels_the_write() -> None:
    journal = Journal()
    journal.hold["record"] = stuck = asyncio.Event()
    monitor, clock, dms = _journaled(journal)
    _down(monitor, clock)
    await asyncio.sleep(0)  # the call starts its write, and waits for it
    (call,) = [t for t in asyncio.all_tasks() if t.get_name() == f"account-dms:{ACC}"]
    (write,) = _writes()
    call.cancel()
    try:
        async with asyncio.timeout(5):  # fails fast, not hangs, if the call awaits its write
            await asyncio.wait({call})
    finally:
        stuck.set()
    await asyncio.wait({write})
    assert write.cancelled() and journal.rows == {} and dms.transitions == []


async def test_a_resolve_stuck_past_its_cancellation_ends_the_call_as_delivered() -> None:
    journal, unretrieved = Journal(), list[object]()
    asyncio.get_running_loop().set_exception_handler(lambda _, context: unretrieved.append(context))
    journal.hold["resolve"], journal.fail["resolve"] = asyncio.Event(), RuntimeError(_ECHO)
    monitor, clock, dms = _journaled(journal, journal_timeout_s=0.001)
    monitor.track(ACC_B)
    try:
        with capture_logs() as logs:
            down = _down(monitor, clock)
            async with asyncio.timeout(5):
                await monitor.drain()
        assert dms.transitions == [down] and monitor.owed() == [] and journal.open() == [ACC]
        assert _journal_failures(logs) == [("error", "resolve", "TimeoutError")]
        assert monitor.journal_failures == 1 and not _HOOK_TROUBLE & {e["event"] for e in logs}
        monitor.rest_ok(ACC_B)  # ACC_B goes down while ACC's write unwinds: the skip is per
        clock.advance(30)  # account, so ACC_B's record is written (its resolve then sticks too)
        monitor.tick()
        await monitor.drain()
        assert journal.open() == [ACC, ACC_B]
    finally:
        journal.hold["resolve"].set()  # its cleanup then fails: the monitor retrieves that
        await asyncio.wait(_writes())  # which retrieves nothing
    gc.collect()
    assert unretrieved == []


@pytest.mark.parametrize("timeout", [0, -1.0, math.inf, math.nan, DMS_HOOK_TIMEOUT_S / 2])
def test_the_journal_bound_must_leave_the_hook_its_own_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="journal_timeout_s"):
        AccountHealthMonitor(FakeClock(), Dms(), journal=Journal(), journal_timeout_s=timeout)


def test_the_default_journal_bound_fits_twice_inside_the_hook_timeout() -> None:
    default = inspect.signature(AccountHealthMonitor).parameters["journal_timeout_s"].default
    assert DMS_JOURNAL_TIMEOUT_S == default == 1.0
    assert 2 * DMS_JOURNAL_TIMEOUT_S < DMS_HOOK_TIMEOUT_S  # so a call that keeps it is never cut


async def test_a_replay_is_ignored_for_an_untracked_account_and_one_that_owes_a_call() -> None:
    monitor, clock, dms = _journaled(Journal())
    dms.hold = asyncio.Event()
    down = _down(monitor, clock)  # ACC owes it, and its call is in flight
    for account in (ACC, ACC_B):
        monitor.replay(HealthTransition(account, down.to_state, down.to_state, "no_success", T0), 9)
    dms.hold.set()
    await monitor.drain()
    assert dms.transitions == [down] and monitor.owed() == []


async def test_an_episode_a_kill_cut_short_is_replayed_once_by_the_next_boot() -> None:
    journal = Journal()
    first = Rig(journal=journal)
    first.dms.hold = asyncio.Event()  # the hook is mid-call when the process is killed
    await _silent_down(first)
    assert journal.open() == [ACC] and first.dms.active == 1
    await _kill()
    second, third = await _restart(journal), await _restart(journal)
    assert second.dms.transitions == first.dms.transitions  # the same episode, dated as it was
    assert third.dms.calls == [] and journal.open() == []


@pytest.mark.parametrize("error", [RuntimeError(_ECHO), asyncio.CancelledError()])
async def test_a_call_whose_resolve_never_committed_is_made_once_more_by_the_next_boot(
    error: BaseException,
) -> None:
    journal = Journal()
    first = Rig(journal=journal)
    journal.fail["resolve"] = error  # the hook has returned; the resolve is lost
    with capture_logs() as logs:
        await _silent_down(first)
        await first.close()
    assert first.dms.calls == [(ACC, "no_success")] and journal.open() == [ACC]
    assert _journal_failures(logs) == [("error", "resolve", type(error).__name__)]
    assert first.runtime.monitor.journal_failures == 1
    del journal.fail["resolve"]
    second, third = await _restart(journal), await _restart(journal)
    assert (second.dms.calls, third.dms.calls) == ([(ACC, "no_success")], [])


async def test_a_resolved_row_is_never_replayed() -> None:
    rig = await _restart(Journal(Episode(ACC, "degraded", "no_success", T0, resolved=True)))
    assert rig.dms.calls == []


async def test_a_row_with_codes_this_version_does_not_know_is_still_replayed() -> None:
    rig = await _restart(Journal(Episode(ACC, "suspended", "key_rejected", T0)))
    lapse = HealthTransition(ACC, HealthState.DOWN, HealthState.DOWN, "no_success", T0)
    assert rig.dms.transitions == [lapse]


async def test_a_failed_replay_read_fails_the_boot_pass_and_the_next_pass_retries_it() -> None:
    journal = Journal(_OPEN)
    journal.fail["read"] = RuntimeError(_ECHO)
    rig = Rig(journal=journal)
    with pytest.raises(RuntimeError):
        await rig.runtime.refresh_tracking()
    assert rig.runtime.monitor.current(ACC) is None  # nothing tracked: the gate refuses it
    journal.fail["read"] = asyncio.CancelledError()  # its driver's: a failed pass, as well
    with pytest.raises(TimeoutError):
        await rig.runtime.refresh_tracking()
    del journal.fail["read"]
    for _ in range(2):  # it works, then a later pass reads no more
        await rig.runtime.refresh_tracking()
    await rig.runtime.monitor.drain()
    assert rig.dms.calls == [(ACC, "no_success")]
    assert journal.limits == [wiring.REPLAY_BATCH + 1] * 3


async def test_a_replay_read_stuck_past_its_cancellation_fails_the_pass_within_its_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiring, "READ_TIMEOUT_S", 0.001)
    journal = Journal(_OPEN)
    journal.hold["read"] = stuck = asyncio.Event()  # it answers neither the read nor its cancel
    rig = Rig(journal=journal)
    for _ in range(2):  # a failed pass each; the second starts no read while the first unwinds
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1) as deadline:  # so that a lost bound fails, not hangs
                await rig.runtime.refresh_tracking()
        assert not deadline.expired() and journal.limits == [wiring.REPLAY_BATCH + 1]
    assert rig.runtime.monitor.current(ACC) is None  # nothing tracked: the gate refuses it
    stuck.set()  # the server answers: the read left to unwind ends, and the next pass replays
    await asyncio.wait({t for t in asyncio.all_tasks() if t.get_name() == "account-health-replay"})
    await rig.runtime.refresh_tracking()
    await rig.runtime.monitor.drain()
    assert rig.dms.calls == [(ACC, "no_success")]


@pytest.mark.parametrize(
    ("batch", "left_open", "logged"),
    [(1, [ACC], [("error", 1)]), (2, [], [])],  # 2: an exact fit
)
async def test_the_replay_reads_one_bounded_batch_and_says_when_rows_are_left_open(
    monkeypatch: pytest.MonkeyPatch, batch: int, left_open: list[Any], logged: list[Any]
) -> None:
    monkeypatch.setattr(wiring, "REPLAY_BATCH", batch)
    journal = Journal(_OPEN, Episode(ACC_B, "healthy", "no_success", T0))
    rig = Rig(ACC, ACC_B, journal=journal)
    with capture_logs() as logs:
        await rig.runtime.refresh_tracking()
        await rig.runtime.monitor.drain()
    assert journal.limits == [batch + 1] and journal.open() == left_open  # the newest first
    truncated = [e for e in logs if e["event"] == "account_health.replay_truncated"]
    assert [(e["log_level"], e["replayed"]) for e in truncated] == logged


async def test_a_replayed_account_no_longer_wanted_is_tracked_for_its_call_then_dropped() -> None:
    rig = Rig(ACC_B, journal=Journal(_OPEN))  # ACC was disabled while the process was down
    before, after = (Conn(rig.hub, rig.topic, owner(), rig.clock) for _ in range(2))
    before.sub(ACC, ACC_B)
    await rig.boot()
    assert rig.dms.calls == [(ACC, "no_success")]  # tracked at boot, so its call is made
    assert rig.runtime.monitor.current(ACC) is not None and rig.runtime.wallets.view(ACC) is None
    after.sub(ACC, ACC_B)  # nor does the `wallet` topic show it: no delta, no snapshot entry
    frames = before.take() + after.take()
    assert {e["exchange_account_id"] for _, p in frames for e in p["health"]} == {str(ACC_B)}
    await rig.run(16)  # the pass at 15 s finds nothing owed for it
    assert rig.runtime.monitor.current(ACC) is None
    await rig.close()


async def test_a_replayed_account_wanted_again_is_announced_by_the_pass_that_finds_it() -> None:
    rig = Rig(ACC_B, journal=Journal(_OPEN))
    conn = Conn(rig.hub, rig.topic, owner(), rig.clock)
    conn.sub(ACC)
    await rig.boot()
    rig.wanted = frozenset({ACC, ACC_B})  # the owner enables ACC again
    await rig.run(16)
    await rig.close()
    assert [len(p["health"]) for _, p in conn.take()] == [0, 1]  # the snapshot, then its start


async def test_an_account_still_down_with_no_evidence_30_s_after_boot_is_owed_one_call() -> None:
    journal = Journal()
    rig = Rig(journal=journal)
    await rig.boot()
    await rig.run(29.5)
    assert rig.dms.calls == []
    await rig.run(60)  # the tick at 30 s finds the window lapsed: one call, not one per tick
    await rig.close()
    at = T0 + timedelta(seconds=30)
    boot = HealthTransition(ACC, HealthState.DOWN, HealthState.DOWN, "never_connected", at)
    assert rig.dms.transitions == [boot] and journal.open() == [] and len(journal.rows) == 1
    assert rig.dms.called_at == [START + 30]  # the tick at exactly 30 s, not the next one


async def test_a_boot_episode_a_late_tick_finds_is_dated_when_its_window_lapsed() -> None:
    clock, dms = FakeClock(), Dms()
    monitor = AccountHealthMonitor(clock, dms)
    monitor.track(ACC, at_boot=True)
    clock.advance(32)  # the first tick after the window comes 2 s late
    monitor.tick()
    await monitor.drain()
    assert [t.at for t in dms.transitions] == [T0 + timedelta(seconds=30)]


async def test_no_boot_episode_once_evidence_arrives_nor_for_an_account_tracked_later() -> None:
    rig = Rig()
    await rig.boot()
    rig.wanted = frozenset({ACC, ACC_B})  # ACC_B is tracked by the pass at 15 s
    await rig.run(10)
    rig.ws.connect()  # ACC's first evidence, at 10 s
    await rig.run(60)
    await rig.close()
    assert rig.dms.calls == []


@pytest.mark.parametrize("fail", [{}, {"record": RuntimeError(_ECHO)}])
async def test_a_replayed_episode_takes_the_place_of_the_boot_episode(
    fail: dict[str, Exception],
) -> None:
    journal = Journal(_OPEN)
    journal.fail.update(fail)  # its call writes no row of its own: it resolves the replayed one
    rig = Rig(journal=journal)
    await rig.boot()
    await rig.run(61)  # still no evidence, well past the boot window
    await rig.close()
    assert (rig.dms.calls, journal.open(), len(journal.rows)) == ([(ACC, "no_success")], [], 1)

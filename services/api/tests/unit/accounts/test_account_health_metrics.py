"""E27-T04 (#837 W6): the catalogue series the account health runtime sets and counts, per state,
reason and result and never per account (SR-125): the health gauge and the transition counter the
AccountDown page reads, the oldest wallet snapshot's age, the reconciliation reads and the
dead-man's-switch journal's failed writes. The wired runtime on a fake clock and sleeper
(`_runtime_rig.Rig`), on the app's catalogue registration."""

from __future__ import annotations

from typing import get_args, get_type_hints

import pytest
from prometheus_client import generate_latest

from candleviewer.account_health_wiring import HEALTH_SERIES, NOTICE_STATES, RECONCILE_RESULTS
from candleviewer.accounts.health import AccountHealthMonitor, HealthReason, HealthState
from candleviewer.accounts.key_age import RotationState
from candleviewer.accounts.verification import KeyRefused, Refusal
from candleviewer.accounts.wallet import WalletPoll, WalletUnavailable
from tests.unit.accounts._fakes import ACC, ACC_B, Dms, FakeClock, Journal
from tests.unit.accounts._runtime_rig import Rig, snapshot

STATES, MOVES = "cv_account_health_state", "cv_account_health_transitions_total"
AGE, READS = "cv_wallet_snapshot_age_seconds", "cv_wallet_reconcile_total"
JOURNAL = "cv_account_dms_journal_failures_total"


def _value(rig: Rig, name: str, **labels: str) -> float | None:
    return rig.metrics.registry.get_sample_value(name, {"env": "demo", **labels})


def _pairs(rig: Rig, name: str) -> dict[tuple[str, str], float | None]:
    return {(s, r): _value(rig, name, state=s, reason=r) for s, r in HEALTH_SERIES}


def test_the_health_pairs_are_the_ones_a_monitored_account_reads_one_per_reason() -> None:
    clock = FakeClock()
    monitor = AccountHealthMonitor(clock, Dms())
    monitor.track(ACC)

    def read() -> tuple[HealthState, HealthReason]:
        view = monitor.view(ACC)
        assert view is not None
        return view.state, view.reason

    seen = [read()]  # never connected
    monitor.ws_heartbeat(ACC)
    seen.append(read())
    clock.advance(10.001)  # the heartbeat has lapsed
    seen.append(read())
    monitor.rest_ok(ACC)
    seen.append(read())
    clock.advance(30)  # no success for the down window
    seen.append(read())
    assert set(seen) == set(HEALTH_SERIES) and len(seen) == len(HEALTH_SERIES)
    assert sorted(reason for _, reason in HEALTH_SERIES) == sorted(get_args(HealthReason))
    assert RECONCILE_RESULTS == get_args(get_type_hints(WalletPoll)["result"])


def test_every_series_reads_zero_from_the_wiring_before_any_event() -> None:
    rig = Rig(source=False)
    assert set(_pairs(rig, STATES).values()) == set(_pairs(rig, MOVES).values()) == {0.0}
    assert {_value(rig, READS, result=result) for result in RECONCILE_RESULTS} == {0.0}
    notices = {_value(rig, "cv_key_rotation_notices_total", state=s) for s in NOTICE_STATES}
    keys = {_value(rig, "cv_keys_rotation_state", state=s) for s in RotationState}
    assert notices == keys == {0.0} and _value(rig, AGE) == _value(rig, JOURNAL) == 0.0


async def test_each_transition_counts_once_under_the_state_entered_and_the_gauge_follows() -> None:
    rig = Rig(ACC, ACC_B)
    await rig.boot()  # both monitored, never connected
    await rig.run(0.5)
    never = {(HealthState.DOWN, "never_connected"): 2.0}
    assert _pairs(rig, STATES) == {pair: never.get(pair, 0.0) for pair in HEALTH_SERIES}
    assert set(_pairs(rig, MOVES).values()) == {0.0}  # never connected is no transition
    rig.ws.connect()
    await rig.run(0.5)
    rig.ws.drop()
    await rig.run(35)  # degraded at once, down 30 s after the last heartbeat
    moved = {("healthy", "ws_heartbeat"), ("degraded", "ws_silent"), ("down", "no_success")}
    assert _pairs(rig, MOVES) == {pair: float(pair in moved) for pair in HEALTH_SERIES}
    now = {(HealthState.DOWN, "no_success"): 1.0, (HealthState.DOWN, "never_connected"): 1.0}
    assert _pairs(rig, STATES) == {pair: now.get(pair, 0.0) for pair in HEALTH_SERIES}
    text = generate_latest(rig.metrics.registry).decode()
    assert str(ACC) not in text and str(ACC_B) not in text  # per state, never per account
    await rig.close()


async def test_the_wallet_age_is_the_oldest_monitored_snapshot_and_0_with_none() -> None:
    rig = Rig(ACC, ACC_B)
    await rig.boot()
    await rig.run(5)
    assert rig.accounts.account_health.wallet_pushed(ACC, snapshot(rig.clock.now()))
    await rig.run(0.5)  # a tick: ACC refreshed 0.5 s ago, ACC_B monitored for 5.5 s with none
    assert _value(rig, AGE) == 5.5
    rig.wanted = frozenset()  # both leave the tracking read: the next one, at 15 s, untracks them
    await rig.run(10)
    assert rig.runtime.monitor.current(ACC_B) is None and _value(rig, AGE) == 0.0
    await rig.close()


async def test_each_reconciliation_read_counts_once_under_how_it_ended() -> None:
    rig = Rig(rest=True)
    await rig.boot()  # not healthy: a read is due every heartbeat window, 10 s
    for error in (WalletUnavailable("no figures"), KeyRefused(Refusal.UNKNOWN_KEY), None):
        rig.rest.error = error
        await rig.run(10)
    assert [_value(rig, READS, result=result) for result in RECONCILE_RESULTS] == [1.0] * 3
    moved = (HealthState.DEGRADED, "rest_only")  # the ok read's `rest_ok` commits it
    assert _pairs(rig, MOVES) == {pair: float(pair == moved) for pair in HEALTH_SERIES}
    await rig.close()


@pytest.mark.parametrize("step", ["record", "resolve"])
async def test_each_failed_journal_write_counts_once_whichever_step_fails(step: str) -> None:
    """The monitor keeps the running total (`journal_failures`); the runtime adds its growth at
    each tick: the series is the total, not the total again at every tick or on each new failure."""
    journal = Journal()
    journal.fail[step] = RuntimeError("echoed exchange text: key abc123")
    rig = Rig(ACC, ACC_B, journal=journal)
    await rig.boot()
    rig.ws.connect()
    await rig.run(0.5)
    rig.ws.drop()  # ACC's last success is at 0 s: down at 30 s
    await rig.run(9.5)
    rig.accounts.account_health.ws_heartbeat(ACC_B)  # ACC_B's is at 10 s: down at 40 s
    await rig.run(35)
    assert rig.runtime.monitor.journal_failures == 2  # one write fails per episode
    assert _value(rig, JOURNAL) == 2.0
    await rig.close()

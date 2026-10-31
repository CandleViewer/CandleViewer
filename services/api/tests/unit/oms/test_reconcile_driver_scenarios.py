"""#914's Gherkin scenarios end to end through the job driver (E29-T06 PR 2b): each pass is started
by a trigger the driver sends B19, on the real binding, built through `cv.statechart.factory`; B1
decides on the real facade where the scenario needs it (`order_rig`), and the naked position is
repaired by the real step-5 writer (`RecordedStopWriter`) on the `critical` lane. The exchange's
rows are the recorded corpus read through the adapter's parser, changing only the fields each test
names (C-13.5). Every scenario asserts the native-stop invariant on its paths (C-2.6). No network,
no sleeps: host timers are held until a test releases them."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.domain.order_entry import OrderEntryGate
from candleviewer.exchange.base.models import RateHeadroom
from candleviewer.oms.reconcile_job import ReconcileJobs
from candleviewer.oms.reconcile_report import STALE_NOTICE, Notice
from candleviewer.oms.reconcile_stops import RecordedStopWriter
from candleviewer.oms.routing import TradingRouter
from candleviewer.statechart.bindings import b19_reconciliation as b19
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from tests.unit.oms.order_rig import Rig
from tests.unit.oms.reconcile_rig import ACCOUNT, T0, World, record, rest, row
from tests.unit.oms.test_reconcile_driver import Timers, _until
from tests.unit.oms.test_reconcile_scenarios import (
    WINDOW_US,
    Scenario,
    _as_row,
    _count,
    _only_reads,
    _Open,
    _unknown,
    rig,
    venue_order,
    venue_position,
)
from tests.unit.oms.test_reconcile_stops import Audit, Gate

__all__ = ["rig"]  # the real facade's fixture, shared with the pass-level scenarios


def _driven(s: Scenario, timers: Timers) -> ReconcileJobs:
    """The scenario's phases under the driver, which is their retry timer too."""
    driver = ReconcileJobs(
        s.phases, standing=s.standing, environment=s.world.environment,
        remediates=lambda _env: True, metrics=s.metrics, pager=s.world.oms,
        sink=InMemoryMachineEventSink(), sleep=timers.sleep,
    )  # fmt: skip
    s.phases._retries = driver  # B19's `schedule_retry_deadline` asks the driver's host timer
    return driver


async def _pass(driver: ReconcileJobs, trigger: Any = None) -> str:
    """One pass: the driver's start (`startup`) or the trigger given; the state B19 rests in."""
    if trigger is None:
        await driver.start([ACCOUNT])
    else:
        await driver.trigger(ACCOUNT, trigger)
    return str(await rest(driver._jobs[ACCOUNT].interp))


@pytest.fixture
def timers() -> Timers:
    return Timers()


async def test_scenario_unknown_resolves_without_resubmission(rig: Rig, timers: Timers) -> None:
    """Given an order in unknown whose orderLinkId is live at the exchange on an order that passes
    the full match with the row, when reconciliation runs, then the order adopts the exchange
    state and no create request is issued."""
    order = await _unknown(rig)
    sent_before = rig.commands.kinds()
    s = Scenario(World(), rig)
    s.world.venue.seed_order(venue_order(**_as_row(order)), uid="1001")
    driver = _driven(s, timers)
    try:
        assert await _pass(driver) == "idle"
        await rig.quiet()
        assert rig.facade.state(order.id) == ("submitted", "not_required")
        assert rig.commands.kinds() == sent_before  # no create was sent
        assert (s.record_of()["trigger"], s.record_of()["corrected"]) == (
            "startup", [order.order_link_id],
        )  # fmt: skip
        _only_reads(s.world)
    finally:
        await driver.stop()


async def test_scenario_unresolvable_order_is_abandoned_deterministically(
    rig: Rig, timers: Timers
) -> None:
    """Given an order in unknown, within the venue's history span, that two consecutive passes
    cannot find in realtime or history, then it becomes rejected with reject_code
    UNRESOLVED_AFTER_RECONCILE and the abandonment is audited."""
    order = await _unknown(rig)
    s = Scenario(World(), rig)
    driver = _driven(s, timers)
    try:
        await _pass(driver)
        await rig.quiet()
        await _pass(driver, "periodic")
        await rig.quiet()
        stored = await rig.store.get(ACCOUNT, order.id)
        assert stored is not None and (stored.state, stored.reject_code) == (
            "rejected", "UNRESOLVED_AFTER_RECONCILE",
        )  # fmt: skip
        events = await rig.events.list_for_order(ACCOUNT, order.id)
        assert [e.to_state for e in events if e.kind == "reconcile_diff"] == ["unknown", "rejected"]
        assert s.record_of()["abandoned"] == [order.order_link_id]  # the `oms.reconcile` record
        _only_reads(s.world)
    finally:
        await driver.stop()


async def test_scenario_exchange_truth_wins_and_is_explained(timers: Timers) -> None:
    """Given local state says the position is 0.2 and the exchange says 0.1, then local state is
    corrected to 0.1, a warning is raised, and the audit record contains both values."""
    from candleviewer.oms.reconciler import PositionDriftSeen

    s = Scenario(World())
    s.world.oms.held[("BTCUSDT", 0)] = PositionDriftSeen("buy", Decimal("0.2"))
    s.world.venue.seed_position(
        venue_position(symbol="BTCUSDT", side="Buy", size="0.1", stopLoss="62000")
    )
    driver = _driven(s, timers)
    try:
        assert await _pass(driver) == "idle"
        [drift] = s.record_of()["position_drift"]
        assert (drift["qty_before"], drift["qty_after"]) == ("0.2", "0.1")
        assert s.notices.published == [(ACCOUNT, Notice("oms.account_desync", "warning"))]
        assert ("apply_position", "BTCUSDT", 0, Decimal("0.1")) in s.world.oms.log
        _only_reads(s.world)
    finally:
        await driver.stop()


async def test_scenario_manual_exchange_orders_are_adopted_not_managed(
    rig: Rig, timers: Timers
) -> None:
    """Given an order exists at Bybit that we never created, then it is stored as untracked,
    shown in the blotter, and is never acted on by rules or algos."""
    s = Scenario(World(), rig)
    manual = venue_order()
    s.world.venue.seed_order(manual, uid="1001")
    driver = _driven(s, timers)
    try:
        await _pass(driver)
        await rig.quiet()
        stored = await rig.store.get_by_exchange_order_id(ACCOUNT, manual.exchange_order_id)
        assert stored is not None and stored.state == "untracked"
        assert [e[0] for e in s.world.oms.log][:2] == ["freeze", "adopted"]  # written ahead
        assert s.record_of()["untracked"] == [stored.order_link_id]
        assert rig.commands.kinds() == []  # never managed: nothing sent for it (S9)
        _only_reads(s.world)
    finally:
        await driver.stop()


async def test_scenario_a_naked_position_is_repaired(timers: Timers) -> None:
    """Given an open position with no exchange-side stop-loss, when reconciliation runs, then with a
    recorded stop in force a protective stop is attached from that record on the critical lane, the
    repair is audited, and naked_position_alerts_total increments; and with no record in force the
    position is paged at P1 and listed in the report, the pass raises its desync notice at
    critical, order entry is not held, and the attach is left to E32-T02."""
    naked = {"symbol": "BTCUSDT", "side": "Buy", "size": "0.2", "stopLoss": "0.00"}
    naked |= {"markPrice": "63100"}  # the trigger can still be placed (24 Sec.8.8 rule 3)
    with_record = Scenario(World())
    with_record.world.oms.records = [record()]
    with_record.world.venue.seed_position(venue_position(**naked))
    audited: list[Any] = []
    writer = RecordedStopWriter(
        router=TradingRouter({"demo": with_record.world.venue},
                             lane_waits={"critical": 5.0, "entry": 5.0, "poll": 5.0}),
        gate=Gate(), audit=Audit(audited),
    )  # fmt: skip
    ports = dataclasses.replace(with_record.reconciler.ports, protective=writer)
    with_record.reconciler._p = ports  # the real step-5 writer in place of the stand-in
    driver = _driven(with_record, timers)
    try:
        await _pass(driver)
        [stop] = [c for c in with_record.world.venue.calls if c.method == "set_trading_stop"]
        assert (stop.lane, stop.request.stop_loss) == ("critical", Decimal(62000))  # native SL
        [(_, recorded)] = audited
        assert (recorded.action, recorded.reason) == ("sl.attached", "record_in_force")
        assert with_record.record_of()["sl_repaired"] == ["BTCUSDT"]
        assert _count(with_record.metrics, "naked_position_alerts_total") == 1
    finally:
        await driver.stop()

    without = Scenario(World())
    without.world.venue.seed_position(venue_position(**naked))
    driver = _driven(without, Timers())
    try:
        await _pass(driver)
        assert [sev for sev, _ in without.world.oms.pages] == ["page"]
        assert without.record_of()["errors"] == [
            {"step": "5", "kind": "no_record_in_force", "subject": "BTCUSDT"}
        ]
        assert without.notices.published == [(ACCOUNT, Notice("oms.account_desync", "critical"))]
        assert without.standing.refusal(ACCOUNT) is None  # order entry is not held (BQ-9)
        _only_reads(without.world)  # no attach: E32-T02's
    finally:
        await driver.stop()


async def test_scenario_repeated_failure_disables_entry_for_that_account(timers: Timers) -> None:
    """Given reconciliation has failed for 2 minutes on account B, then account B is marked stale,
    order entry for it is refused, and the state is published to clients."""
    s = Scenario(World())
    s.world.venue.set_headroom(ACCOUNT, RateHeadroom(lane="poll", tokens=0, wait_s=60))
    driver = _driven(s, timers)
    try:
        assert await _pass(driver) == "backing_off"
        s.world.now_us += WINDOW_US
        await timers.release()  # the driver's host timer sends RETRY_DUE
        assert await _until(driver, "stale_lockout") == "stale_lockout"
        refusal = OrderEntryGate(_Open(), s.standing).refusal(ACCOUNT)
        assert refusal is not None and refusal.reason == "account_stale"
        assert s.notices.published == [(ACCOUNT, STALE_NOTICE)]  # to the system topic
        assert await driver.trigger(ACCOUNT, "periodic") is None  # skipped: no pass runs locked
        assert driver._jobs[ACCOUNT].interp.deferred_count == 0
    finally:
        await driver.stop()


async def test_scenario_a_live_unknown_older_than_24_hours_is_held_never_abandoned(
    timers: Timers,
) -> None:
    """Given a live order in unknown that is older than 24 hours and that two consecutive passes
    cannot find in realtime or history, then it stays unknown, it is paged at P1, and it is not
    rejected."""
    s = Scenario(World(environment="live"))
    s.world.oms.seed(
        row(1, "unknown", lifecycle_state="unknown", created_ts=T0 - timedelta(hours=25))
    )
    driver = _driven(s, timers)
    try:
        await _pass(driver)
        await _pass(driver, "periodic")
        assert s.world.oms.effects("command") == []  # no RECON_MISS: never abandoned
        assert [sev for sev, _ in s.world.oms.pages] == ["page"]  # paged once
        assert s.record_of()["abandoned"] == []
    finally:
        await driver.stop()
    assert not b19.ports_wired()

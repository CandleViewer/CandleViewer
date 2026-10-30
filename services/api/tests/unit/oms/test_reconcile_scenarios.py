"""E29-T06's acceptance scenarios at the unit level (#914 PR 2a; the ticket's Gherkin, named one
test each). The exchange's rows are derived in-test from the recorded corpus (`packages/fixtures/
bybit/2026-10-05/rest/trading-*.json`, the documentation transcriptions) and read through the
adapter's own parser (C-13.5): each test changes only the fields it names. Where B1 decides, the
pass drives the real facade on the real binding (`order_rig`); the rest of the OMS is the recording
double of `reconcile_rig`. Every scenario asserts the native-stop invariant on the paths it takes
(C-2.6): the pass sends no order of its own, and a naked position is attached or paged. The
fixture-replay integration of the wired job is PR 2b's."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator, Collection, Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, ClassVar, Literal
from uuid import UUID

import pytest
from prometheus_client import generate_latest

from candleviewer.domain.order_entry import OrderEntryGate
from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.models import (
    AccountRef,
    Order,
    Position,
    RateHeadroom,
    TradingStopRequest,
)
from candleviewer.exchange.bybit import trading_parse as tp
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import IllegalTransition
from candleviewer.oms.fakes import InMemoryTradingAccounts
from candleviewer.oms.reconcile_phases import ReconcilePhases
from candleviewer.oms.reconcile_report import (
    STALE_NOTICE,
    Notice,
    ReconcileMetrics,
    ReconcileReport,
)
from candleviewer.oms.reconcile_standing import STALE_AFTER_S, FailureTracker, ReconcileStanding
from candleviewer.oms.reconciler import (
    Plan,
    PositionDriftSeen,
    ReconcilePorts,
    Reconciler,
    StopWrite,
)
from candleviewer.oms.routing import TradingRouter
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.bindings import b19_reconciliation as b19
from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from tests._corpus import rest
from tests.unit.oms.order_rig import Rig, build_rig, order_of
from tests.unit.oms.reconcile_rig import (
    ACCOUNT,
    SWEEP_ID,
    T0,
    Marks,
    Notices,
    OmsPositions,
    Records,
    Retries,
    Watermarks,
    World,
    fill,
    record,
    ref,
    row,
    started,
)
from tests.unit.oms.reconcile_rig import (
    rest as rest_of,
)

REALTIME: Mapping[str, Any] = rest("rest/trading-order-realtime.json")["result"]["list"][0]
POSITION: Mapping[str, Any] = rest("rest/trading-position-list.json")["result"]["list"][0]
WINDOW_US = round(STALE_AFTER_S * 1_000_000)


def venue_order(**changed: Any) -> Order:
    """The recorded realtime row, `changed` replacing the fields it names, as the adapter reads
    it."""
    return tp.to_order(tp.parse(tp.OrderRow, {**REALTIME, **changed}, "order"), ref())


def venue_position(**changed: Any) -> Position:
    """The recorded position row (an inverse example: the tests name a linear symbol)."""
    return tp.to_position(tp.parse(tp.PositionRow, {**POSITION, **changed}, "positions"), ref())


def _as_row(order: Any) -> dict[str, Any]:
    """The realtime fields that make the recorded row the rig's order 1 (`order_rig.order_of`)."""
    return {
        "orderId": "x1", "orderLinkId": order.order_link_id, "symbol": "BTCUSDT", "side": "Buy",
        "price": "63000", "qty": "1", "leavesQty": "1", "stopLoss": "62000", "takeProfit": "0",
        "positionIdx": 0,
    }  # fmt: skip


class StoreReads:
    """The order and execution stores' reads the pass takes, over the rig's in-memory stores."""

    def __init__(self, rig: Rig) -> None:
        self._rig = rig
        rig.store._environments[ACCOUNT] = "demo"  # the account's environment (`seed_account`)

    async def unfinished_for(self, account_id: UUID) -> tuple[OrderRow, ...]:
        rows = await self._rig.store.list_unfinished("demo", limit=1000)
        return tuple(r for r in rows if r.exchange_account_id == account_id)

    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> OrderRow | None:
        return await self._rig.store.get_by_exchange_order_id(account_id, xid)

    async def get_by_link_id(self, account_id: UUID, link: str) -> OrderRow | None:
        return await self._rig.store.get_by_link_id(account_id, link)

    async def link_id_taken(self, link: str) -> bool:
        return await self._rig.store.link_id_taken(link)

    async def stored(self, account_id: UUID, exec_ids: Collection[str]) -> frozenset[str]:
        held = [i for i in exec_ids if await self._rig.fills.get(account_id, i) is not None]
        return frozenset(held)

    async def insert(self, execution: NewExecution) -> bool:
        return await self._rig.fills.insert(execution)


class VenueStopWriter:
    """A stand-in for E29-T04's recorded-stop writer (PR 2b binds the real one): the record's stop
    sent with `set_trading_stop`, which the venue takes on the `critical` lane."""

    def __init__(self, world: World) -> None:
        self._venue = world.venue

    async def attach_recorded(
        self, account: AccountRef, p: Position, rec: RecordedStopRow, *, pass_id: str
    ) -> StopWrite:
        request = TradingStopRequest(
            account=account, symbol=p.symbol, position_idx=p.position_idx,
            stop_loss=rec.trigger_price,
        )  # fmt: skip
        return "sent" if (await self._venue.set_trading_stop(request)).ok else "refused"

    async def restore_recorded(
        self, account: AccountRef, p: Position, rec: RecordedStopRow, *, pass_id: str
    ) -> StopWrite:
        return await self.attach_recorded(account, p, rec, pass_id=pass_id)


@dataclass
class Scenario:
    """The pass over the real facade (`facade`), or the recording one, with B19's port."""

    world: World
    rig: Rig | None = None

    def __post_init__(self) -> None:
        w, oms = self.world, self.world.oms
        reads: Any = StoreReads(self.rig) if self.rig is not None else oms
        machines: Any = self.rig.facade if self.rig is not None else oms
        waits = {"critical": 5.0, "entry": 5.0, "poll": 5.0}
        ports = ReconcilePorts(
            accounts=InMemoryTradingAccounts(ref(environment=w.environment)),
            router=TradingRouter({w.environment: w.venue}, lane_waits=waits),
            orders=reads, executions=reads, stops=oms, handovers=oms, machines=machines,
            positions=OmsPositions(oms), protective=VenueStopWriter(w), lockout=oms,
            exchange_placed=oms, adoptions=oms, pager=oms,
        )  # fmt: skip
        self.metrics = Metrics("dev")
        self.standing = ReconcileStanding()
        self.notices, self.records, self.watermarks = Notices(), Records(), Watermarks()
        self.episode = False  # a desync or stale episode open, as B19's context carries it
        counted = ReconcileMetrics(self.metrics)
        self.reconciler = Reconciler(ports, now_us=lambda: w.now_us, on_naked=counted.naked)
        self.phases = ReconcilePhases(
            self.reconciler, standing=self.standing, tracker=FailureTracker(), marks=Marks(),
            watermarks=self.watermarks, records=self.records, notices=self.notices,
            retries=Retries(), metrics=counted, pager=oms, now_us=lambda: w.now_us,
        )  # fmt: skip

    async def run(self, trigger: str = "periodic") -> dict[str, Any]:
        """One pass as B19 runs it: its phases, its report, then its notices handed on."""
        account = str(ACCOUNT)
        await self.phases.fetch(account, pass_id=SWEEP_ID, trigger=trigger)
        await self.phases.diff(account, pass_id=SWEEP_ID)
        await self.phases.remediate(account, pass_id=SWEEP_ID)
        summary = dict(await self.phases.report(
            account, pass_id=SWEEP_ID, trigger=trigger, episode_open=self.episode, failure=None
        ))  # fmt: skip
        self.episode = summary["episode_open"]
        self.phases.publish(account, summary["notices"])
        self.phases.observe(account, pass_id=SWEEP_ID)
        return summary

    def record_of(self, n: int = -1) -> Mapping[str, Any]:
        """The `oms.reconcile` record of pass `n` (`stage: finished`)."""
        return self.records.rows[n][2]


def _only_reads(world: World, *also: str) -> None:
    """C-2.6: the pass placed, amended and cancelled nothing at the venue."""
    allowed = {"open_orders", "positions", "executions", "order_history", *also}
    assert {c.method for c in world.venue.calls} <= allowed


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = build_rig()
    yield built
    await built.facade.stop()


async def _unknown(rig: Rig) -> Any:
    """Order 1, whose place had an ambiguous outcome: `unknown` and unbound (24 Sec.8.2 S1)."""

    async def ambiguous(_command: b01.Command) -> Mapping[str, Any]:
        raise TimeoutError

    rig.commands.on_place = ambiguous
    order = order_of()
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    assert rig.facade.state(order.id) == ("unknown", "not_required")
    return order


async def test_scenario_unknown_resolves_without_resubmission(rig: Rig) -> None:
    """Given an order in unknown whose orderLinkId is live at the exchange on an order that passes
    the full match with the row, when reconciliation runs, then the order adopts the exchange state
    and no create request is issued."""
    order = await _unknown(rig)
    sent_before = rig.commands.kinds()
    s = Scenario(World(), rig)
    s.world.venue.seed_order(venue_order(**_as_row(order)), uid="1001")
    summary = await s.run()
    await rig.quiet()
    assert rig.facade.state(order.id) == ("submitted", "not_required")
    stored = await rig.store.get(ACCOUNT, order.id)
    assert stored is not None and (stored.exchange_order_id, stored.stop_loss) == (
        "x1",
        Decimal(62000),
    )
    assert rig.commands.kinds() == sent_before  # no create, and no other command, was sent
    _only_reads(s.world)
    assert (s.record_of()["corrected"], summary["outcome"]) == (
        [order.order_link_id],
        "corrected",
    )


async def test_scenario_unresolvable_order_is_abandoned_deterministically(rig: Rig) -> None:
    """Given an order in unknown, within the venue's history span, that two consecutive passes
    cannot find in realtime or history, then it becomes rejected with reject_code
    UNRESOLVED_AFTER_RECONCILE and the abandonment is audited."""
    order = await _unknown(rig)
    s = Scenario(World(), rig)
    await s.run()
    await rig.quiet()
    assert rig.facade.state(order.id) == ("unknown", "not_required")
    await s.run()
    await rig.quiet()
    stored = await rig.store.get(ACCOUNT, order.id)
    assert stored is not None and (stored.state, stored.reject_code) == (
        "rejected", "UNRESOLVED_AFTER_RECONCILE",
    )  # fmt: skip
    events = await rig.events.list_for_order(ACCOUNT, order.id)
    misses = [e for e in events if e.kind == "reconcile_diff"]
    assert [(e.source, e.to_state) for e in misses] == [
        ("reconcile", "unknown"),
        ("reconcile", "rejected"),
    ]
    assert (s.record_of(0)["abandoned"], s.record_of(1)["abandoned"]) == ([], [order.order_link_id])
    _only_reads(s.world)


async def test_scenario_exchange_truth_wins_and_is_explained() -> None:
    """Given local state says the position is 0.2 and the exchange says 0.1, then local state is
    corrected to 0.1, a warning is raised, and the audit record contains both values."""
    s = Scenario(World())
    s.world.oms.held = {("BTCUSDT", 0): PositionDriftSeen("buy", Decimal("0.2"))}
    s.world.venue.seed_position(
        venue_position(symbol="BTCUSDT", side="Buy", size="0.1", stopLoss="62000")
    )
    await s.run()
    assert s.world.oms.held[("BTCUSDT", 0)] == PositionDriftSeen("buy", Decimal("0.1"))
    assert s.notices.published == [(ACCOUNT, Notice("oms.account_desync", "warning"))]
    [drift] = s.record_of()["position_drift"]
    assert (drift["qty_before"], drift["qty_after"]) == ("0.2", "0.1")
    _only_reads(s.world)


async def test_scenario_manual_exchange_orders_are_adopted_not_managed(rig: Rig) -> None:
    """Given an order exists at Bybit that we never created, then it is stored as untracked, shown
    in the blotter, and is never acted on by rules or algos."""
    s = Scenario(World(), rig)
    manual = venue_order()  # the recorded row as it stands: a link id that is none of ours
    s.world.venue.seed_order(manual, uid="1001")
    await s.run()
    await rig.quiet()
    stored = await rig.store.get_by_exchange_order_id(ACCOUNT, manual.exchange_order_id)
    assert stored is not None
    assert (stored.state, stored.provenance, stored.order_link_id) == (
        "untracked", "reconciliation", ext_key(manual.exchange_order_id),
    )  # fmt: skip
    kinds = [e[0] for e in s.world.oms.log]
    assert kinds[:2] == ["freeze", "adopted"]  # SR-E27-19, then written ahead of the row (BQ-17)
    for actor in ("rule", "algo"):
        with pytest.raises(IllegalTransition):
            await rig.facade.command(ACCOUNT, stored.id, "CANCEL", actor=actor)  # S9
    assert rig.commands.kinds() == []
    _only_reads(s.world)


async def test_a_resting_untracked_order_is_found_every_pass_but_never_a_correction(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BQ-6, 23 Sec.15.9: B1's `untracked` takes `RECON_FOUND_LIVE` and stays there, so the pass
    after an adoption sends the finding, lists no correction, is clean and sends the synced row.
    The untracked count reads 1 after each pass; a pass that cannot read the rows leaves it."""
    s = Scenario(World(), rig)
    counted: list[int | None] = []
    sent: list[str] = []
    finish, command = s.reconciler.finish, rig.facade.command

    def counting(plan: Plan) -> ReconcileReport:
        counted.append(plan.untracked)
        return finish(plan)

    async def spying(*args: Any, **kwargs: Any) -> str:
        sent.append(args[2])
        return await command(*args, **kwargs)

    monkeypatch.setattr(s.reconciler, "finish", counting)
    monkeypatch.setattr(rig.facade, "command", spying)
    manual = venue_order()
    s.world.venue.seed_order(manual, uid="1001")
    first = await s.run()
    await rig.quiet()
    second = await s.run()
    await rig.quiet()
    stored = await rig.store.get_by_exchange_order_id(ACCOUNT, manual.exchange_order_id)
    assert stored is not None and stored.state == "untracked"
    assert (s.record_of(0)["untracked"], first["notices"]) == (
        [stored.order_link_id], [["oms.account_desync", "warning"]],
    )  # fmt: skip
    assert (sent, s.record_of(1)["corrected"], s.record_of(1)["result"]) == (
        ["RECON_FOUND_LIVE"], [], "clean",
    )  # fmt: skip
    assert second["notices"] == [["oms.account_synced", "info"]]
    assert (counted, _count(s.metrics, "oms_untracked_orders")) == ([1, 1], 1)

    async def unreadable(*_a: Any, **_k: Any) -> Any:
        raise ConnectionError("the order store is down")

    monkeypatch.setattr(rig.store, "list_unfinished", unreadable)
    await s.run()
    assert (counted[-1], _count(s.metrics, "oms_untracked_orders")) == (None, 1)
    _only_reads(s.world)


async def _filled_after_adoption(s: Scenario, rig: Rig, *parts: str) -> Order:
    """A manual order adopted `untracked`, then filled at the venue in `parts`, each a fill the
    next pass's window holds."""
    manual = venue_order()
    s.world.venue.seed_order(manual, uid="1001")
    await s.run()
    await rig.quiet()
    s.world.venue._open.pop(manual.exchange_order_id)  # it filled after its adoption
    filled = venue_order(orderStatus="Filled", cumExecQty="0.10", leavesQty="0", avgPrice="1600")
    s.world.venue.seed_order(filled, uid="1001")
    s.world.now_us += 30_000_000
    for n, qty in enumerate(parts, start=1):
        s.world.venue.seed_execution(fill(
            f"m{n}", exchange_order_id=manual.exchange_order_id,
            order_link_id=manual.order_link_id, symbol="ETHUSDT", price=Decimal(1600),
            qty=Decimal(qty), ts_exec=s.world.now_us - 10_000_000 + n, seq=n,
        ))  # fmt: skip
    await s.run()
    await rig.quiet()
    return manual


async def test_an_adopted_untracked_order_that_later_fills_is_closed_by_its_finding(
    rig: Rig,
) -> None:
    """B1's `untracked` closes on `RECON_FOUND_FILLED`, which carries the fill that completes it:
    the pass holds that fill for the finding, so the row ends `filled` with the fill stored,
    nothing is listed `fills_unread`, the watermark advances, and nothing is sent to the venue."""
    s = Scenario(World(), rig)
    manual = await _filled_after_adoption(s, rig, "0.10")
    stored = await rig.store.get_by_exchange_order_id(ACCOUNT, manual.exchange_order_id)
    assert stored is not None and stored.state == "filled"
    assert await rig.fills.get(ACCOUNT, "m1") is not None
    assert (s.record_of()["resolved_from_history"], s.record_of()["errors"]) == (
        [stored.order_link_id], [],
    )  # fmt: skip
    assert s.watermarks.advanced[-1] == s.world.now_us
    assert rig.commands.kinds() == []  # a discovered order's stop is not the OMS's (S9)
    _only_reads(s.world)


async def test_an_untracked_order_filled_in_several_fills_is_never_sent_a_refused_finding(
    rig: Rig,
) -> None:
    """B1 version 7 records an `untracked` row's `EXEC` and applies nothing, and the store takes
    `filled` only with the row's `qty` filled, so no one fill can close an order filled in two:
    the pass sends it no finding the store would refuse and lists it, holding the watermark."""
    s = Scenario(World(), rig)
    manual = await _filled_after_adoption(s, rig, "0.04", "0.06")
    stored = await rig.store.get_by_exchange_order_id(ACCOUNT, manual.exchange_order_id)
    assert stored is not None and stored.state == "untracked"
    assert s.record_of()["errors"] == [
        {"step": "3b", "kind": "fills_unread", "subject": stored.order_link_id}
    ]
    assert (len(s.watermarks.advanced), rig.commands.kinds()) == (1, [])  # the adoption's only
    _only_reads(s.world)


async def test_scenario_a_naked_position_is_repaired() -> None:
    """Given an open position with no exchange-side stop-loss, when reconciliation runs, then with a
    recorded stop in force a protective stop is attached from that record on the critical lane,
    the repair is audited, and naked_position_alerts_total increments; and with no record in force
    the position is paged at P1 and listed in the report, the pass raises its desync notice at
    critical, order entry is not held, and the attach is left to E32-T02."""
    naked = {"symbol": "BTCUSDT", "side": "Buy", "size": "0.2", "stopLoss": "0.00"}
    with_record = Scenario(World())
    with_record.world.oms.records = [record()]
    with_record.world.venue.seed_position(venue_position(**naked))
    await with_record.run()
    [stop] = [c for c in with_record.world.venue.calls if c.method == "set_trading_stop"]
    assert (stop.lane, stop.request.stop_loss) == ("critical", Decimal(62000))  # native SL
    assert with_record.record_of()["sl_repaired"] == ["BTCUSDT"]
    assert _count(with_record.metrics, "naked_position_alerts_total") == 1
    _only_reads(with_record.world, "set_trading_stop")

    without = Scenario(World())
    without.world.venue.seed_position(venue_position(**naked))
    summary = await without.run()
    assert [s for s, _ in without.world.oms.pages] == ["page"]
    assert without.record_of()["errors"] == [
        {"step": "5", "kind": "no_record_in_force", "subject": "BTCUSDT"}
    ]
    assert without.notices.published == [(ACCOUNT, Notice("oms.account_desync", "critical"))]
    assert without.standing.refusal(ACCOUNT) is None and summary["unresolved"] == 0
    _only_reads(without.world)  # no attach: E32-T02's


async def test_scenario_repeated_failure_disables_entry_for_that_account() -> None:
    """Given reconciliation has failed for 2 minutes on account B, then account B is marked stale,
    order entry for it is refused, and the state is published to clients."""
    s = Scenario(World())
    s.world.venue.set_headroom(ACCOUNT, RateHeadroom(lane="poll", tokens=0, wait_s=60))
    b19.set_ports(s.phases)
    interp = await started()
    try:
        await interp.send("STARTUP")
        assert await rest_of(interp) == "backing_off"
        s.world.now_us += WINDOW_US
        await interp.send("RETRY_DUE")
        assert await rest_of(interp) == "stale_lockout"
        refusal = OrderEntryGate(_Open(), s.standing).refusal(ACCOUNT)
        assert refusal is not None and refusal.reason == "account_stale"
        assert s.notices.published == [(ACCOUNT, STALE_NOTICE)]  # handed on to the system topic
    finally:
        await interp.stop()
        b19.set_ports(None)


async def test_scenario_a_live_unknown_older_than_24_hours_is_held_never_abandoned() -> None:
    """Given a live order in unknown that is older than 24 hours and that two consecutive passes
    cannot find in realtime or history, then it stays unknown, it is paged at P1, and it is not
    rejected."""
    s = Scenario(World(environment="live"))
    old = row(1, "unknown", lifecycle_state="unknown", created_ts=T0 - timedelta(hours=25))
    s.world.oms.seed(old)
    await s.run()
    await s.run()
    assert s.world.oms.effects("command") == []
    assert [sev for sev, _ in s.world.oms.pages] == ["page"]
    assert s.record_of(1)["abandoned"] == []


class _Open:
    """The maintenance check, open: the gate's first slot."""

    scope: ClassVar[Literal["global"]] = "global"

    def refusal(self, account_id: UUID) -> None:
        return None


def _count(metrics: Metrics, name: str) -> float:
    lines = generate_latest(metrics.registry).decode().splitlines()
    return sum(float(line.rsplit(" ", 1)[1]) for line in lines if line.split("{")[0] == name)

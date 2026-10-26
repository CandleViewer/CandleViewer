"""A recorded stop's order on the private stream (E29-T05 #848, S6b; 24-internal-schemas.md
Sec.8.12 pairing step 3, Sec.8.3 rule 7): `StreamPushes` over the real `RecordedStopStream`, the
real facade (`OrderMachines` on B1) and the in-memory stores. The pushes come from #4135's
transcribed frame shapes through the adapter's own parser (C-13.5). No network, no sleeps."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import AccountRef, Execution, Order, Position, PrivateEvent
from candleviewer.oms import recorded_stop_stream as rss
from candleviewer.oms import stream_push
from candleviewer.oms.errors import OrderStepRefused
from candleviewer.oms.fakes import InMemoryRecordedStopStore
from candleviewer.oms.pairing import ToRecordedStop
from candleviewer.oms.ports import KeyedRecord, PositionKey
from candleviewer.oms.push_mapping import ForPairing, route
from candleviewer.oms.recorded_stop_stream import RecordedStopStream, Successor
from candleviewer.oms.repository import RecordedStopRepository
from candleviewer.oms.stream_push import StreamPushes
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.orders import NewOrder, OrderRow, RecordedStopBind
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B, account, link
from tests.unit.oms import position_rig
from tests.unit.oms.order_rig import T0, Rig, build_rig, order_of
from tests.unit.oms.submission_contract import EVENT, trading_stop
from tests.unit.oms.test_stream_push import STOP, event

XID = "9aac161b-8ed6-450d-9cab-c5cc67c21784"  # the transcribed frames' order id
ROW_ID = UUID(int=0x5B)
WINNER = UUID(int=0x77)  # the row a concurrent materialise wrote first
KEY = PositionKey(ACCOUNT_A, "BTCUSDT", 0)
TRIGGERED = STOP | {"orderStatus": "Triggered"}
FULL = STOP | {"stopOrderType": "StopLoss", "tpslMode": "Full", "qty": "0.7"}


@dataclass
class Ports:
    """Every other port of the stream: the fill's order, the lockout, the hand-over, the
    exchange-placed records, the counts, the pager, the account and the record hook."""

    order: Order | None = None
    calls: list[str] = field(default_factory=list)
    counts: list[str] = field(default_factory=list)
    hooked: list[PositionKey] = field(default_factory=list)
    account_error: Exception | None = None
    position: Position | None = None  # the projection's last applied row for the key
    summaries: list[tuple[str, str]] = field(default_factory=list)
    audited: list[KeyedRecord] = field(default_factory=list)  # the successor's release records

    async def order_of(self, account_id: UUID, xid: str, symbol: str) -> Order | None:
        return self.order

    async def open(self, account_id: UUID, *, finding: str, key: str) -> None:
        self.calls.append(f"lockout:{finding}")

    async def exchange_placed(self, account_id: UUID, *, finding: str, key: str) -> None:
        self.calls.append("exchange_placed")

    async def hand_over_execution(
        self, account_id: AccountId, execution: Execution, *, empty_read: bool = False
    ) -> None:
        self.calls.append("handover")

    def count(self, outcome: str) -> None:
        self.counts.append(outcome)

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.calls.append("page")
        self.summaries.append((machine_kind, summary))

    async def trading_account(self, account_id: AccountId) -> AccountRef:
        if self.account_error is not None:
            raise self.account_error
        return account(account_id)

    async def after_bind(self, key: PositionKey) -> None:
        self.hooked.append(key)

    def last_applied(self, key: PositionKey) -> Position | None:
        return self.position if key == KEY else None

    async def write(self, record: KeyedRecord) -> None:  # the successor's `ReleaseAudit`
        self.audited.append(record)


@dataclass
class World:
    rig: Rig
    ports: Ports = field(default_factory=Ports)
    machines: Any = None
    positions: Any = None
    reads: Any = None  # the stream's order reads, when not the store's own
    stops: Any = None  # the successor's record store, when not the repository over the rig's
    clock: Callable[[], datetime] = lambda: T0  # the OMS's clock
    audit: Any = None  # the successor's release audit, when not the ports' list
    kept: Successor | None = None  # one successor across runs (its push times), when set

    def successor(self) -> Successor:
        stops = self.stops or RecordedStopRepository(self.rig.store.stops)
        return Successor(
            stops=stops, audit=self.audit or self.ports, positions=self.positions or self.ports,
            counts=self.ports, clock=self.clock,
        )  # fmt: skip

    def stream(self) -> RecordedStopStream:
        return RecordedStopStream(
            machines=self.machines or self.rig.facade, reads=self.reads or self.rig.orders,
            accounts=self.ports, positions=self.positions or self.ports, counts=self.ports,
            pager=self.ports, new_id=lambda: ROW_ID,
        )  # fmt: skip

    async def run(self, ev: PrivateEvent) -> None:
        r = route(ev)
        assert isinstance(r, ForPairing)
        p = self.ports
        pushes = StreamPushes(
            target=self.rig.facade, reads=self, fill_orders=p, lockout=p, handovers=p,
            stops=self.stream(), successors=self.kept or self.successor(), no_intent=p,
            counts=p, pager=p, monotonic=asyncio.get_running_loop().time,
        )  # fmt: skip
        async with asyncio.timeout(5.0):  # real seconds: only a failing test's
            await pushes.handle(ev.account_id, ev, r)

    # `StreamReads`: the order store's reads and the recorded stops' live read.
    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> OrderRow | None:
        return await self.rig.orders.get_by_exchange_order_id(account_id, xid)

    async def get_by_link_id(self, account_id: UUID, link_id: str) -> OrderRow | None:
        return await self.rig.orders.get_by_link_id(account_id, link_id)

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        return await self.rig.store.stops.live_for_key(account_id, symbol, position_idx)

    async def record(self, **over: Any) -> RecordedStopRow:
        """The account's recorded Partial stop-loss of the long that `STOP` matches; for a
        take-profit, that side of a request whose stop-loss side never matches the push."""
        values: dict[str, Any] = {"tpsl_mode": "Partial", "size": Decimal("0.5")}
        values |= {"trigger_price": Decimal(94000)}
        request = [trading_stop(ACCOUNT_A, **(values | over))]
        if over.get("kind") == "take_profit":
            audit = request[0].audit_record_id
            sl = values | {"trigger_price": Decimal(60000), "audit_record_id": audit}
            request.insert(0, trading_stop(ACCOUNT_A, **sl))
        return (await self.rig.store.stops.insert(request))[-1]

    async def row(self) -> OrderRow | None:
        return await self.rig.orders.get_by_exchange_order_id(ACCOUNT_A, XID)

    async def bound(self) -> list[UUID]:
        return [r.id for r in await self.rig.store.stops.for_exchange_order(ACCOUNT_A, XID)]


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    out = World(build_rig())
    yield out
    await out.rig.facade.stop()


def stop_order(**push: Any) -> Order:
    """The recorded stop's TP/SL order as a push or a read shows it."""
    order = event("order", orderId=XID, **(STOP | push)).payload
    assert isinstance(order, Order)
    return order


def decision(record: RecordedStopRow, **push: Any) -> ToRecordedStop:
    return ToRecordedStop(record, stop_order(**push))


async def take(world: World, d: ToRecordedStop) -> OrderRow | None:
    return await world.stream().take(ACCOUNT_A, d, d.order, None, 0)


# The materialised row (AC 7; 24 Sec.8.3 rule 7).
@pytest.mark.parametrize(
    ("kind", "stop_order_type"),
    [("stop_loss", "PartialStopLoss"), ("take_profit", "PartialTakeProfit")],
    ids=["stop_loss", "take_profit"],
)
async def test_recorded_stop_order_push_materialises_a_bound_reduce_only_row_and_sends_nothing(
    world: World, kind: str, stop_order_type: str
) -> None:
    """The row's purpose is the record's kind (the security lens's F3)."""
    record = await world.record(kind=kind)
    await world.run(event("order", orderId=XID, **(STOP | {"stopOrderType": stop_order_type})))
    row = await world.row()
    assert row is not None and row.id == ROW_ID
    assert (row.provenance, row.intent, row.lifecycle_state) == (
        "recorded_stop", kind, "submitted",
    )  # fmt: skip
    assert (row.reduce_only, row.close_on_trigger, row.trade_group_leg_id) == (True, True, None)
    assert (row.qty, row.trigger_price, row.position_idx, row.side) == (
        Decimal("0.5"), Decimal(94000), 0, "Sell",
    )  # fmt: skip
    assert await world.bound() == [record.id]
    assert world.rig.commands.sent == [] and world.ports.calls == []
    assert world.ports.counts == ["stop_materialised"] and world.ports.hooked == [KEY]


async def test_recorded_stop_fill_first_materialises_from_the_order_read_and_applies_to_the_row(
    world: World,
) -> None:
    """Pairing step 3 on a fill's order read: the row is materialised from the read order and
    the fill applies to it; no lockout, no hand-over."""
    record = await world.record()
    world.ports.order = stop_order(**TRIGGERED)
    await world.run(event("execution", orderId=XID))
    row = await world.row()
    assert row is not None and row.cum_exec_qty == Decimal("0.5")
    assert await world.bound() == [record.id] and world.ports.calls == []
    assert world.ports.counts == ["stop_materialised", "paired"]


@pytest.mark.parametrize("held", [False, True], ids=["ours", "held"])
async def test_materialised_rows_link_id_is_ours_when_no_row_holds_it_else_ext_key(
    world: World, held: bool
) -> None:
    ours = link()
    if held:  # an order of the account already holds the push's own id
        await world.rig.store.create(
            order_of(5, exchange_account_id=ACCOUNT_A, order_link_id=ours), EVENT
        )
    await world.record()
    await world.run(event("order", orderId=XID, **(STOP | {"orderLinkId": ours})))
    row = await world.row()
    assert row is not None and row.order_link_id == (ext_key(XID) if held else ours)


async def test_materialised_rows_foreign_or_empty_link_id_is_ext_key(world: World) -> None:
    await world.record()
    await world.run(event("order", orderId=XID, **(STOP | {"orderLinkId": ""})))
    row = await world.row()
    assert row is not None and row.order_link_id == ext_key(XID)


async def test_materialised_full_mode_row_takes_the_orders_quantity_never_the_records(
    world: World,
) -> None:
    await world.record(tpsl_mode="Full", size=None)
    await world.run(event("order", orderId=XID, **FULL))
    row = await world.row()
    assert row is not None and (row.qty, row.tpsl_mode) == (Decimal("0.7"), "Full")


@pytest.mark.parametrize("shown", ["0.7", "0"], ids=["order_qty", "qty_zero"])
async def test_full_mode_fill_materialises_a_row_sized_to_the_fill_which_fills_it(
    world: World, shown: str
) -> None:
    """The orchestrator's 07:20Z ruling: a Full-mode stop closes whatever the position is at its
    trigger, so a fill that materialises the row sizes it (the security lens's F1 fix b): the
    row is filled, with no over-fill and no lockout, whatever the order showed."""
    record = await world.record(tpsl_mode="Full", size=None)
    world.ports.order = stop_order(**(FULL | {"qty": shown, "orderStatus": "Triggered"}))
    await world.run(event("execution", orderId=XID, execQty="0.4"))
    row = await world.row()
    assert row is not None and (row.qty, row.cum_exec_qty, row.lifecycle_state) == (
        Decimal("0.4"), Decimal("0.4"), "filled",
    )  # fmt: skip
    assert await world.bound() == [record.id] and world.ports.calls == []
    assert world.ports.counts == ["stop_materialised", "paired"]


async def test_partial_mode_fill_materialises_a_row_sized_to_its_order_not_to_the_fill(
    world: World,
) -> None:
    """Only a Full-mode fill sizes the row (the delta's D1): a Partial stop's first fill of 0.2
    leaves its row at the order's 0.5, partially filled, so its later fills fit."""
    record = await world.record()
    world.ports.order = stop_order(orderStatus="Triggered")
    await world.run(event("execution", orderId=XID, execQty="0.2"))
    row = await world.row()
    assert row is not None and (row.qty, row.cum_exec_qty, row.lifecycle_state) == (
        Decimal("0.5"), Decimal("0.2"), "partially_filled",
    )  # fmt: skip
    assert await world.bound() == [record.id]


async def test_full_mode_fill_after_a_flat_push_materialises_from_the_fill_and_ends_the_record(
    world: World,
) -> None:
    """S5c R5 with the order showing 0 (the security lens's F2): the flat push came first, so the
    projection holds no open position to size from; the fill sizes the row, the record binds,
    and the hook then ends it."""
    record = await world.record(tpsl_mode="Full", size=None)
    world.rig.store._stops[record.id] = replace(record, status="in_force", in_force_at=T0)
    rig = position_rig.Rig()
    stops = RecordedStopRepository(InMemoryRecordedStopStore(world.rig.store))
    made = rig.projection(stops=stops, order_rows=world.rig.orders, now=lambda: T0)
    flat = position_rig.position(
        account_id=ACCOUNT_A, qty=Decimal(0), side=None, updated_at=_us(T0 + timedelta(hours=1))
    )
    await made.take(ACCOUNT_A, flat, position_rig.routed(flat))
    world.positions = made
    world.ports.order = stop_order(**ZERO)
    await world.run(event("execution", orderId=XID, execQty="0.4"))
    row = await world.row()
    assert row is not None and (row.qty, row.lifecycle_state) == (Decimal("0.4"), "filled")
    assert await world.bound() == [record.id]
    assert world.rig.store._stops[record.id].status == "ended"
    assert world.ports.calls == []


async def test_materialise_then_after_bind_ends_a_fired_full_stop_whose_flat_push_came_first(
    world: World,
) -> None:
    """S5c R5 carried through: the flat push came first and kept the unbound record; its order's
    push materialises the row, binds the record, and the hook then ends it."""
    record = await world.record(tpsl_mode="Full", size=None)
    world.rig.store._stops[record.id] = replace(record, status="in_force", in_force_at=T0)
    rig = position_rig.Rig()
    stops = RecordedStopRepository(InMemoryRecordedStopStore(world.rig.store))
    made = rig.projection(stops=stops, order_rows=world.rig.orders, now=lambda: T0)
    later = T0 + timedelta(hours=1)
    flat = position_rig.position(
        account_id=ACCOUNT_A, qty=Decimal(0), side=None, updated_at=_us(later)
    )
    await made.take(ACCOUNT_A, flat, position_rig.routed(flat))
    assert world.rig.store._stops[record.id].status == "in_force"
    world.positions = made
    await world.run(event("order", orderId=XID, **(FULL | {"orderStatus": "Triggered"})))
    assert await world.bound() == [record.id]
    assert world.rig.store._stops[record.id].status == "ended"


# Nothing acts on an unknown or refused write (24 Sec.8.12, the ruling's Q5).
@dataclass
class Racing:
    """A materialise that another materialise of the same order beat: the winner's row lands
    first, so this one meets `ux_orders_exch_id` (the second finds the row)."""

    world: World
    winner: UUID = WINNER
    calls: int = 0

    async def materialise(
        self, order: NewOrder, *, environment: str, binds: RecordedStopBind | None = None
    ) -> str:
        self.calls += 1
        first = replace(order, id=self.winner)
        await self.world.rig.facade.materialise(first, environment=environment, binds=binds)
        return await self.world.rig.facade.materialise(order, environment=environment, binds=binds)


async def test_materialise_meeting_a_concurrent_one_rereads_and_the_push_goes_to_the_found_row(
    world: World,
) -> None:
    record = await world.record()
    racing = Racing(world)
    world.machines = racing
    await world.run(event("order", orderId=XID, **TRIGGERED))
    row = await world.row()
    assert racing.calls == 1 and row is not None and row.id == racing.winner
    state = world.rig.facade.state(racing.winner)
    assert state is not None and state[0] == "triggered"
    assert world.rig.facade.state(ROW_ID) is None and await world.bound() == [record.id]
    assert world.ports.counts == ["stop_found", "paired"] and world.ports.calls == []


async def test_materialise_meeting_a_bound_record_rereads_and_never_acts_on_the_refused_write(
    world: World,
) -> None:
    """The record was bound meanwhile (to another order): `RecordedStopNotBindable`, nothing
    written; the re-read finds no row, so nothing is decided: no row, no lockout."""
    record = await world.record()
    d = decision(record)
    world.rig.store._stops[record.id] = replace(record, exchange_order_id="other")
    with capture_logs() as logs:
        assert await take(world, d) is None
    assert await world.row() is None and world.rig.facade.state(ROW_ID) is None
    [refused] = [e for e in logs if e["event"] == "stream_recorded_stop_not_materialised"]
    assert refused["kind"] == OrderStepRefused.__name__
    assert world.ports.counts == ["stop_undecided"] and world.ports.hooked == []


@dataclass
class Stalled:
    """A materialise whose answer never came: one that wrote nothing never answers, so the bound
    cuts it; one whose row committed answers `TimeoutError` after its write, as the bound cutting
    it after the commit does (so the test never races a real bound against a real write)."""

    world: World
    writes: bool

    async def materialise(
        self, order: NewOrder, *, environment: str, binds: RecordedStopBind | None = None
    ) -> str:
        if self.writes:
            await self.world.rig.facade.materialise(order, environment=environment, binds=binds)
            raise TimeoutError
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.parametrize("writes", [False, True], ids=["nothing_written", "row_written"])
async def test_materialise_timeout_rereads_and_only_a_found_row_takes_the_push(
    world: World, monkeypatch: pytest.MonkeyPatch, writes: bool
) -> None:
    """Q5: a materialise that does not answer within its bound is an unknown outcome: the row is
    read again; a row found takes the push (C-2.6), none decides nothing."""
    if not writes:  # a real bound never races the real write (`Stalled`)
        monkeypatch.setattr(rss, "MATERIALISE_BOUND_S", 0.01)
    await world.record()
    world.machines = Stalled(world, writes)
    await world.run(event("order", orderId=XID, **TRIGGERED))
    row = await world.row()
    if writes:
        assert row is not None and world.ports.counts == ["stop_found", "paired"]
        state = world.rig.facade.state(ROW_ID)
        assert state is not None and state[0] == "triggered" and world.ports.hooked == [KEY]
    else:
        assert row is None and world.ports.counts == ["stop_undecided", "undecided"]
        assert world.ports.calls == [] and world.ports.hooked == []


@dataclass
class MissingByExchangeId:
    """Order reads whose read by the exchange id misses the row a materialise just wrote (a
    replica lag, or a failed read); the read by the row's id finds it."""

    world: World
    fails: bool = False
    by_id: list[UUID] = field(default_factory=list)

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None:
        self.by_id.append(order_id)
        return await self.world.rig.orders.get(account_id, order_id)

    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> OrderRow | None:
        if self.fails:
            raise StorageQueryFailed("08006")
        return None

    async def get_by_link_id(self, account_id: UUID, link_id: str) -> OrderRow | None:
        return await self.world.rig.orders.get_by_link_id(account_id, link_id)


@pytest.mark.parametrize("fails", [False, True], ids=["missed", "failed"])
async def test_materialised_row_missed_by_its_exchange_id_is_read_by_its_id_and_takes_the_push(
    world: World, fails: bool
) -> None:
    """The security lens's F7: after a materialise that answered, a read-back by the exchange id
    that misses falls back to the new row's id, so the push is delivered and the hook runs."""
    record = await world.record()
    world.reads = MissingByExchangeId(world, fails)
    await world.run(event("order", orderId=XID, **TRIGGERED))
    state = world.rig.facade.state(ROW_ID)
    assert state is not None and state[0] == "triggered" and await world.bound() == [record.id]
    assert world.ports.counts == ["stop_materialised", "paired"] and world.ports.hooked == [KEY]


async def test_a_refused_materialise_never_reads_the_row_by_its_id(world: World) -> None:
    """Only a materialise that answered falls back to the new row's id: one that did not decided
    nothing, and the exchange id's read alone decides (no row: undecided)."""
    record = await world.record()
    reads = MissingByExchangeId(world)
    world.reads = reads
    world.rig.store._stops[record.id] = replace(record, exchange_order_id="other")
    assert await take(world, decision(record)) is None
    assert reads.by_id == [] and world.ports.counts == ["stop_undecided"]


def test_materialise_bound_is_the_facades_push_bound_and_the_take_budget_fits_the_seams() -> None:
    assert rss.MATERIALISE_BOUND_S == stream_push.PUSH_TIMEOUT_S == 30.0
    assert rss.TAKE_BUDGET_S == stream_push.STOP_TAKE_BOUND_S


async def test_require_exchange_order_id_value_error_decides_nothing_and_is_never_no_intent(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-S2B-3: a read the store refuses (`ValueError`) is a failed read, never no intent."""
    record = await world.record()

    async def refused(account_id: UUID, key: Any) -> OrderRow | None:
        raise ValueError("an exchange order id of 1 to 64 characters")

    for read in ("get_by_exchange_order_id", "get"):  # both read-backs (F7's fallback too)
        monkeypatch.setattr(world.rig.orders, read, refused)
    assert await take(world, decision(record)) is None
    assert world.ports.counts == ["stop_undecided"] and world.ports.calls == []


@pytest.mark.parametrize(
    "stray",
    [{"exchange_account_id": ACCOUNT_B}, {"exchange_order_id": "other"}],
    ids=["another-account", "another-order"],
)
async def test_read_back_answering_a_row_that_is_not_the_orders_is_none(
    world: World, monkeypatch: pytest.MonkeyPatch, stray: dict[str, Any]
) -> None:
    """A store defect's answer is never the order's row (C-12.4): nothing takes the push."""
    record = await world.record()
    for read in ("get_by_exchange_order_id", "get"):  # both read-backs (F7's fallback too)
        real = getattr(world.rig.orders, read)

        async def leaking(account_id: UUID, key: Any, real: Any = real) -> OrderRow | None:
            found = await real(account_id, key)
            return None if found is None else replace(found, **stray)

        monkeypatch.setattr(world.rig.orders, read, leaking)
    with capture_logs() as logs:
        assert await take(world, decision(record)) is None
    assert world.ports.counts == ["stop_undecided"]
    assert any(e["event"] == "stream_recorded_stop_foreign_row" for e in logs)


@pytest.mark.parametrize(
    "failure",
    [StorageQueryFailed("23505"), StorageQueryFailed("08006"), RuntimeError("x")],
    ids=["unique", "outage", "failed"],
)
async def test_storage_query_failed_on_materialise_decides_nothing(
    world: World, failure: Exception
) -> None:
    record = await world.record()

    @dataclass
    class Failing:
        async def materialise(self, order: NewOrder, **kw: Any) -> str:
            raise failure

    world.machines = Failing()
    assert await take(world, decision(record)) is None
    assert await world.row() is None and await world.bound() == []
    assert world.ports.counts == ["stop_undecided"]


@pytest.mark.parametrize("port", ["account", "link"])
async def test_a_failed_account_or_link_read_materialises_nothing_and_decides_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch, port: str
) -> None:
    record = await world.record()
    push: dict[str, Any] = {}
    if port == "account":
        world.ports.account_error = RuntimeError("x")
    else:
        push = {"orderLinkId": link()}

        async def failed(account_id: UUID, link_id: str) -> OrderRow | None:
            raise RuntimeError("x")

        monkeypatch.setattr(world.rig.orders, "get_by_link_id", failed)
    assert await take(world, decision(record, **push)) is None
    assert await world.row() is None and await world.bound() == []


async def test_recorded_stop_stream_raises_nothing_but_cancelled_error(world: World) -> None:
    record = await world.record()
    world.machines = Stalled(world, writes=False)
    task = asyncio.create_task(take(world, decision(record)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await world.row() is None and world.ports.counts == []


async def test_logs_carry_ids_only(world: World) -> None:
    await world.record()
    with capture_logs() as logs:
        await world.run(event("order", orderId=XID, **(STOP | {"orderLinkId": link()})))
    text = str([e for e in logs if e["event"].startswith("stream_recorded_stop")])
    assert XID in text and str(ACCOUNT_A) in text
    assert link() not in text and "94000" not in text and "0.5" not in text


# The F1 carry (S6a's security lens): the record must be on the position the order closes.
@pytest.mark.parametrize(
    ("record_over", "push_over"),
    [
        ({"position_side": "Sell"}, {}),
        ({}, {"side": "Buy"}),
        ({"kind": "take_profit"}, {}),
        ({"symbol": "ETHUSDT"}, {}),
        ({"position_idx": 1}, {}),
        ({"exchange_account_id": ACCOUNT_B}, {}),
    ],
    ids=["record_side", "order_side", "kind", "symbol", "position_idx", "account"],
)
async def test_take_refuses_a_record_not_on_the_position_the_order_closes_before_any_write(
    world: World, record_over: dict[str, Any], push_over: dict[str, Any]
) -> None:
    record = replace(await world.record(), **record_over)
    with capture_logs() as logs:
        assert await take(world, decision(record, **push_over)) is None
    assert await world.row() is None and await world.bound() == []
    assert world.ports.counts == ["pairing_refused"]
    assert any(e["event"] == "stream_recorded_stop_mismatch" for e in logs)
    assert world.ports.summaries == [("oms.recorded_stop_stream", rss._PAGES["mismatch"])]


async def test_take_pages_a_mismatch_once_per_account_and_exchange_order_id(world: World) -> None:
    """The review's F2: a refused pairing pages, once per (account, exchange order id)."""
    record = replace(await world.record(), position_side="Sell")
    stream = world.stream()
    xid = "0bd1c5ee-1a7e-4f63-9d37-5b8cb1ab6f10"
    other = ToRecordedStop(record, stop_order().model_copy(update={"exchange_order_id": xid}))
    for d in (decision(record), decision(record), other):
        assert await stream.take(ACCOUNT_A, d, d.order, None, 0) is None
    assert world.ports.calls == ["page", "page"]
    assert world.ports.counts == ["pairing_refused"] * 3


async def test_mismatch_pages_forget_the_oldest_order_past_their_bound(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rss, "PAGED_ORDERS", 1)
    record = replace(await world.record(), position_side="Sell")
    stream = world.stream()
    xid = "0bd1c5ee-1a7e-4f63-9d37-5b8cb1ab6f10"
    other = ToRecordedStop(record, stop_order().model_copy(update={"exchange_order_id": xid}))
    for d in (decision(record), other, decision(record)):
        assert await stream.take(ACCOUNT_A, d, d.order, None, 0) is None
    assert world.ports.calls == ["page"] * 3


# A quantity of 0 (the code lens's F1; the coordinator's rule, pending the orchestrator's ruling).
ZERO = FULL | {"qty": "0", "orderStatus": "Triggered"}


def long(qty: str, side: Any = "buy") -> Position:
    return position_rig.position(account_id=ACCOUNT_A, qty=Decimal(qty), side=side)


async def test_full_mode_order_showing_zero_takes_the_positions_size_and_its_fill_fits(
    world: World,
) -> None:
    record = await world.record(tpsl_mode="Full", size=None)
    world.ports.position = long("0.4")
    await world.run(event("order", orderId=XID, **ZERO))
    row = await world.row()
    assert row is not None and (row.qty, row.tpsl_mode) == (Decimal("0.4"), "Full")
    assert await world.bound() == [record.id]
    await world.run(event("execution", orderId=XID, execQty="0.4"))
    row = await world.row()
    assert row is not None and (row.cum_exec_qty, row.lifecycle_state) == (
        Decimal("0.4"), "filled",
    )  # fmt: skip
    assert world.ports.counts == ["stop_materialised", "paired", "paired"]  # the push, the fill
    assert world.ports.calls == []


async def test_full_mode_order_showing_zero_is_sized_from_the_projections_last_applied_row(
    world: World,
) -> None:
    """The real projection: the row's quantity is the position it last applied for the key."""
    await world.record(tpsl_mode="Full", size=None)
    stops = RecordedStopRepository(InMemoryRecordedStopStore(world.rig.store))
    made = position_rig.Rig().projection(stops=stops, order_rows=world.rig.orders, now=lambda: T0)
    held = long("0.3")
    await made.take(ACCOUNT_A, held, position_rig.routed(held))
    assert made.last_applied(KEY) == held
    world.positions = made
    await world.run(event("order", orderId=XID, **ZERO))
    row = await world.row()
    assert row is not None and row.qty == Decimal("0.3")


@pytest.mark.parametrize(
    "held",
    [None, long("0", side=None), long("0"), long("0.4", side="sell")],
    ids=["unknown", "flat", "flat_hedge_leg", "other_side"],
)
async def test_full_mode_order_showing_zero_with_no_open_position_decides_nothing(
    world: World, held: Position | None
) -> None:
    record = await world.record(tpsl_mode="Full", size=None)
    world.ports.position = held
    with capture_logs() as logs:
        assert await take(world, decision(record, **ZERO)) is None
    assert await world.row() is None and await world.bound() == []
    assert world.ports.counts == ["stop_no_position"] and world.ports.calls == []
    assert any(e["event"] == "stream_recorded_stop_no_position" for e in logs)


async def test_partial_mode_order_showing_zero_is_refused_counted_and_paged_once(
    world: World,
) -> None:
    record = await world.record()
    world.ports.position = long("0.4")
    stream = world.stream()
    d = decision(record, qty="0")
    for _ in range(2):
        assert await stream.take(ACCOUNT_A, d, d.order, None, 0) is None
    assert await world.row() is None and await world.bound() == []
    assert world.ports.counts == ["stop_qty_refused"] * 2
    assert world.ports.summaries == [("oms.recorded_stop_stream", rss._PAGES["qty_zero"])]


# C-2.6.
async def test_materialised_row_starts_no_protection_region_and_protecting_never_lists_it(
    world: World,
) -> None:
    """INV-B1-o: a TP/SL only closes its position, so its fill starts no `protection` region."""
    await world.record()
    world.ports.order = stop_order(**TRIGGERED)
    await world.run(event("execution", orderId=XID))
    assert ROW_ID not in world.rig.facade.protecting(KEY)
    row = await world.row()
    assert row is not None and row.cum_exec_qty > 0


async def test_kill_on_a_materialised_row_sends_no_cancel(world: World) -> None:
    """INV-B1-p: a KILL never cancels the stop that protects the position; it keeps its record."""
    record = await world.record()
    await world.run(event("order", orderId=XID, **STOP))
    assert await world.rig.facade.kill("kill switch engaged") == ()
    assert world.rig.commands.sent == [] and await world.bound() == [record.id]
    state = world.rig.facade.state(ROW_ID)
    assert state is not None and state[0] == "submitted"


async def test_a_matched_recorded_stops_fill_never_opens_the_lockout(world: World) -> None:
    await world.record()
    world.ports.order = stop_order(**TRIGGERED)
    await world.run(event("execution", orderId=XID))
    await world.run(event("execution", orderId=XID, execId="another-exec"))
    assert not any(c.startswith(("lockout", "handover", "page")) for c in world.ports.calls)
    assert "exchange_placed" not in world.ports.calls


@pytest.mark.parametrize(
    "machines",
    [lambda w: Racing(w), lambda w: Stalled(w, writes=True)],
    ids=["lost_race", "timeout"],
)
async def test_a_protecting_stops_order_push_always_reaches_its_bound_row(
    world: World, machines: Callable[[World], Any]
) -> None:
    """C-2.6: whatever the materialise answered, the push reaches the row bound to its order,
    which its record binds; it is never dropped."""
    record = await world.record()
    world.machines = machines(world)
    await world.run(event("order", orderId=XID, **TRIGGERED))
    row = await world.row()
    assert row is not None and await world.bound() == [record.id]
    state = world.rig.facade.state(row.id)
    assert state is not None and state[0] == "triggered"


def _us(at: Any) -> int:
    return int(at.timestamp() * 1_000_000)

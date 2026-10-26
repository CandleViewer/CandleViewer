"""A recorded stop's successor bind on the private stream (E29-T05 #848, S7b; 24-internal-schemas.md
Sec.8.12 "The successor's bind", Sec.8.3 rule 7, Sec.15.5 `successor_bind`; the orchestrator's
2026-10-25 rulings Q4, Q11 and Q17). `StreamPushes` over the real `Successor`, the real facade (B1)
and the in-memory stores, with `RecordedStopRepository.release_and_bind` (S2c2's) unchanged. The
pushes come from #4135's transcribed frame shapes through the adapter's own parser (C-13.5). No
network, no sleeps."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.exchange.base.models import Order
from candleviewer.oms import recorded_stop_stream as rss
from candleviewer.oms import stream_push
from candleviewer.oms.errors import AuditNotDurable
from candleviewer.oms.ports import KeyedRecord, PositionKey
from candleviewer.oms.repository import RecordedStopRepository
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.recorded_stops import (
    RecordedStopRow,
    ReleaseWriteAhead,
    StopStatus,
)
from tests.unit.exchange.bybit._trading import ACCOUNT_A, ACCOUNT_B
from tests.unit.oms.order_rig import T0, build_rig
from tests.unit.oms.stream_rig import Rig
from tests.unit.oms.test_recorded_stop_stream import FULL, KEY, ROW_ID, Ports, World
from tests.unit.oms.test_stream_push import STOP, event, order_row

XID = "9aac161b-8ed6-450d-9cab-c5cc67c21784"  # the transcribed frames' order id
AT = datetime(2031, 3, 4, 5, 6, 7, tzinfo=UTC)  # the OMS's clock, nowhere near the wall clock
STOP_TIME = "1672364262457"  # the transcribed order row's `updatedTime`
ENDED_OTHERWISE = ["cancelled", "rejected", "expired", "deactivated", "partially_filled_canceled"]


@dataclass
class Spy:
    """The successor's record store: the repository over the rig's records, its calls noted; a
    release can meet a race first (`before`), fail (`fail`) or never answer (`hang`)."""

    inner: RecordedStopRepository
    calls: list[str] = field(default_factory=list)
    at: list[datetime] = field(default_factory=list)
    before: Callable[[], None] | None = None
    fail: Exception | None = None
    hang: bool = False
    reread_fails: bool = False

    async def for_exchange_order(self, account_id: UUID, xid: str) -> tuple[RecordedStopRow, ...]:
        self.calls.append("for_exchange_order")
        if self.reread_fails and "release_and_bind" in self.calls:
            raise StorageQueryFailed("08006")
        return await self.inner.for_exchange_order(account_id, xid)

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        self.calls.append("live_for_key")
        return await self.inner.live_for_key(account_id, symbol, position_idx)

    async def release_and_bind(
        self, account_id: UUID, predecessor_id: UUID, successor_id: UUID, xid: str, *,
        at: datetime, write_ahead: ReleaseWriteAhead,
    ) -> tuple[RecordedStopRow, RecordedStopRow]:  # fmt: skip
        self.calls.append("release_and_bind")
        self.at.append(at)
        if self.before is not None:
            self.before()
        if self.fail is not None:
            raise self.fail
        if self.hang:
            await asyncio.Event().wait()
        return await self.inner.release_and_bind(
            account_id, predecessor_id, successor_id, xid, at=at, write_ahead=write_ahead
        )


@pytest.fixture
async def world(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    out = World(build_rig(), Ports())
    yield out
    await out.rig.facade.stop()


def spy(world: World) -> Spy:
    out = Spy(RecordedStopRepository(world.rig.store.stops))
    world.stops = out
    return out


def stops(world: World) -> dict[UUID, RecordedStopRow]:
    return world.rig.store._stops  # the fake's own table


async def predecessor(world: World, push: dict[str, Any] = STOP, **values: Any) -> RecordedStopRow:
    """A record of the side, answered and in force, bound to the order by its order's push (the
    row materialised); the ports' notes then cleared."""
    record = await world.record(**values)
    for r in list(stops(world).values()):  # the request answered: no stop-loss left in flight
        stops(world)[r.id] = replace(r, status="in_force", in_force_at=T0)
    await world.run(event("order", orderId=XID, **push))
    assert await world.bound() == [record.id]
    world.ports.counts.clear()
    world.ports.hooked.clear()
    return stops(world)[record.id]


async def later(world: World, old: RecordedStopRow, seconds: int = 1, **values: Any) -> UUID:
    """A pending record of the side, `seconds` later than `old` (by `created_at`)."""
    new = await world.record(**values)
    stops(world)[new.id] = replace(new, created_at=old.created_at + timedelta(seconds=seconds))
    return new.id


def stop_order(state: str | None = None) -> Order:
    """The recorded stop's order as the transcribed push shows it, in the adapter's status
    `state` when given (the normalised status the parser yields)."""
    out = event("order", orderId=XID, **STOP).payload
    assert isinstance(out, Order)
    return out if state is None else out.model_copy(update={"state": state})


async def bound_row(world: World) -> OrderRow:
    row = await world.row()
    assert row is not None and row.id == ROW_ID
    return row


# --- The release and the bind (24 Sec.8.3 rule 7, Sec.8.12) ---------------------------------------


async def test_successor_record_matching_the_push_releases_the_predecessor_and_binds_in_one_transaction(  # noqa: E501 -- the plan's test name, verbatim
    world: World,
) -> None:
    """One `release_and_bind`: the hook is handed the predecessor released and the successor bound
    (its record names both and the order) while neither is committed, and both land together; the
    record hook then runs for the key."""
    old = await predecessor(world)
    new = await later(world, old)
    seen: list[tuple[str | None, str | None]] = []
    details: list[Any] = []

    class Ahead:
        async def write(self, record: KeyedRecord) -> None:
            table = stops(world)
            seen.append((table[old.id].exchange_order_id, table[new].exchange_order_id))
            details.append(record.detail)

    world.audit = Ahead()
    calls = spy(world).calls
    await world.run(event("order", orderId=XID, **STOP))
    assert calls == ["for_exchange_order", "live_for_key", "release_and_bind"]
    assert seen == [(XID, None)]  # written ahead: nothing committed yet
    assert details == [
        {"kind": "stop_loss", "predecessor_id": str(old.id), "successor_id": str(new),
         "exchange_order_id": XID},
    ]  # fmt: skip
    released, bound = stops(world)[old.id], stops(world)[new]
    assert (released.exchange_order_id, released.released_at) == (None, T0)
    assert (bound.exchange_order_id, bound.released_at) == (XID, None)
    assert await world.bound() == [new]
    assert world.ports.counts == ["successor_bound"] and world.ports.hooked == [KEY]


@pytest.mark.parametrize(
    ("values", "push"),
    [
        ({"trigger_price": Decimal(93500)}, {"triggerPrice": "93500"}),
        ({"trigger_price": Decimal(93500), "size": Decimal("0.4")},
         {"triggerPrice": "93500", "qty": "0.4"}),
    ],
    ids=["trigger", "trigger_and_size"],
)  # fmt: skip
async def test_a_stop_moved_in_place_sends_its_terms_then_binds_the_later_record(
    world: World, values: dict[str, Any], push: dict[str, str]
) -> None:
    """The main case: the OMS moves its Partial stop in place, so the push carries the later
    record's terms. `TERMS_CHANGED` is sent first, the row follows the push, and then the binding
    moves to the later record, with one record written ahead."""
    old = await predecessor(world)
    new = await later(world, old, **values)
    calls = spy(world).calls
    await world.run(event("order", orderId=XID, **(STOP | push)))
    assert world.ports.counts == ["terms", "successor_bound"]
    row = await bound_row(world)
    assert (row.trigger_price, row.qty) == (Decimal(93500), values.get("size", Decimal("0.5")))
    assert calls == ["for_exchange_order", "live_for_key", "release_and_bind"]
    assert await world.bound() == [new] and stops(world)[old.id].released_at == T0
    assert [r.name for r in world.ports.audited] == [f"successor_bind:{new}"]


async def test_a_stale_push_never_moves_the_binding_back(world: World) -> None:
    """The security lens: once a newer push bound the later record, a late or redelivered push of
    the order still showing the old terms, older by the venue's time, matches a record written
    since at those terms, and decides nothing: the binding stays, nothing is released."""
    old = await predecessor(world)
    moved = await later(world, old, trigger_price=Decimal(93500))
    calls = spy(world).calls
    world.kept = world.successor()
    newer = str(int(STOP_TIME) + 1_000)
    await world.run(
        event("order", orderId=XID, **(STOP | {"triggerPrice": "93500", "updatedTime": newer}))
    )
    assert await world.bound() == [moved]
    stops(world)[moved] = replace(stops(world)[moved], status="in_force", in_force_at=T0)
    back = await later(world, stops(world)[moved])  # the OMS records the old terms again
    calls.clear()
    await world.run(event("order", orderId=XID, **(STOP | {"updatedTime": STOP_TIME})))
    assert "release_and_bind" not in calls and await world.bound() == [moved]
    assert stops(world)[moved].released_at is None and stops(world)[back].exchange_order_id is None


async def test_an_entrys_attach_is_never_a_successor(world: World) -> None:
    """The security lens: a pending attach of an entry not yet filled, at the push's terms, is
    never handed a bound order's binding; its stop arrives as an order of its own at the fill."""
    old = await predecessor(world)
    new = await later(world, old)
    stops(world)[new] = replace(stops(world)[new], source="entry_attach", order_id=uuid4())
    calls = spy(world).calls
    await world.run(event("order", orderId=XID, **STOP))
    assert calls == ["for_exchange_order", "live_for_key"]
    assert await world.bound() == [old.id] and stops(world)[new].exchange_order_id is None
    assert world.ports.audited == []


@pytest.mark.parametrize(
    ("values", "seconds"),
    [(None, 1), ({"trigger_price": Decimal(93000)}, 1), ({}, -1), ({"size": Decimal("0.4")}, 1)],
    ids=["no_other_record", "other_trigger", "earlier_record", "other_size"],
)
async def test_no_later_match_keeps_the_binding(
    world: World, values: dict[str, Any] | None, seconds: int
) -> None:
    old = await predecessor(world)
    other = None if values is None else await later(world, old, seconds, **values)
    calls = spy(world).calls
    await world.run(event("order", orderId=XID, **STOP))
    assert calls == ["for_exchange_order", "live_for_key"]
    assert await world.bound() == [old.id] and stops(world)[old.id].released_at is None
    assert other is None or stops(world)[other].exchange_order_id is None
    assert world.ports.counts == [] and world.ports.audited == []


@pytest.mark.parametrize("state", ENDED_OTHERWISE)
async def test_successor_never_binds_an_order_ended_cancelled_rejected_expired_or_deactivated(
    world: World, state: str
) -> None:
    """Rule 7: a successor binds an order that has ended only when it ended `filled`."""
    old = await predecessor(world)
    new = await later(world, old)
    calls = spy(world).calls
    await world.successor().check(ACCOUNT_A, await bound_row(world), stop_order(state=state))
    assert calls == [] and await world.bound() == [old.id]
    assert stops(world)[new].exchange_order_id is None and world.ports.counts == []


async def test_successor_never_binds_on_a_pushed_end_through_the_stream(world: World) -> None:
    """The pushed end is delivered (`REMOTE_CANCELLED`), and the record keeps its order."""
    old = await predecessor(world)
    await later(world, old)
    calls = spy(world).calls
    await world.run(event("order", orderId=XID, **(STOP | {"orderStatus": "Cancelled"})))
    assert calls == [] and await world.bound() == [old.id]
    assert world.ports.counts == ["paired"]


@pytest.mark.parametrize("state", ["filled", "triggered", "partially_filled", "new"])
async def test_successor_binds_an_order_ended_filled(world: World, state: str) -> None:
    """`filled`, and every live status, binds the later match."""
    old = await predecessor(world)
    new = await later(world, old)
    await world.successor().check(ACCOUNT_A, await bound_row(world), stop_order(state=state))
    assert await world.bound() == [new] and stops(world)[old.id].released_at == T0
    assert world.ports.counts == ["successor_bound"]


async def test_successor_check_is_for_the_rows_own_order_only(world: World) -> None:
    """A row bound to another order is not this push's: nothing is read."""
    old = await predecessor(world)
    await later(world, old)
    calls = spy(world).calls
    row = replace(await bound_row(world), exchange_order_id="another")
    await world.successor().check(ACCOUNT_A, row, stop_order())
    assert calls == [] and await world.bound() == [old.id]


# --- Nothing acts on a refused or unknown write (24 Sec.8.12) ------------------------------------


@pytest.mark.parametrize(
    "failure", ["not_bindable", "storage", "timeout", "audit_late"], ids=lambda f: str(f)
)
async def test_successor_refused_rereads_for_exchange_order_and_writes_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """`RecordedStopNotBindable` (the successor bound meanwhile, to another order), a failed
    write, the bound, or a late audit: the record bound to the order is read again and logged by
    id; nothing is counted bound, no hook runs, and nothing the write may have done is acted on."""
    old = await predecessor(world)
    new = await later(world, old)
    s = spy(world)
    if failure == "not_bindable":  # the successor's binding taken first, by another order
        s.before = lambda: stops(world).__setitem__(
            new, replace(stops(world)[new], exchange_order_id="another")
        )
    elif failure == "storage":
        s.fail = StorageQueryFailed("08006")
    elif failure == "timeout":
        monkeypatch.setattr(rss, "RELEASE_BOUND_S", 0.01)
        s.hang = True
    else:
        s.fail = AuditNotDurable("the release's write-ahead audit did not land in time")
    with capture_logs() as logs:
        await world.run(event("order", orderId=XID, **STOP))
    assert s.calls == [
        "for_exchange_order",
        "live_for_key",
        "release_and_bind",
        "for_exchange_order",
    ]
    assert await world.bound() == [old.id] and stops(world)[old.id].released_at is None
    assert world.ports.counts == ["successor_undecided"] and world.ports.hooked == []
    assert world.ports.audited == []
    [line] = [e for e in logs if e["event"] == "stream_successor_undecided"]
    assert line["holders"] == [str(old.id)]
    assert (line["predecessor_id"], line["successor_id"]) == (str(old.id), str(new))


async def test_a_failed_reread_after_a_refused_write_is_counted_once_and_decides_nothing(
    world: World,
) -> None:
    old = await predecessor(world)
    await later(world, old)
    s = spy(world)
    s.fail, s.reread_fails = StorageQueryFailed("08006"), True
    await world.run(event("order", orderId=XID, **STOP))
    assert world.ports.counts == ["successor_undecided"] and world.ports.hooked == []
    assert await world.bound() == [old.id]


async def test_a_refused_release_audit_leaves_both_records_as_they_were(world: World) -> None:
    """The write-ahead hook raising: the store commits neither the release nor the bind."""
    old = await predecessor(world)
    new = await later(world, old)

    class Refusing:
        async def write(self, record: KeyedRecord) -> None:
            raise RuntimeError("the audit WAL refused the record")

    world.audit = Refusing()
    await world.run(event("order", orderId=XID, **STOP))
    assert await world.bound() == [old.id] and stops(world)[new].exchange_order_id is None
    assert stops(world)[old.id].released_at is None
    assert world.ports.counts == ["successor_undecided"]


@pytest.mark.parametrize(
    ("kind", "action", "push"),
    [
        ("stop_loss", "sl.modified", STOP),
        ("take_profit", "tp.modified", STOP | {"stopOrderType": "PartialTakeProfit"}),
    ],
    ids=["stop_loss", "take_profit"],
)
async def test_release_audit_is_written_ahead_with_ids_only(
    world: World, kind: str, action: str, push: dict[str, Any]
) -> None:
    """24 Sec.15.5: the side's action, keyed `successor_bind:<successor id>`, as `system:oms`,
    the successor its object; its detail names the two records and the order, never a price."""
    old = await predecessor(world, push, kind=kind)
    new = await later(world, old, kind=kind)
    await world.run(event("order", orderId=XID, **push))
    [record] = world.ports.audited
    assert (record.action, record.name, record.reason) == (
        action, f"successor_bind:{new}", "successor_bind",
    )  # fmt: skip
    assert (record.object_kind, record.object_id, record.account_id) == (
        "recorded_stop", new, ACCOUNT_A,
    )  # fmt: skip
    assert (record.actor_user_id, record.actor, record.outcome) == (None, None, "success")
    assert dict(record.detail) == {
        "kind": kind, "predecessor_id": str(old.id), "successor_id": str(new),
        "exchange_order_id": XID,
    }  # fmt: skip
    assert await world.bound() == [new]


async def test_successor_uses_the_oms_clock_never_datetime_now(world: World) -> None:
    """SEC-S2C-4: the release is stamped on the injected OMS clock."""
    old = await predecessor(world)
    await later(world, old)
    world.clock = lambda: AT
    s = spy(world)
    await world.run(event("order", orderId=XID, **STOP))
    assert s.at == [AT] and stops(world)[old.id].released_at == AT


@pytest.mark.parametrize("status", ["ended", "void"])
async def test_an_ended_predecessor_is_never_released(world: World, status: StopStatus) -> None:
    """Rule 7: a record that has ended keeps its order whatever a later push shows."""
    old = await predecessor(world)
    stops(world)[old.id] = replace(old, status=status, closed_at=T0)
    new = await later(world, old)
    calls = spy(world).calls
    await world.run(event("order", orderId=XID, **STOP))
    assert calls == ["for_exchange_order"]
    assert await world.bound() == [old.id] and stops(world)[new].exchange_order_id is None
    assert world.ports.counts == []


# --- Store defects are refused, never acted on (C-12.4) ------------------------------------------


@dataclass
class Scripted:
    """A record store answering `holders` and `live`, or failing a read."""

    holders: tuple[RecordedStopRow, ...] = ()
    live: tuple[RecordedStopRow, ...] = ()
    fails: str = ""
    released: list[UUID] = field(default_factory=list)

    async def for_exchange_order(self, account_id: UUID, xid: str) -> tuple[RecordedStopRow, ...]:
        if self.fails == "holders":
            raise StorageQueryFailed("08006")
        return self.holders

    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        if self.fails == "live":
            raise TimeoutError
        return self.live

    async def release_and_bind(
        self, account_id: UUID, predecessor_id: UUID, successor_id: UUID, xid: str, *,
        at: datetime, write_ahead: ReleaseWriteAhead,
    ) -> tuple[RecordedStopRow, RecordedStopRow]:  # fmt: skip
        self.released.append(predecessor_id)
        raise AssertionError("never reached")


def _rec(n: int, **over: Any) -> RecordedStopRow:
    values: dict[str, Any] = {
        "id": UUID(int=n), "exchange_account_id": ACCOUNT_A, "symbol": "BTCUSDT",
        "position_idx": 0, "position_side": "Buy", "kind": "stop_loss", "source": "trading_stop",
        "order_id": None, "tpsl_mode": "Partial", "trigger_price": Decimal(94000),
        "size": Decimal("0.5"), "trailing_distance": None, "trailing_active_price": None,
        "exchange_order_id": None, "status": "in_force", "audit_record_id": UUID(int=99),
        "actor_user_id": None, "created_at": T0 + timedelta(seconds=n), "answered_at": None,
        "in_force_at": None, "closed_at": None, "released_at": None, "position_marker": None,
    }  # fmt: skip
    return RecordedStopRow(**(values | over))


def _successor(store: Scripted, ports: Ports) -> rss.Successor:
    return rss.Successor(stops=store, audit=ports, positions=ports, counts=ports, clock=lambda: AT)


@pytest.mark.parametrize(
    ("store", "count", "line"),
    [
        (
            Scripted(holders=(_rec(1, exchange_order_id=XID), _rec(2, exchange_order_id=XID))),
            ["pairing_refused"], "stream_successor_two_holders",
        ),
        (
            Scripted(holders=(_rec(1, exchange_order_id=XID),), live=(_rec(3, symbol="ETHUSDT"),)),
            ["pairing_refused"], "stream_successor_foreign_record",
        ),
        (
            Scripted(holders=(_rec(1, exchange_order_id=XID, exchange_account_id=ACCOUNT_B),)),
            ["pairing_refused"], "stream_successor_foreign_record",
        ),
        (Scripted(fails="holders"), ["successor_undecided"], "stream_successor_read_failed"),
        (
            Scripted(holders=(_rec(1, exchange_order_id=XID),), fails="live"),
            ["successor_undecided"], "stream_successor_read_failed",
        ),
    ],
    ids=["two_holders", "foreign_live_record", "foreign_holder", "holders_failed", "live_failed"],
)  # fmt: skip
async def test_store_defect_or_failed_read_decides_nothing(
    store: Scripted, count: list[str], line: str
) -> None:
    ports = Ports()
    with capture_logs() as logs:
        await _successor(store, ports).check(ACCOUNT_A, order_row(), stop_order())
    assert store.released == [] and ports.counts == count and ports.hooked == []
    assert any(e["event"] == line for e in logs)


async def test_after_bind_failing_is_logged_and_counted_and_the_bind_stands(world: World) -> None:
    old = await predecessor(world)
    new = await later(world, old)

    class Failing(Ports):
        async def after_bind(self, key: PositionKey) -> None:
            raise RuntimeError("x")

    world.positions = Failing()
    await world.run(event("order", orderId=XID, **STOP))
    assert await world.bound() == [new]
    assert world.ports.counts == ["successor_bound", "after_bind_failed"]


# --- C-2.6 -------------------------------------------------------------------------------------


async def test_a_released_predecessors_fills_still_never_open_the_lockout(world: World) -> None:
    """The order's fills pair through its row's bound id, which no release touches: the fill is
    applied, with no lockout and no hand-over, after the record's binding moved on."""
    old = await predecessor(world)
    new = await later(world, old)
    await world.run(event("order", orderId=XID, **STOP))
    assert await world.bound() == [new]
    world.ports.counts.clear()
    await world.run(event("execution", orderId=XID, execQty="0.2"))
    row = await bound_row(world)
    assert row.cum_exec_qty == Decimal("0.2") and world.ports.calls == []
    assert world.ports.counts == ["paired"] and stops(world)[old.id].released_at == T0


_LOOSER = st.integers(80_000, 93_999)  # a long's stop-loss further from the market: looser
_SIZE = st.sampled_from(["0.1", "0.2", "0.3", "0.4", "0.6", "0.7", "0.9"])


@settings(max_examples=40, deadline=None)
@given(trigger=_LOOSER, size=_SIZE, mode=st.sampled_from(["Partial", "Full"]), other=st.booleans())
async def test_property_looser_foreign_in_place_change_on_a_bound_partial_stop_keeps_the_binding_and_follows_terms(  # noqa: E501 -- the plan's test name, verbatim
    trigger: int, size: str, mode: str, other: bool
) -> None:
    """The LANE-43 rider, E29-T05's half (Q11): a foreign or venue in-place change that loosens a
    bound stop (its trigger, its size, in Partial or Full mode) is exchange truth the row follows;
    the record keeps its binding and its own terms, nothing is released, even with a later record
    of the side holding the old terms, and no lockout opens. The restore, or the
    `sl_restore_refused` page, is E29-T06's (Sec.8.5 step 5)."""
    saved = b01._ATTEMPTS
    b01._ATTEMPTS = OrderedDict()
    world = World(build_rig(), Ports())
    try:
        push = STOP if mode == "Partial" else FULL
        values: dict[str, Any] = {"tpsl_mode": "Full", "size": None} if mode == "Full" else {}
        old = await predecessor(world, push, **values)
        new = await later(world, old, **values) if other else None
        calls = spy(world).calls
        await world.run(
            event("order", orderId=XID, **(push | {"triggerPrice": str(trigger), "qty": size}))
        )
        row = await bound_row(world)
        assert (row.trigger_price, row.qty) == (Decimal(trigger), Decimal(size))
        assert await world.bound() == [old.id]
        kept = stops(world)[old.id]
        assert (kept.trigger_price, kept.released_at) == (Decimal(94000), None)
        assert "release_and_bind" not in calls
        assert new is None or stops(world)[new].exchange_order_id is None
        assert world.ports.calls == [] and world.ports.audited == []
        assert world.ports.counts == ["terms"]
    finally:
        await world.rig.facade.stop()
        b01._ATTEMPTS = saved


# --- The push's seam (`StreamPushes`) ----------------------------------------------------------


def test_successor_budget_fits_the_seams_bounds() -> None:
    """The seam's bound is the check's inner bounds plus a margin, so they always end it first."""
    assert rss.RELEASE_BOUND_S == stream_push.PUSH_TIMEOUT_S
    assert rss.SUCCESSOR_BUDGET_S == 3 * stream_push.PORT_TIMEOUT_S + rss.RELEASE_BOUND_S
    assert stream_push.SUCCESSOR_BOUND_S > rss.SUCCESSOR_BUDGET_S


_ROW = order_row(
    state="submitted", provenance="recorded_stop", qty=Decimal("0.5"),
    trigger_price=Decimal(94000), cum_exec_qty=Decimal(0),
)  # fmt: skip


async def test_successor_check_runs_after_the_terms_step_and_the_pushs_event() -> None:
    rig = Rig(answers={"bound": _ROW})
    moved = STOP | {"orderStatus": "Triggered", "triggerPrice": "93500"}
    await rig.run(event("order", orderId=XID, **moved))
    assert rig.trace == ["TERMS_CHANGED", "TRIGGERED", "successor"]
    assert rig.successors == [(_ROW.id, "triggered")]


@pytest.mark.parametrize("push", ["fill", "placed_row"])
async def test_successor_check_is_never_run_for_a_fill_or_a_placed_rows_push(push: str) -> None:
    row = _ROW if push == "fill" else replace(_ROW, provenance="placed")
    rig = Rig(answers={"bound": row})
    await rig.run(
        event("execution", orderId=XID, execQty="0.1")
        if push == "fill"
        else event("order", orderId=XID, **STOP)
    )
    assert rig.successors == []


@pytest.mark.parametrize("how", ["raises", "overruns"])
async def test_a_failing_successor_seam_is_logged_and_counted_and_decides_nothing(
    monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    rig = Rig(answers={"bound": _ROW})
    if how == "raises":
        rig.raises["successor"] = RuntimeError("x")
    else:
        monkeypatch.setattr(stream_push, "SUCCESSOR_BOUND_S", 0.01)
        rig.hang.add("successor")
    with capture_logs() as logs:
        await rig.run(event("order", orderId=XID, **STOP))
    assert rig.counts == ["successor_undecided"]
    [line] = [e for e in logs if e["event"] == "stream_successor_failed"]
    assert line["kind"] in {"RuntimeError", "TimeoutError"}


def test_the_stale_check_keeps_no_unstamped_push_and_forgets_the_oldest_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A push with no venue time is never stale and moves nothing; past `STAMPED_ORDERS` the
    oldest order's time is forgotten (C-2.18), so its next push is judged afresh."""
    monkeypatch.setattr(rss, "STAMPED_ORDERS", 1)
    check, ids = _successor(Scripted(), Ports()), {"exchange_order_id": XID}
    stamped = stop_order()
    assert stamped.updated_at is not None
    assert not check._stale(ACCOUNT_A, stamped.model_copy(update={"updated_at": None}), ids)
    assert not check._stamps
    assert not check._stale(ACCOUNT_A, stamped, ids)
    other = stamped.model_copy(update={"exchange_order_id": "x-other"})
    assert not check._stale(ACCOUNT_A, other, ids)
    assert list(check._stamps) == [(ACCOUNT_A, "x-other")]
    older = stamped.model_copy(update={"updated_at": stamped.updated_at - 1})
    assert not check._stale(ACCOUNT_A, older, ids)  # forgotten: judged afresh

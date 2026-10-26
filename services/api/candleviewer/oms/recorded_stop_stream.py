"""A recorded stop's TP/SL order on the private stream (E29-T05 #848, S6b; 24-internal-schemas.md
Sec.8.12, Sec.8.3 rule 7). Plain code on the hot-path contract (C-2.20): `RecordedStopStream` is
`StreamPushes`' `RecordedStopStream` seam, for a push that pairing step 3 matched to a recorded side
(`ToRecordedStop`) with no `orders` row bound to its order yet.

`take` materialises that order's row through the facade (`OrderMachines.materialise`, `MATERIALISED`
from `ws_private`), with the record's bind in the same transaction (`binds`), and answers the row
the order's exchange id reads afterwards, which the caller gives the push. The row is the one 24
Sec.8.3 rule 7 names: provenance `recorded_stop`, the record's side as its purpose, the order's
trigger price, a size (below) and position index, `reduce_only` and
`close_on_trigger` set (INV-B1-o), no trade group, and the id "Adopted rows" gives: the push's own
`OUR_ID` when no row of the account holds it, else `ext_key(orderId)`. The record must be the
account's, of the order's key and side, on the position the order closes (the security lens's F1,
which the first bind checks again): anything else is a defect, refused before any write (C-12.4),
and paged once per order.

**The row's size (the orchestrator's 2026-10-26 07:20Z ruling).** It is a provisional snapshot taken
when the row is created, never the record's size: the order's quantity; for a Full-mode order
showing `qty` 0 (which `ord_qty` refuses), the size of the position it closes as the projection last
applied it; and when a Full-mode order's fill materialises the row, the fill's quantity (a Full-mode
stop closes whatever the position is at its trigger, so the fill is the truth and fits the row).
With that position flat, unknown or on the other side, an order push decides nothing (no row,
counted `stop_no_position`). A Partial-mode order showing 0 cannot be closed as a Partial: it is
refused, counted `stop_qty_refused` and paged once per order. A Full-mode fill whose quantity
differs from an existing row's size (the position scaled in or out) is E29-T06's to reconcile as
filled.

**Bounds (24 Sec.8.12, the 2026-10-25 ruling Q5).** The account's environment and the link-id read
are each bounded at `PORT_TIMEOUT_S`; the materialise at `MATERIALISE_BOUND_S` (30 s, the facade's
push bound: B1's 10 s write-ahead through its 5 s ports, never the 5 s hand-over bound, as the
match has already decided the order's intent); each read-back at `PORT_TIMEOUT_S`, on a deadline of
its own, so a materialise that spent its bound never starves it. `TAKE_BUDGET_S` is their sum.

**Nothing acts on an unknown or refused write.** A materialise that does not answer in time, that
meets the order's row materialised meanwhile (`ux_orders_exch_id`: the second finds the row) or its
record bound meanwhile (`RecordedStopNotBindable`), or that fails, decides nothing itself: the row
is read again by the order's exchange id (after a materialise that answered, by the new row's id
when that read misses, the security lens's F7), a row found takes the push, and none leaves the
order to the next pass (`take` answers None). So a protecting stop's order push always reaches a
bound row or is left to be read afresh, never dropped (C-2.6). `after_bind` then runs the position
projection's record hook for the key (S5c), so a fired Full-mode stop whose flat push came first
ends once its order is bound (on its order push, or on its fill, which sizes the row).

Both raise nothing but `CancelledError`. Logs carry ids, a kind and an outcome only: never a price,
a size or the push's link id (C-12.6). Nothing here imports the facade or the statechart.

**The successor's bind (S7b; 24 Sec.8.12, Sec.8.3 rule 7, Sec.15.5).** `Successor.check` runs on
every order push to a bound recorded stop's row whose order is live or ended `filled`, after its
terms step: it reads the record bound to the order and the key's live records, each bounded at
`PORT_TIMEOUT_S`, and when a record later than the bound one (by `created_at`, then `id`) matches
the push (`pairing.matching_record`), it releases the bound one and binds the later in one
transaction (`RecordedStopRepository.release_and_bind`), stamped on the OMS's clock and written
ahead (`sl.modified` or `tp.modified`, reason `successor_bind`, keyed, ids only), bounded at
`RELEASE_BOUND_S`. A record that has ended keeps its order, and so does one whose order ended
other than `filled`. A write refused (`RecordedStopNotBindable`), failed or cut short decides
nothing: the record bound to the order is read again and logged by id, and nothing acts on what
the write may have done. A bind then runs the projection's record hook for the key (`after_bind`).
Two guards keep a push from moving a binding it should not (the security lens): a push older, by
the venue's `updated_at`, than the newest one the check met for the order is stale and decides
nothing (the facade ignores such a step and answers as for one it took, so the stream cannot learn
it there), and an entry's attach (`entry_attach`) is never a successor, as its stop arrives as a
new order at the entry's fill, never as an in-place change of a bound one (the first bind, in
`pairing.first_bindable`, takes one only for an order the venue created after it).

Known residual (the orchestrator's Q3 ruling): `Order` carries no trail, so a fired native trail
the OMS recorded never reaches here; it reads as no OMS intent until E29-K01 (`oms.pairing`).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol
from uuid import UUID, uuid4

import structlog

from candleviewer.domain.order_link import OUR_ID, ext_key
from candleviewer.domain.primitives import AccountId, TsUs
from candleviewer.exchange.base.models import Execution, Order, Position
from candleviewer.storage.repositories.orders import (
    CLOSED_BY,
    NewOrder,
    OrderRow,
    OrderSide,
    OrderType,
    RecordedStopBind,
    TimeInForce,
)
from candleviewer.storage.repositories.recorded_stops import (
    LIVE_STOP_STATUSES,
    RecordedStopRow,
    ReleaseWriteAhead,
)

from .pairing import STOP_SIDES, ToRecordedStop, matching_record
from .ports import KeyedRecord, PositionKey, TradingAccounts
from .stream_push import PAGED_ORDERS, PORT_TIMEOUT_S, PUSH_TIMEOUT_S, Event, Pager, PushCounts

#: 24 Sec.8.12 (Q5): a recorded stop's materialise, bounded as the facade's push is, not at 5 s.
MATERIALISE_BOUND_S: Final = PUSH_TIMEOUT_S
#: One `take` at worst: the account, the link-id read, the materialise and the two read-backs.
TAKE_BUDGET_S: Final = 4 * PORT_TIMEOUT_S + MATERIALISE_BOUND_S
#: 24 Sec.8.12 "The successor's bind": the orders a successor may bind, live or ended `filled`; one
#: ended otherwise (cancelled, rejected, expired, deactivated) keeps its record (Sec.8.3 rule 7).
SUCCESSOR_STATES: Final = frozenset(
    {"new", "untriggered", "partially_filled", "triggered", "filled"}
)
#: The release and bind, bounded as the facade's push is: the store's write-ahead audit inside it.
RELEASE_BOUND_S: Final = PUSH_TIMEOUT_S
#: One `Successor.check` at worst: the two reads, the release and the re-read or the record hook.
SUCCESSOR_BUDGET_S: Final = 3 * PORT_TIMEOUT_S + RELEASE_BOUND_S
#: The orders whose newest push time the successor's check keeps, the oldest forgotten past it.
STAMPED_ORDERS: Final = PAGED_ORDERS
SUCCESSOR_BIND: Final = "successor_bind"  # 24 Sec.15.5: the record's reason and name prefix
_MODIFIED: Final[Mapping[str, str]] = MappingProxyType(
    {"stop_loss": "sl.modified", "take_profit": "tp.modified"}
)

_SIDES: Final[Mapping[str, OrderSide]] = MappingProxyType({"buy": "Buy", "sell": "Sell"})
_TYPES: Final[Mapping[str, OrderType]] = MappingProxyType({"market": "Market", "limit": "Limit"})
_TIFS: Final[Mapping[str, TimeInForce]] = MappingProxyType(
    {"gtc": "GTC", "ioc": "IOC", "fok": "FOK", "post_only": "PostOnly"}
)
_PAGES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "mismatch": "a recorded stop's order is not on the position its record closes; refused",
        "qty_zero": "a Partial-mode recorded stop's order shows a quantity of 0; refused",
    }
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class Materialiser(Protocol):  # `OrderMachines.materialise`, structurally
    async def materialise(
        self, order: NewOrder, *, environment: str, binds: RecordedStopBind | None = None
    ) -> str: ...


class OrderReads(Protocol):  # the order store's reads
    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None: ...
    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> OrderRow | None: ...
    async def get_by_link_id(self, account_id: UUID, order_link_id: str) -> OrderRow | None: ...


class BoundStops(Protocol):  # `PositionProjection`'s record hook and last row, structurally
    async def after_bind(self, key: PositionKey) -> None: ...
    def last_applied(self, key: PositionKey) -> Position | None: ...  # sync


class SuccessorStops(Protocol):  # `RecordedStopRepository`, structurally
    async def for_exchange_order(
        self, account_id: UUID, exchange_order_id: str
    ) -> tuple[RecordedStopRow, ...]: ...
    async def live_for_key(
        self, account_id: UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]: ...
    async def release_and_bind(
        self, account_id: UUID, predecessor_id: UUID, successor_id: UUID, exchange_order_id: str,
        *, at: datetime, write_ahead: ReleaseWriteAhead,
    ) -> tuple[RecordedStopRow, RecordedStopRow]: ...  # fmt: skip


class ReleaseAudit(Protocol):  # `SubmitAudit.write`, structurally: durable or it raises (C-2.9)
    async def write(self, record: KeyedRecord) -> None: ...


class RecordedStopStream:
    def __init__(
        self, *, machines: Materialiser, reads: OrderReads, accounts: TradingAccounts,
        positions: BoundStops, counts: PushCounts, pager: Pager,
        new_id: Callable[[], UUID] = uuid4,
    ) -> None:  # fmt: skip
        self._machines, self._reads, self._accounts = machines, reads, accounts
        self._positions, self._counts, self._new_id = positions, counts, new_id
        self._pager = pager
        self._paged: OrderedDict[tuple[str, AccountId, str], None] = OrderedDict()

    async def take(
        self, account_id: AccountId, decision: ToRecordedStop, push: Order | Execution,
        event: Event | None, ts_event: TsUs,
    ) -> OrderRow | None:  # fmt: skip
        """The row of `decision.order`, materialised now or found by its exchange id, or None:
        the order is left to the next pass. Raises nothing but `CancelledError`."""
        record, order = decision.record, decision.order
        ids = _ids(account_id, order)
        if not _its_stop(account_id, record, order):
            _log().error("stream_recorded_stop_mismatch", record_id=str(record.id), **ids)
            self._counts.count("pairing_refused")
            self._page_once("mismatch", account_id, order)
            return None
        qty = self._qty_of(account_id, record, order, push, ids)
        if qty is None:
            return None
        row_id, xid = self._new_id(), order.exchange_order_id
        took = await self._materialise(account_id, record, order, qty, row_id, ids)
        row = await self._read_back(account_id, xid, self._reads.get_by_exchange_order_id, xid, ids)
        if row is None and took:  # the security lens's F7: the row this call wrote, by its id
            row = await self._read_back(account_id, xid, self._reads.get, row_id, ids)
        if row is None:
            _log().warning("stream_recorded_stop_not_found", **ids)
            self._counts.count("stop_undecided")
            return None
        _log().info("stream_recorded_stop_row", materialised=took, order_id=str(row.id), **ids)
        self._counts.count("stop_materialised" if took else "stop_found")
        return row

    async def after_bind(self, account_id: AccountId, decision: ToRecordedStop) -> None:
        """The projection's record hook for the record's key, after its order's row took the push
        (S5c). The projection bounds it and raises nothing but `CancelledError`; the caller bounds
        it again."""
        record = decision.record
        await self._positions.after_bind(
            PositionKey(account_id, record.symbol, record.position_idx)
        )

    def _qty_of(
        self, account_id: AccountId, record: RecordedStopRow, order: Order,
        push: Order | Execution, ids: Mapping[str, str],
    ) -> Decimal | None:  # fmt: skip
        """The row's provisional size: a Full-mode order's fill's quantity (the fill is the whole
        position); else the order's; for a Full-mode order showing 0, the size of the position it
        closes; None (nothing decided) when neither is known or it is refused."""
        if isinstance(push, Execution) and record.tpsl_mode == "Full":
            return push.qty
        if order.qty > 0:
            return order.qty
        if record.tpsl_mode == "Partial":
            _log().error("stream_recorded_stop_qty_refused", **ids)
            self._counts.count("stop_qty_refused")
            self._page_once("qty_zero", account_id, order)
            return None
        p = self._positions.last_applied(PositionKey(account_id, order.symbol, order.position_idx))
        if p is None or p.side is None or p.qty <= 0 or _SIDES[p.side] != record.position_side:
            _log().warning("stream_recorded_stop_no_position", **ids)
            self._counts.count("stop_no_position")
            return None
        return p.qty

    def _page_once(
        self, why: Literal["mismatch", "qty_zero"], account_id: AccountId, order: Order
    ) -> None:
        """One page per (reason, account, exchange order id); the oldest forgotten past the
        bound."""
        key = (why, account_id, order.exchange_order_id)
        if key in self._paged:
            return
        self._paged[key] = None
        if len(self._paged) > PAGED_ORDERS:
            self._paged.popitem(last=False)
        self._pager.raise_alert("page", _PAGES[why], machine_kind="oms.recorded_stop_stream")

    async def _materialise(
        self, account_id: AccountId, record: RecordedStopRow, order: Order, qty: Decimal,
        row_id: UUID, ids: Mapping[str, str],
    ) -> bool:  # fmt: skip
        """True when this call materialised the row and bound the record. Anything else, a
        refusal, a lost race or the bound among them, decides nothing: the caller reads again."""
        try:
            ref = await _bounded(self._accounts.trading_account(account_id), PORT_TIMEOUT_S)
            link = await self._link(account_id, order)
            new = _row_of(row_id, account_id, record, order, link, qty)
            binds = RecordedStopBind(record_id=record.id, kind=record.kind)
            await _bounded(
                self._machines.materialise(new, environment=ref.environment, binds=binds),
                MATERIALISE_BOUND_S,
            )
        except Exception as exc:  # never a CancelledError
            _log().warning("stream_recorded_stop_not_materialised", kind=type(exc).__name__, **ids)
            return False
        return True

    async def _link(self, account_id: AccountId, order: Order) -> str:
        """24 Sec.8.3 "Adopted rows": the push's `OUR_ID` when no row of the account holds it,
        else (or for any other id) `ext_key(orderId)`."""
        link = order.order_link_id
        if OUR_ID.fullmatch(link) is None:
            return ext_key(order.exchange_order_id)
        held = await _bounded(self._reads.get_by_link_id(account_id, link), PORT_TIMEOUT_S)
        return link if held is None else ext_key(order.exchange_order_id)

    async def _read_back[K](
        self, account_id: AccountId, xid: str,
        read: Callable[[UUID, K], Awaitable[OrderRow | None]], key: K, ids: Mapping[str, str],
    ) -> OrderRow | None:  # fmt: skip
        """The account's row `read` answers for `key` (the order's exchange id, or the id this call
        wrote), on a deadline of its own; None when none is, or the read failed, or answered a row
        that is not the order's (a store defect, C-12.4)."""
        try:
            row = await _bounded(read(account_id, key), PORT_TIMEOUT_S)
        except Exception as exc:
            _log().warning("stream_recorded_stop_reread_failed", kind=type(exc).__name__, **ids)
            return None
        if row is None:
            return None
        if (row.exchange_account_id, row.exchange_order_id) != (account_id, xid):
            _log().error("stream_recorded_stop_foreign_row", **ids)
            return None
        return row


class Successor:
    """24 Sec.8.12 "The successor's bind" (module docstring). Raises nothing but
    `CancelledError`."""

    def __init__(
        self, *, stops: SuccessorStops, audit: ReleaseAudit, positions: BoundStops,
        counts: PushCounts, clock: Callable[[], datetime],
    ) -> None:  # fmt: skip
        self._stops, self._audit, self._positions = stops, audit, positions
        self._counts, self._clock = counts, clock
        self._stamps: OrderedDict[tuple[AccountId, str], int] = OrderedDict()

    async def check(self, account_id: AccountId, row: OrderRow, order: Order) -> None:
        """An order push to `row`, a bound recorded stop's row: the side's later matching record,
        if any, takes the order's binding from the record that holds it."""
        xid = order.exchange_order_id
        mine = (order.account_id, row.exchange_account_id) == (account_id, account_id)
        if row.exchange_order_id != xid or not mine:  # the caller's check, again (C-12.4)
            return
        ids = _ids(account_id, order)
        if self._stale(account_id, order, ids) or order.state not in SUCCESSOR_STATES:
            return
        held = await self._read(self._stops.for_exchange_order(account_id, xid), ids)
        live = [r for r in held or () if r.status in LIVE_STOP_STATUSES and r.released_at is None]
        if len(live) != 1:  # none: an ended record keeps its order (rule 7); two: never
            if len(live) > 1:
                self._refused("stream_successor_two_holders", ids)
            return
        [old] = live
        key = (account_id, order.symbol, order.position_idx)
        rows = await self._read(self._stops.live_for_key(*key), ids)
        if rows is None:
            return
        if any(_key(r) != key for r in (old, *rows)):  # a store defect (C-12.4)
            self._refused("stream_successor_foreign_record", ids)
            return
        candidates = [r for r in rows if r.source != "entry_attach"]  # never an entry's attach
        new = matching_record(order, candidates)
        if new is None or new.kind != old.kind or _age(new) <= _age(old):  # never an earlier one
            return
        pair = {"predecessor_id": str(old.id), "successor_id": str(new.id)} | ids
        if not await self._release(account_id, old.id, new.id, xid, pair):
            again = await self._read(self._stops.for_exchange_order(account_id, xid), ids)
            if again is not None:  # a failed re-read was counted already
                holders = [str(r.id) for r in again]
                _log().warning("stream_successor_undecided", holders=holders, **pair)
                self._counts.count("successor_undecided")
            return
        _log().info("stream_successor_bound", **pair)
        self._counts.count("successor_bound")
        try:  # the hook runs again at the key's next applied position row
            await _bounded(self._positions.after_bind(PositionKey(*key)), PORT_TIMEOUT_S)
        except Exception as exc:
            _log().warning("stream_after_bind_failed", kind=type(exc).__name__, **ids)
            self._counts.count("after_bind_failed")

    def _stale(self, account_id: AccountId, order: Order, ids: Mapping[str, str]) -> bool:
        """True when the push is older, by the venue's `updated_at`, than the newest one this check
        met for the order (a late or redelivered push); else that newest time moves to it. A push
        with no time is never judged stale."""
        stamp, key = order.updated_at, (account_id, order.exchange_order_id)
        if stamp is None:
            return False
        last = self._stamps.get(key)
        if last is not None and stamp < last:
            _log().info("stream_successor_stale_push", **ids)
            return True
        self._stamps[key] = stamp
        self._stamps.move_to_end(key)
        if len(self._stamps) > STAMPED_ORDERS:
            self._stamps.popitem(last=False)
        return False

    async def _release(
        self, account_id: AccountId, old: UUID, new: UUID, xid: str, pair: Mapping[str, str]
    ) -> bool:
        """True when the release and bind committed; anything else decided nothing known."""
        try:
            await _bounded(
                self._stops.release_and_bind(
                    account_id, old, new, xid, at=self._clock(), write_ahead=self._write_ahead
                ),
                RELEASE_BOUND_S,
            )
        except Exception as exc:  # refused, failed, a late audit or the bound: never acted on
            _log().warning("stream_successor_not_bound", kind=type(exc).__name__, **pair)
            return False
        return True

    async def _write_ahead(self, rows: tuple[RecordedStopRow, RecordedStopRow]) -> None:
        """24 Sec.15.5: one keyed record ahead of the commit, as `system:oms`, ids only."""
        released, bound = rows
        detail: dict[str, str | None] = {
            "kind": bound.kind, "predecessor_id": str(released.id),
            "successor_id": str(bound.id), "exchange_order_id": bound.exchange_order_id,
        }  # fmt: skip
        record = KeyedRecord(
            _MODIFIED[bound.kind], f"{SUCCESSOR_BIND}:{bound.id}", bound.exchange_account_id,
            "recorded_stop", bound.id, "success", "info", SUCCESSOR_BIND, None, detail,
        )  # fmt: skip
        await self._audit.write(record)

    async def _read(
        self, call: Awaitable[tuple[RecordedStopRow, ...]], ids: Mapping[str, str]
    ) -> tuple[RecordedStopRow, ...] | None:
        """A record read, bounded; None when it failed or the bound cut it (decides nothing)."""
        try:
            return await _bounded(call, PORT_TIMEOUT_S)
        except Exception as exc:
            _log().warning("stream_successor_read_failed", kind=type(exc).__name__, **ids)
            self._counts.count("successor_undecided")
            return None

    def _refused(self, event: str, ids: Mapping[str, str]) -> None:
        _log().error(event, **ids)
        self._counts.count("pairing_refused")


def _row_of(
    row_id: UUID, account_id: AccountId, record: RecordedStopRow, order: Order, link: str,
    qty: Decimal,
) -> NewOrder:  # fmt: skip
    """The materialised row (24 Sec.8.3 rule 7): the order's terms, the record's side, and `qty`
    from `_qty_of`."""
    return NewOrder(
        id=row_id,
        exchange_account_id=account_id,
        order_link_id=link,
        symbol=order.symbol,
        side=_SIDES[order.side],
        intent=record.kind,
        order_type=_TYPES[order.order_type],
        qty=qty,
        price=order.price,
        trigger_price=order.trigger_price,
        tpsl_mode=record.tpsl_mode,
        time_in_force=_TIFS.get(order.time_in_force, "GTC"),
        reduce_only=True,
        close_on_trigger=True,
        position_idx=order.position_idx,
        exchange_order_id=order.exchange_order_id,
        provenance="recorded_stop",
    )


def _its_stop(account_id: AccountId, record: RecordedStopRow, order: Order) -> bool:
    """The decision's record is the account's, of the order's key and side, on the position the
    order closes (`CLOSED_BY`, F1), and the order is the account's TP/SL claim of that side."""
    side = STOP_SIDES.get(order.order_kind)
    key = (account_id, order.symbol, order.position_idx)
    return (
        side is not None
        and side[0] == record.kind
        and order.account_id == account_id
        and (record.exchange_account_id, record.symbol, record.position_idx) == key
        and record.position_side == CLOSED_BY[_SIDES[order.side]]
    )


async def _bounded[T](call: Awaitable[T], seconds: float) -> T:
    async with asyncio.timeout(seconds):
        return await call


def _age(record: RecordedStopRow) -> tuple[datetime, UUID]:  # later and latest (rule 7)
    return record.created_at, record.id


def _key(record: RecordedStopRow) -> tuple[UUID, str, int]:
    return record.exchange_account_id, record.symbol, record.position_idx


def _ids(account_id: AccountId, order: Order) -> dict[str, str]:  # ids only (C-12.6)
    return {"account_id": str(account_id), "exchange_order_id": order.exchange_order_id}

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

Known residual (the orchestrator's Q3 ruling): `Order` carries no trail, so a fired native trail
the OMS recorded never reaches here; it reads as no OMS intent until E29-K01 (`oms.pairing`).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
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
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow

from .pairing import STOP_SIDES, ToRecordedStop
from .ports import PositionKey, TradingAccounts
from .stream_push import PAGED_ORDERS, PORT_TIMEOUT_S, PUSH_TIMEOUT_S, Event, Pager, PushCounts

#: 24 Sec.8.12 (Q5): a recorded stop's materialise, bounded as the facade's push is, not at 5 s.
MATERIALISE_BOUND_S: Final = PUSH_TIMEOUT_S
#: One `take` at worst: the account, the link-id read, the materialise and the two read-backs.
TAKE_BUDGET_S: Final = 4 * PORT_TIMEOUT_S + MATERIALISE_BOUND_S

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


def _ids(account_id: AccountId, order: Order) -> dict[str, str]:  # ids only (C-12.6)
    return {"account_id": str(account_id), "exchange_order_id": order.exchange_order_id}

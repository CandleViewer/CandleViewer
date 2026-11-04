"""The venue of E29-Q04's chaos suite (#1148): the demo `FakeTradingPort`, the exchange truth the
oracle compares the book against (C-13.5: no network, no recorded session), moved only through the
fake's public seeding methods (`seed_order`, `seed_execution`, `seed_position`, `push`, `script`)
and read through its own reads. A fill keeps the venue consistent with itself: the order's totals
are the sum of its executions, its average at the columns' 18 places, and the position an entry
opens carries the stop and take-profit its create attached, as a Full mode attach does (C-2.6), so
the reconciliation pass, which adopts no totals without their fills (`reconciler.py`,
`found_sends`), can find the truth. Its pushes reach the account's private stream
(`subscribe_private`), or are withheld. The creates are counted per `order_link_id` from the fake's
own call log, outside the app (#1148's "counted at the mock exchange").

The venue facts are 24's documented ones, not measured: E29-K01 (#843) is open, so the shapes are
derived, not evidence (E29-T05's ruling Q1). This module names no venue field (C-2.2)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from typing import Final, Literal

from candleviewer.domain.primitives import OrderLinkId, Symbol, TsUs
from candleviewer.exchange.base.errors import AmbiguousResultError
from candleviewer.exchange.base.fakes import LandedThenAmbiguous
from candleviewer.exchange.base.models import (
    AccountRef,
    Execution,
    Order,
    PlaceOrderRequest,
    Position,
    PrivateEvent,
)
from tests.unit.oms.test_oms_runtime import Port

#: The taker rate a fill pays, as `submit_rig.figures()` reads the venue's.
TAKER: Final = Decimal("0.00055")
#: The states a fill leaves an order in, and those it fills in (24 Sec.8.12).
FILLED: Final = "filled"
PARTIAL: Final = "partially_filled"
_OPEN: Final = frozenset({"new", "untriggered", "triggered", PARTIAL})


class VenuePort(Port):
    """The demo venue's port, on the world's wall clock. `seed_order` puts an order that ended in
    the venue's history but cannot take it out of its open book, so the open reads leave out the
    orders the venue ended (`ended`), as the venue's own read does."""

    def __init__(self, *, now_us: Callable[[], TsUs]) -> None:
        super().__init__(environment="demo", now_us=now_us)
        self.ended: set[str] = set()

    async def open_orders(
        self,
        account: AccountRef,
        symbol: Symbol | None = None,
        *,
        order_link_id: OrderLinkId | None = None,
    ) -> Sequence[Order]:
        held = await super().open_orders(account, symbol, order_link_id=order_link_id)
        return [order for order in held if order.exchange_order_id not in self.ended]


@dataclass
class Venue:
    """The account's venue: what it holds and how it moves (module docstring)."""

    port: VenuePort
    account: AccountRef
    clock: Callable[[], TsUs]
    positions: dict[tuple[str, int], Position] = field(default_factory=dict)
    #: Each order's filled value, the sum of its executions' (exact, unrounded).
    values: dict[str, Decimal] = field(default_factory=dict)
    fills: int = 0
    last_us: TsUs = 0

    def creates(self) -> Counter[str]:
        """Each `order_link_id`'s create requests that reached the venue, landed or not."""
        sent = (c.request for c in self.port.calls if c.method in ("place_order", "place_batch"))
        flat = (r for item in sent for r in (item if isinstance(item, tuple) else (item,)))
        return Counter(r.order_link_id for r in flat if isinstance(r, PlaceOrderRequest))

    def lose_ack(self) -> None:
        """The `place` door: the next create lands, then its answer is lost (a post-send
        timeout, 24 Sec.8.6 "Order creates")."""
        self.port.script("place_order", LandedThenAmbiguous())

    def time_out(self) -> None:
        """The `place` door: the next create times out after the send and never lands."""
        self.port.script("place_order", AmbiguousResultError("the create timed out unanswered"))

    async def order(self, link: str) -> Order:
        """The venue's order under `link`, open or in history, read as any reader reads it."""
        held = [*await self.port.open_orders(self.account, order_link_id=OrderLinkId(link))]
        held += await self.port.order_history(self.account, order_link_id=OrderLinkId(link))
        [order] = held
        return order

    async def fill(self, link: str, qty: Decimal, price: Decimal, *, push: bool) -> Execution:
        """One execution of the order under `link`: its totals, its end once filled, and its
        position, each seeded; pushed on the account's stream with `push`, else withheld."""
        order = await self.order(link)
        done = order.filled_qty + qty
        if qty <= 0 or done > order.qty or order.state not in _OPEN:
            raise ValueError("a fill takes part of what an open order leaves")
        now, seq = max(self.clock(), self.last_us + 1), self.fills + 1  # each later than the last
        xid = order.exchange_order_id
        value = self.values.get(xid, Decimal(0)) + price * qty
        state: Literal["filled", "partially_filled"] = FILLED if done == order.qty else PARTIAL
        order = order.model_copy(update={
            "filled_qty": done, "leaves_qty": order.qty - done, "avg_fill_price": _avg(value, done),
            "state": state, "updated_at": now, "terminal_at": now if state == FILLED else None,
        })  # fmt: skip
        execution = Execution(
            exec_id=f"q04-exec-{seq:04d}", exchange_order_id=xid,
            order_link_id=order.order_link_id, account_id=order.account_id, symbol=order.symbol,
            side=order.side, price=price, qty=qty, fee=price * qty * TAKER, fee_rate=TAKER,
            fee_currency="USDT", is_maker=False, exec_type="trade", closed_pnl=None,
            ts_exec=now, ts_ingest=now, seq=seq,
        )  # fmt: skip
        position = self._moved(order, execution, now)  # refused before the venue moves
        self.fills, self.last_us, self.values[xid] = seq, now, value
        self.positions[(position.symbol, position.position_idx)] = position
        self.port.seed_order(order, uid=self.account.uid)
        if state == FILLED:
            self.port.ended.add(xid)
        self.port.seed_execution(execution)
        self.port.seed_position(position)
        if push:
            for kind, payload in (("order", order), ("execution", execution)):
                self._push(kind, payload, now)
            self._push("position", position, now)
        return execution

    def _moved(self, order: Order, fill: Execution, now: TsUs) -> Position:
        """The order's position after `fill`: an entry adds to its own side at its average and
        carries the stop and take-profit its create attached (Full mode), a reducing fill takes
        from it, and a flat one carries no stop (the venue clears both sides). No flip."""
        key = (order.symbol, order.position_idx)
        held = self.positions.get(key)
        qty, avg = (Decimal(0), None) if held is None else (held.qty, held.avg_entry_price)
        side = order.side if held is None or held.side is None else held.side
        if (side != order.side) != order.reduce_only or (order.reduce_only and fill.qty > qty):
            raise ValueError("an entry adds to its own side, a reducing fill takes what is held")
        if order.reduce_only:
            size, avg_entry = qty - fill.qty, avg
        else:
            size = qty + fill.qty
            avg_entry = _avg(fill.price * fill.qty + (avg or Decimal(0)) * qty, size)
        flat = size == 0
        stops = held if held is not None and order.reduce_only else order
        return Position(
            account_id=order.account_id, symbol=order.symbol, position_idx=order.position_idx,
            side=None if flat else side, qty=size, avg_entry_price=None if flat else avg_entry,
            mark_price=fill.price, liq_price=None, leverage=Decimal(10),
            unrealised_pnl=Decimal(0), cum_realised_pnl=Decimal(0),
            take_profit=None if flat else stops.take_profit,
            stop_loss=None if flat else stops.stop_loss,
            trailing_stop_distance=None, updated_at=now,
        )  # fmt: skip

    def _push(self, kind: str, payload: object, at: TsUs) -> None:
        values = {"kind": kind, "account_id": self.account.account_id, "payload": payload}
        self.port.push(PrivateEvent.model_validate(values | {"ts_event": at, "ts_ingest": at}))


def _avg(value: Decimal, qty: Decimal) -> Decimal:
    """An average at the columns' scale: the exact quotient, rounded once to 18 places."""
    return Decimal(round(Fraction(value) / Fraction(qty) * 10**18)).scaleb(-18)

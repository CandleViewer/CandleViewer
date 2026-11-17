"""The venue of E29-Q04's chaos suite (#1148): the demo `FakeTradingPort`, the exchange truth the
oracle compares the book against (C-13.5: no network, no recorded session), moved only through the
fake's public seeding methods (`seed_order`, `seed_execution`, `seed_position`, `push`, `script`)
and read through its own reads. A fill keeps the venue consistent with itself: the order's totals
are the sum of its executions, its average at the columns' 18 places, and the position an entry
opens carries the stop and take-profit its create attached, as a Full mode attach does (C-2.6), so
the reconciliation pass, which adopts no totals without their fills (`reconciler.py`,
`found_sends`), can find the truth; or none (`attached` off), so the OMS's attach is due, and a
stop it writes moves the position as the venue does. Its pushes reach the account's private stream
(`subscribe_private`), or are withheld. The creates are counted per `order_link_id` from the fake's
own call log, outside the app (#1148's "counted at the mock exchange"). Its stream's own news
(`status`: a socket lost, a reconnect) and an order's end pushed while its reads still show the
order open (`end_unread`, then `settle`: the venue's REST view lags its stream) are the stream
faults. With the adapter's rate governor (`TokenBucketGovernor`), a `10018` it answers holds every
caller as the REST client holds it, and its headroom is the governor's (the IP hold, 24 Sec.8.6).

The venue facts are 24's documented ones, not measured: E29-K01 (#843) is open, so the shapes are
derived, not evidence (E29-T05's ruling Q1). This module names no venue field (C-2.2)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from typing import Final, Literal

from candleviewer.domain.primitives import AccountId, OrderLinkId, TsUs
from candleviewer.exchange.base.errors import (
    AmbiguousResultError,
    OmsErrorCode,
    RateLimitError,
)
from candleviewer.exchange.base.fakes import FakeReject, LandedThenAmbiguous
from candleviewer.exchange.base.models import (
    AccountRef,
    Execution,
    Order,
    OrderAck,
    PlaceOrderRequest,
    Position,
    PrivateEvent,
    PrivateStreamReason,
    PrivateStreamState,
    PrivateStreamStatus,
    RateHeadroom,
    RateLane,
    TradingStopRequest,
)
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from tests.unit.oms.command_rig import LANE_WAITS
from tests.unit.oms.test_oms_runtime import Port

#: The taker rate a fill pays, as `submit_rig.figures()` reads the venue's.
TAKER: Final = Decimal("0.00055")
#: The states a fill leaves an order in, and those it fills in (24 Sec.8.12).
FILLED: Final = "filled"
PARTIAL: Final = "partially_filled"
_OPEN: Final = frozenset({"new", "untriggered", "triggered", PARTIAL})
#: `10018`, the IP-wide limit, and the hold the REST client sets on it (24 Sec.8.6: at least 10
#: minutes, `rest.py`'s `_IP_HOLD_S`, as `tests/unit/exchange/bybit/test_rest_rate_limit_reset.py`
#: pins it: `test_rate_limit_10018_holds_every_uid_for_ten_minutes`).
IP_LIMIT: Final = 10018
IP_HOLD_S: Final = 600.0


class VenuePort(Port):
    """The demo venue's port, on the world's wall clock. An order seeded as ended leaves the open
    book for the history, as the venue moves it (the fake's `seed_order` keeps the open copy). A
    stop it takes (`set_trading_stop`) moves the position no earlier than the millisecond after
    the position's last change, the venue's clock moving on between two of its changes (its times
    are ms), and its stream pushes the position. With a `governor`, it is the Bybit port's in three
    things (`exchange/bybit/trading.py`, `rest.py`): a create waits for its token within its lane's
    wait (`LANE_WAITS`), refused with nothing sent (`place_order`'s; `place_batch` takes no token
    here); the headroom it reads is the governor's; and a `10018` it answers holds the IP first."""

    def __init__(
        self, *, now_us: Callable[[], TsUs], governor: TokenBucketGovernor | None = None
    ) -> None:
        super().__init__(environment="demo", now_us=now_us)
        self.governor = governor

    def seed_order(self, order: Order, *, uid: str) -> None:
        super().seed_order(order, uid=uid)
        if order.state not in _OPEN:
            self._open.pop(order.exchange_order_id, None)

    def holding(self, account_id: AccountId, symbol: str, position_idx: int) -> Position | None:
        """The position the venue holds under the key: its own book, read with no call logged."""
        key = (account_id, symbol, position_idx)
        return next((p for p in self._positions if _key(p) == key), None)

    async def set_trading_stop(self, req: TradingStopRequest) -> OrderAck:
        key = (req.account.account_id, req.symbol, req.position_idx)
        before = self.holding(*key)
        ack = await super().set_trading_stop(req)
        moved = self.holding(*key)
        if ack.ok and before is not None and moved is not None:  # the fake moved it: stamp, push
            at = max(moved.updated_at, (before.updated_at // 1_000 + 1) * 1_000)
            moved = moved.model_copy(update={"updated_at": at})
            self.seed_position(moved)
            self.push(_event("position", moved.account_id, moved, at))
        return ack

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        if self.governor is not None:  # `RateBudgetExceededError` once the wait passes the lane's
            wait = LANE_WAITS[req.lane]
            await self.governor.acquire(
                req.account.uid, EndpointClass.ORDER, lane=req.lane, deadline_s=wait
            )
        return await super().place_order(req)

    def headroom(self, account: AccountRef, lane: RateLane) -> RateHeadroom:
        if self.governor is None:
            return super().headroom(account, lane)
        reads = EndpointClass.ACCOUNT if lane == "poll" else EndpointClass.ORDER
        tokens, wait_s = self.governor.headroom(account.uid, reads, lane=lane)
        return RateHeadroom(lane=lane, tokens=tokens, wait_s=wait_s)

    def _outcome(self, method: str) -> FakeReject | LandedThenAmbiguous | None:
        try:
            return super()._outcome(method)
        except RateLimitError as exc:
            if exc.exchange_ret_code == IP_LIMIT and self.governor is not None:
                self.governor.hold_ip(IP_HOLD_S)  # as the REST client does (`rest.py`)
            raise


@dataclass
class Venue:
    """The account's venue: what it holds and how it moves (module docstring)."""

    port: VenuePort
    account: AccountRef
    clock: Callable[[], TsUs]
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

    def drift(self) -> None:
        """The next create is refused `10002`, its timestamp outside `recv_window` after the
        adapter's one re-signed retry (24 Sec.8.6): answered, so nothing landed."""
        self.port.script("place_order", FakeReject(OmsErrorCode.CLOCK_DRIFT, 10002))

    def ip_limit(self, method: str) -> None:
        """The next `method` is answered `10018`, the IP-wide limit (24 Sec.8.6)."""
        limited = RateLimitError("the IP rate limit was exceeded", exchange_ret_code=IP_LIMIT)
        self.port.script(method, limited)

    def status(self, state: PrivateStreamState, reason: PrivateStreamReason, epoch: int) -> None:
        """The account's stream's own news (24 Sec.14.2 rule 13): its socket `epoch` lost
        (`down`), or a new socket to reconcile over (`resyncing`)."""
        account = self.account.account_id
        news = PrivateStreamStatus(
            account_id=account, state=state, reason=reason, epoch=epoch, ts=self.clock()
        )
        self.port.push(news)

    async def end_unread(self, link: str) -> Order:
        """The order under `link` cancelled on the account's stream while the venue's reads
        still show it open, its REST view behind its stream until `settle`: the end pushed."""
        now = self.last_us = max(self.clock(), self.last_us + 1)
        update = {"state": "cancelled", "terminal_at": now, "updated_at": now}
        ended = (await self.order(link)).model_copy(update=update)
        self._push("order", ended, now)
        return ended

    async def ack(self, link: str) -> None:
        """The order under `link` acknowledged on the account's stream: its row as the venue
        holds it, pushed again as often as this is called (a redelivery)."""
        order = await self.order(link)
        self._push("order", order, order.updated_at or self.clock())

    def settle(self, ended: Order) -> None:
        """The venue's reads catch up with an end it pushed (`end_unread`)."""
        self.port.seed_order(ended, uid=self.account.uid)

    async def order(self, link: str) -> Order:
        """The venue's order under `link`, open or in history, read as any reader reads it."""
        held = [*await self.port.open_orders(self.account, order_link_id=OrderLinkId(link))]
        held += await self.port.order_history(self.account, order_link_id=OrderLinkId(link))
        [order] = held
        return order

    async def fill(
        self, link: str, qty: Decimal, price: Decimal, *, push: bool, attached: bool = True
    ) -> Execution:
        """One execution of the order under `link`: its totals, its end once filled, and its
        position, each seeded; pushed on the account's stream with `push`, else withheld. With
        `attached` off the position shows no stop, the create's not on it, so the OMS's attach is
        due (24 Sec.8.8 rule 2)."""
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
        if not attached:
            position = position.model_copy(update={"stop_loss": None})
        self.fills, self.last_us, self.values[xid] = seq, now, value
        self.port.seed_order(order, uid=self.account.uid)
        self.port.seed_execution(execution)
        self.port.seed_position(position)
        if push:
            for kind, payload in (("order", order), ("execution", execution)):
                self._push(kind, payload, now)
            self._push("position", position, now)
        return execution

    def _moved(self, order: Order, fill: Execution, now: TsUs) -> Position:
        """The order's position after `fill`, from the one the venue holds (`holding`, so a stop
        written since stays): an entry adds to its own side at its average and carries the stop
        and take-profit its create attached (Full mode), a reducing fill takes from it, and a flat
        one carries no stop (the venue clears both sides). No flip."""
        held = self.port.holding(order.account_id, order.symbol, order.position_idx)
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
        self.port.push(_event(kind, self.account.account_id, payload, at))


def _key(position: Position) -> tuple[AccountId, str, int]:
    return position.account_id, position.symbol, position.position_idx


def _event(kind: str, account_id: AccountId, payload: object, at: int) -> PrivateEvent:
    """A row the venue pushes on the account's private stream, stamped `at` (event and ingest)."""
    values = {"kind": kind, "account_id": account_id, "payload": payload}
    return PrivateEvent.model_validate(values | {"ts_event": at, "ts_ingest": at})


def _avg(value: Decimal, qty: Decimal) -> Decimal:
    """An average at the columns' scale: the exact quotient, rounded once to 18 places."""
    return Decimal(round(Fraction(value) / Fraction(qty) * 10**18)).scaleb(-18)

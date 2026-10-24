"""Which row takes a private-stream push (E29-T05 #848; 24-internal-schemas.md Sec.8.12 "Pairing",
Sec.8.3 rule 7, SR-E29-03). Pure: no I/O, no clock, no interpreter (C-2.20), on the hot-path
contract. `pair` decides from the reads made so far (`Reads`) and otherwise names the read it needs
next, each step's read only once the steps before it found nothing: (1) the row bound to the push's
exchange order id, in any state; (2) a live row of the account, unbound and not held, that the
push's normalised order link id names, whose reorder buffer holds it until its own bind decides;
(3) for an order the stream or a fill's order read shows as a TP/SL claim, the latest live record
of its position whose side it matches (Sec.8.8 rule 6, [O-4], failing closed); (4) no OMS intent.
A read that failed or that the hand-over bound cut short decides nothing, and so does a completed
read of a fill's order that found none. A row pairs through the bound id alone: an order link id
only names a row to wait on, and a fill is never matched on its own symbol, side or direction. A
read that answers another account's row, or a step-1 row bound to another exchange order id, is a
store or adapter defect: refused, never paired (C-12.4).

Known residual (the orchestrator's Q3 ruling): `Order` carries no trail, so a trailing order and a
record with a trail never match: a fired native trail the OMS recorded reads as no OMS intent (a
page and a lockout) until E29-K01 gives `Order` the trail.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, Literal

from candleviewer.exchange.base.models import Execution, Order
from candleviewer.storage.repositories.orders import UNFINISHED_STATES, OrderRow, TpslMode
from candleviewer.storage.repositories.recorded_stops import (
    LIVE_STOP_STATUSES,
    RecordedStopRow,
    StopKind,
)


class NoAnswer(Enum):  # nothing to decide on: not read yet, or it failed or the bound cut it short
    NOT_READ = "not_read"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Reads:
    """The reads made so far; `None` is a completed read that found nothing."""

    bound: OrderRow | NoAnswer | None = NoAnswer.NOT_READ  # OrderStore.get_by_exchange_order_id
    named: OrderRow | NoAnswer | None = NoAnswer.NOT_READ  # OrderStore.get_by_link_id
    order: Order | NoAnswer | None = NoAnswer.NOT_READ  # a fill's order, by its exchange order id
    stops: tuple[RecordedStopRow, ...] | NoAnswer = NoAnswer.NOT_READ  # live_for_key


# The read `pair` needs next: the caller makes it, bounded, and sets the field of `Reads` it fills.
@dataclass(frozen=True, slots=True)
class NeedBound:
    exchange_order_id: str


@dataclass(frozen=True, slots=True)
class NeedNamed:
    order_link_id: str


@dataclass(frozen=True, slots=True)
class NeedOrder:
    exchange_order_id: str


@dataclass(frozen=True, slots=True)
class NeedStops:
    symbol: str
    position_idx: int


@dataclass(frozen=True, slots=True)
class ToRow:
    """Step 1: the row bound to the push's exchange order id takes it, in any state."""

    row: OrderRow


@dataclass(frozen=True, slots=True)
class WaitOnRow:
    """Step 2: the push waits in this unbound row's reorder buffer for its bind; it never pairs."""

    row: OrderRow


@dataclass(frozen=True, slots=True)
class ToRecordedStop:
    """Step 3: `record` is `order`'s recorded stop; S6 materialises the row from `order`."""

    record: RecordedStopRow
    order: Order


@dataclass(frozen=True, slots=True)
class NoIntent:
    """Step 4: no row or record takes the push. `key` is the order's exchange order id or the fill's
    `exec_id`; `exchange_placed` is the read order's, so an unread fill's order is never exempt."""

    finding: Literal["order", "execution"]
    key: str
    exchange_placed: bool


@dataclass(frozen=True, slots=True)
class Undecided:
    """A read failed, was cut short or (`empty_read`) completed with no order for a fill."""

    empty_read: bool


type Need = NeedBound | NeedNamed | NeedOrder | NeedStops
type Pairing = Need | ToRow | WaitOnRow | ToRecordedStop | NoIntent | Undecided


class PairingRefused(ValueError):
    """A read answered a row, order or record that is not the push's. Names no value."""


#: A TP/SL claim's kind as the record side it can match ([O-4]); a trailing stop matches none.
STOP_SIDES: Final[Mapping[str, tuple[StopKind, TpslMode]]] = MappingProxyType({
    "stop_loss": ("stop_loss", "Full"), "take_profit": ("take_profit", "Full"),
    "partial_stop_loss": ("stop_loss", "Partial"),
    "partial_take_profit": ("take_profit", "Partial"),
})  # fmt: skip
_CLAIMS: Final = frozenset(STOP_SIDES) | {"trailing_stop"}
_CLOSING: Final = {"Buy": "sell", "Sell": "buy"}  # a record's position side -> the order's side
_REFUSED: Final = "a read answered a row that is not the push's: nothing is paired"


def pair(push: Order | Execution, reads: Reads) -> Pairing:
    """The decision `reads` allow for `push`, or the read it needs next (module docstring)."""
    trade = isinstance(push, Execution) and push.exec_type == "trade"
    if not (isinstance(push, Order) or trade):
        raise TypeError("only an order row or a trade execution is paired")
    xid = push.exchange_order_id
    if isinstance(reads.bound, NoAnswer):
        return _ask(reads.bound, NeedBound(xid))
    if reads.bound is not None:
        return ToRow(_own(push, reads.bound, step=1))
    if isinstance(reads.named, NoAnswer):
        return _ask(reads.named, NeedNamed(push.order_link_id))
    if reads.named is not None:
        named = _own(push, reads.named, step=2)
        if named.exchange_order_id == xid:  # bound to this very order since step 1 read none
            return ToRow(named)
        if takes_waiting(named):
            return WaitOnRow(named)
    if isinstance(push, Order):
        order = push
    elif isinstance(reads.order, NoAnswer):
        return _ask(reads.order, NeedOrder(xid))
    elif reads.order is None:
        return Undecided(empty_read=True)
    else:
        order = _same_order(push, reads.order)
    if is_stop_claim(order):
        if isinstance(reads.stops, NoAnswer):
            return _ask(reads.stops, NeedStops(order.symbol, order.position_idx))
        record = matching_record(order, _of_key(push, order, reads.stops))
        if record is not None:
            return ToRecordedStop(record, order)
    if isinstance(push, Order):
        return NoIntent("order", xid, push.exchange_placed)
    return NoIntent("execution", push.exec_id, order.exchange_placed)


def takes_waiting(row: OrderRow) -> bool:
    """Whether a push the row's link id names waits for its bind: unbound, unfinished, not held."""
    return row.exchange_order_id is None and row.state in UNFINISHED_STATES and row.state != "held"


def is_stop_claim(order: Order) -> bool:
    """Whether the order claims to be a position's TP/SL, which only a record makes the OMS's."""
    return order.order_kind in _CLAIMS


def matching_record(order: Order, records: Sequence[RecordedStopRow]) -> RecordedStopRow | None:
    """The record `order` matches, the latest by (`created_at`, `id`), or None (Sec.8.8 rule 6,
    Sec.8.3 rule 7): same kind and mode, the order's stated mode agreeing; live, unbound, not
    released, no trail; on the side that closes the record's position; at its trigger price; and
    in Partial mode at its size. The caller passes the records of the order's own position."""
    found = [r for r in records if _matches(order, r)]
    return max(found, key=lambda r: (r.created_at, r.id), default=None)


def _matches(order: Order, r: RecordedStopRow) -> bool:
    side = STOP_SIDES.get(order.order_kind)
    if side is None or (r.kind, r.tpsl_mode) != side:
        return False
    if order.tpsl_mode is not None and order.tpsl_mode != side[1].lower():
        return False
    unclaimed = r.exchange_order_id is None and r.released_at is None
    if r.status not in LIVE_STOP_STATUSES or not unclaimed:
        return False
    if r.trailing_distance is not None or order.side != _CLOSING[r.position_side]:
        return False
    if order.trigger_price is None or order.trigger_price != r.trigger_price:
        return False
    return side[1] == "Full" or (r.size is not None and order.qty == r.size)


def _ask(answer: NoAnswer, need: Need) -> Pairing:  # a read that failed decides nothing
    return need if answer is NoAnswer.NOT_READ else Undecided(empty_read=False)


def _own(push: Order | Execution, row: OrderRow, *, step: Literal[1, 2]) -> OrderRow:
    bound = row.exchange_order_id == push.exchange_order_id  # step 1: the bound id
    named = row.order_link_id == push.order_link_id  # step 2: the order link id
    if row.exchange_account_id != push.account_id or not (bound if step == 1 else named):
        raise PairingRefused(_REFUSED)
    return row


def _same_order(fill: Execution, order: Order) -> Order:
    if order.account_id != fill.account_id or order.exchange_order_id != fill.exchange_order_id:
        raise PairingRefused(_REFUSED)
    return order


def _of_key(
    push: Order | Execution, order: Order, stops: tuple[RecordedStopRow, ...]
) -> tuple[RecordedStopRow, ...]:
    key = (push.account_id, order.symbol, order.position_idx)
    if any((r.exchange_account_id, r.symbol, r.position_idx) != key for r in stops):
        raise PairingRefused(_REFUSED)
    return stops

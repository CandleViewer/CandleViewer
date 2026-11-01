"""The native-stop assertions every rule test that reaches the order path uses (E35-T11 slice 3a;
C-2.6; 24 Sec.8.8 rules 1 and 6; the E35-T11 to T14 plan's native-SL helper).

`assert_entry_carries_native_stop` holds a rule's entry to C-2.6 at every layer it crosses: the
order row it was recorded as, its first persist's recorded stop (`entry_attach`), that stop's
`sl.attached` record and the create the exchange fake was sent. `assert_position_stop_untouched`
holds a position's native stop to the ratchet (24 Sec.8.8 rule 5): neither removed nor loosened.
Each takes plain rows, records and calls, so any rig, in memory or on Postgres, can hand them over.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from candleviewer.exchange.base.fakes import FakeCall
from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.oms.ports import KeyedRecord

#: The record a recorded stop's request writes, keyed by its row (21 Sec.3.3.11 "Audit").
SL_ATTACHED = "sl.attached"
ENTRY_ATTACH = "entry_attach"

type Side = Literal["Buy", "Sell", "buy", "sell"]


class EntryRow(Protocol):
    """An `orders` row as the helper reads it (`NewOrder` or `OrderRow`)."""

    @property
    def id(self) -> UUID: ...
    @property
    def order_link_id(self) -> str: ...
    @property
    def side(self) -> str: ...
    @property
    def reduce_only(self) -> bool: ...
    @property
    def stop_loss(self) -> Decimal | None: ...


class StopRow(Protocol):
    """A `recorded_stops` row as the helper reads it (`NewRecordedStop` or `RecordedStopRow`)."""

    @property
    def id(self) -> UUID: ...
    @property
    def kind(self) -> str: ...
    @property
    def source(self) -> str: ...
    @property
    def order_id(self) -> UUID | None: ...
    @property
    def trigger_price(self) -> Decimal: ...


def _buys(side: str) -> bool:
    if side.lower() not in ("buy", "sell"):
        raise AssertionError(f"no order side: {side!r}")
    return side.lower() == "buy"


def _creates(calls: Iterable[FakeCall]) -> list[PlaceOrderRequest]:
    """Every create the exchange fake was sent: each `place_order` and each `place_batch` item."""
    sent: list[PlaceOrderRequest] = []
    for call in calls:
        if call.method == "place_order" and isinstance(call.request, PlaceOrderRequest):
            sent.append(call.request)
        elif call.method == "place_batch" and isinstance(call.request, tuple):
            sent += [r for r in call.request if isinstance(r, PlaceOrderRequest)]
    return sent


def assert_entry_carries_native_stop(
    order: EntryRow,
    *,
    reference_price: Decimal,
    stops: Iterable[StopRow],
    records: Iterable[object],
    calls: Iterable[FakeCall],
) -> None:
    """C-2.6 for one entry: it is not reduce-only and carries a finite `stop_loss` above zero on
    the protective side of `reference_price` (below a buy's, above a sell's); its first persist
    recorded that stop as the order's `stop_loss` `entry_attach` row, whose `sl.attached` record
    landed keyed by it; and the create the exchange fake was sent under its id carried the same
    stop. Raises `AssertionError` naming the layer that fails."""
    stop = order.stop_loss
    if order.reduce_only:
        raise AssertionError("an entry is not reduce-only")
    if not isinstance(stop, Decimal) or not stop.is_finite() or stop <= 0:
        raise AssertionError("an entry carries a finite stop_loss above zero")
    if not (stop < reference_price if _buys(order.side) else stop > reference_price):
        raise AssertionError("the stop_loss sits on the protective side of the reference price")
    attached = [
        row
        for row in stops
        if (row.kind, row.source, row.order_id) == ("stop_loss", ENTRY_ATTACH, order.id)
    ]
    if [row.trigger_price for row in attached] != [stop]:
        raise AssertionError("the first persist records the entry's stop as its entry_attach row")
    names = {
        record.name
        for record in records
        if isinstance(record, KeyedRecord)
        and (record.action, record.reason) == (SL_ATTACHED, ENTRY_ATTACH)
    }
    if str(attached[0].id) not in names:
        raise AssertionError("the entry_attach row's sl.attached record landed")
    sent = [r for r in _creates(calls) if r.order_link_id == order.order_link_id]
    if not sent or any(r.stop_loss != stop for r in sent):
        raise AssertionError("every create of the entry carried its native stop")


def assert_position_stop_untouched(
    side: Side, *, before: Decimal | None, after: Decimal | None
) -> None:
    """A position's native stop after an action is its stop before it or tighter (24 Sec.8.8 rule
    5): one that was set is never removed, and never moved away from the market (lower for a
    long, higher for a short). Raises `AssertionError` naming which."""
    if before is None:
        return
    if after is None:
        raise AssertionError("the position's native stop was removed")
    if after < before if _buys(side) else after > before:
        raise AssertionError("the position's native stop was loosened")

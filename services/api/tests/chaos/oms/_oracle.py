"""E29-Q04's correctness oracle (#1148, "The oracle is authoritative"; the precedent is
`tests/chaos/ingestion/_oracle.py`): after a scenario, once the runtime has settled and the
account's reconciliation job rests, the book is compared field by field against the venue's truth,
and every difference fails the scenario, listed in one `OracleMismatch`.

**Exchange truth** is what the venue holds, read through its own reads (open orders, history,
executions, positions) and its create log, counted outside the app (`_venue.Venue.creates`).
**The book** is the account's `orders`, `executions` and `positions` rows.

**What it compares.** Each venue order with the row that holds it, by its bound exchange id, else
by its `order_link_id`: the ids, the B1 state against the venue's status through 24 Sec.8.12's
table (written here, never imported from the mapping under test), the quantity and the filled
quantity, which is the sum of the order's executions on both sides, the average fill price, the
price, the trigger, the stop and take-profit, `reduce_only`, the side and `position_idx`. Each
execution by its `exec_id`: the same set on both sides, and each one's quantity, price, fee and
order. Each open position: side, size, average entry and stop, and C-2.6 as the ruling on #1148
(BQ-6) reads it: the venue holds a native stop sized to the position, its own Full-mode stop, or
Partial-mode stop orders whose quantities add up to the position, never more or less. And the
cardinality: no row the venue does not hold but a `rejected` or `killed` one, no venue order
without a row, and one create per `order_link_id` of ours. Money compares as `Decimal`, by value."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID

from candleviewer.domain.order_link import OUR_ID
from candleviewer.exchange.base.models import Execution, Order, Position
from candleviewer.storage.repositories.executions import ExecutionRow
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.positions import PositionRow

#: The B1 state a correct row holds for each venue status (24 Sec.8.12's table): an open order
#: rests `submitted` (`triggered` once its trigger fired) or `partially_filled`; an end is
#: `filled`, or `cancelled` (a deactivated stop and a rejection after the acceptance among them).
LIFECYCLE: Final[Mapping[str, str]] = {
    "new": "submitted", "untriggered": "submitted", "triggered": "triggered",
    "partially_filled": "partially_filled", "filled": "filled", "cancelled": "cancelled",
    "partially_filled_canceled": "cancelled", "deactivated": "cancelled", "rejected": "cancelled",
}  # fmt: skip
#: ...but an `ioc` or `fok` order that ended cancelled is `expired` (the Q4 ruling, 24 Sec.8.12).
_EXPIRING: Final = frozenset({"ioc", "fok"})
_ENDED_CANCELLED: Final = frozenset({"cancelled", "partially_filled_canceled"})
_OPEN: Final = frozenset({"new", "untriggered", "triggered", "partially_filled"})
#: The only rows the venue may not hold: refused, unresolved or killed before any create landed.
UNHELD: Final = frozenset({"rejected", "killed"})


@dataclass(frozen=True, slots=True)
class Diff:
    """One field where the book and the venue disagree."""

    item: str
    field: str
    book: object
    venue: object

    def __str__(self) -> str:
        return f"{self.item}: {self.field} book={self.book!r} venue={self.venue!r}"


class OracleMismatch(AssertionError):
    """The book is not the venue's: every differing field, one per line."""

    def __init__(self, diffs: Sequence[Diff]) -> None:
        self.diffs = tuple(diffs)
        super().__init__("\n".join(map(str, self.diffs)))


@dataclass(frozen=True, slots=True)
class Book:
    orders: tuple[OrderRow, ...]
    fills: tuple[ExecutionRow, ...]
    positions: tuple[PositionRow, ...]


@dataclass(frozen=True, slots=True)
class Truth:
    orders: tuple[Order, ...]
    fills: tuple[Execution, ...]
    positions: tuple[Position, ...]
    creates: Mapping[str, int]


class Checked(Protocol):
    """What the oracle checks: a world it settles, then reads on both sides."""

    checked: bool

    async def settle(self) -> None: ...

    async def book(self) -> Book: ...

    async def truth(self) -> Truth: ...


async def check(world: Checked) -> None:
    """The scenario's end (module docstring): settled, compared, and `OracleMismatch` on any
    difference. The world is marked checked first, so a scenario that expects the raise counts."""
    world.checked = True
    await world.settle()
    diffs = compare(await world.book(), await world.truth())
    if diffs:
        raise OracleMismatch(diffs)


def compare(book: Book, truth: Truth) -> list[Diff]:
    return [*_orders(book, truth), *_fills(book, truth), *_positions(book, truth)]


def expected(order: Order, *, untracked: bool = False) -> str:
    """The B1 state 24 Sec.8.12 gives a row of an order in this venue state; an `untracked` row
    (an adoption, S9) stays `untracked` while its order is open (B1 version 8)."""
    if untracked and order.state in _OPEN:
        return "untracked"
    if order.state in _ENDED_CANCELLED and order.time_in_force in _EXPIRING:
        return "expired"
    return LIFECYCLE.get(order.state, f"no state for {order.state!r}")


def _orders(book: Book, truth: Truth) -> Iterator[Diff]:
    held = {o.exchange_order_id: o for o in truth.orders}
    by_link = {o.order_link_id: o for o in truth.orders}
    venue_fills = _summed((f.exchange_order_id, f.qty) for f in truth.fills)
    xids: dict[UUID | None, str | None] = {r.id: r.exchange_order_id for r in book.orders}
    book_fills = _summed((xids.get(f.order_id), f.exec_qty) for f in book.fills)
    matched: set[str] = set()
    for row in book.orders:
        item = f"order {row.order_link_id}"
        order = held.get(row.exchange_order_id or "") or by_link.get(row.order_link_id)
        if order is None:
            if row.lifecycle_state not in UNHELD:
                yield Diff(item, "venue order", row.lifecycle_state, None)
            continue
        matched.add(order.exchange_order_id)
        xid = order.exchange_order_id
        yield from _differing(item, (
            ("order_link_id", row.order_link_id, order.order_link_id),
            ("exchange_order_id", row.exchange_order_id, xid),
            ("lifecycle_state", row.lifecycle_state,
             expected(order, untracked=row.lifecycle_state == "untracked")),
            ("qty", row.qty, order.qty),
            ("filled_qty", row.cum_exec_qty, order.filled_qty),
            ("executions", book_fills.get(xid, Decimal(0)), venue_fills.get(xid, Decimal(0))),
            ("avg_fill_price", row.avg_price, order.avg_fill_price),
            ("price", row.price, order.price),
            ("trigger_price", row.trigger_price, order.trigger_price),
            ("stop_loss", row.stop_loss, order.stop_loss),
            ("take_profit", row.take_profit, order.take_profit),
            ("reduce_only", row.reduce_only, order.reduce_only),
            ("side", row.side.lower(), order.side),
            ("position_idx", row.position_idx, order.position_idx),
        ))  # fmt: skip
        if order.filled_qty != (executed := venue_fills.get(xid, Decimal(0))):
            yield Diff(item, "venue's own fills", executed, order.filled_qty)  # a harness defect
    for order in truth.orders:
        if order.exchange_order_id not in matched:
            yield Diff(f"order {order.order_link_id}", "row", None, order.state)
    ours = {o.order_link_id for o in truth.orders if OUR_ID.fullmatch(o.order_link_id)}
    for link in sorted(ours | set(truth.creates)):
        if truth.creates.get(link, 0) != 1:
            yield Diff(f"order {link}", "creates", None, truth.creates.get(link, 0))


def _fills(book: Book, truth: Truth) -> Iterator[Diff]:
    xids: dict[UUID | None, str | None] = {r.id: r.exchange_order_id for r in book.orders}
    mine = {f.exec_id: f for f in book.fills}
    theirs = {f.exec_id: f for f in truth.fills}
    for exec_id in sorted(mine.keys() | theirs.keys()):
        row, fill = mine.get(exec_id), theirs.get(exec_id)
        if row is None or fill is None:
            yield Diff(f"execution {exec_id}", "exec_id", row is not None, fill is not None)
            continue
        yield from _differing(f"execution {exec_id}", (
            ("qty", row.exec_qty, fill.qty), ("price", row.exec_price, fill.price),
            ("fee", row.exec_fee, fill.fee),
            ("exchange_order_id", xids.get(row.order_id), fill.exchange_order_id),
        ))  # fmt: skip


def _positions(book: Book, truth: Truth) -> Iterator[Diff]:
    mine = {(p.symbol, p.position_idx): p for p in book.positions if p.size > 0}
    theirs = {(p.symbol, p.position_idx): p for p in truth.positions if p.qty > 0}
    partial = [o for o in truth.orders if o.order_kind == "partial_stop_loss" and o.state in _OPEN]
    for key in sorted(mine.keys() | theirs.keys()):
        row, held, item = mine.get(key), theirs.get(key), f"position {key[0]}/{key[1]}"
        if row is None or held is None:
            yield Diff(item, "open", row is not None, held is not None)
            continue
        sized = [o.qty for o in partial if (o.symbol, o.position_idx) == key]
        if held.stop_loss is None and not sized:  # C-2.6: no native stop at the venue
            yield Diff(item, "native stop", row.stop_loss, None)
        if sized and sum(sized) != held.qty:  # a Partial-mode stop sized to another position
            yield Diff(item, "stop size", row.size, sum(sized))
        yield from _differing(item, (
            ("side", (row.side or "").lower(), held.side), ("size", row.size, held.qty),
            ("avg_entry_price", row.avg_price, held.avg_entry_price),
            ("stop_loss", row.stop_loss, held.stop_loss),
        ))  # fmt: skip


def _differing(item: str, pairs: Sequence[tuple[str, Any, Any]]) -> Iterator[Diff]:
    return (Diff(item, name, mine, theirs) for name, mine, theirs in pairs if mine != theirs)


def _summed(pairs: Iterable[tuple[str | None, Decimal]]) -> dict[str | None, Decimal]:
    totals: dict[str | None, Decimal] = {}
    for key, qty in pairs:
        totals[key] = totals.get(key, Decimal(0)) + qty
    return totals

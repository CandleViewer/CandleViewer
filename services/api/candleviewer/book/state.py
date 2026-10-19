"""`BookState` - the L2 book for one `(env, symbol, depth)` (E08-S05).

Hot path (catalogue §1.2 / INV-B14-a): plain code, never a statechart.
Levels are parallel arrays (ticks ascending, qty, price) kept sorted with
`bisect`, the shape measured by E08-K01 and portable to a native extension.
Bids are read from the end of their arrays (descending), asks from the start.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from decimal import Decimal

from candleviewer.book.errors import BookInvariantError, BookPayloadError
from candleviewer.exchange.base.models import BookLevel


class _Side:
    """One side, in one price order: its prices rise strictly with its ticks (#3806).

    Each write checks only its own level, against its slot and the slot's neighbours (O(1) past
    the bisect, no scan): found ticks must hold the level's price; an insert, or a delete that
    finds nothing, must fall strictly between the neighbours' prices. Else the level is off the
    book's grid: `BookInvariantError("grid")`, before any write. By induction levels == distinct
    prices always holds, and a held price is only ever reached at its own ticks.
    """

    __slots__ = ("price", "qty", "ticks")

    def __init__(self) -> None:
        self.ticks: list[int] = []
        self.qty: list[Decimal] = []
        self.price: list[Decimal] = []

    def upsert(self, lvl: BookLevel) -> None:
        ticks, price = self.ticks, self.price
        i = bisect_left(ticks, lvl.price_ticks)
        if i < len(ticks) and ticks[i] == lvl.price_ticks:
            if price[i] != lvl.price:
                raise BookInvariantError("grid")
            self.qty[i] = lvl.qty
        elif (i and price[i - 1] >= lvl.price) or (i < len(ticks) and price[i] <= lvl.price):
            raise BookInvariantError("grid")
        else:
            ticks.insert(i, lvl.price_ticks)
            self.qty.insert(i, lvl.qty)
            price.insert(i, lvl.price)

    def delete(self, lvl: BookLevel) -> None:
        ticks, price = self.ticks, self.price
        i = bisect_left(ticks, lvl.price_ticks)
        if i < len(ticks) and ticks[i] == lvl.price_ticks:
            if price[i] != lvl.price:
                raise BookInvariantError("grid")
            del ticks[i], self.qty[i], price[i]
        elif (i and price[i - 1] >= lvl.price) or (i < len(ticks) and price[i] <= lvl.price):
            raise BookInvariantError("grid")  # a no-op could leave a deleted level held

    def __len__(self) -> int:
        return len(self.ticks)


def _validate(levels: Sequence[BookLevel], *, allow_zero: bool, bound: int) -> None:
    """Security note: reject garbled payloads before any mutation."""
    if len(levels) > bound:
        raise BookPayloadError(f"level count {len(levels)} exceeds tier bound {bound}")
    for lvl in levels:
        if not lvl.qty.is_finite() or not lvl.price.is_finite():
            raise BookPayloadError("non-finite price/qty")
        if lvl.qty < 0 or (lvl.qty == 0 and not allow_zero):
            raise BookPayloadError("negative or zero resting size")


class BookState:
    """Two sorted price->size sides with O(log n) lookup."""

    __slots__ = ("_asks", "_bids", "depth")

    def __init__(self, depth: int) -> None:
        self.depth = depth
        self._bids = _Side()
        self._asks = _Side()

    @classmethod
    def from_levels(
        cls, depth: int, bids: Sequence[BookLevel], asks: Sequence[BookLevel]
    ) -> BookState:
        _validate(bids, allow_zero=False, bound=depth)
        _validate(asks, allow_zero=False, bound=depth)
        book = cls(depth)
        for lvl in bids:
            book._bids.upsert(lvl)
        for lvl in asks:
            book._asks.upsert(lvl)
        book.check()
        return book

    def apply(self, bids: Sequence[BookLevel], asks: Sequence[BookLevel]) -> None:
        """Apply one delta (qty == 0 deletes). Validates first, then checks
        the book invariants; a violation raises and the caller resyncs."""
        bound = 2 * self.depth
        _validate(bids, allow_zero=True, bound=bound)
        _validate(asks, allow_zero=True, bound=bound)
        for side, levels in ((self._bids, bids), (self._asks, asks)):
            for lvl in levels:
                if lvl.qty == 0:
                    side.delete(lvl)
                else:
                    side.upsert(lvl)
        self.check()

    def check(self) -> None:
        """No crossed book, by price so that it holds on any grid (with each side's order, no
        price is then on both sides, #3806); size bound per tier (sorting is structural)."""
        bids, asks = self._bids.price, self._asks.price
        if bids and asks and bids[-1] >= asks[0]:
            raise BookInvariantError("crossed")
        if len(self._bids) > 2 * self.depth or len(self._asks) > 2 * self.depth:
            raise BookInvariantError("unbounded")

    def top(self, n: int) -> tuple[tuple[BookLevel, ...], tuple[BookLevel, ...]]:
        b, a = self._bids, self._asks
        nb, na = min(n, len(b)), min(n, len(a))
        bids = tuple(
            BookLevel(price=b.price[i], qty=b.qty[i], price_ticks=b.ticks[i])
            for i in range(len(b) - 1, len(b) - 1 - nb, -1)
        )
        asks = tuple(
            BookLevel(price=a.price[i], qty=a.qty[i], price_ticks=a.ticks[i]) for i in range(na)
        )
        return bids, asks

    def snapshot(self) -> tuple[tuple[BookLevel, ...], tuple[BookLevel, ...]]:
        return self.top(max(len(self._bids), len(self._asks)))

    def as_dicts(self) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
        return dict(zip(self._bids.ticks, self._bids.qty, strict=True)), dict(
            zip(self._asks.ticks, self._asks.qty, strict=True)
        )

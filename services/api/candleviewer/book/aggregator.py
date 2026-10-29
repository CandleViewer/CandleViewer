"""`DepthAggregator` (E21-T01, 24 §2.2, BQ-5): level-aggregated views of the live `BookState`.

A bucket is keyed by an integer `price_ticks` multiple of `bucket_ticks`: bids round **down** to
their bucket and asks **up**, so an aggregated bid is never above and an aggregated ask never
below a raw level, and a book that is not crossed never aggregates into a crossed one. A bucket's
size is the `Decimal` sum of its raw levels, and its price is its key times the tick size: no
float anywhere (C5). `bucket_ticks = 1` returns the raw levels. At most `depth` buckets per side,
counted after bucketing, bids descending then asks ascending.

Pure and synchronous: it reads the book it is given and holds nothing else (C-2.20).
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Final

from candleviewer.book.state import BookState
from candleviewer.exchange.base.models import BookLevel

#: The bucket widths the ladder offers (24 §2.2).
BUCKET_TICKS: Final = frozenset({1, 5, 25})

Side = tuple[BookLevel, ...]


class DepthAggregator:
    """Aggregated views of one live book on one tick grid."""

    __slots__ = ("_book", "_tick")

    def __init__(self, book: BookState, tick_size: Decimal) -> None:
        if not tick_size.is_finite() or tick_size <= 0:
            raise ValueError("tick_size must be a positive finite Decimal")
        self._book, self._tick = book, tick_size

    def aggregate(self, bucket_ticks: int, depth: int) -> tuple[Side, Side]:
        """The best `depth` buckets of `bucket_ticks` ticks per side (see the module docstring)."""
        if bucket_ticks not in BUCKET_TICKS:
            raise ValueError(f"bucket_ticks must be one of {sorted(BUCKET_TICKS)}")
        if depth < 1:
            raise ValueError("depth must be positive")
        if bucket_ticks == 1:
            return self._book.top(depth)
        bids = self._side(self._book.walk(bids=True), bucket_ticks, depth, ceil=False)
        asks = self._side(self._book.walk(bids=False), bucket_ticks, depth, ceil=True)
        return bids, asks

    def _side(
        self, levels: Iterator[tuple[int, Decimal]], width: int, depth: int, *, ceil: bool
    ) -> Side:
        """Walks best-first, so each bucket's levels are adjacent and a bucket closes when the
        next level falls in another one: the walk stops at the first level past `depth`."""
        out: list[BookLevel] = []
        key: int | None = None
        size = Decimal(0)
        for ticks, qty in levels:
            k = -(-ticks // width) * width if ceil else ticks // width * width
            if k != key:
                if key is not None:
                    out.append(self._level(key, size))
                    if len(out) == depth:
                        return tuple(out)
                key, size = k, Decimal(0)
            size += qty
        if key is not None:
            out.append(self._level(key, size))
        return tuple(out)

    def _level(self, key: int, size: Decimal) -> BookLevel:
        return BookLevel(price=key * self._tick, qty=size, price_ticks=key)


__all__ = ["BUCKET_TICKS", "DepthAggregator"]

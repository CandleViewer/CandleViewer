"""E21-T01 (24 §2.8, BQ-1): `BestQuoteEvent` from `top(1)` of the live tier, only on change."""

from __future__ import annotations

from decimal import Decimal

from candleviewer.book.quote import QuoteTracker
from candleviewer.book.state import BookState

from ._builders import delta, lvl, snap


def test_quote_is_the_top_of_the_book_with_spread_and_mid() -> None:
    book = BookState.from_levels(200, [lvl(999, 2), lvl(998, 5)], [lvl(1001, 3)])
    quote = QuoteTracker().update(book, snap(7, [], []))
    assert quote is not None and quote.symbol == "BTCUSDT"
    assert (quote.bid, quote.bid_qty, quote.ask, quote.ask_qty) == (
        Decimal("99.9"), Decimal(2), Decimal("100.1"), Decimal(3),
    )  # fmt: skip
    assert quote.spread_ticks == 2 and quote.mid == Decimal("100.0")
    assert quote.spread_bps == Decimal("0.2") / Decimal("100.0") * 10_000
    assert (quote.ts_event, quote.ts_ingest, quote.source) == (7, 7, "live")


def test_quote_is_published_only_when_a_field_changes() -> None:
    tracker = QuoteTracker()
    book = BookState.from_levels(200, [lvl(999, 2), lvl(990, 1)], [lvl(1001, 3)])
    assert tracker.update(book, snap(1, [], [])) is not None
    book.apply([lvl(990, 4)], [])  # below the top: no quote
    assert tracker.update(book, delta(2, 1)) is None
    book.apply([lvl(999, 6)], [])  # the best bid's size
    changed = tracker.update(book, delta(3, 2))
    assert changed is not None and changed.bid_qty == Decimal(6)
    tracker.forget("BTCUSDT")  # left LIVE: the next live top is a change again
    assert tracker.update(book, delta(4, 3)) is not None


def test_quote_needs_both_sides() -> None:
    tracker = QuoteTracker()
    book = BookState.from_levels(200, [lvl(999, 2)], [])
    assert tracker.update(book, snap(1, [], [])) is None

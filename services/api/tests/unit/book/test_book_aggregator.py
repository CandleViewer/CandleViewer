"""E21-T01 (BQ-5, 24 §2.2): `DepthAggregator` buckets the live book on integer ticks: bids floor,
asks ceil, `Decimal` sums, `depth` counted after bucketing. Unit cases at 1 / 5 / 25 ticks and
hypothesis properties of the invariants (C-13.2)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.book.aggregator import BUCKET_TICKS, DepthAggregator
from candleviewer.book.state import BookState
from candleviewer.exchange.base.models import BookLevel

from ._builders import lvl

TICK = Decimal("0.1")


def _book(bids: dict[int, str], asks: dict[int, str]) -> BookState:
    return BookState.from_levels(
        200, [lvl(t, q) for t, q in bids.items()], [lvl(t, q) for t, q in asks.items()]
    )


def _view(levels: tuple[BookLevel, ...]) -> list[tuple[int, Decimal]]:
    return [(lv.price_ticks, lv.qty) for lv in levels]


def test_aggregate_one_tick_returns_the_raw_levels() -> None:
    book = _book({99: "1", 98: "2"}, {101: "3", 103: "4"})
    assert DepthAggregator(book, TICK).aggregate(1, 50) == book.top(50)


def test_aggregate_five_ticks_floors_bids_and_ceils_asks_with_decimal_sums() -> None:
    book = _book({104: "0.1", 101: "0.2", 100: "1", 99: "2"}, {106: "0.3", 110: "0.4", 111: "5"})
    bids, asks = DepthAggregator(book, TICK).aggregate(5, 50)
    assert _view(bids) == [(100, Decimal("1.3")), (95, Decimal("2"))]
    assert _view(asks) == [(110, Decimal("0.7")), (115, Decimal("5"))]
    assert [lv.price for lv in (*bids, *asks)] == [
        Decimal("10.0"), Decimal("9.5"), Decimal("11.0"), Decimal("11.5"),
    ]  # fmt: skip


def test_aggregate_twenty_five_ticks_counts_depth_after_bucketing() -> None:
    bids = {1000 - i: "1" for i in range(100)}  # 100 raw levels -> 4 or 5 buckets of 25
    asks = {1001 + i: "1" for i in range(100)}
    got_bids, got_asks = DepthAggregator(_book(bids, asks), TICK).aggregate(25, 3)
    assert _view(got_bids) == [(1000, Decimal(1)), (975, Decimal(25)), (950, Decimal(25))]
    assert _view(got_asks) == [(1025, Decimal(25)), (1050, Decimal(25)), (1075, Decimal(25))]


def test_aggregate_refuses_an_unoffered_bucket_or_depth_and_a_bad_tick() -> None:
    agg = DepthAggregator(_book({99: "1"}, {101: "1"}), TICK)
    with pytest.raises(ValueError, match="bucket_ticks"):
        agg.aggregate(2, 10)
    with pytest.raises(ValueError, match="depth"):
        agg.aggregate(5, 0)
    with pytest.raises(ValueError, match="tick_size"):
        DepthAggregator(BookState(200), Decimal(0))


def test_aggregate_of_an_empty_side_is_empty() -> None:
    bids, asks = DepthAggregator(_book({99: "1"}, {}), TICK).aggregate(5, 10)
    assert _view(bids) == [(95, Decimal(1))] and asks == ()


_SIZES = st.decimals(min_value=Decimal("0.001"), max_value=Decimal(1000), places=3)


@st.composite
def _books(draw: st.DrawFn) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    mid = draw(st.integers(min_value=100, max_value=100_000))
    spread = draw(st.integers(min_value=1, max_value=60))
    bid_off = draw(st.sets(st.integers(min_value=0, max_value=300), min_size=0, max_size=60))
    ask_off = draw(st.sets(st.integers(min_value=0, max_value=300), min_size=0, max_size=60))
    bids = {mid - o: draw(_SIZES) for o in bid_off}
    asks = {mid + spread + o: draw(_SIZES) for o in ask_off}
    return bids, asks


@given(book=_books(), width=st.sampled_from(sorted(BUCKET_TICKS)), depth=st.integers(1, 80))
@settings(max_examples=200, deadline=None)
def test_aggregate_properties_hold_for_any_uncrossed_book(
    book: tuple[dict[int, Decimal], dict[int, Decimal]], width: int, depth: int
) -> None:
    """Buckets are integer multiples of the width; a bid bucket is never above its raw levels nor
    an ask bucket below; sizes are the exact `Decimal` sums of an independent model; at most
    `depth` buckets per side, best first; an uncrossed book never aggregates crossed."""
    raw_b, raw_a = book
    state = BookState.from_levels(
        200,
        [BookLevel(price=t * TICK, qty=q, price_ticks=t) for t, q in raw_b.items()],
        [BookLevel(price=t * TICK, qty=q, price_ticks=t) for t, q in raw_a.items()],
    )
    bids, asks = DepthAggregator(state, TICK).aggregate(width, depth)
    model_b: dict[int, Decimal] = defaultdict(Decimal)
    model_a: dict[int, Decimal] = defaultdict(Decimal)
    for t, q in raw_b.items():
        model_b[t // width * width] += q
    for t, q in raw_a.items():
        model_a[-(-t // width) * width] += q
    assert _view(bids) == sorted(model_b.items(), reverse=True)[:depth]
    assert _view(asks) == sorted(model_a.items())[:depth]
    for lv in (*bids, *asks):
        assert lv.price_ticks % width == 0 and lv.price == lv.price_ticks * TICK and lv.qty > 0
    if bids and asks:
        assert bids[0].price_ticks < asks[0].price_ticks

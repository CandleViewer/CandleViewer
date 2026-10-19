"""#3806 (E08-Q06 F1): a book holds one grid, so one level per price. A level whose ticks or price
contradict the book raises `BookInvariantError("grid")` before it is written; the stream half (a
tick-size change in the catalogue) is `tests/unit/ingestion/test_book_grid_resync.py`."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.book.errors import BookInvariantError
from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.book.resync import BookEngine
from candleviewer.book.state import BookState
from candleviewer.exchange.base.models import BookDelta, BookLevel

from ._builders import delta, lvl, snap

STEP = Decimal("0.05")  # the grids below are STEP x 1, 2 (the `lvl` builder's 0.1) or 4
Side = dict[Decimal, tuple[int, Decimal]]  # the model of one side: price -> (ticks, qty)


def at(ticks: int, price: str, qty: int | str = 1) -> BookLevel:  # ticks and price apart
    return BookLevel(price=Decimal(price), qty=Decimal(qty), price_ticks=ticks)


def _book() -> BookState:
    return BookState.from_levels(200, [lvl(98, 1), lvl(99, 2)], [lvl(101, 3)])


def _raises_grid(book: BookState, bids: Sequence[BookLevel]) -> None:
    before = book.snapshot()
    with pytest.raises(BookInvariantError) as ei:
        book.apply(bids, [])
    assert ei.value.kind == "grid"
    assert book.snapshot() == before  # the level was refused before it was written


def test_book_state_update_at_held_ticks_with_another_price_raises_grid() -> None:
    _raises_grid(_book(), [at(99, "19.8", 5)])  # 99 ticks of 0.2; the book holds 9.9 there


def test_book_state_insert_of_a_held_price_at_other_ticks_raises_grid() -> None:
    _raises_grid(_book(), [at(49, "9.8", 5)])  # 9.8 is held at 98 ticks: a second 9.8 level


@pytest.mark.parametrize("level", [at(11, "1.0"), at(11, "1.2")], ids=["left", "right"])
def test_book_state_insert_at_a_neighbours_price_raises_grid(level: BookLevel) -> None:
    _raises_grid(BookState.from_levels(200, [at(10, "1.0"), at(12, "1.2")], []), [level])


def test_book_state_delete_at_held_ticks_with_another_price_raises_grid() -> None:
    _raises_grid(_book(), [at(99, "19.8", 0)])  # never deletes the 9.9 held at 99 ticks


@pytest.mark.parametrize("level", [at(49, "9.8", 0), at(198, "9.9", 0)], ids=["below", "above"])
def test_book_state_delete_of_a_held_price_at_other_ticks_raises_grid(level: BookLevel) -> None:
    _raises_grid(_book(), [level])  # never a silent no-op that keeps the held level


def test_book_state_snapshot_with_one_price_at_two_ticks_is_refused() -> None:
    with pytest.raises(BookInvariantError) as ei:
        BookState.from_levels(200, [lvl(98, 1), at(49, "9.8")], [lvl(101, 3)])
    assert ei.value.kind == "grid"


def test_book_state_crossed_compares_prices_so_a_price_on_both_sides_is_crossed() -> None:
    book = BookState.from_levels(200, [lvl(99, 2)], [])
    with pytest.raises(BookInvariantError) as ei:
        book.apply([], [at(198, "9.9")])  # 9.9 on 0.05: 198 ticks, above the bid's 99
    assert ei.value.kind == "crossed"


async def test_engine_resyncs_with_reason_grid_on_a_mixed_grid_delta() -> None:
    """One frame on two grids, which the stream's check (one tick size per frame) cannot see."""
    out: list[object] = []

    async def publish(ev: object) -> None:
        out.append(ev)

    eng = BookEngine(symbol="BTCUSDT", depth=200, publish=publish,
                     resubscribe=lambda: asyncio.sleep(0), now_us=lambda: 0)  # fmt: skip
    await eng.start()
    await eng.on_event(snap(10, [lvl(98, 1), lvl(99, 2)], [lvl(101, 3)]))
    await eng.on_event(delta(11, 10, [lvl(99, 5), at(49, "9.8", 4)]))  # on 0.1, then 9.8 on 0.2
    status = out[-1]
    assert isinstance(status, BookStatus) and status.state is BookPhase.DESYNCED
    assert status.reason == "grid" and eng.phase is BookPhase.SNAPSHOT_PENDING
    assert eng.book is None and eng.live_snapshot() is None and eng.last_u == 10
    assert not any(isinstance(o, BookDelta) for o in out)  # nothing of the delta was served


@st.composite
def _level(draw: st.DrawFn, mults: tuple[int, ...]) -> tuple[bool, BookLevel]:
    """(is_bid, level) on one of the grids STEP x m; bids sit at or below 3.0, asks above it."""
    bid, m = draw(st.booleans()), draw(st.sampled_from(mults))
    k = draw(st.integers(1, 60 // m) if bid else st.integers(60 // m + 1, 120 // m))
    return bid, BookLevel(price=k * m * STEP, qty=Decimal(draw(st.integers(0, 3))), price_ticks=k)


def _contradicts(model: dict[bool, Side], levels: list[tuple[bool, BookLevel]]) -> bool:
    """Apply `levels` to `model` by price, in `BookState.apply`'s order (bids first); True once a
    level contradicts it: held ticks at another price, or a held price at other ticks."""
    for side in (True, False):
        held = model[side]
        for lv in (lv for bid, lv in levels if bid == side):
            at_ticks = next((p for p, (t, _) in held.items() if t == lv.price_ticks), lv.price)
            if at_ticks != lv.price or held.get(lv.price, (lv.price_ticks,))[0] != lv.price_ticks:
                return True
            if lv.qty == 0:
                held.pop(lv.price, None)
            else:
                held[lv.price] = (lv.price_ticks, lv.qty)
    return False


@pytest.mark.parametrize("mults", [(2,), (1, 2, 4)], ids=["one-grid", "three-grids"])
@settings(max_examples=300, deadline=None, derandomize=True, database=None)
@given(data=st.data())
def test_book_state_keeps_one_level_per_price_or_raises_grid(
    mults: tuple[int, ...], data: st.DataObject
) -> None:
    """Gherkin 2: after every applied delta the book is right by price, in price order, with
    levels == distinct prices; a level that contradicts it raises `grid` (never on one grid)."""
    book, model = BookState(1000), dict[bool, Side]({True: {}, False: {}})
    for d in data.draw(st.lists(st.lists(_level(mults), max_size=5), max_size=40)):
        contradicts = _contradicts(model, d)
        try:
            book.apply([lv for b, lv in d if b], [lv for b, lv in d if not b])
        except BookInvariantError as exc:  # the engine drops the book and resyncs
            assert exc.kind == "grid" and len(mults) > 1
            return
        assert not contradicts  # a contradicting level is never written
        bids, asks = book.snapshot()
        for side, levels in ((True, bids), (False, asks)):
            assert {lv.price: (lv.price_ticks, lv.qty) for lv in levels} == model[side]
        assert all(x.price > y.price for x, y in pairwise(bids))
        assert all(x.price < y.price for x, y in pairwise(asks))
        prices = [lv.price for lv in (*bids, *asks)]
        assert len(prices) == len(set(prices))  # levels == distinct prices

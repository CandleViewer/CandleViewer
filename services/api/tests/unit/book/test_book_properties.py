"""E21-T01 test plan, "Property (hypothesis)" (03-testing-strategy.md, Book engine): the engine's
invariants over arbitrary delta sequences, no network, no clock."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine
from candleviewer.exchange.base.models import BookLevel

from ._builders import delta, lvl, snap
from .test_book_ws_topic import World, sub, top

_QTY = st.integers(min_value=0, max_value=50)  # 0 deletes
_BID = st.integers(min_value=900, max_value=999)
_ASK = st.integers(min_value=1001, max_value=1100)


@st.composite
def _deltas(draw: st.DrawFn) -> list[tuple[list[BookLevel], list[BookLevel]]]:
    n = draw(st.integers(min_value=1, max_value=30))
    out = []
    for _ in range(n):
        bids = [lvl(t, q) for t, q in draw(st.dictionaries(_BID, _QTY, max_size=6)).items()]
        asks = [lvl(t, q) for t, q in draw(st.dictionaries(_ASK, _QTY, max_size=6)).items()]
        out.append((bids, asks))
    return out


def _engine() -> tuple[BookEngine, list[object]]:
    out: list[object] = []

    async def publish(ev: object) -> None:
        out.append(ev)

    async def resub() -> None:
        return None

    return BookEngine(
        symbol="BTCUSDT", depth=200, publish=publish, resubscribe=resub, now_us=lambda: 0
    ), out


async def _replay(levels: list[tuple[list[BookLevel], list[BookLevel]]]) -> BookEngine:
    eng, _ = _engine()
    await eng.start()
    await eng.on_event(snap(10, [lvl(999, 1), lvl(950, 2)], [lvl(1001, 1), lvl(1050, 2)]))
    u = 10
    for bids, asks in levels:
        await eng.on_event(delta(u + 1, u, bids, asks))
        u += 1
    return eng


@given(seq=_deltas())
@settings(max_examples=100, deadline=None)
def test_property_book_never_holds_a_negative_or_zero_size(
    seq: list[tuple[list[BookLevel], list[BookLevel]]],
) -> None:
    eng = asyncio.run(_replay(seq))
    assert eng.phase is BookPhase.LIVE  # bids and asks never meet in this space
    assert eng.book is not None
    bids, asks = eng.book.snapshot()
    assert all(lv.qty > 0 for lv in (*bids, *asks))


@given(seq=_deltas())
@settings(max_examples=50, deadline=None)
def test_property_replaying_the_same_deltas_from_the_same_snapshot_is_deterministic(
    seq: list[tuple[list[BookLevel], list[BookLevel]]],
) -> None:
    a, b = asyncio.run(_replay(seq)), asyncio.run(_replay(seq))
    assert a.book is not None and b.book is not None
    assert a.book.as_dicts() == b.book.as_dicts() and a.last_u == b.last_u


@given(seq=_deltas())
@settings(max_examples=50, deadline=None)
def test_property_a_snapshot_fully_resets_the_state(
    seq: list[tuple[list[BookLevel], list[BookLevel]]],
) -> None:
    async def run() -> BookEngine:
        eng = await _replay(seq)
        await eng.invalidate("reconnect")  # the venue re-sends a snapshot after a reconnect
        await eng.on_event(snap(500, [lvl(990, 3)], [lvl(1010, 4)]))
        return eng

    eng = asyncio.run(run())
    assert eng.book is not None and eng.last_u == 500
    assert eng.book.as_dicts() == ({990: Decimal(3)}, {1010: Decimal(4)})


@given(seq=_deltas(), back=st.integers(min_value=0, max_value=40))
@settings(max_examples=50, deadline=None)
def test_property_a_stale_seq_is_a_no_op_or_a_resync(
    seq: list[tuple[list[BookLevel], list[BookLevel]]], back: int
) -> None:
    async def run() -> tuple[BookEngine, dict[int, Decimal], int]:
        eng = await _replay(seq)
        assert eng.book is not None
        before, resyncs = eng.book.as_dicts()[0], eng.resync_count
        stale_u = max(1, eng.last_u - back)
        await eng.on_event(delta(stale_u, stale_u - 1, [lvl(999, 42)]))
        return eng, before, resyncs

    eng, before, resyncs = asyncio.run(run())
    resynced = eng.resync_count == resyncs + 1 and eng.book is None
    untouched = eng.book is not None and eng.book.as_dicts()[0] == before
    assert resynced or untouched


@given(
    dup=st.lists(st.integers(min_value=900, max_value=1100), min_size=1, max_size=8),
    garbage=st.sampled_from(["-1", "NaN", "Infinity"]),
)
@settings(max_examples=50, deadline=None)
def test_property_malformed_or_duplicate_deletes_never_crash(dup: list[int], garbage: str) -> None:
    async def run() -> BookEngine:
        eng = await _replay([])
        bids = [lvl(t, 0) for t in dup if t < 1000] * 2  # duplicate deletes, of absent levels too
        asks = [lvl(t, 0) for t in dup if t > 1000] * 2
        await eng.on_event(delta(11, 10, bids, asks))
        if eng.phase is BookPhase.LIVE:
            bad = BookLevel.model_construct(
                price=Decimal(garbage), qty=Decimal(garbage), price_ticks=1
            )
            await eng.on_event(delta(12, 11).model_copy(update={"bids": (bad,)}))
        return eng

    eng = asyncio.run(run())
    assert eng.phase in {BookPhase.LIVE, BookPhase.SNAPSHOT_PENDING}
    if eng.book is not None:
        bids, asks = eng.book.snapshot()
        assert all(lv.qty > 0 for lv in (*bids, *asks))


@given(
    seq=_deltas(),
    depth=st.sampled_from([1, 50, 200]),
    steps=st.lists(st.sampled_from([0.0, 0.01, 0.2]), min_size=30, max_size=30),
)
@settings(max_examples=60, deadline=None)
def test_property_replaying_a_windows_d_frames_over_its_snapshot_is_the_live_top(
    seq: list[tuple[list[BookLevel], list[BookLevel]]], depth: int, steps: list[float]
) -> None:
    """S4: whatever the cadence, applying every `d` a window sent to the snapshot it served gives
    exactly `book.top(served)`: no stale level is left behind and none is missing."""

    async def run() -> tuple[dict[str, dict[Decimal, Decimal]], dict[str, dict[Decimal, Decimal]]]:
        w = World()
        eng = await w.engine()
        await w.feed(eng, snap(10, [lvl(999, 1), lvl(950, 2)], [lvl(1001, 1), lvl(1050, 2)]))
        held = w.attach(sub(depth))
        u = 10
        for (bids, asks), step in zip(seq, steps, strict=False):
            await w.feed(eng, delta(u + 1, u, bids, asks))
            u += 1
            w.clock.now += step
            w.topic.tick()
        w.clock.now += 1
        w.topic.tick()
        return held.held, top(eng, depth)

    held, live = asyncio.run(run())
    assert held == live

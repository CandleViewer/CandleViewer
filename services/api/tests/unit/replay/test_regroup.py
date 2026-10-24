"""`RegroupedStream` (E26-T03, 24 Sec.13.7): the recorder's one row per changed level becomes one
event per book update before the clock, so a clock step is one update. Gap markers and every other
event pass through as they are; an update is delivered whole or not at all."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.replay import (
    RegroupedStream,
    ReplayClock,
    ReplayEventRefused,
    ReplayGap,
    ReplayItem,
    ReplaySourceUnavailable,
)
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import (
    RecordedBookDelta,
    RecordedBookUpdate,
    RecordedEvent,
)
from tests.unit.replay._events import SECOND, SYM, T0, Harness, request, snapshot, trade
from tests.unit.replay._playback import ListStream, RecordingObserver, RecordingSink
from tests.unit.replay._time import FakeTime

DELTAS, SNAPSHOTS, TRADES = (
    StreamKind.ORDERBOOK_DELTA,
    StreamKind.ORDERBOOK_SNAPSHOT,
    StreamKind.TRADES,
)


def row(
    offset_us: int,
    update_id: int,
    side: str,
    price: str,
    size: str = "1",
    *,
    cross_seq: int | None = None,
    prev_update_id: int | None = None,
    ts_match: int | None = None,
    symbol: str = SYM,
    depth: int = 200,
) -> RecordedEvent:
    """One recorded `orderbook_deltas` row, as `event_from_row` maps it."""
    px = Decimal(price)
    payload = RecordedBookDelta(
        depth, side, px, Decimal(size), update_id, cross_seq, prev_update_id, ts_match
    )
    seq = update_id if cross_seq is None else cross_seq
    key = (update_id, depth, side, px)
    return RecordedEvent(T0 + offset_us, seq, symbol, DELTAS, key, payload)


async def regroup(items: Iterable[ReplayItem]) -> list[ReplayItem]:
    return [item async for item in RegroupedStream(ListStream(items))]


def updates(items: Iterable[ReplayItem]) -> list[RecordedBookUpdate]:
    return [
        i.payload
        for i in items
        if isinstance(i, RecordedEvent) and isinstance(i.payload, RecordedBookUpdate)
    ]


def lv(price: str, size: str = "1") -> tuple[Decimal, Decimal]:
    return Decimal(price), Decimal(size)


async def test_regroup_folds_one_updates_rows_into_one_event_best_levels_first() -> None:
    rows = [
        row(5, 7, "ask", "101", cross_seq=40, prev_update_id=6, ts_match=T0 + 3),
        row(5, 7, "ask", "102", "0", cross_seq=40, prev_update_id=6, ts_match=T0 + 3),
        row(5, 7, "bid", "99", cross_seq=40, prev_update_id=6, ts_match=T0 + 3),
        row(5, 7, "bid", "100", "2", cross_seq=40, prev_update_id=6, ts_match=T0 + 3),
        row(5, 8, "bid", "98", cross_seq=41),
    ]
    out = await regroup(rows)
    assert len(out) == 2
    first = out[0]
    assert isinstance(first, RecordedEvent)
    assert (first.ts_us, first.seq, first.symbol, first.stream) == (T0 + 5, 40, SYM, DELTAS)
    assert first.tiebreak == (7, 200)
    assert first.payload == RecordedBookUpdate(
        depth=200,
        update_id=7,
        cross_seq=40,
        bids=(lv("100", "2"), lv("99")),
        asks=(lv("101"), lv("102", "0")),
        prev_update_id=6,
        ts_match=T0 + 3,
    )
    assert updates(out[1:]) == [RecordedBookUpdate(200, 8, 41, (lv("98"),), ())]


async def test_regroup_passes_markers_and_every_other_event_through_unchanged() -> None:
    marker = ReplayGap(T0, SYM, DELTAS, T0, T0 + SECOND, "ws_disconnect")
    tr, snap = trade(5), snapshot(5, update_id=6)
    items: list[ReplayItem] = [
        marker,
        tr,
        snap,
        row(5, 7, "bid", "99"),
        marker,
        row(6, 8, "bid", "98"),
        tr,
    ]
    out = await regroup(items)
    assert out[0] is marker and out[1] is tr and out[2] is snap
    assert out[4] is marker and out[6] is tr
    assert [u.update_id for u in updates(out)] == [7, 8]
    assert len(out) == len(items)


@pytest.mark.parametrize(
    "other",
    [
        row(6, 7, "ask", "101"),  # another instant
        row(5, 7, "ask", "101", cross_seq=9),  # another sequence
        row(5, 7, "ask", "101", prev_update_id=5),
        row(5, 7, "ask", "101", ts_match=T0 + 1),
        row(5, 7, "ask", "101", symbol="ETHUSDT"),
    ],
    ids=["ts", "cross_seq", "prev_update_id", "ts_match", "symbol"],
)
async def test_regroup_never_merges_rows_that_disagree_on_their_update(
    other: RecordedEvent,
) -> None:
    """Corrupt rows sharing an `update_id` stay two updates: the replay book then sees the
    second as a sequence mismatch instead of one silently merged update."""
    out = await regroup([row(5, 7, "bid", "100"), other])
    assert [u.update_id for u in updates(out)] == [7, 7]


async def test_regroup_ends_after_the_last_update_without_another_read() -> None:
    stream = RegroupedStream(ListStream([row(5, 7, "bid", "100"), row(5, 7, "ask", "101")]))
    assert len(updates([await anext(stream)])) == 1
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_regroup_close_closes_the_wrapped_stream_and_ends() -> None:
    inner = ListStream([row(5, 7, "bid", "100"), trade(6)])
    stream = RegroupedStream(inner)
    await anext(stream)  # read one ahead: the trade is held
    await stream.aclose()
    assert inner.closes == 1
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_regroup_raises_a_failure_mid_update_and_never_yields_the_partial_update() -> None:
    failure = ReplaySourceUnavailable(tier="questdb", symbol=SYM, stream=DELTAS, reason="timeout")
    items: list[ReplayItem] = [trade(4), row(5, 7, "bid", "100"), row(5, 7, "ask", "101")]
    stream = RegroupedStream(ListStream(items, fail_at=2, error=failure))
    assert await anext(stream) is items[0]
    with pytest.raises(ReplaySourceUnavailable):
        await anext(stream)
    with pytest.raises(StopAsyncIteration):  # the source ended; no partial update follows
        await anext(stream)


class GatedStream(ListStream):
    """A `ListStream` whose read of item `gate_at` waits until `gate` is set."""

    def __init__(self, items: Iterable[ReplayItem], *, gate_at: int) -> None:
        super().__init__(items)
        self.gate, self.gate_at, self.reads = asyncio.Event(), gate_at, 0

    async def __anext__(self) -> ReplayItem:
        if self.reads == self.gate_at:
            await self.gate.wait()
        self.reads += 1
        return await super().__anext__()


async def test_regroup_a_cancelled_read_keeps_the_rows_read_so_far() -> None:
    inner = GatedStream([row(5, 7, "bid", "100"), row(5, 7, "ask", "101")], gate_at=1)
    stream = RegroupedStream(inner)
    pending = asyncio.ensure_future(anext(stream))
    for _ in range(5):
        await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    inner.gate_at = -1  # the next read goes through: the update completes with both rows
    folded = updates([await anext(stream)])
    assert folded == [RecordedBookUpdate(200, 7, None, (lv("100"),), (lv("101"),))]


async def test_regroup_refuses_a_row_without_a_book_side() -> None:
    with pytest.raises(ReplayEventRefused):
        await regroup([row(5, 7, "mid", "100")])


def update_rows(depth: int, per_side: int) -> list[RecordedEvent]:
    """`per_side` rows a side of one update (id 7) of a `depth` book, each at its own price."""
    bids = [row(5, 7, "bid", str(1000 - i), depth=depth) for i in range(per_side)]
    asks = [row(5, 7, "ask", str(1001 + i), depth=depth) for i in range(per_side)]
    return bids + asks


@pytest.mark.parametrize("depth", [1, 50])
@pytest.mark.parametrize("a_side", [1, 2], ids=["2x-depth-rows", "4x-depth-rows"])
async def test_regroup_folds_an_update_as_long_as_any_the_live_book_applies(
    depth: int, a_side: int
) -> None:
    """The live book applies a delta of up to `2 * depth` levels a side, levels leaving its
    window as others enter (`BookState.apply`): `2 * depth` rows and the longest, `4 * depth`,
    are each one update."""
    rows = update_rows(depth, a_side * depth)
    [update] = updates(await regroup([*rows, trade(6)]))
    assert (len(update.bids), len(update.asks)) == (a_side * depth, a_side * depth)


async def test_regroup_refuses_an_update_past_its_depths_rows_before_buffering_more() -> None:
    """A run of one update's key past `4 * depth` rows is corrupt data: the regrouping buffer
    is bounded, so the next row is refused, never buffered, and nothing after it is read. The
    refusal names no recorded value."""
    rows = [*update_rows(1, 2), row(5, 7, "bid", "990", depth=1), row(5, 7, "bid", "989", depth=1)]
    inner = GatedStream([*rows, trade(6)], gate_at=-1)
    with pytest.raises(ReplayEventRefused) as refused:
        await anext(RegroupedStream(inner))
    assert inner.reads == 5  # the four rows of the longest update, then the one refused
    message = str(refused.value)
    assert not any(value in message for value in ("990", "1000", "1001", "7", "BTCUSDT"))


async def test_regroup_one_clock_step_delivers_one_whole_update() -> None:
    time = FakeTime()
    sink = RecordingSink(time)
    rows = [row(1, 7, "bid", "100"), row(1, 7, "ask", "101"), row(2, 8, "bid", "99")]
    clock = ReplayClock(
        RegroupedStream(ListStream(rows)),
        sink,
        RecordingObserver(),
        time=time,
        start_us=T0,
        end_us=T0 + SECOND,
        speed=0,
        budget_lane=None,
    )
    async with clock:
        assert await clock.step_event() == "step"
    assert updates(sink.events) == [RecordedBookUpdate(200, 7, None, (lv("100"),), (lv("101"),))]
    assert clock.stats().events_emitted == 1


# --- the read order puts one update's rows next to each other (24 Sec.13.7) -------------------

SYMBOLS = ("AAAUSDT", "BBBUSDT")


@st.composite
def recordings(
    draw: st.DrawFn,
) -> tuple[list[RecordedEvent], dict[tuple[str, int], tuple[int, int | None, set[str]]]]:
    """Every symbol's book updates (rows on one to three hot instants, so equal `ts` and `seq`
    across symbols, streams and updates are common), trades and snapshots on the same instants,
    in any storage order; and each update's `(ts, cross_seq, {side:price})` as recorded."""
    instants = draw(st.lists(st.integers(0, 3 * SECOND), min_size=1, max_size=3, unique=True))
    at = st.sampled_from(instants)
    events: list[RecordedEvent] = []
    book: dict[tuple[str, int], tuple[int, int | None, set[str]]] = {}
    for symbol in SYMBOLS:
        update_id = 0
        for _ in range(draw(st.integers(0, 5))):
            update_id += draw(st.integers(1, 3))
            ts, cross = draw(at), draw(st.none() | st.integers(1, 12))
            levels = draw(
                st.lists(
                    st.tuples(st.sampled_from(("bid", "ask")), st.integers(90, 110)),
                    min_size=1,
                    max_size=4,
                    unique=True,
                )
            )
            for side, px in levels:
                events.append(row(ts, update_id, side, str(px), cross_seq=cross, symbol=symbol))
            book[symbol, update_id] = (ts, cross, {f"{s}:{p}" for s, p in levels})
        for n in range(draw(st.integers(0, 3))):
            events.append(trade(draw(at), seq=n, trade_id=f"{symbol}-{n}", symbol=symbol))
        for n in range(draw(st.integers(0, 2))):
            events.append(snapshot(draw(at), update_id=n + 1, cross_seq=n * 4, symbol=symbol))
    return draw(st.permutations(events)), book


@settings(max_examples=60)
@given(recordings())
def test_read_order_keeps_one_updates_rows_adjacent_and_regroup_folds_each_once(
    recording: tuple[list[RecordedEvent], dict[tuple[str, int], tuple[int, int | None, set[str]]]],
) -> None:
    stored, book = recording
    harness = Harness(
        hot=stored,
        req=request(symbols=SYMBOLS, streams=(TRADES, DELTAS, SNAPSHOTS), end_us=4 * SECOND),
    )
    merged = asyncio.run(harness.read_all())
    runs: dict[tuple[str, int], list[tuple[int, RecordedEvent]]] = {}
    for position, item in enumerate(merged):
        if isinstance(item, RecordedEvent) and isinstance(item.payload, RecordedBookDelta):
            runs.setdefault((item.symbol, item.payload.update_id), []).append((position, item))
    for key, run in runs.items():
        positions = [p for p, _ in run]
        assert positions == list(range(positions[0], positions[0] + len(run))), key
        assert len({(e.ts_us, e.seq, e.symbol) for _, e in run}) == 1, key  # one instant and seq

    folded = asyncio.run(regroup(merged))
    got = {}
    for item in folded:
        assert not (isinstance(item, RecordedEvent) and isinstance(item.payload, RecordedBookDelta))
        if isinstance(item, RecordedEvent) and isinstance(item.payload, RecordedBookUpdate):
            u = item.payload
            assert (item.symbol, u.update_id) not in got  # one event per update
            sides = {f"bid:{p}" for p, _ in u.bids} | {f"ask:{p}" for p, _ in u.asks}
            got[item.symbol, u.update_id] = (item.ts_us - T0, u.cross_seq, sides)
    assert got == book
    rest = [i for i in folded if not isinstance(getattr(i, "payload", None), RecordedBookUpdate)]
    assert rest == [
        i for i in merged if not isinstance(getattr(i, "payload", None), RecordedBookDelta)
    ]

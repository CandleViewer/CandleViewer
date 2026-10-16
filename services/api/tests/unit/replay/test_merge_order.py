"""Ordered k-way merge (E26-T02): one total, stable order whatever the tier or storage order.

The order is 24 Sec.13.7's `(ts_us, rank, symbol ordinal, sequence-domain ordinal, seq, stream
ordinal, tiebreak)`; the tests below spell it out independently of `merge.py`'s constants.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections import Counter
from decimal import Decimal
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.replay import ReplayItem, ReplayMemoryCeilingExceeded
from candleviewer.replay.merge import SEQUENCE_DOMAIN, STREAM_ORDINAL, approx_bytes, row_bytes
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import (
    REPLAYABLE_STREAMS,
    RecordedEvent,
    RecordedTrade,
    Tiebreak,
)
from tests.unit.replay._events import (
    ROOMY,
    SECOND,
    SYM,
    T0,
    Harness,
    delta,
    digest,
    request,
    snapshot,
    ticker,
    trade,
)

TRADES, DELTAS = StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA
SNAPSHOTS, TICKERS = StreamKind.ORDERBOOK_SNAPSHOT, StreamKind.TICKERS
ETH = "ETHUSDT"


def events(items: list[ReplayItem]) -> list[RecordedEvent]:
    assert all(isinstance(item, RecordedEvent) for item in items)
    return [item for item in items if isinstance(item, RecordedEvent)]


async def replay(stored: list[RecordedEvent], *streams: StreamKind) -> list[RecordedEvent]:
    return events(await Harness(hot=stored, req=request(streams=streams)).read_all())


def test_the_book_streams_share_one_sequence_domain_and_the_snapshot_sorts_first() -> None:
    """24 Sec.13.7: domains in `stream_kind` order, the two book streams in one of them."""
    assert dict(SEQUENCE_DOMAIN) == {
        TRADES: 0,
        DELTAS: 1,
        SNAPSHOTS: 1,
        TICKERS: 2,
        StreamKind.KLINES: 3,
        StreamKind.LIQUIDATIONS: 4,
        StreamKind.OPEN_INTEREST: 5,
        StreamKind.FUNDING_RATES: 6,
    }
    assert set(STREAM_ORDINAL) == set(REPLAYABLE_STREAMS)
    assert STREAM_ORDINAL[SNAPSHOTS] < STREAM_ORDINAL[DELTAS]


async def test_the_symbol_ordinal_orders_an_instant_before_the_sequence_domain() -> None:
    stored = [trade(1, symbol=ETH), ticker(1)]
    harness = Harness(hot=stored, req=request(symbols=(ETH, SYM), streams=(TRADES, TICKERS)))

    got = events(await harness.read_all())

    assert [(e.symbol, e.stream) for e in got] == [(SYM, TICKERS), (ETH, TRADES)]


async def test_the_sequence_domain_orders_an_instant_before_seq() -> None:
    """A trade's ingest counter and the book's `cross_seq` are never compared."""
    got = await replay([delta(1, update_id=3, cross_seq=9), trade(1, seq=10)], TRADES, DELTAS)

    assert [e.stream for e in got] == [TRADES, DELTAS]


async def test_seq_orders_snapshots_and_deltas_inside_the_book_domain() -> None:
    stored = [
        snapshot(1, update_id=30, cross_seq=10),
        delta(1, update_id=20, cross_seq=9),
        snapshot(1, update_id=10, cross_seq=8),
    ]

    got = await replay(stored, DELTAS, SNAPSHOTS)

    assert [(e.stream, e.seq) for e in got] == [(SNAPSHOTS, 8), (DELTAS, 9), (SNAPSHOTS, 10)]


async def test_a_snapshot_replays_before_a_delta_with_the_same_cross_seq() -> None:
    stored = [delta(1, update_id=9, cross_seq=9), snapshot(1, update_id=9, cross_seq=9)]

    got = await replay(stored, DELTAS, SNAPSHOTS)

    assert [e.stream for e in got] == [SNAPSHOTS, DELTAS]


async def test_seq_orders_one_stream_before_its_tiebreak() -> None:
    got = await replay([trade(1, seq=2, trade_id="a"), trade(1, seq=1, trade_id="b")], TRADES)

    assert [e.tiebreak for e in got] == [("b",), ("a",)]


async def test_the_tiebreak_orders_one_stream_on_an_equal_seq() -> None:
    got = await replay([trade(1, trade_id="b"), trade(1, trade_id="a")], TRADES)

    assert [e.tiebreak for e in got] == [("a",), ("b",)]


PROP_SYMBOLS = ("AAAUSDT", "BBBUSDT", "CCCUSDT")
PROP_STREAMS = (TRADES, DELTAS, SNAPSHOTS, TICKERS)
#: The ruled order written out by hand: domain, then the stream inside the book domain.
_DOMAIN = {TRADES: 0, DELTAS: 1, SNAPSHOTS: 1, TICKERS: 2}
_STREAM = {TRADES: 0, SNAPSHOTS: 1, DELTAS: 2, TICKERS: 3}


def ruled_key(e: RecordedEvent) -> tuple[int, int, int, int, int, Tiebreak]:
    symbol = PROP_SYMBOLS.index(e.symbol)
    return e.ts_us, symbol, _DOMAIN[e.stream], e.seq, _STREAM[e.stream], e.tiebreak


@st.composite
def dense_instants(draw: st.DrawFn) -> tuple[list[RecordedEvent], int]:
    """Up to `cap` rows per `(symbol, stream, instant)` over ten instants, with small
    sequence numbers, so equal timestamps and equal `seq` across streams are the norm. Every
    row has its own dedup key (one ticker per `(symbol, instant)`)."""
    cap = draw(st.integers(1, 8))
    cells = st.tuples(
        st.sampled_from(PROP_SYMBOLS),
        st.sampled_from(PROP_STREAMS),
        st.integers(0, 9),
        st.integers(0, 3),
    )
    rows: list[RecordedEvent] = []
    per_cell: Counter[tuple[str, StreamKind, int]] = Counter()
    for i, (symbol, stream, at_us, seq) in enumerate(draw(st.lists(cells, max_size=60))):
        cell = (symbol, stream, at_us)
        if per_cell[cell] == (1 if stream is TICKERS else cap):
            continue
        per_cell[cell] += 1
        if stream is TRADES:
            rows.append(trade(at_us, seq=seq, trade_id=f"t{i}", symbol=symbol))
        elif stream is DELTAS:
            rows.append(delta(at_us, update_id=i, cross_seq=seq, depth=1, symbol=symbol))
        elif stream is SNAPSHOTS:
            rows.append(snapshot(at_us, update_id=i, cross_seq=seq, depth=1, symbol=symbol))
        else:
            rows.append(ticker(at_us, symbol=symbol))
    return rows, cap


@given(
    recording=dense_instants(),
    data=st.data(),
    window_us=st.integers(1, 64),
    batch=st.integers(1, 8),
)
def test_any_storage_order_replays_as_the_ruled_total_order(
    recording: tuple[list[RecordedEvent], int], data: st.DataObject, window_us: int, batch: int
) -> None:
    """Ticket AC 1 as a property: 3 symbols x 4 streams on few instants, any storage order,
    read windows of 1-64 µs and row caps of 1-8 per read: every row once, in the ruled order."""
    rows, cap = recording
    stored = data.draw(st.permutations(rows))
    req = request(symbols=PROP_SYMBOLS, streams=PROP_STREAMS, depth=1, end_us=16)
    budget = cap * row_bytes(SNAPSHOTS, 1) * len(PROP_SYMBOLS) * len(PROP_STREAMS)
    harness = Harness(hot=stored, req=req)

    got = asyncio.run(
        harness.read_all(batch=batch, budget_bytes=budget, window_us=window_us, max_window_us=64)
    )

    assert got == sorted(rows, key=ruled_key)


async def test_two_reads_over_differently_ordered_storage_are_byte_identical() -> None:
    """Ticket AC 1: same recorded window, same bytes; `(ts_event, seq)` never decreases inside
    one `(symbol, sequence domain)` (24 Sec.13.7)."""
    stored = [trade(t // 3 * SECOND, seq=t % 3, trade_id=f"i{t}") for t in range(90)]
    stored += [delta(t * SECOND // 2, update_id=t, cross_seq=t % 2) for t in range(60)]
    shuffled = stored[1::2][::-1] + stored[::2]  # storage order unrelated to time order
    req = request(streams=(TRADES, DELTAS))

    first = await Harness(hot=stored, req=req).read_all()
    second = await Harness(hot=shuffled, req=req).read_all(batch=7, window_us=3 * SECOND)

    assert digest(first) == digest(second)
    assert len(first) == len(stored)
    for stream in (TRADES, DELTAS):
        keys = [(e.ts_us, e.seq) for e in events(first) if e.stream is stream]
        assert keys == sorted(keys)


async def test_a_duplicated_row_keeps_the_copy_read_last() -> None:
    """A re-exported cold part repeats rows (21 Sec.5.3), oldest copy first: the newest wins."""
    first = trade(SECOND, trade_id="x")
    assert isinstance(first.payload, RecordedTrade)
    newer = dataclasses.replace(first, payload=dataclasses.replace(first.payload, size=Decimal(2)))
    harness = Harness(cold=[first, newer], archived=True)

    assert await harness.read_all() == [newer]


async def test_only_events_inside_the_half_open_replay_window_replay() -> None:
    """`[start, end)`: the last read is clipped to `end`, so nothing at or after it leaks in."""
    end = 50 * SECOND
    names = {-1: "before", 0: "start", end - 1: "last", end: "end", end + 1: "after"}
    stored = [trade(at, trade_id=name) for at, name in names.items()]
    harness = Harness(hot=stored, req=request(end_us=end))

    got = events(await harness.read_all(window_us=30 * SECOND))

    assert [e.tiebreak[0] for e in got] == ["start", "last"]


async def test_a_sparse_stream_doubles_its_read_window_up_to_the_cap_and_clips_the_last() -> None:
    harness = Harness(hot=[trade(5 * SECOND)], req=request(end_us=200 * SECOND))

    await harness.read_all(window_us=10 * SECOND, max_window_us=40 * SECOND)

    edges = [0, 10, 30, 70, 110, 150, 190, 200]
    assert harness.hot.windows == [(lo * SECOND, hi * SECOND) for lo, hi in pairwise(edges)]


async def test_a_capped_read_is_halved_and_reread_without_losing_rows() -> None:
    dense = [trade(i, trade_id=f"d{i:03}") for i in range(400)]
    harness = Harness(hot=dense)

    got = events(await harness.read_all(budget_bytes=row_bytes(TRADES, 200) * 50))

    assert [e.ts_us for e in got] == [T0 + i for i in range(400)]
    assert harness.hot.reads > 400 // 50


async def test_an_instant_denser_than_the_row_cap_is_refused_at_a_one_microsecond_read() -> None:
    harness = Harness(hot=[trade(0, trade_id=f"s{i}") for i in range(5)])

    with pytest.raises(ReplayMemoryCeilingExceeded) as raised:
        await harness.read_all(budget_bytes=row_bytes(TRADES, 200) * 2)

    assert (raised.value.symbol, raised.value.stream) == (SYM, TRADES)
    assert harness.hot.windows[-1] == (0, 1)


async def test_an_instant_of_exactly_the_row_cap_replays() -> None:
    """A full read (cap + 1 rows) means truncated; exactly `cap` rows is a legal dense instant."""
    dense = [trade(0, trade_id=f"s{i}") for i in range(3)]

    got = await Harness(hot=dense).read_all(budget_bytes=row_bytes(TRADES, 200) * 3)

    assert len(got) == 3


@pytest.mark.parametrize(
    ("symbols", "streams"),
    [((SYM,), (TRADES, TICKERS)), ((SYM, ETH), (TRADES,))],
    ids=["two-streams", "two-symbols"],
)
async def test_each_cursor_gets_only_its_share_of_the_budget(
    symbols: tuple[str, ...], streams: tuple[StreamKind, ...]
) -> None:
    """Two cursors at three rows each: four trades at one instant exceed their cursor's share,
    although the whole budget would hold six."""
    dense = [trade(0, trade_id=f"s{i}") for i in range(4)]
    harness = Harness(hot=dense, req=request(symbols=symbols, streams=streams))

    with pytest.raises(ReplayMemoryCeilingExceeded):
        await harness.read_all(budget_bytes=2 * 3 * row_bytes(TRADES, 200))


async def test_every_read_asks_for_at_most_the_row_ceiling_whatever_the_budget() -> None:
    """Threat model Sec.4: 8 192 rows a read (+1 to detect truncation), though this byte budget
    alone would allow about two million."""
    harness = Harness(hot=[trade(SECOND)])

    await harness.read_all(budget_bytes=ROOMY)

    assert set(harness.hot.limits) == {8_193}


def test_a_budget_below_one_row_per_stream_is_refused_up_front() -> None:
    harness = Harness(req=request(streams=(SNAPSHOTS,), depth=500))

    with pytest.raises(ReplayMemoryCeilingExceeded):
        harness.merge(budget_bytes=row_bytes(SNAPSHOTS, 500) - 1)


async def test_batches_are_cut_by_events_or_bytes_whichever_binds_first() -> None:
    stored = [trade(i) for i in range(10)]
    by_events = Harness(hot=stored).merge()
    by_bytes = Harness(hot=stored).merge()

    event_sizes = [len(b) async for b in by_events.batches(max_events=3, max_bytes=ROOMY)]
    two_events = 2 * approx_bytes(stored[0])
    byte_sizes = [len(b) async for b in by_bytes.batches(max_events=100, max_bytes=two_events)]

    assert event_sizes == [3, 3, 3, 1]
    assert byte_sizes == [2, 2, 2, 2, 2]


def test_snapshot_rows_are_budgeted_by_depth() -> None:
    assert row_bytes(SNAPSHOTS, 500) > row_bytes(SNAPSHOTS, 50) > row_bytes(TRADES, 500)
    assert approx_bytes(snapshot(0)) > approx_bytes(trade(0))

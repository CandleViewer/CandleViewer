"""Ordered k-way merge (E26-T02): one total, stable order whatever the tier or storage order."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from candleviewer.replay import ReplayItem, ReplayMemoryCeilingExceeded
from candleviewer.replay.merge import approx_bytes, row_bytes
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import RecordedEvent, RecordedTrade
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


def events(items: list[ReplayItem]) -> list[RecordedEvent]:
    assert all(isinstance(item, RecordedEvent) for item in items)
    return [item for item in items if isinstance(item, RecordedEvent)]


async def test_events_sharing_an_instant_and_seq_order_by_stream_then_symbol_then_key() -> None:
    """Ticket AC 1 tie-break: stream ordinal (`stream_kind` order), symbol, then the dedup key."""
    now = 5 * SECOND
    stored = [
        ticker(now, symbol="ETHUSDT"),
        ticker(now),
        snapshot(now, update_id=0),
        delta(now, update_id=0, cross_seq=0),
        trade(now, trade_id="b"),
        trade(now, trade_id="a"),
        trade(now, trade_id="a", symbol="ETHUSDT"),
    ]
    req = request(symbols=("ETHUSDT", SYM), streams=(TICKERS, SNAPSHOTS, DELTAS, TRADES))

    got = events(await Harness(hot=stored, req=req).read_all())

    assert [(e.stream, e.symbol, e.tiebreak[:1]) for e in got] == [
        (TRADES, "BTCUSDT", ("a",)),
        (TRADES, "BTCUSDT", ("b",)),
        (TRADES, "ETHUSDT", ("a",)),
        (DELTAS, "BTCUSDT", (0,)),
        (SNAPSHOTS, "BTCUSDT", (0,)),
        (TICKERS, "BTCUSDT", ()),
        (TICKERS, "ETHUSDT", ()),
    ]


async def test_the_exchange_sequence_orders_an_instant_before_the_stream_ordinal() -> None:
    stored = [trade(1, seq=10), delta(1, update_id=3, cross_seq=9)]

    got = events(await Harness(hot=stored, req=request(streams=(TRADES, DELTAS))).read_all())

    assert [e.stream for e in got] == [DELTAS, TRADES]


async def test_two_reads_over_differently_ordered_storage_are_byte_identical() -> None:
    """Ticket AC 1: same recorded window, same bytes, non-decreasing in (ts_event, seq)."""
    stored = [trade(t // 3 * SECOND, seq=t % 3, trade_id=f"i{t}") for t in range(90)]
    stored += [delta(t * SECOND // 2, update_id=t, cross_seq=t % 2) for t in range(60)]
    shuffled = stored[1::2][::-1] + stored[::2]  # storage order unrelated to time order
    req = request(streams=(TRADES, DELTAS))

    first = await Harness(hot=stored, req=req).read_all()
    second = await Harness(hot=shuffled, req=req).read_all(batch=7, window_us=3 * SECOND)

    assert digest(first) == digest(second)
    assert len(first) == len(stored)
    keys = [(e.ts_us, e.seq) for e in events(first)]
    assert keys == sorted(keys)


async def test_a_duplicated_row_keeps_the_copy_read_last() -> None:
    """A re-exported cold part repeats rows (21 Sec.5.3): dedup on read, newest wins."""
    first = trade(SECOND, trade_id="x")
    assert isinstance(first.payload, RecordedTrade)
    newer = dataclasses.replace(first, payload=dataclasses.replace(first.payload, size=Decimal(2)))
    harness = Harness(cold=[first, newer], archived=True)

    assert await harness.read_all() == [newer]


async def test_a_capped_read_is_halved_and_reread_without_losing_rows() -> None:
    dense = [trade(i, trade_id=f"d{i:03}") for i in range(400)]
    harness = Harness(hot=dense)

    got = events(await harness.read_all(budget_bytes=row_bytes(TRADES, 200) * 50))

    assert [e.ts_us for e in got] == [T0 + i for i in range(400)]
    assert harness.hot.reads > 400 // 50


async def test_a_sparse_stream_widens_its_read_window() -> None:
    hourly = [trade(hour * 3_600 * SECOND) for hour in range(3)]
    harness = Harness(hot=hourly, req=request(end_us=3 * 3_600 * SECOND))

    got = await harness.read_all(window_us=SECOND)

    assert len(got) == 3
    assert harness.hot.reads < 40  # 1 s doubling to the 1 h cap, not 10 800 one-second reads


async def test_an_instant_denser_than_the_budget_raises_the_memory_ceiling() -> None:
    same_instant = [trade(0, trade_id=f"s{i}") for i in range(5)]

    with pytest.raises(ReplayMemoryCeilingExceeded) as raised:
        await Harness(hot=same_instant).read_all(budget_bytes=row_bytes(TRADES, 200) * 2)

    assert (raised.value.symbol, raised.value.stream) == (SYM, TRADES)


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

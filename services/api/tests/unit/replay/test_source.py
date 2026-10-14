"""`ReplaySource` (E26-T02): bounded read-ahead, ordered failures, clean cancellation."""

from __future__ import annotations

import asyncio
import tracemalloc
from collections.abc import Callable

import pytest
from prometheus_client import REGISTRY

from candleviewer.replay import (
    ReadAheadConfig,
    ReplayMemoryCeilingExceeded,
    ReplaySource,
    ReplaySourceUnavailable,
    ReplayWindowTooLarge,
)
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent
from candleviewer.storage.testing import InMemoryRecordedTier
from tests.unit.replay._events import SECOND, Harness, digest, request, snapshot, trade

SMALL = ReadAheadConfig(
    window_us=SECOND, readahead_events=256, batch_events=64, readahead_bytes=1 << 20
)


def _gauge() -> float:
    return REGISTRY.get_sample_value("replay_readahead_depth") or 0.0


def _many(count: int) -> list[RecordedEvent]:
    return [trade(i * 2_000, trade_id=f"t{i:05}") for i in range(count)]


async def _until_parked(source: ReplaySource, *, at_least: int) -> None:
    """Yield to the producer until it has filled the buffer and parked on the full queue."""
    for _ in range(10_000):
        if source.buffered_events >= at_least:
            for _ in range(50):  # let it try (and fail) to make more progress
                await asyncio.sleep(0)
            return
        await asyncio.sleep(0)
    raise AssertionError("the producer never filled the read-ahead buffer")


async def test_a_slow_consumer_stops_storage_reads_and_loses_nothing() -> None:
    """Ticket AC 4: the buffer fills, storage reads stop, memory stays flat, nothing is dropped."""
    stored = _many(20_000)
    harness = Harness(hot=stored)
    tracemalloc.start()
    try:
        async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
            await _until_parked(source, at_least=256)
            reads, buffered = harness.hot.reads, source.buffered_events
            before, _ = tracemalloc.get_traced_memory()
            for _ in range(500):  # a consumer that has stopped reading
                await asyncio.sleep(0)
            after, _ = tracemalloc.get_traced_memory()

            assert harness.hot.reads == reads
            assert source.buffered_events == buffered <= 256 + 64  # queue slots + one in flight
            assert after - before < 64 * 1024

            got = [item async for item in source]
    finally:
        tracemalloc.stop()

    assert got == stored


async def test_the_readahead_gauge_tracks_buffered_events_and_returns_to_zero() -> None:
    baseline = _gauge()
    stored = _many(2_000)
    harness = Harness(hot=stored)
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    async with source:
        await _until_parked(source, at_least=256)
        assert _gauge() == baseline + source.buffered_events
        first = await anext(source)

    assert first == stored[0]
    assert _gauge() == baseline


async def test_closing_a_parked_source_cancels_the_producer_and_stops_iteration() -> None:
    harness = Harness(hot=_many(2_000))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)
    async with source:
        await _until_parked(source, at_least=256)
    await source.aclose()  # idempotent

    assert source.buffered_events == 0
    assert [item async for item in source] == []


class _NeverAnswers(InMemoryRecordedTier):
    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        await asyncio.Event().wait()
        return []


async def test_closing_from_another_task_wakes_a_consumer_parked_on_the_queue() -> None:
    harness = Harness().replace_ports(hot=_NeverAnswers())
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    async def consume() -> list[object]:
        return [item async for item in source]

    async with asyncio.timeout(5), asyncio.TaskGroup() as group:
        consumer = group.create_task(consume())
        for _ in range(50):  # the consumer parks on the empty queue, the producer on storage
            await asyncio.sleep(0)
        await source.aclose()

    assert consumer.result() == []


class _FailsOnSecondRead(InMemoryRecordedTier):
    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        if self.reads >= 1:
            raise StorageTierUnavailable("questdb went away")
        return await super().read(symbol, stream, rng, depth=depth, limit=limit)


async def test_events_merged_before_a_failure_are_delivered_before_the_typed_error() -> None:
    stored = [trade(t * SECOND // 2, trade_id=f"t{t}") for t in range(10)]
    harness = Harness().replace_ports(hot=_FailsOnSecondRead(stored))
    got: list[object] = []

    with pytest.raises(ReplaySourceUnavailable):
        async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
            async for item in source:
                got.append(item)

    assert got == stored[:2]  # the first 1 s window, then the failure


async def test_iterating_without_a_context_manager_runs_to_completion() -> None:
    harness = Harness(hot=_many(300))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    got = [item async for item in source]

    assert digest(got) == digest(_many(300))
    await source.aclose()


def test_a_window_beyond_the_span_cap_is_refused_before_any_read() -> None:
    harness = Harness(req=request(end_us=3 * 3_600 * SECOND))
    one_hour = ReadAheadConfig(max_span_us=3_600 * SECOND)

    with pytest.raises(ReplayWindowTooLarge):
        ReplaySource(harness.req, harness.tiers, config=one_hour)

    assert harness.hot.reads == 0


def test_a_ceiling_that_leaves_no_room_for_one_row_is_refused() -> None:
    harness = Harness(req=request(streams=(StreamKind.ORDERBOOK_SNAPSHOT,), depth=500))
    tight = ReadAheadConfig(readahead_bytes=1 << 20, memory_ceiling_bytes=(1 << 20) + 1_024)

    with pytest.raises(ReplayMemoryCeilingExceeded):
        ReplaySource(harness.req, harness.tiers, config=tight)


@pytest.mark.parametrize(
    "build",
    [
        lambda: ReadAheadConfig(readahead_events=0),
        lambda: ReadAheadConfig(max_rows_per_read=0),
        lambda: ReadAheadConfig(io_timeout_s=0.0),
        lambda: ReadAheadConfig(window_us=10, max_window_us=5),
        lambda: ReadAheadConfig(batch_events=512, readahead_events=256),
        lambda: ReadAheadConfig(readahead_bytes=100, memory_ceiling_bytes=100),
    ],
)
def test_inconsistent_readahead_bounds_are_rejected(build: Callable[[], ReadAheadConfig]) -> None:
    with pytest.raises(ValueError, match="must"):
        build()


async def test_the_anchor_lookup_is_served_through_the_source() -> None:
    book = request(streams=(StreamKind.ORDERBOOK_SNAPSHOT,))
    harness = Harness(hot=[snapshot(5 * SECOND)], req=book)
    source = ReplaySource(harness.req, harness.tiers)

    anchor = await source.anchor_at("BTCUSDT", harness.req.start_us + 10 * SECOND)

    assert anchor is not None and anchor.stream is StreamKind.ORDERBOOK_SNAPSHOT
    await source.aclose()

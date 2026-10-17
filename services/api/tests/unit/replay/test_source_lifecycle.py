"""`ReplaySource` lifecycle (E26-T02): close, cancellation, a stopped or stuck producer."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.replay import (
    ReadAheadConfig,
    ReplayInternalError,
    ReplayItem,
    ReplaySource,
    ReplaySourceUnavailable,
)
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent
from candleviewer.storage.testing import InMemoryRecordedTier
from tests.unit.replay._events import SECOND, Harness
from tests.unit.replay._source import (
    SMALL,
    MintingTier,
    drain,
    drain_into,
    many,
    pull,
    until_parked,
)


def _gauge() -> float:
    return REGISTRY.get_sample_value("replay_readahead_depth") or 0.0


def _producers() -> list[asyncio.Task[object]]:
    return [t for t in asyncio.all_tasks() if t.get_name() == "replay-source" and not t.done()]


async def _finished(producer: asyncio.Task[object]) -> None:
    """A producer that was cancelled or let go ends within seconds, or the test fails."""
    async with asyncio.timeout(5):
        await asyncio.wait({producer})


class _NeverAnswers(InMemoryRecordedTier):
    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        await asyncio.Event().wait()
        return []


class _Gated(InMemoryRecordedTier):
    """Answers only once `gate` is set."""

    def __init__(self, events: list[RecordedEvent]) -> None:
        super().__init__(events)
        self.gate = asyncio.Event()

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        await self.gate.wait()
        return await super().read(symbol, stream, rng, depth=depth, limit=limit)


class _IgnoresCancellation(InMemoryRecordedTier):
    """A reader that breaks the port's contract: it swallows cancellation until released, then
    serves what it holds."""

    def __init__(self, events: list[RecordedEvent] | None = None) -> None:
        super().__init__(events or [])
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        self.entered.set()
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                continue
        return await super().read(symbol, stream, rng, depth=depth, limit=limit)


async def test_closing_a_parked_source_cancels_the_producer_and_stops_iteration() -> None:
    baseline = _gauge()
    harness = Harness(hot=many(2_000))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)
    async with source:
        await until_parked(source, at_least=128)
        assert len(_producers()) == 1
    await source.aclose()  # idempotent

    assert (source.buffered_events, _gauge(), _producers()) == (0, baseline, [])
    assert await drain(source) == []


async def test_closing_from_another_task_wakes_a_consumer_parked_on_the_queue() -> None:
    harness = Harness().replace_ports(hot=_NeverAnswers())
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    async def consume() -> list[ReplayItem]:
        return await drain(source)

    async with asyncio.timeout(5), asyncio.TaskGroup() as group:
        consumer = group.create_task(consume())
        for _ in range(50):  # the consumer parks on the empty queue, the producer on storage
            await asyncio.sleep(0)
        await source.aclose()

    assert consumer.result() == []


async def test_a_consumer_cancelled_while_parked_loses_no_event() -> None:
    stored = many(300)
    reader = _Gated(stored)
    harness = Harness().replace_ports(hot=reader)

    async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
        first = asyncio.create_task(anext(source))
        for _ in range(20):  # it parks on the empty queue: storage has not answered
            await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        reader.gate.set()

        got = await drain(source)

    assert got == stored


async def test_a_producer_cancelled_by_someone_else_ends_a_parked_consumer_with_an_error() -> None:
    harness = Harness().replace_ports(hot=_NeverAnswers())
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    async with source:
        waiting = asyncio.create_task(anext(source))
        for _ in range(20):
            await asyncio.sleep(0)
        (producer,) = _producers()
        producer.cancel()

        with capture_logs() as logs:
            async with asyncio.timeout(5):
                with pytest.raises(ReplayInternalError) as raised:
                    await waiting
        with pytest.raises(StopAsyncIteration):
            await pull(source)

    assert str(raised.value) == "the replay read failed unexpectedly"
    assert [e["event"] for e in logs if e["log_level"] == "error"] == [
        "replay_source_producer_stopped"
    ]


async def test_the_producer_cancelled_by_someone_else_still_delivers_what_was_queued() -> None:
    stored = many(2_000)
    harness = Harness(hot=stored)
    got: list[ReplayItem] = []

    async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
        await until_parked(source, at_least=128)
        (producer,) = _producers()
        producer.cancel()
        for _ in range(20):
            await asyncio.sleep(0)

        with pytest.raises(ReplayInternalError):
            await drain_into(source, got)

    assert got == stored[:128]  # the two queued batches, then the error: nothing skipped silently


async def test_a_producer_cancelled_while_the_queue_is_full_raises_nothing_in_the_loop() -> None:
    """The done callback wakes a consumer parked on an empty queue: with the queue full it must
    not try to put (a `QueueFull` in a callback is only logged by the loop, not raised)."""
    seen: list[dict[str, object]] = []
    asyncio.get_running_loop().set_exception_handler(lambda _loop, context: seen.append(context))
    harness = Harness(hot=many(2_000))

    async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
        await until_parked(source, at_least=128)
        (producer,) = _producers()
        producer.cancel()
        for _ in range(20):
            await asyncio.sleep(0)

    assert seen == []


async def test_a_storage_read_that_never_answers_ends_the_replay_with_a_typed_timeout() -> None:
    harness = Harness().replace_ports(hot=_NeverAnswers())
    config = ReadAheadConfig(window_us=1_000_000, io_timeout_s=0.01)

    async with asyncio.timeout(5):  # a source without its own deadline fails here, not hangs
        async with ReplaySource(harness.req, harness.tiers, config=config) as source:
            with pytest.raises(ReplaySourceUnavailable) as raised:
                await pull(source)

    assert raised.value.reason == "timeout"


async def test_closing_gives_up_on_a_producer_that_ignores_cancellation_after_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float | None] = []
    real_timeout = asyncio.timeout

    def recording_timeout(delay: float | None) -> asyncio.Timeout:
        delays.append(delay)
        return real_timeout(delay)

    monkeypatch.setattr(asyncio, "timeout", recording_timeout)
    reader = _IgnoresCancellation()
    harness = Harness().replace_ports(hot=reader)
    config = ReadAheadConfig(window_us=1_000_000, io_timeout_s=0.01)
    source = ReplaySource(harness.req, harness.tiers, config=config)
    await source.__aenter__()
    await reader.entered.wait()
    (producer,) = _producers()

    try:
        with capture_logs() as logs:
            async with asyncio.timeout(5):  # without its own bound, closing fails here
                await source.aclose()

        assert [(e["event"], e["wait_s"]) for e in logs if e["log_level"] == "error"] == [
            ("replay_source_producer_did_not_stop", 0.01)
        ]
        assert {d for d in delays if d is not None and d < 1} == {0.01}  # io_timeout_s, no more
        assert await drain(source) == []
    finally:
        reader.release.set()  # the reader gives the producer back, which then ends by itself
        await _finished(producer)


async def test_a_closed_source_hands_out_nothing_more_even_from_the_batch_in_hand() -> None:
    harness = Harness(hot=many(2_000))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)
    async with source:
        assert await pull(source) == many(2_000)[0]  # 63 more of its batch are in hand
        await source.aclose()

        with pytest.raises(StopAsyncIteration):
            await pull(source)


async def test_closing_wakes_a_parked_consumer_even_when_the_producer_ignores_cancellation() -> (
    None
):
    reader = _IgnoresCancellation()
    harness = Harness().replace_ports(hot=reader)
    config = ReadAheadConfig(window_us=1_000_000, io_timeout_s=0.01)
    source = ReplaySource(harness.req, harness.tiers, config=config)
    consumer = asyncio.create_task(drain(source))
    await reader.entered.wait()
    (producer,) = _producers()

    try:
        await source.aclose()
        assert await asyncio.wait_for(consumer, 5) == []
    finally:
        reader.release.set()
        await _finished(producer)


async def test_a_producer_that_outlives_the_give_up_queues_nothing_for_the_closed_source() -> None:
    """The reader hands the orphaned producer its rows after `aclose` has given up on it: it
    stops at its next batch, reads no more and leaves the queue and the gauge alone."""
    baseline = _gauge()
    reader = _IgnoresCancellation(many(2_000))
    harness = Harness().replace_ports(hot=reader)
    source = ReplaySource(harness.req, harness.tiers, config=replace(SMALL, io_timeout_s=0.01))
    await source.__aenter__()
    await reader.entered.wait()
    (producer,) = _producers()

    try:
        async with asyncio.timeout(5):
            await source.aclose()
    finally:
        reader.release.set()
        await _finished(producer)

    # one read (its first window of 500 rows holds the first batch of 64), nothing queued
    assert (reader.reads, source.buffered_events, _gauge()) == (1, 0, baseline)
    assert await drain(source) == []


async def test_a_producer_that_outlives_the_give_up_does_not_park_on_the_closed_queue() -> None:
    """With one queue slot, already holding the end marker the close left, a producer that put
    its own marker would wait for room that never comes."""
    reader = _IgnoresCancellation()
    harness = Harness().replace_ports(hot=reader)
    one_slot = ReadAheadConfig(
        window_us=SECOND, readahead_events=9, batch_events=3, io_timeout_s=0.01
    )
    source = ReplaySource(harness.req, harness.tiers, config=one_slot)
    await source.__aenter__()
    await reader.entered.wait()
    (producer,) = _producers()

    try:
        async with asyncio.timeout(5):
            await source.aclose()
    finally:
        reader.release.set()
        await _finished(producer)  # the orphan ends by itself, it is not left waiting


async def test_closing_cancelled_while_it_waits_still_releases_everything() -> None:
    baseline = _gauge()
    tier = MintingTier(many(2_000))
    harness = Harness().replace_ports(hot=tier)
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)
    await source.__aenter__()
    await until_parked(source, at_least=128)
    (producer,) = _producers()

    closing = asyncio.create_task(source.aclose())
    await asyncio.sleep(0)  # it has cancelled the producer and waits for it to end
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await _finished(producer)
    del producer, closing  # a cancelled task keeps its traceback, and that the batch it held

    assert (source.buffered_events, _gauge(), tier.alive()) == (0, baseline, 0)
    assert await drain(source) == []


async def test_a_closed_source_never_starts_its_producer() -> None:
    harness = Harness(hot=many(10))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)
    await source.aclose()

    async with source:
        assert _producers() == []
        assert await drain(source) == []

    assert harness.hot.reads == 0


async def test_a_failing_body_still_closes_the_source() -> None:
    harness = Harness(hot=many(2_000))
    baseline = _gauge()

    with pytest.raises(ZeroDivisionError):
        async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
            await until_parked(source, at_least=128)
            raise ZeroDivisionError

    await asyncio.sleep(0)
    assert (_producers(), _gauge()) == ([], baseline)

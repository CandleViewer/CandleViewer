"""`ReplaySource` lifecycle (E26-T02): close, cancellation, a stopped or stuck producer."""

from __future__ import annotations

import asyncio

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.replay import ReadAheadConfig, ReplaySource, ReplaySourceUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent
from candleviewer.storage.testing import InMemoryRecordedTier
from tests.unit.replay._events import Harness
from tests.unit.replay._source import SMALL, many, until_parked


def _gauge() -> float:
    return REGISTRY.get_sample_value("replay_readahead_depth") or 0.0


def _producers() -> list[asyncio.Task[object]]:
    return [t for t in asyncio.all_tasks() if t.get_name() == "replay-source" and not t.done()]


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
    """A reader that breaks the port's contract: it swallows cancellation until released."""

    def __init__(self) -> None:
        super().__init__()
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
        return []


async def test_closing_a_parked_source_cancels_the_producer_and_stops_iteration() -> None:
    baseline = _gauge()
    harness = Harness(hot=many(2_000))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)
    async with source:
        await until_parked(source, at_least=128)
        assert len(_producers()) == 1
    await source.aclose()  # idempotent

    assert (source.buffered_events, _gauge(), _producers()) == (0, baseline, [])
    assert [item async for item in source] == []


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

        got = [item async for item in source]

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

        async with asyncio.timeout(5):
            with pytest.raises(RuntimeError, match="stopped before the replay ended"):
                await waiting
        with pytest.raises(StopAsyncIteration):
            await anext(source)


async def test_the_producer_cancelled_by_someone_else_still_delivers_what_was_queued() -> None:
    stored = many(2_000)
    harness = Harness(hot=stored)
    got: list[object] = []

    async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
        await until_parked(source, at_least=128)
        (producer,) = _producers()
        producer.cancel()
        for _ in range(20):
            await asyncio.sleep(0)

        async with asyncio.timeout(5):
            with pytest.raises(RuntimeError, match="stopped before the replay ended"):
                async for item in source:
                    got.append(item)

    assert got == stored[:128]  # the two queued batches, then the error: nothing skipped silently


async def test_a_storage_read_that_never_answers_ends_the_replay_with_a_typed_timeout() -> None:
    harness = Harness().replace_ports(hot=_NeverAnswers())
    config = ReadAheadConfig(window_us=1_000_000, io_timeout_s=0.01)

    async with asyncio.timeout(5):  # a source without its own deadline fails here, not hangs
        async with ReplaySource(harness.req, harness.tiers, config=config) as source:
            with pytest.raises(ReplaySourceUnavailable) as raised:
                await anext(source)

    assert raised.value.reason == "timeout"


async def test_closing_gives_up_on_a_producer_that_ignores_cancellation_after_the_timeout() -> None:
    reader = _IgnoresCancellation()
    harness = Harness().replace_ports(hot=reader)
    config = ReadAheadConfig(window_us=1_000_000, io_timeout_s=0.01)
    source = ReplaySource(harness.req, harness.tiers, config=config)
    await source.__aenter__()
    await reader.entered.wait()
    (producer,) = _producers()

    with capture_logs() as logs:
        async with asyncio.timeout(5):
            await source.aclose()

    assert [e["event"] for e in logs if e["log_level"] == "error"] == [
        "replay_source_producer_did_not_stop"
    ]
    assert [item async for item in source] == []
    reader.release.set()  # the reader gives the producer back, which then ends by itself
    await asyncio.wait({producer})


async def test_closing_cancelled_while_it_waits_still_releases_everything() -> None:
    baseline = _gauge()
    harness = Harness(hot=many(2_000))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)
    await source.__aenter__()
    await until_parked(source, at_least=128)
    (producer,) = _producers()

    closing = asyncio.create_task(source.aclose())
    await asyncio.sleep(0)  # it has cancelled the producer and waits for it to end
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await asyncio.wait({producer})

    assert (source.buffered_events, _gauge()) == (0, baseline)
    assert [item async for item in source] == []


async def test_a_closed_source_never_starts_its_producer() -> None:
    harness = Harness(hot=many(10))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)
    await source.aclose()

    async with source:
        assert _producers() == []
        assert [item async for item in source] == []

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

"""`ReplaySource` (E26-T02): bounded read-ahead, ordered failures, one window cap, the anchor."""

from __future__ import annotations

import asyncio
import dataclasses
import tracemalloc

import pytest
from prometheus_client import REGISTRY

from candleviewer.replay import (
    ReadAheadConfig,
    ReplayMemoryCeilingExceeded,
    ReplayRequestInvalid,
    ReplaySource,
    ReplaySourceUnavailable,
    ReplayTierStraddle,
)
from candleviewer.replay.merge import DEFAULT_MAX_ROWS_PER_READ
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent
from candleviewer.storage.testing import InMemoryRecordedTier
from tests.unit.replay._events import SECOND, Harness, at, digest, request, snapshot, trade
from tests.unit.replay._source import SMALL, count_items, many, until_parked

HOUR = 3_600 * SECOND


def _gauge() -> float:
    return REGISTRY.get_sample_value("replay_readahead_depth") or 0.0


async def test_a_slow_consumer_stops_storage_reads_and_loses_nothing() -> None:
    """Ticket AC 4: the buffer fills, storage reads stop, memory stays flat, nothing is dropped."""
    stored = many(20_000)
    harness = Harness(hot=stored)
    tracemalloc.start()
    try:
        async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
            await until_parked(source, at_least=128)
            reads, buffered = harness.hot.reads, source.buffered_events
            before, _ = tracemalloc.get_traced_memory()
            for _ in range(500):  # a consumer that has stopped reading
                await asyncio.sleep(0)
            after, _ = tracemalloc.get_traced_memory()

            assert harness.hot.reads == reads
            assert source.buffered_events == buffered == 2 * 64  # the queue's two slots
            assert after - before < 64 * 1024

            got = [item async for item in source]
    finally:
        tracemalloc.stop()

    assert got == stored


async def test_the_readahead_gauge_tracks_buffered_events_and_returns_to_zero() -> None:
    baseline = _gauge()
    stored = many(2_000)
    harness = Harness(hot=stored)
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    async with source:
        await until_parked(source, at_least=128)
        assert _gauge() == baseline + source.buffered_events == baseline + 128
        first = await anext(source)
        assert _gauge() == baseline + source.buffered_events == baseline + 64
        await until_parked(source, at_least=128)
        assert _gauge() == baseline + 128

    assert first == stored[0]
    assert _gauge() == baseline


async def test_the_gauge_returns_to_zero_when_the_replay_is_read_to_its_end() -> None:
    baseline = _gauge()
    harness = Harness(hot=many(500))

    assert await count_items(ReplaySource(harness.req, harness.tiers, config=SMALL)) == 500

    assert _gauge() == baseline


async def test_iterating_without_a_context_manager_runs_to_completion() -> None:
    harness = Harness(hot=many(300))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    got = [item async for item in source]

    assert digest(got) == digest(many(300))
    await source.aclose()
    assert [item async for item in source] == []


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


async def test_a_source_that_failed_or_ended_stays_stopped() -> None:
    failing = Harness().replace_ports(hot=_FailsOnSecondRead([trade(0), trade(SECOND, seq=1)]))
    source = ReplaySource(failing.req, failing.tiers, config=SMALL)
    assert await anext(source) == trade(0)
    with pytest.raises(ReplaySourceUnavailable):
        await anext(source)
    for _ in range(2):
        with pytest.raises(StopAsyncIteration):
            await anext(source)
    await source.aclose()

    done = ReplaySource(Harness().req, Harness().tiers, config=SMALL)
    assert [item async for item in done] == []
    with pytest.raises(StopAsyncIteration):
        await anext(done)


async def test_a_straddling_session_fails_the_first_read_before_any_event() -> None:
    harness = Harness(hot=many(10), req=request(end_us=60 * SECOND)).archive(0, 10 * SECOND)

    with pytest.raises(ReplayTierStraddle):
        async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
            await anext(source)

    assert harness.hot.reads == harness.cold.reads == 0


async def test_a_dense_instant_fails_the_replay_naming_the_row_ceiling_after_earlier_events() -> (
    None
):
    """The memory ceiling reaches the consumer in order: the events before the instant, then
    the typed error, which names the row ceiling because the byte share was ample."""
    early = [trade(t * SECOND, trade_id=f"e{t}") for t in (1, 2, 3)]
    dense = [trade(40 * SECOND, trade_id=f"d{i:05}") for i in range(DEFAULT_MAX_ROWS_PER_READ + 1)]
    harness = Harness(hot=early + dense)
    got: list[object] = []

    with pytest.raises(ReplayMemoryCeilingExceeded) as raised:
        async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
            async for item in source:
                got.append(item)

    assert got == early
    assert raised.value.max_rows == DEFAULT_MAX_ROWS_PER_READ
    assert (raised.value.symbol, raised.value.stream) == ("BTCUSDT", StreamKind.TRADES)


def test_a_cap_above_a_day_is_the_requests_own_not_a_default_of_the_source() -> None:
    """One window cap: a 31-day window under a 31-day cap is accepted, so the source has no
    24 h of its own (the setting's ceiling is 24 x 31 h)."""
    month = 31 * 24 * HOUR
    for window in (30 * 24 * HOUR, month):
        req = request(end_us=window, max_span_us=month)

        ReplaySource(req, Harness(req=req).tiers, config=SMALL)


def test_the_config_carries_no_window_cap_of_its_own() -> None:
    assert "max_span_us" not in {field.name for field in dataclasses.fields(ReadAheadConfig)}


def test_a_request_widened_after_validation_is_refused_before_any_read() -> None:
    """`model_copy(update=...)` skips validation, as a seek deriving its request would."""
    req = request(end_us=HOUR, max_span_us=HOUR)
    harness = Harness(hot=many(10), req=req)
    ReplaySource(req, harness.tiers, config=SMALL)  # exactly the cap: accepted

    widened = req.model_copy(update={"end": at(HOUR + 1)})

    with pytest.raises(ReplayRequestInvalid, match=f"exceeds the {HOUR} µs cap"):
        ReplaySource(widened, harness.tiers, config=SMALL)
    assert harness.hot.reads == 0


def test_a_derived_request_cannot_raise_its_cap_past_the_settings_ceiling() -> None:
    req = request(end_us=HOUR, max_span_us=HOUR)
    raised = req.model_copy(update={"max_span_us": 31 * 24 * HOUR + 1})

    with pytest.raises(ReplayRequestInvalid, match=r"max_span_us \(less_than_equal\)"):
        ReplaySource(raised, Harness(req=req).tiers, config=SMALL)


async def test_the_anchor_lookup_is_served_through_the_source() -> None:
    book = request(streams=(StreamKind.ORDERBOOK_SNAPSHOT,))
    harness = Harness(hot=[snapshot(5 * SECOND)], req=book)
    source = ReplaySource(harness.req, harness.tiers)

    anchor = await source.anchor_at("BTCUSDT", harness.req.start_us + 10 * SECOND)

    assert anchor == snapshot(5 * SECOND)
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "replay-source"]


async def test_the_anchor_lookup_works_while_reading_and_after_close() -> None:
    book = request(streams=(StreamKind.ORDERBOOK_SNAPSHOT,))
    rows = [snapshot(s * SECOND, update_id=s) for s in range(1, 40)]
    harness = Harness(hot=rows, req=book)
    at_us = harness.req.start_us + 10 * SECOND + 1

    async with ReplaySource(harness.req, harness.tiers, config=SMALL) as source:
        await anext(source)
        assert await source.anchor_at("BTCUSDT", at_us) == snapshot(10 * SECOND, update_id=10)
    assert await source.anchor_at("BTCUSDT", at_us) == snapshot(10 * SECOND, update_id=10)


class _NoAnchor(InMemoryRecordedTier):
    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        raise StorageTierUnavailable("questdb went away")


async def test_a_failing_anchor_lookup_is_typed_and_never_read_as_no_anchor() -> None:
    book = request(streams=(StreamKind.ORDERBOOK_SNAPSHOT,))
    harness = Harness(req=book).replace_ports(hot=_NoAnchor())
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    with pytest.raises(ReplaySourceUnavailable) as raised:
        await source.anchor_at("BTCUSDT", harness.req.start_us + SECOND)

    assert (raised.value.tier, raised.value.reason) == ("questdb", "STORAGE_TIER_UNAVAILABLE")
    assert [item async for item in source] == []  # the read-ahead is unaffected


@pytest.mark.parametrize(
    ("symbol", "offset_us"), [("ETHUSDT", SECOND), ("BTCUSDT", -1), ("BTCUSDT", 61 * SECOND)]
)
async def test_an_anchor_outside_the_replay_is_refused(symbol: str, offset_us: int) -> None:
    harness = Harness(req=request(streams=(StreamKind.ORDERBOOK_SNAPSHOT,)))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    with pytest.raises(ReplayRequestInvalid):
        await source.anchor_at(symbol, harness.req.start_us + offset_us)

    assert harness.hot.reads == harness.cold.reads == 0

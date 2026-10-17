"""The read-ahead's bounds (E26-T02): config, how they become batches, the memory ceiling."""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from candleviewer.replay import (
    ReadAheadConfig,
    ReplayConfigInvalid,
    ReplayMemoryCeilingExceeded,
    ReplaySource,
)
from candleviewer.storage.models import StreamKind
from tests.unit.replay._events import SECOND, SYM, Harness, request
from tests.unit.replay._source import many, pull, until_parked

TRADES, SNAPSHOTS = StreamKind.TRADES, StreamKind.ORDERBOOK_SNAPSHOT
ROW = 512  # `merge.approx_bytes` of one trade


def _config(**bounds: int) -> ReadAheadConfig:
    """1 s read windows and a 2 s deadline, so a source that fails to stop fails a test quickly."""
    return ReadAheadConfig(window_us=SECOND, io_timeout_s=2.0, **bounds)


@pytest.mark.parametrize(
    ("build", "message"),
    [
        pytest.param(lambda: ReadAheadConfig(window_us=0), "read windows need", id="zero-window"),
        pytest.param(
            lambda: ReadAheadConfig(window_us=10, max_window_us=5),
            "read windows need",
            id="max-window-below-window",
        ),
        pytest.param(
            lambda: ReadAheadConfig(io_timeout_s=0.0), "io_timeout_s must be", id="zero-timeout"
        ),
        pytest.param(
            lambda: ReadAheadConfig(io_timeout_s=-1.0),
            "io_timeout_s must be",
            id="negative-timeout",
        ),
        pytest.param(
            lambda: ReadAheadConfig(io_timeout_s=math.inf),
            "io_timeout_s must be",
            id="unbounded-timeout",
        ),
        pytest.param(
            lambda: ReadAheadConfig(io_timeout_s=math.nan), "io_timeout_s must be", id="nan-timeout"
        ),
        pytest.param(lambda: ReadAheadConfig(batch_events=0), "must be positive", id="zero-batch"),
        pytest.param(
            lambda: ReadAheadConfig(readahead_bytes=0), "must be positive", id="zero-bytes"
        ),
        pytest.param(
            lambda: ReadAheadConfig(readahead_events=2), "at least three batches", id="two-events"
        ),
        pytest.param(
            lambda: ReadAheadConfig(readahead_bytes=100, memory_ceiling_bytes=100),
            "must exceed readahead_bytes",
            id="ceiling-equals-readahead",
        ),
        pytest.param(
            lambda: ReadAheadConfig(readahead_bytes=100, memory_ceiling_bytes=99),
            "must exceed readahead_bytes",
            id="ceiling-below-readahead",
        ),
    ],
)
def test_inconsistent_bounds_are_refused_as_a_typed_config_error(
    build: Callable[[], ReadAheadConfig], message: str
) -> None:
    with pytest.raises(ReplayConfigInvalid, match=message):
        build()


def test_the_least_consistent_bounds_are_accepted() -> None:
    least = ReadAheadConfig(
        window_us=1,
        max_window_us=1,
        io_timeout_s=1e-9,
        batch_events=1,
        readahead_events=3,
        readahead_bytes=1,
        memory_ceiling_bytes=2,
    )

    assert (least.readahead_events, least.memory_ceiling_bytes) == (3, 2)


def test_a_config_error_is_a_value_error_too() -> None:
    with pytest.raises(ValueError, match="at least three batches"):
        ReadAheadConfig(readahead_events=1)


async def parked_events(config: ReadAheadConfig, *, at_least: int) -> int:
    """What the read-ahead holds once the producer has filled it and parked."""
    harness = Harness(hot=many(2_000))
    async with ReplaySource(harness.req, harness.tiers, config=config) as source:
        await until_parked(source, at_least=at_least)
        return source.buffered_events


async def test_events_bind_first_when_the_byte_bound_is_roomy() -> None:
    """256 events in batches of 64 are four batches: the queue has two slots (the producer holds
    one and the consumer one)."""
    held = await parked_events(_config(readahead_events=256, batch_events=64), at_least=128)

    assert held == 2 * 64


async def test_bytes_cut_batches_before_events_when_they_bind_first() -> None:
    """20 480 B hold ten 2 048 B batches; a batch ends at 2 048 - 512 = 1 536 B, three trades."""
    config = _config(readahead_events=1_000, batch_events=100, readahead_bytes=ROW * 40)

    assert await parked_events(config, at_least=24) == 8 * 3


async def test_a_batch_fills_its_byte_share_up_to_its_last_row() -> None:
    """A 2 049 B share less the 512 B row is 1 537 B: three trades (1 536 B) are a byte short, so
    a fourth joins, and the four (2 048 B) still fit the share."""
    config = _config(readahead_events=1_000, batch_events=100, readahead_bytes=ROW * 40 + 10)

    assert await parked_events(config, at_least=32) == 8 * 4


async def test_a_small_byte_bound_shrinks_the_queue_to_the_rows_it_can_hold() -> None:
    """Twelve rows fit 12 batches of one trade, however many events are allowed."""
    config = _config(readahead_events=1_000_000, readahead_bytes=ROW * 12)

    assert await parked_events(config, at_least=10) == 10


async def test_a_batch_is_at_most_a_third_of_the_readahead_events() -> None:
    config = _config(readahead_events=5, batch_events=1_024)

    assert await parked_events(config, at_least=3) == 3


async def test_the_queue_keeps_two_batches_of_room_for_the_producer_and_the_consumer() -> None:
    """Seven events in batches of two are three batches: one queue slot."""
    assert await parked_events(_config(readahead_events=7, batch_events=2), at_least=2) == 2


@pytest.mark.parametrize(
    "streams",
    [(SNAPSHOTS,), (TRADES, SNAPSHOTS), (SNAPSHOTS, TRADES)],
    ids=["snapshots", "trades-then-snapshots", "snapshots-then-trades"],
)
def test_three_rows_of_the_deepest_requested_stream_are_the_least_the_bytes_can_hold(
    streams: tuple[StreamKind, ...],
) -> None:
    deepest = ROW + 128 * 2 * 500  # a 500-level snapshot: `merge.row_bytes`
    req = request(streams=streams, depth=500)
    harness = Harness(req=req)

    ReplaySource(req, harness.tiers, config=_config(readahead_bytes=3 * deepest))
    with pytest.raises(ReplayConfigInvalid, match="three rows of the requested depth"):
        ReplaySource(req, harness.tiers, config=_config(readahead_bytes=3 * deepest - 1))

    assert harness.hot.reads == 0


async def test_a_batch_gets_the_readahead_bytes_over_the_batches_held() -> None:
    """Thirty events in batches of ten are three batches, so each has a third of 12 rows' bytes:
    2 048 B, less the 512 B of the largest row, is three trades to a batch."""
    config = _config(readahead_events=30, batch_events=10, readahead_bytes=ROW * 12)

    assert await parked_events(config, at_least=3) == 1 * 3


def test_only_the_requested_streams_size_the_largest_row() -> None:
    """A trades-only session at depth 500 needs 3 x 512 B, not three 500-level snapshots."""
    req = request(depth=500)

    ReplaySource(req, Harness(req=req).tiers, config=_config(readahead_bytes=3 * ROW))


def test_a_ceiling_that_leaves_no_room_for_one_row_is_refused() -> None:
    req = request(streams=(SNAPSHOTS,), depth=500)
    harness = Harness(req=req)
    tight = _config(readahead_bytes=1 << 20, memory_ceiling_bytes=(1 << 20) + 1_024)

    with pytest.raises(ReplayMemoryCeilingExceeded) as raised:
        ReplaySource(req, harness.tiers, config=tight)

    assert (raised.value.symbol, raised.value.stream) == (SYM, SNAPSHOTS)
    assert raised.value.budget_bytes == 1_024 and raised.value.max_rows is None
    assert harness.hot.reads == 0


async def test_the_readahead_counts_toward_the_ceiling() -> None:
    """The cursors share what the read-ahead leaves: 100 rows of the ceiling's 1 MiB + 51 200 B
    after the 1 MiB read-ahead, so a read asks for 101 (one past the cap detects truncation)."""
    config = _config(readahead_bytes=1 << 20, memory_ceiling_bytes=(1 << 20) + 100 * ROW)
    harness = Harness(hot=many(50))

    async with ReplaySource(harness.req, harness.tiers, config=config) as source:
        await pull(source)

    assert harness.hot.limits[0] == 101

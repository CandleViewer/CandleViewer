"""What a `ReplaySource` keeps (E26-T02): nothing once the replay is read, failed or closed, and
while it runs no more than the read-ahead and the cursors' windows, however slow the consumer.

Weak references count what is alive (`MintingTier`): the consumer keeps only the item in hand.
"""

from __future__ import annotations

import asyncio
import dataclasses
import gc

import pytest

from candleviewer.replay import ReplaySource, ReplaySourceUnavailable
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent
from tests.unit.replay._events import SECOND, Harness
from tests.unit.replay._source import SMALL, MintingTier, count_items, many, until_parked


class _FailsOnRefill(MintingTier):
    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        if self.reads:
            raise StorageTierUnavailable("questdb went away")
        return await super().read(symbol, stream, rng, depth=depth, limit=limit)


async def test_a_replay_read_to_its_end_holds_no_event() -> None:
    tier = MintingTier(many(2_000))
    harness = Harness().replace_ports(hot=tier)
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    assert await count_items(source) == 2_000

    assert tier.alive() == 0


async def test_a_closed_source_holds_no_event() -> None:
    tier = MintingTier(many(2_000))
    harness = Harness().replace_ports(hot=tier)
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)
    async with source:
        await until_parked(source, at_least=128)
        assert tier.alive() > 128  # the read-ahead and a cursor window: the count is not vacuous

    assert tier.alive() == 0


async def test_a_replay_that_failed_holds_no_event() -> None:
    tier = _FailsOnRefill(many(2_000))
    harness = Harness().replace_ports(hot=tier)
    source = ReplaySource(harness.req, harness.tiers, config=SMALL)

    with pytest.raises(ReplaySourceUnavailable) as raised:
        await count_items(source)
    del raised  # its traceback holds the producer's frame, and that frame its last batch
    gc.collect()  # ... in a reference cycle (exception, traceback, frame, the queued failure)

    assert tier.alive() == 0


async def test_events_alive_stay_within_the_readahead_and_a_cursor_window() -> None:
    """Twenty thousand events, a consumer that stops and goes: the producer never has more than
    the 256 events of the read-ahead (four batches of 64) beyond the 500 rows a 1 s window holds,
    so memory does not follow the length of the replay."""
    tier = MintingTier(many(20_000))
    harness = Harness().replace_ports(hot=tier)
    one_second_windows = dataclasses.replace(SMALL, max_window_us=SECOND)  # 500 rows each
    peaks: list[int] = []

    async with ReplaySource(harness.req, harness.tiers, config=one_second_windows) as source:
        await until_parked(source, at_least=128)
        peaks.append(tier.alive())
        pulled = 0
        async with asyncio.timeout(60):
            async for _ in source:
                pulled += 1
                assert pulled <= 20_000
                if pulled % 500 == 0:
                    for _ in range(3):  # a slow consumer: the producer gets a few turns in between
                        await asyncio.sleep(0)
                    peaks.append(tier.alive())

    assert pulled == 20_000
    assert 500 <= max(peaks) <= 256 + 500  # one window held whole, plus the read-ahead at most

"""One pass and no dead weight (E26-T02): a merge is read once, and a source's entries are
released the moment it is drained, so a finished, failed or closed pass holds no recorded data.

Weak references count what is alive (`MintingTier`, `MintingGaps`): the consumer keeps only the
batch it is looking at.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing

import pytest

from candleviewer.replay import ReplayConfigInvalid, ReplayItem, ReplaySourceUnavailable
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent
from tests.unit.replay._events import ROOMY, SYM, T0, BoundedTier, Harness, drain, request, trade
from tests.unit.replay._source import MintingGaps, MintingTier, many

AAA, BBB = "AAAUSDT", "BBBUSDT"


class _StallsOnRefill(BoundedTier):
    """Serves its first read, then never answers: the merge waits on it mid-batch."""

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        if self.reads:
            await asyncio.Event().wait()
        return await super().read(symbol, stream, rng, depth=depth, limit=limit)


class _GatedRefill(MintingTier):
    """Serves its first read, then every later read only once `gate` is set."""

    def __init__(self, events: list[RecordedEvent]) -> None:
        super().__init__(events)
        self.gate = asyncio.Event()

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        if self.reads:
            await self.gate.wait()
        return await super().read(symbol, stream, rng, depth=depth, limit=limit)


class _FailsOnRefill(MintingTier):
    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        if self.reads:
            raise StorageTierUnavailable("questdb went away")
        return await super().read(symbol, stream, rng, depth=depth, limit=limit)


def test_a_second_pass_is_refused_by_the_call_before_any_read() -> None:
    harness = Harness(hot=many(5))
    merge = harness.merge()
    merge.batches(max_events=8, max_bytes=ROOMY)  # claims the pass, never iterated

    with pytest.raises(ReplayConfigInvalid, match="read once"):
        merge.batches(max_events=8, max_bytes=ROOMY)

    assert (harness.hot.reads, harness.gaps.limits) == (0, [])


async def test_a_finished_pass_cannot_be_read_again() -> None:
    harness = Harness(hot=many(5))
    merge = harness.merge()
    assert len([i async for b in merge.batches(max_events=8, max_bytes=ROOMY) for i in b]) == 5
    reads, gap_reads = harness.hot.reads, len(harness.gaps.limits)

    with pytest.raises(ReplayConfigInvalid):
        merge.batches(max_events=8, max_bytes=ROOMY)

    assert (harness.hot.reads, len(harness.gaps.limits)) == (reads, gap_reads)


async def _pull(batches: AsyncGenerator[list[ReplayItem]]) -> list[ReplayItem]:
    return await anext(batches)


async def test_a_pass_cancelled_mid_batch_cannot_resume_past_the_batch_in_flight() -> None:
    """Five events are merged into the batch under construction when the refill stalls and the
    consumer is cancelled: a second pass would resume after them and skip them silently."""
    stored = [trade(i, trade_id=f"t{i:02}") for i in range(10)]
    harness = Harness().replace_ports(hot=_StallsOnRefill(stored))
    merge = harness.merge(window_us=5)
    first = asyncio.create_task(_pull(merge.batches(max_events=100, max_bytes=ROOMY)))
    for _ in range(20):
        await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    with pytest.raises(ReplayConfigInvalid):
        merge.batches(max_events=100, max_bytes=ROOMY)


def _two_symbols(*, hot: MintingTier, gaps: MintingGaps | None = None) -> Harness:
    harness = Harness(req=request(symbols=(AAA, BBB), end_us=200))
    return harness.replace_ports(hot=hot, gaps=gaps)


async def test_a_drained_cursor_releases_its_entries_while_other_symbols_play_on() -> None:
    rows = [trade(i, trade_id=f"a{i:02}", symbol=AAA) for i in range(20)]
    rows += [trade(i, trade_id=f"b{i:02}", symbol=BBB) for i in range(20)]
    rows += [trade(100 + i, trade_id=f"c{i:02}", symbol=BBB) for i in range(20)]
    tier = MintingTier(rows)
    merge = _two_symbols(hot=tier).merge(window_us=200)  # one read per cursor
    seen: dict[int, int] = {}

    async with aclosing(merge.batches(max_events=1, max_bytes=ROOMY)) as batches:
        async for batch in batches:
            at_us = batch[0].ts_us - T0
            if at_us in (0, 100):
                seen[at_us] = tier.alive(AAA)
            if at_us == 100:
                break

    assert seen == {0: 20, 100: 0}


async def test_a_drained_symbols_markers_are_released_while_other_symbols_play_on() -> None:
    gaps = MintingGaps([(AAA, i, i + 1) for i in range(30)])
    late = MintingTier([trade(100 + i, trade_id=f"c{i:02}", symbol=BBB) for i in range(20)])
    merge = _two_symbols(hot=late, gaps=gaps).merge(window_us=200)
    seen: dict[int, int] = {}

    async with aclosing(merge.batches(max_events=1, max_bytes=ROOMY)) as batches:
        async for batch in batches:
            at_us = batch[0].ts_us - T0
            if at_us in (0, 100):
                seen[at_us] = gaps.alive(AAA)
            if at_us == 100:
                break

    assert seen == {0: 30, 100: 0}


async def test_a_cursor_does_not_hold_its_consumed_window_across_the_refill() -> None:
    """The window of 20 rows is read out when the refill starts; only the item in the batch
    under construction is alive while storage answers."""
    tier = _GatedRefill([trade(i, trade_id=f"t{i:02}") for i in range(40)])
    merge = Harness().replace_ports(hot=tier).merge(window_us=20)
    batches = merge.batches(max_events=1, max_bytes=ROOMY)
    for _ in range(19):
        await _pull(batches)

    blocked = asyncio.create_task(_pull(batches))  # the 20th item empties the window
    for _ in range(20):
        await asyncio.sleep(0)
    held = tier.alive()
    tier.gate.set()
    await blocked
    await batches.aclose()

    assert held == 1


async def test_closing_a_pass_early_releases_every_entry() -> None:
    tier = MintingTier(many(200))
    merge = Harness().replace_ports(hot=tier).merge(window_us=60_000_000)
    batches = merge.batches(max_events=10, max_bytes=ROOMY)

    first = await anext(batches)
    assert (len(first), tier.alive()) == (10, 200)
    await batches.aclose()
    del first

    assert tier.alive() == 0


async def test_a_failed_pass_lets_go_of_the_markers_it_never_played() -> None:
    """30 gap rows lie past the failure: while the error is alive, its traceback keeps the
    generator frame, and the markers must not be in it (the heap's head key holds one cause)."""
    tier = _FailsOnRefill(many(200))
    gaps = MintingGaps([(SYM, 150_000 + i, 150_001 + i) for i in range(30)])
    merge = Harness().replace_ports(hot=tier, gaps=gaps).merge(window_us=100_000)

    delivered, error = await drain(merge, batch=8)
    del delivered

    assert isinstance(error, ReplaySourceUnavailable)
    assert gaps.alive(SYM) <= 1


async def test_a_failed_pass_releases_every_entry() -> None:
    tier = _FailsOnRefill(many(200))
    merge = Harness().replace_ports(hot=tier).merge(window_us=100_000)  # 100 ms: 50 rows a read

    delivered, error = await drain(merge, batch=8)

    assert isinstance(error, ReplaySourceUnavailable) and len(delivered) == 50
    del delivered, error  # the error's traceback holds the frame, and the frame its last batch
    assert tier.alive() == 0

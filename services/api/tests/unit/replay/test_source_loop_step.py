"""`ReplaySource` starts a dense replay without a long loop step (C-2.17, #2731).

The first `__anext__` starts the producer, which merges and queues the whole read-ahead. The
longest single step of the event loop over that start and initial fill must stay under 50 ms,
so WS fan-out and the OMS sharing the loop are not held while a replay opens. The probe times
every loop callback, which is deterministic where a heartbeat task is not. Cyclic GC is off for
the span: a collection over a large heap is a pause of its own, not the producer's.
"""

from __future__ import annotations

import asyncio
import bisect
import gc
import time
from asyncio import events
from collections.abc import Iterator

import pytest

from candleviewer.replay import ReadAheadConfig, ReplaySource
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent
from tests.unit.replay._events import Harness, request, trade
from tests.unit.replay._source import until_parked

#: C-2.17's bound on one loop step, in seconds.
STEP_BUDGET_S = 0.050
#: The default read-ahead, in events; the replay holds a little more than it, 100 us apart, and
#: the span must cover at least three quarters of the fill.
READ_AHEAD = ReadAheadConfig().readahead_events
EVENTS = READ_AHEAD * 17 // 16
FILLED = READ_AHEAD * 3 // 4


class _SortedTier:
    """Trades of one symbol, time-sorted, with bisect range reads. The stock in-memory tier scans
    and sorts every stored row on each read, which is a long loop step of the fixture's own (an
    awaited store would not hold the loop), so the probe would time the stand-in, not the source."""

    def __init__(self, rows: list[RecordedEvent]) -> None:
        self._rows = rows
        self._ts = [row.ts_us for row in rows]

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        lo = bisect.bisect_left(self._ts, rng.start_us)
        hi = bisect.bisect_left(self._ts, rng.end_us)
        return self._rows[lo : min(hi, lo + limit)]

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        return None


@pytest.fixture
def longest_step(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """The duration of every loop callback run while the test body awaits, longest last."""
    steps: list[float] = []
    run = events.Handle._run

    def timed(self: events.Handle) -> None:
        started = time.perf_counter()
        try:
            run(self)
        finally:
            steps.append(time.perf_counter() - started)

    monkeypatch.setattr(events.Handle, "_run", timed)
    was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        yield steps
    finally:
        if was_enabled:
            gc.enable()


@pytest.mark.perf  # a wall-clock budget (C-13.9): run by `py-perf`, not the default unit run
async def test_dense_replay_start_keeps_every_loop_step_under_50_ms(
    longest_step: list[float],
) -> None:
    rows = [trade(i * 100, trade_id=f"t{i:06}") for i in range(EVENTS)]
    harness = Harness(req=request(end_us=60_000_000))
    harness.replace_ports(hot=_SortedTier(rows))
    await asyncio.sleep(0)  # the step that built the fixture is not the producer's
    longest_step.clear()

    async with ReplaySource(harness.req, harness.tiers, config=ReadAheadConfig()) as source:
        await source.__anext__()
        # The consumer is handed the first batch while the producer is still early in the fill; a
        # producer that ran the whole fill in one step would park on the full queue before it.
        at_first_item = source.buffered_events
        await until_parked(source, at_least=FILLED)
        filled = source.buffered_events

    assert at_first_item < FILLED // 2, f"{at_first_item} events queued at the first item"
    assert filled >= FILLED  # the span covered the read-ahead fill, not a short one
    assert max(longest_step) < STEP_BUDGET_S, f"longest loop step {max(longest_step) * 1e3:.1f} ms"

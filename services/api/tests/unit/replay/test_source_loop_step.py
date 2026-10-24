"""`ReplaySource` starts a dense replay without a long loop step (C-2.17, #2731).

The first `__anext__` starts the producer, which merges and queues the whole read-ahead. The
longest single step of the event loop over that start and initial fill must stay under 50 ms,
so WS fan-out and the OMS sharing the loop are not held while a replay opens. The probe times
every loop callback, which is deterministic where a heartbeat task is not. Cyclic GC is off for
the span: a collection over a large heap is a pause of its own, not the producer's.
"""

from __future__ import annotations

import asyncio
import gc
import time
from asyncio import events
from collections.abc import Iterator

import pytest

from candleviewer.replay import ReadAheadConfig, ReplaySource
from tests.unit.replay._events import Harness, request, trade
from tests.unit.replay._source import until_parked

#: C-2.17's bound on one loop step, in seconds.
STEP_BUDGET_S = 0.050
#: Roughly one and a half times the default read-ahead (131 072 events), 100 us apart.
EVENTS = 140_000
FILLED = 100_000


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
    gc.collect()
    gc.disable()
    try:
        yield steps
    finally:
        gc.enable()


@pytest.mark.perf  # a wall-clock budget (C-13.9): run by `py-perf`, not the default unit run
async def test_dense_replay_start_keeps_every_loop_step_under_50_ms(
    longest_step: list[float],
) -> None:
    rows = [trade(i * 100, trade_id=f"t{i:06}") for i in range(EVENTS)]
    harness = Harness(hot=rows, req=request(end_us=60_000_000))
    await asyncio.sleep(0)  # the step that built the fixture is not the producer's
    longest_step.clear()

    async with ReplaySource(harness.req, harness.tiers, config=ReadAheadConfig()) as source:
        await source.__anext__()
        await until_parked(source, at_least=FILLED)
        filled = source.buffered_events

    assert filled >= FILLED  # the span covered the read-ahead fill, not a short one
    assert max(longest_step) < STEP_BUDGET_S, f"longest loop step {max(longest_step) * 1e3:.1f} ms"

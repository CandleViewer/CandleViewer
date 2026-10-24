"""A dense replay step keeps to its share of the event loop (#2668 G1, C-2.17): 100 000 events
through `build_replay_run` (source, clock, injector, `ReplayBooks`, in-process bus) at a 0.25
share, beside a 10 ms sleeper. The probe times every loop callback; cyclic GC is off for the span.
"""

from __future__ import annotations

import asyncio
import bisect
import gc
import statistics
import time
import uuid
from asyncio import events
from collections.abc import Iterator
from decimal import Decimal

import pytest
from prometheus_client import REGISTRY

from candleviewer.bus.bus import Bus
from candleviewer.replay import STEP, LoopTime, PlaybackStats, ReplayGap, ReplayLoopBudget
from candleviewer.replay_wiring import build_replay_run
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedEvent,
    RecordedTrade,
)
from tests.unit.replay._events import SECOND, SYM, T0, Harness, request

STEP_BUDGET_S = 0.050  # C-2.17's bound on one loop step
SHARE, MAX_SHARE_SEEN = 0.25, 0.3
EVENTS = 100_000
SLEEP_S, MAX_OVERSHOOT_S = 0.010, 0.050
REPLAY_TASKS = frozenset({"replay-step", "replay-source"})
STREAMS = (StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA, StreamKind.ORDERBOOK_SNAPSHOT)


def _rows() -> list[RecordedEvent]:
    """A snapshot, then book updates and trades alternating 100 µs apart (10 s of replay)."""
    px = Decimal
    book = RecordedBookSnapshot(200, 1, None, ((px("100.0"), px("1")),), ((px("100.2"), px("1")),))
    rows = [RecordedEvent(T0, 1, SYM, StreamKind.ORDERBOOK_SNAPSHOT, (1, 200, -1), book)]
    for i in range(1, EVENTS):
        ts = T0 + i * 100
        if i % 2:
            uid, size = 1 + (i + 1) // 2, px(1 + i % 7)
            delta = RecordedBookDelta(200, "bid", px("100.1"), size, uid, None)
            key = (uid, 200, "bid", px("100.1"))
            rows.append(RecordedEvent(ts, uid, SYM, StreamKind.ORDERBOOK_DELTA, key, delta))
        else:
            trade = RecordedTrade("buy", px("100.1"), px("0.5"), f"r{i}", None)
            rows.append(RecordedEvent(ts, i, SYM, StreamKind.TRADES, (f"r{i}",), trade))
    return rows


class _SortedTier:
    """Time-sorted rows per stream with bisect range reads: the stock in-memory tier sorts every
    row on each read, a long step of the fixture's own that the probe would time, not replay's."""

    def __init__(self, rows: list[RecordedEvent]) -> None:
        self._rows = {s: [r for r in rows if r.stream is s] for s in STREAMS}
        self._ts = {s: [r.ts_us for r in kept] for s, kept in self._rows.items()}

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        lo = bisect.bisect_left(self._ts[stream], rng.start_us)
        return self._rows[stream][
            lo : min(bisect.bisect_left(self._ts[stream], rng.end_us), lo + limit)
        ]

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        return None


class _Port:
    def on_progress(self, stats: PlaybackStats) -> None: ...

    def on_gap(self, gap: ReplayGap, *, stopped: bool, stats: PlaybackStats) -> None: ...

    def on_backpressure(self, active: bool, stats: PlaybackStats) -> None: ...

    def on_loop(self, generation: int, stats: PlaybackStats) -> None: ...

    def on_stop(self, reason: object, error: Exception | None, stats: PlaybackStats) -> None: ...


@pytest.fixture
def loop_steps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[float, str]]]:
    """Every loop callback run while the test body awaits: its duration and its task's name."""
    steps: list[tuple[float, str]] = []
    run = events.Handle._run

    def timed(self: events.Handle) -> None:
        task = getattr(self._callback, "__self__", None)
        name = task.get_name() if isinstance(task, asyncio.Task) else ""
        started = time.perf_counter()
        try:
            run(self)
        finally:
            steps.append((time.perf_counter() - started, name))

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
async def test_dense_replay_step_keeps_to_its_share_of_the_loop(
    loop_steps: list[tuple[float, str]],
) -> None:
    harness = Harness(req=request(streams=STREAMS, end_us=60 * SECOND))
    harness.replace_ports(hot=_SortedTier(_rows()))
    run = build_replay_run(
        session_id=uuid.uuid4(),
        request=harness.req,
        tick_sizes={SYM: Decimal("0.1")},
        tiers=harness.tiers,
        bus=Bus(),
        port=_Port(),
        speed=STEP,
        budget=ReplayLoopBudget(SHARE, 0.05, LoopTime()),
    )
    overshoot: list[float] = []

    async def sleeper() -> None:
        while True:
            began = time.perf_counter()
            await asyncio.sleep(SLEEP_S)
            overshoot.append(time.perf_counter() - began - SLEEP_S)

    charged = REGISTRY.get_sample_value("replay_loop_seconds_total") or 0.0
    async with run:
        await asyncio.sleep(0)  # the steps that built the fixture are not replay's
        loop_steps.clear()
        began, other = time.perf_counter(), asyncio.create_task(sleeper(), name="sleeper")
        step = asyncio.create_task(run.step_events(EVENTS), name="replay-step")
        assert await step == "step"
        wall = time.perf_counter() - began
        other.cancel()
    charged = (REGISTRY.get_sample_value("replay_loop_seconds_total") or 0.0) - charged

    assert run.stats().events_emitted == EVENTS
    longest = max(d for d, _ in loop_steps)
    replay = sum(d for d, name in loop_steps if name in REPLAY_TASKS)
    p99 = statistics.quantiles(overshoot, n=100)[98]
    assert longest < STEP_BUDGET_S, f"longest loop step {longest * 1e3:.1f} ms"
    assert replay / wall <= MAX_SHARE_SEEN, f"replay took {replay / wall:.3f} of {wall:.1f} s"
    assert charged / wall <= MAX_SHARE_SEEN, f"charged {charged / wall:.3f} of {wall:.1f} s"
    assert p99 < MAX_OVERSHOOT_S, f"sleeper p99 overshoot {p99 * 1e3:.1f} ms"

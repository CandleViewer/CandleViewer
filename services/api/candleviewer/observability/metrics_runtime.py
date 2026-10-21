"""Background metric tasks (E04-T03): loop-lag sampler, cardinality check, fallback snapshot,
and the garbage-collection pause timer (#3641).

The three tasks are plain coroutines the caller owns (TaskGroup / supervisor, C-2.18);
each takes an injected `sleep` so tests drive them deterministically.
"""

from __future__ import annotations

import asyncio
import gc
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any, Final

import structlog

from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import SNAPSHOT_KEYS

#: 100 ms cadence: a 1 s cadence would make a 100 ms alert measure its own error.
LOOP_LAG_INTERVAL_S: Final = 0.1
CARDINALITY_CHECK_INTERVAL_S: Final = 60.0
FALLBACK_SNAPSHOT_INTERVAL_S: Final = 300.0

Sleep = Callable[[float], Awaitable[None]]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.observability.metrics")


async def run_loop_lag_sampler(
    histogram: BoundedMetric,
    clock: Callable[[], float],
    *,
    interval: float = LOOP_LAG_INTERVAL_S,
    sleep: Sleep = asyncio.sleep,
    iterations: int | None = None,
) -> None:
    """Sleep `interval`, record the overshoot. `iterations=None` runs forever."""
    child = histogram.child()
    n = 0
    while iterations is None or n < iterations:
        start = clock()
        await sleep(interval)
        child.observe(max(0.0, clock() - start - interval))
        n += 1


async def run_cardinality_check(
    metrics: Metrics,
    *,
    interval: float = CARDINALITY_CHECK_INTERVAL_S,
    sleep: Sleep = asyncio.sleep,
    iterations: int | None = None,
) -> None:
    """Every 60 s, log the metrics that sit at their `max_series` bound."""
    n = 0
    while iterations is None or n < iterations:
        await sleep(interval)
        breached = metrics.check_cardinality()
        if breached:
            _log().error("metric_cardinality_at_bound", metrics=breached)
        n += 1


def write_fallback_snapshot(metrics: Metrics) -> dict[str, float]:
    """Write one compact snapshot of the key gauges to the structured log."""
    snap = metrics.snapshot(SNAPSHOT_KEYS)
    _log().info("metrics_fallback_snapshot", env=metrics.env, metrics=snap)
    return snap


async def run_fallback_snapshots(
    metrics: Metrics,
    *,
    interval: float = FALLBACK_SNAPSHOT_INTERVAL_S,
    sleep: Sleep = asyncio.sleep,
    iterations: int | None = None,
) -> None:
    """Scrape-failure fallback: a Prometheus outage still leaves a log trail."""
    n = 0
    while iterations is None or n < iterations:
        await sleep(interval)
        write_fallback_snapshot(metrics)
        n += 1


class GcPauseTimer:
    """Times every garbage collection (#3641). Under the GIL a collection on any thread stalls
    the event loop, so a full one (generation 2) can be a C-2.17 block of its own. Each pause goes
    to `cv_gc_pause_seconds{generation}`. After a full collection, `cv_gc_blocks_in_use` reads
    the allocated pymalloc blocks, a proxy for the heap that collection walked: about 55 us to
    read, where counting `gc.get_objects()` costs about 19 ms and is a block itself. It reads 0
    until the first full collection. The callback runs inside the collector on whichever thread
    allocates, so it only reads a clock and updates children bound here; a `stop` without its
    `start` (an `install` from another thread mid-collection) is skipped."""

    def __init__(
        self,
        pauses: BoundedMetric,
        heap: BoundedMetric,
        *,
        clock: Callable[[], float] = time.perf_counter,
        blocks: Callable[[], int] = sys.getallocatedblocks,
        on_pause: Callable[[int, float], None] | None = None,
    ) -> None:
        self._pauses = tuple(pauses.labels(str(generation)) for generation in range(3))
        self._heap = heap.child()
        self._clock, self._blocks, self._on_pause = clock, blocks, on_pause
        self._started: float | None = None

    def __call__(self, phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            self._started = self._clock()
            return
        started, self._started = self._started, None
        if started is None:
            return
        generation, pause = info["generation"], self._clock() - started
        self._pauses[generation].observe(pause)
        if self._on_pause is not None:  # a bench keeps each pause (`bench/ingestion/engine.py`)
            self._on_pause(generation, pause)
        if generation == 2:
            self._heap.set(self._blocks())

    def install(self) -> None:
        """Join `gc.callbacks` once; a second call is a no-op."""
        if self not in gc.callbacks:
            gc.callbacks.append(self)

    def remove(self) -> None:
        """Leave `gc.callbacks`; any other callback stays."""
        if self in gc.callbacks:
            gc.callbacks.remove(self)

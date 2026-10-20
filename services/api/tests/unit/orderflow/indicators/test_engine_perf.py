"""Perf evidence for the indicator engine (E13-T02, #426; `perf` label, C-13.9).

Times one closed-bar update of the whole server set (the nine `compute: server` indicators) on
one symbol, through `IndicatorEngine.emit`: at default parameters, and at period 5000 (the
SR-E13-01 bound) after enough bars for every window to be full. Noise-robust as the big-trade
perf test is: GC disabled around the timed loops, fastest-of-N rounds, and:

* a **generous absolute bound**: the p95 of one close for the whole set stays under 20 ms, the
  backend-internal fan-out envelope the ticket cites (06-performance-and-load-standard.md §6.1,
  budget #6);
* a **consumer ratio**: ten consumers of the same instances cost what one does (within 1.5x):
  the memo makes N consumers O(1) computations (the call count is pinned in
  `test_engine_memo.py`);
* a **period ratio**: period 5000 costs at most 10x the default per close (each kernel is O(1)
  per bar except ZigZag's pivot test and the checkpoint snapshots, which read the window).

These time the engine's update alone, with no listener: the WS fan-out after it is not in them.
A full recompute is timed apart: the longest stretch its read and fold hold the event loop
without letting another task run stays under C-2.17's 50 ms.

E13-Q03 owns the CI regression gate. The p95 measured on the dev laptop is in the PR body."""

from __future__ import annotations

import asyncio
import gc
import time
from bisect import bisect_left
from datetime import datetime, timedelta
from typing import Any, Final

import pytest

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.models import BarSpec, BarUpdate
from candleviewer.bars.reader import BarReader, BarTail
from candleviewer.bars.rows import bar_row
from candleviewer.bars.series_store import SeriesStore
from candleviewer.domain.sql_names import EPOCH_NAIVE
from candleviewer.orderflow.indicators.engine import (
    IndicatorEngine,
    StoredHistory,
    resolve_instances,
)
from tests.unit.orderflow.indicators._engine import M1, SYM, wave

pytestmark = pytest.mark.perf

ROUNDS: Final = 5
TIMED: Final = 200
DEFAULTS: Final[list[dict[str, Any]]] = [
    {"indicator": name}
    for name in ("sma", "ema", "rsi", "atr", "adx", "vwap", "cvd", "volume", "zigzag")
]
LONGEST: Final[list[dict[str, Any]]] = [
    *({"indicator": name, "params": {"n": 5000}} for name in ("sma", "ema", "rsi", "atr", "adx")),
    {"indicator": "vwap"},
    {"indicator": "cvd"},
    {"indicator": "volume"},
    {"indicator": "zigzag", "params": {"depth": 5000}},
]


def _emission(k: int) -> BarEmission:
    return BarEmission(
        M1, 0, (BarUpdate.model_construct(kind="close", bar=wave(k), amended=False),)
    )


async def _per_close_ns(
    instances: list[dict[str, Any]], warm: int, consumers: int = 1
) -> list[int]:
    """The ns of each of `TIMED` closes, after `warm` untimed ones, fastest round of `ROUNDS`
    (each round on a fresh engine)."""
    best: list[int] = []
    for _ in range(ROUNDS):
        store = SeriesStore()
        hold = await store.ensure(SYM, M1)
        engine = IndicatorEngine(store)
        requested = resolve_instances(instances, M1)
        for n in range(consumers):  # system consumers: nine instances pass no user cap
            engine.admit(SYM, M1, requested, f"c{n}", None, history=500)
        for k in range(warm):
            emission = _emission(k)
            await store.emit(emission)
            await engine.emit(emission)
        times: list[int] = []
        gc.collect()
        gc.disable()
        try:
            for k in range(warm, warm + TIMED):
                emission = _emission(k)
                await store.emit(emission)
                t0 = time.perf_counter_ns()
                await engine.emit(emission)
                times.append(time.perf_counter_ns() - t0)
        finally:
            gc.enable()
        hold.release()
        if not best or sum(times) < sum(best):
            best = times
    return best


def _p95(times: list[int]) -> float:
    return sorted(times)[int(len(times) * 0.95)] / 1e6  # ms


async def test_one_close_of_the_whole_server_set_stays_within_the_fan_out_envelope() -> None:
    default = await _per_close_ns(DEFAULTS, warm=100)
    longest = await _per_close_ns(LONGEST, warm=10_100)  # every 5000-bar window is full
    assert _p95(default) < 20.0 and _p95(longest) < 20.0
    assert sum(longest) <= 10 * sum(default)


async def test_ten_consumers_of_the_set_cost_what_one_does() -> None:
    one = await _per_close_ns(DEFAULTS, warm=100)
    ten = await _per_close_ns(DEFAULTS, warm=100, consumers=10)
    assert sum(ten) <= 1.5 * sum(one)


class _Fetch:
    """A PG-wire fake for `BarReader.read_bars`: the stored rows from the query's start, at most its
    `LIMIT`, found by bisection so the fake costs nothing measurable."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.ts = [int(str(r["ts"])) for r in rows]

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        limit = int(sql.rsplit("LIMIT", 1)[1])
        start = params[2]  # `ts_param`: a naive UTC datetime
        assert isinstance(start, datetime)
        first = bisect_left(self.ts, (start - EPOCH_NAIVE) // timedelta(microseconds=1))
        return self.rows[first : first + limit]


async def _no_rebuild(symbol: str, spec_hash: str, from_us: int, to_us: int) -> None:
    return None


async def test_a_full_recompute_never_holds_the_loop_past_c_2_17() -> None:
    """C-2.17 and SR-E13-04 (security review of the WS delivery): eight ZigZag instances (depth
    4 993..5 000, a warmup of up to 10 001 bars) with 1 000 bars of history, on a one-minute
    series (the shortest a topic names) whose generation holds 11 001 closed bars: one admission
    reads the 10 001 bars the store does not hold through `StoredHistory` and a real `BarReader`
    (pages of checked rows), then folds them for each instance. A task that only yields measures
    the loop: its longest wait is the longest stretch the recompute held the loop, and stays
    under 50 ms."""
    bars = [wave(i) for i in range(11_001)]

    async def tail(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        return BarTail([(0, b) for b in bars[-limit:]])

    rows = [bar_row(b, M1, generation=0) for b in bars]
    store = SeriesStore(tail)
    hold = await store.ensure(SYM, M1)
    reader = BarReader(_Fetch(rows), _no_rebuild, now_us=lambda: bars[-1].open_time)
    engine = IndicatorEngine(store, history=StoredHistory(reader))
    deep = [{"indicator": "zigzag", "params": {"depth": d}} for d in range(4_993, 5_001)]
    requested = resolve_instances(deep, M1)
    waits: list[float] = []
    done = asyncio.Event()

    async def loop_probe() -> None:
        last = time.perf_counter()
        while not done.is_set():
            await asyncio.sleep(0)
            now = time.perf_counter()
            waits.append(now - last)
            last = now

    gc.collect()
    gc.disable()  # a collection's pause is not the recompute's
    probe = asyncio.create_task(loop_probe())
    try:
        await asyncio.sleep(0)  # the probe starts measuring
        engine.admit(SYM, M1, requested, "c1", None, history=1_000)
        await asyncio.gather(*list(engine._tasks))
    finally:
        done.set()
        await probe
        gc.enable()
        hold.release()
    for r in requested:
        batch = engine.snapshot(SYM, r.key, 1_000)
        assert batch is not None and batch.points[0].index == 10_001  # primed from the read
    assert max(waits) < 0.050, f"the loop was held {max(waits) * 1e3:.1f} ms"

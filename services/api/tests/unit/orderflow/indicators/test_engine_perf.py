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
Priming is timed apart: the longest stretch an admission, a re-prime on the emit path or a full
recompute's read and fold holds the event loop without letting another task run stays under
C-2.17's 50 ms, a sparse time series' fillers included.

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
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import BarReader, BarTail
from candleviewer.bars.rows import bar_row
from candleviewer.bars.series import BarSeries
from candleviewer.bars.series_store import SeriesStore
from candleviewer.domain.sql_names import EPOCH_NAIVE
from candleviewer.orderflow.indicators.engine import (
    Available,
    IndicatorEngine,
    StoredHistory,
    resolve_instances,
)
from candleviewer.orderflow.indicators.kernels import compute
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, bar_input
from tests.unit.orderflow.indicators._engine import M1, S1, SYM, wave

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


class _LoopProbe:
    """A task that only yields while the test runs: its longest wait is the longest stretch
    anything held the event loop. GC is off meanwhile: a collection's pause is no one's."""

    def __init__(self) -> None:
        self.waits: list[float] = []
        self._done = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> _LoopProbe:
        gc.collect()
        gc.disable()
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0)  # the probe starts measuring
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._done.set()
        if self._task is not None:
            await self._task
        gc.enable()

    async def _run(self) -> None:
        last = time.perf_counter()
        while not self._done.is_set():
            await asyncio.sleep(0)
            now = time.perf_counter()
            self.waits.append(now - last)
            last = now

    def longest(self) -> float:
        return max(self.waits, default=0.0)


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
    try:
        async with _LoopProbe() as probe:
            engine.admit(SYM, M1, requested, "c1", None, history=1_000)
            await asyncio.gather(*list(engine._tasks))
    finally:
        hold.release()
    for r in requested:
        batch = engine.snapshot(SYM, r.key, 1_000)
        assert batch is not None and batch.points[0].index == 10_001  # primed from the read
    assert probe.longest() < 0.050, f"the loop was held {probe.longest() * 1e3:.1f} ms"


#: An illiquid symbol on a one-second series: the store's 1 000 closes, 1 000 s apart (999 empty
#: slots each), so folding them is about a million kernel updates per instance.
SPARSE: Final = [wave(i, spec=S1, slot=i * 1_000) for i in range(1_000)]


def _tails(series: dict[str, list[Bar]]) -> Any:
    """The store's hydration read: each symbol's bars, all of generation 0."""

    async def tail(symbol: str, spec: BarSpec, limit: int) -> BarTail:
        bars = series[symbol][-limit:]
        return BarTail([(0, b) for b in bars], since_us=0, fetched=len(bars))

    return tail


async def test_a_sparse_series_is_primed_without_holding_the_loop_past_c_2_17() -> None:
    """C-2.17 and SR-E13-04 (security review of the WS delivery): eight default instances on the
    sparse series. Folding the store's bars takes far more than `MAX_SYNC_PRIME_UPDATES`, so
    `admit` folds none of them at once: a full recompute folds them, `PRIME_CHUNK_UPDATES` kernel
    updates (and one bar's fillers) at a time. Neither holds the loop 50 ms (about 4 s before),
    and every instance ends with the store's 1 000 points."""
    store = SeriesStore(_tails({SYM: SPARSE}))
    hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store)
    requested = resolve_instances(DEFAULTS[:8], S1)
    try:
        async with _LoopProbe() as probe:
            started = time.perf_counter()
            engine.admit(SYM, S1, requested, "c1", None, history=500)
            admitted = time.perf_counter() - started
            await asyncio.gather(*list(engine._tasks))
    finally:
        hold.release()
    assert admitted < 0.050, f"admit held the loop {admitted * 1e3:.1f} ms"
    assert probe.longest() < 0.050, f"the loop was held {probe.longest() * 1e3:.1f} ms"
    for r in requested:
        batch = engine.snapshot(SYM, r.key, 1_000)
        assert batch is not None and [p.index for p in batch.points] == list(range(1_000))


async def test_a_re_prime_on_the_emit_path_never_holds_the_loop_past_c_2_17() -> None:
    """C-2.17 (security review of the WS delivery): the eight instances re-prime on the emit path
    when a close names another generation (the store missed the swap: a sink that fails is
    skipped, 20 §4.2) and on the store's repair hook. With the slot free the re-prime is a full
    recompute; with it taken (by a read that waits) the store's newest bars within
    `MAX_SYNC_PRIME_UPDATES` are folded at once, here the newest alone. Neither the emit, nor the
    hook, nor any stretch of the recompute holds the loop 50 ms."""
    ticks = [wave(i, spec=S1) for i in range(100, 110)]
    store = SeriesStore(_tails({SYM: SPARSE, "ETHUSDT": ticks}))
    holds = [await store.ensure(SYM, S1), await store.ensure("ETHUSDT", S1)]
    gate = asyncio.Event()

    async def waiting(*_: object) -> list[tuple[int, BarInput]]:
        await gate.wait()
        return []

    engine = IndicatorEngine(store, history=waiting, slots=1)
    requested = resolve_instances(DEFAULTS[:8], S1)
    engine.admit(SYM, S1, requested, "c1", None, history=500)
    await asyncio.gather(*list(engine._tasks))
    swap = BarUpdate.model_construct(kind="close", bar=wave(0, spec=S1, slot=999_001))
    try:
        async with _LoopProbe() as probe:
            started = time.perf_counter()
            await engine.emit(BarEmission(S1, 1, (swap,)))
            emitted = time.perf_counter() - started
            await asyncio.gather(*list(engine._tasks))
            sma = resolve_instances([{"indicator": "sma", "params": {"n": 20}}], S1)
            engine.admit("ETHUSDT", S1, sma, "c2", None, history=5)  # its read takes the slot
            started = time.perf_counter()
            engine.history_repair(SYM, S1, 1)
            repaired = time.perf_counter() - started
            gate.set()
            await asyncio.gather(*list(engine._tasks))
    finally:
        for hold in holds:
            hold.release()
    assert emitted < 0.050, f"the swap's emit held the loop {emitted * 1e3:.1f} ms"
    assert repaired < 0.050, f"the repair held the loop {repaired * 1e3:.1f} ms"
    assert probe.longest() < 0.050, f"the loop was held {probe.longest() * 1e3:.1f} ms"
    for r in requested:
        batch = engine.snapshot(SYM, r.key, 1_000)
        assert batch is not None and [p.index for p in batch.points] == [999]


async def test_a_session_read_of_sparse_bars_is_folded_in_short_chunks() -> None:
    """C-2.17 (security review of the WS delivery): a vwap instance on a one-second series whose
    session holds a bar every 300 s for 23 h. The store holds the newest 76, so its read brings
    the other 200, and the session's 82 500 slots are folded `PRIME_CHUNK_UPDATES` kernel updates
    at a time (one chunk of 512 bars held the loop 64-69 ms before), never 50 ms; the value served
    is the whole session's."""
    day = [wave(i, spec=S1, slot=i * 300) for i in range(276)]

    async def read(
        symbol: str, spec: BarSpec, generation: int, start_us: int, end_us: int
    ) -> list[tuple[int, BarInput]]:
        return [(b.index, bar_input(b)) for b in day if start_us <= b.open_time < end_us]

    store = SeriesStore(_tails({SYM: day[200:]}))
    hold = await store.ensure(SYM, S1)
    engine = IndicatorEngine(store, history=read)
    (r,) = resolve_instances([{"indicator": "vwap"}], S1)
    try:
        async with _LoopProbe() as probe:
            engine.admit(SYM, S1, (r,), "c1", None, history=500)
            await asyncio.gather(*list(engine._tasks))
    finally:
        hold.release()
    assert probe.longest() < 0.050, f"the loop was held {probe.longest() * 1e3:.1f} ms"
    dense = BarSeries(S1, day).densify()
    rows = compute(
        "vwap", [bar_input(b) for b in dense], r.params, source="hlc3", context=KernelContext()
    )
    got = engine.read(SYM, r.key)
    assert isinstance(got, Available) and repr(got.value) == repr(rows[-1][0])

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

E13-Q03 owns the CI regression gate. The p95 measured on the dev laptop is in the PR body."""

from __future__ import annotations

import gc
import time
from typing import Any, Final

import pytest

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.models import BarUpdate
from candleviewer.bars.series_store import SeriesStore
from candleviewer.orderflow.indicators.engine import IndicatorEngine, resolve_instances
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

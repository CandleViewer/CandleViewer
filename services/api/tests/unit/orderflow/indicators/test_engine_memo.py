"""Scenario 2, "One computation serves many consumers" (E13-T02, #426; 24-internal-schemas §7.3):
ten consumers of `atr(14)` on one symbol and bar spec share one instance, which each close updates
once. Verified by a call count on the kernel, not by wall time (the `perf` file times it)."""

from __future__ import annotations

import pytest

from candleviewer.bars.series_store import SeriesStore
from candleviewer.orderflow.indicators.engine import Available, IndicatorEngine
from candleviewer.orderflow.indicators.kernels import AtrKernel
from candleviewer.orderflow.indicators.metrics import (
    indicator_cache_hits_total,
    indicator_cache_misses_total,
)
from candleviewer.orderflow.indicators.types import BarInput, Outputs
from tests.unit.orderflow.indicators._engine import ATR14, M1, SYM, admit, close, counter, wave


@pytest.fixture
def updates(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Every `AtrKernel.update` call, by bar open time: a spy on the kernel class itself."""
    seen: list[int] = []
    real = AtrKernel.update

    def counting(self: AtrKernel, bar: BarInput) -> Outputs:
        seen.append(bar.t)
        return real(self, bar)

    monkeypatch.setattr(AtrKernel, "update", counting)
    return seen


async def test_ten_consumers_of_atr14_cost_one_update_per_bar_close(updates: list[int]) -> None:
    store = SeriesStore()
    hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    hits, misses = counter(indicator_cache_hits_total), counter(indicator_cache_misses_total)
    keys = {
        admit(engine, ATR14, consumer=f"c{i}", user=f"u{i}" if i % 2 else None)[0].key
        for i in range(10)
    }
    assert len(keys) == 1 and engine.instances(SYM, M1.spec_hash) == 1
    for k in range(30):
        await close(store, engine, wave(k))
    assert len(updates) == 30 and len(set(updates)) == 30  # once per close, not ten times
    assert counter(indicator_cache_misses_total) - misses == 1  # one start
    assert counter(indicator_cache_hits_total) - hits == 9  # nine joins of the running instance
    (key,) = keys
    reads = [engine.read(SYM, key) for _ in range(10)]
    assert isinstance(reads[0], Available) and reads == [reads[0]] * 10
    assert (reads[0].index, reads[0].build_version) == (29, AtrKernel.build_version)
    hold.release()


async def test_a_joining_consumer_starts_no_computation_and_sees_the_running_values(
    updates: list[int],
) -> None:
    store = SeriesStore()
    hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    (r,) = admit(engine, ATR14, consumer="first")
    for k in range(20):
        await close(store, engine, wave(k))
    folded = len(updates)
    before = engine.snapshot(SYM, r.key, 500)
    admit(engine, ATR14, consumer="second", user="u2")
    assert len(updates) == folded  # joining re-folds nothing
    assert engine.snapshot(SYM, r.key, 500) == before
    hold.release()


async def test_different_params_or_bar_specs_are_different_instances() -> None:
    store = SeriesStore()
    holds = [await store.ensure(SYM, M1)]
    engine = IndicatorEngine(store)
    a = admit(engine, ATR14)[0].key
    b = admit(engine, [{"indicator": "atr", "params": {"n": 15}}])[0].key
    c = admit(engine, [{"indicator": "atr", "params": {"n": 14.0}}], consumer="c2")[0].key
    assert a != b and a == c  # 14 and 14.0 share one identity (24 §7.4)
    assert engine.instances(SYM, M1.spec_hash) == 2
    for h in holds:
        h.release()

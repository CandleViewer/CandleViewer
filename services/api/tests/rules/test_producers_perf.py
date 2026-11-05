"""Perf evidence for the metric producer bridge's push (E35-T15, #5745; `perf` label, C-13.9).

The ticket's budget: one push through the sink costs at most 5 microseconds at the median (a
dictionary write and one frozen `MetricValue`, no other allocation). Noise-robust as the indicator
engine's perf test is: GC disabled around the timed loop, fastest-of-N rounds, the median of each
round's per-push time, the real metrics facade counting each push. The bookkeeping of a ref's
first push (its key) is outside the loop.

The bar sink's budget: one emission costs at most 100 microseconds at the median with 20 demanded
refs (the five bar fields of four symbols). An emission is one symbol lane's (`bars/builder_set.py`
emits per lane), so each carries one close: its five pushes and its tick are timed, the lookup
of its symbol among the 20 refs included."""

from __future__ import annotations

import gc
import statistics
import time
from decimal import Decimal

import pytest

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.models import BarUpdate
from candleviewer.rules.manager import EvaluableRule
from candleviewer.rules_producers_wiring import BAR_METRICS, BarFieldProducer
from tests.rules.test_instance_binding import rule
from tests.rules.test_producers import TS, Producer, Rig
from tests.rules.test_producers_bars import CLOSE_US, M1, STEP, _bar, _bar_rule, _never

pytestmark = pytest.mark.perf

PUSH_MEDIAN_BUDGET_US = 5.0
ROUNDS, BATCHES, PER_BATCH = 5, 200, 100
EMISSION_MEDIAN_BUDGET_US = 100.0
EMISSIONS = 200
SYMBOLS = ("AUSDT", "BUSDT", "CUSDT", "DUSDT")


async def test_push_median_stays_within_five_microseconds() -> None:
    quote = Producer("quote", {"book_pressure"})
    rig = Rig([rule({"metric": "book_pressure", "params": {"n": 20}}, symbols=("BTCUSDT",))], quote)
    async with rig:
        sink = quote.sink
        assert sink is not None
        (want,) = sink.wanted("book_pressure", "BTCUSDT")
        value = Decimal("0.25")
        assert sink.push(want, "BTCUSDT", value, TS, 100)
        rounds: list[float] = []
        gc.disable()
        try:
            for _ in range(ROUNDS):
                batches: list[float] = []
                for _ in range(BATCHES):
                    t0 = time.perf_counter_ns()
                    for i in range(PER_BATCH):
                        sink.push(want, "BTCUSDT", value, TS + i, 100)
                    batches.append((time.perf_counter_ns() - t0) / PER_BATCH / 1000)
                rounds.append(statistics.median(batches))
        finally:
            gc.enable()
    assert min(rounds) < PUSH_MEDIAN_BUDGET_US, f"push median {min(rounds):.2f} us"


async def test_bar_sink_emission_median_at_twenty_refs_stays_within_100_microseconds() -> None:
    step_us = 1_000  # each emission one ms after the last: a fresh close that pushes and ticks
    now_us = CLOSE_US + ROUNDS * EMISSIONS * step_us + 1_000_000
    producer = BarFieldProducer(lambda: None, lambda _s: STEP, now_us=lambda: now_us, sleep=_never)
    rules = [_bar_rule(m, symbols=SYMBOLS, rid=i + 1) for i, m in enumerate(BAR_METRICS)]
    rig = Rig(rules, producer)  # type: ignore[arg-type]  # a MetricProducer
    rig.items = [EvaluableRule(r, "simulate", None, "v1", "h") for r in rules]
    emissions = [
        BarEmission(M1, i, (BarUpdate(kind="close", bar=_bar(
            symbol=SYMBOLS[i % len(SYMBOLS)], close_us=CLOSE_US + i * step_us
        )),))
        for i in range(ROUNDS * EMISSIONS)
    ]  # fmt: skip
    async with rig:
        assert rig.bridge.demand.size == len(BAR_METRICS) * len(SYMBOLS)  # 20 refs
        for emission in emissions[: len(SYMBOLS)]:  # each key's first push outside the timing
            await producer.emit(emission)
        assert len(rig.ticks) == len(SYMBOLS)
        rounds: list[float] = []
        gc.disable()
        try:
            for r in range(ROUNDS):
                times: list[float] = []
                for emission in emissions[r * EMISSIONS + len(SYMBOLS) : (r + 1) * EMISSIONS]:
                    t0 = time.perf_counter_ns()
                    await producer.emit(emission)
                    times.append((time.perf_counter_ns() - t0) / 1000)
                rounds.append(statistics.median(times))
        finally:
            gc.enable()
        assert len(rig.ticks) == ROUNDS * EMISSIONS - (ROUNDS - 1) * len(SYMBOLS)  # each ticked
    assert min(rounds) < EMISSION_MEDIAN_BUDGET_US, f"emission median {min(rounds):.1f} us"

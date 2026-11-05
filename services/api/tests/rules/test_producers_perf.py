"""Perf evidence for the metric producer bridge's push (E35-T15, #5745; `perf` label, C-13.9).

The ticket's budget: one push through the sink costs at most 5 microseconds at the median (a
dictionary write and one frozen `MetricValue`, no other allocation). Noise-robust as the indicator
engine's perf test is: GC disabled around the timed loop, fastest-of-N rounds, the median of each
round's per-push time, the real metrics facade counting each push. The bookkeeping of a ref's
first push (its key) is outside the loop."""

from __future__ import annotations

import gc
import statistics
import time
from decimal import Decimal

import pytest

from tests.rules.test_instance_binding import rule
from tests.rules.test_producers import TS, Producer, Rig

pytestmark = pytest.mark.perf

PUSH_MEDIAN_BUDGET_US = 5.0
ROUNDS, BATCHES, PER_BATCH = 5, 200, 100


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

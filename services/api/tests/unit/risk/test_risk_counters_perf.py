"""E39-T01 (#881) slice 2 perf (C-13.9): the order-path steps within the 5 ms p95 risk budget
(US-PROF-004, BQ-10) on 20 open positions and a day of 40 000 closes (m6: `figures` is
O(positions), never O(closes)); m10: a venue record and the expiry stay under 1 ms off the order
path (`20-python-backend.md`). GC off, fastest round's p95, as `test_risk_evaluator_perf`."""

from __future__ import annotations

import gc
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import pytest

from candleviewer.risk.counters import AccountCounters
from candleviewer.risk.evaluator import evaluate
from candleviewer.risk.inputs import VenueClosedPnl
from tests.unit.risk._risk_builders import NOW, D, caps, counters, fill, mark, order

pytestmark = pytest.mark.perf

ROUNDS, SAMPLES, CLOSES = 3, 2000, 40_000
BUDGET_NS = 5_000_000
OFF_PATH_NS = 1_000_000
S = timedelta(seconds=1)
LIMIT = caps(
    pol={"max_orders_per_minute": 10**6},
    prof={"max_concurrent_orders": 50, "max_daily_loss_pct": D(5)},
)


def busy_day() -> AccountCounters:
    c = counters()
    for n in range(20):
        symbol = f"S{n:03d}USDT"
        c.apply_fill(fill(f"o{n}", opening=True, symbol=symbol, order_ref=f"r{n}"), NOW)
        c.apply_mark(mark(99, symbol=symbol))
    for n in range(CLOSES):  # one a second over the day so far
        close = fill(f"c{n}", exec_pnl=D(n % 3 - 1), order_ref=f"x{n}")
        c.apply_fill(replace(close, exec_time=NOW - (CLOSES - n) * S), NOW)
    return c


def p95_ns(step: Callable[[int], object]) -> int:
    best, gc_was_on = 0, gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        for r in range(ROUNDS):
            samples: list[int] = []
            for n in range(r * SAMPLES, (r + 1) * SAMPLES):
                started = time.perf_counter_ns()
                step(n)
                samples.append(time.perf_counter_ns() - started)
            p95 = sorted(samples)[int(0.95 * (len(samples) - 1))]
            best = p95 if best == 0 else min(best, p95)
    finally:
        if gc_was_on:
            gc.enable()
    return best


def test_venue_record_and_expiry_p95_on_a_day_of_closes() -> None:  # m10
    c = busy_day()
    later = NOW + 5 * 60 * S
    assert len(c.expire_records(later)) == CLOSES  # once: the day's closes time out
    for n in range(100):  # a few closes still awaiting their records
        c.apply_fill(fill(f"w{n}", exec_pnl=D(-1), order_ref=f"w{n}", exec_time=NOW), later)

    def record(n: int) -> None:  # each matches the key of ~120 closes in its window
        at = NOW - (n * 7 % (CLOSES - 200)) * S
        c.apply_venue_record(
            VenueClosedPnl(f"r{n}", "BTCUSDT", "buy", D(1), D(100), D("0.1"), D(-1), at), later
        )

    record_ns = p95_ns(record)
    expiry_ns = p95_ns(lambda n: c.expire_records(later))
    print(f"record p95 {record_ns / 1e3:.1f} us, expiry p95 {expiry_ns / 1e3:.1f} us")
    assert 0 < record_ns <= OFF_PATH_NS and 0 < expiry_ns <= OFF_PATH_NS


def test_figures_and_evaluate_p95_on_a_day_of_closes() -> None:
    c, o = busy_day(), order(notional=D(100))
    best, gc_was_on = 0, gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        for r in range(ROUNDS):
            samples: list[int] = []
            for n in range(r * SAMPLES, (r + 1) * SAMPLES):  # a close lands, an order is judged
                started = time.perf_counter_ns()
                c.apply_fill(fill(f"n{n}", exec_pnl=D(n % 2 * 2 - 1), order_ref=f"n{n}"), NOW)
                figures = c.figures(NOW)
                ok = figures is not None and evaluate(o, figures, LIMIT, now=NOW).decision.allowed
                samples.append(time.perf_counter_ns() - started)
                assert ok
            p95 = sorted(samples)[int(0.95 * (len(samples) - 1))]
            best = p95 if best == 0 else min(best, p95)
    finally:
        if gc_was_on:
            gc.enable()
    print(f"figures + evaluate p95 {best / 1e3:.1f} us")
    assert 0 < best <= BUDGET_NS, f"p95 {best / 1e3:.0f} us over its budget"

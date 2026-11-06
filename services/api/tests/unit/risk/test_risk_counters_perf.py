"""E39-T01 (#881) slice 2 perf (C-13.9): the order-path steps within the 5 ms p95 risk budget
(US-PROF-004, BQ-10) on 20 open positions and a day of 40 000 closes (m6: `figures` is
O(positions), never O(closes)). GC off, fastest round's p95, as `test_risk_evaluator_perf`."""

from __future__ import annotations

import gc
import time

import pytest

from candleviewer.risk.counters import AccountCounters
from candleviewer.risk.evaluator import evaluate
from tests.unit.risk._risk_builders import NOW, D, caps, counters, fill, mark, order

pytestmark = pytest.mark.perf

ROUNDS, SAMPLES, CLOSES = 3, 2000, 40_000
BUDGET_NS = 5_000_000
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
    for n in range(CLOSES):
        c.apply_fill(fill(f"c{n}", exec_pnl=D(n % 3 - 1), order_ref=f"x{n}"), NOW)
    return c


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

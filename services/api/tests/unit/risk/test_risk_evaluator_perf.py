"""E39-T01 (#881) perf (C-13.9): `evaluate` on its longest path (every cap set, every check passed)
within the order path's 5 ms p95 risk budget (US-PROF-004). The evaluator's own 1 ms target is
recorded in the PR; CI asserts the looser bound. GC off, fastest round's p95, as
`test_trade_groups_perf`."""

from __future__ import annotations

import gc
import time

import pytest

from candleviewer.risk.caps import ManagerCaps
from tests.unit.risk._risk_builders import D, caps, figures, order, run

pytestmark = pytest.mark.perf

ROUNDS, SAMPLES = 3, 2000
BUDGET_NS = 5_000_000


def test_evaluate_p95_within_the_order_path_risk_budget() -> None:
    c = caps(
        prof={
            "max_position_notional_usd": D(50_000),
            "max_position_pct_equity": D(50),
            "max_daily_loss_pct": D(5),
            "max_concurrent_orders": 50,
            "max_consecutive_losses": 5,
            "max_leverage_cap": D(10),
        },
        mgr=ManagerCaps(D(5000)),
    )
    f = figures(
        daily_figure=D("-123.456"),
        day_peak_figure=D("10.5"),
        open_positions=3,
        open_orders=4,
        orders_last_minute=7,
        symbol_notional={f"S{n:03d}USDT": D(1000) for n in range(20)} | {"BTCUSDT": D(5000)},
    )
    o = order()
    assert run(o, f, c).decision.allowed
    best, gc_was_on = 0, gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        for _ in range(ROUNDS):
            samples: list[int] = []
            for _ in range(SAMPLES):
                started = time.perf_counter_ns()
                run(o, f, c)
                samples.append(time.perf_counter_ns() - started)
            p95 = sorted(samples)[int(0.95 * (len(samples) - 1))]
            best = p95 if best == 0 else min(best, p95)
    finally:
        if gc_was_on:
            gc.enable()
    print(f"evaluate p95 {best / 1e3:.1f} us")
    assert 0 < best <= BUDGET_NS, f"p95 {best / 1e3:.0f} us over its budget"

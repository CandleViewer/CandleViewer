"""E40-T03 follow-up (#1867): `AlertEvaluator` with 500 armed alerts over 20 symbols (C-13.9).

Budget: condition -> `alert_deliveries` committed <= 1 s p95 at 500 armed alerts
(E40-T03 "Budgets", US-ALRT-001 NFR; `docs/plan/backlog/E40.json`). The measured span is
`AlertEvaluator.process` for one tick, which covers the condition evaluation, the gating and the
in-memory firing record, so it bounds the condition -> record latency from below; the production
store's own commit is E40-Q02's gate. The alerts mix four comparison ops, both trigger modes and
cooldowns, with distinct thresholds, so the evaluator keeps ~500 subscriptions (the worst case of
the sharing it relies on). The tick stream is a seeded random walk per symbol, one tick per
second on a fake clock. The span includes the `alert_fired` log line each firing renders, as in
production, so the figure errs high. The 1 s bound is the plan's budget and sits far above the
measured figure; a tighter regression tripwire is E40-Q02's gate. Memory has no numeric budget in
the plan: its peak is reported, not asserted. Deselected by default (`-m perf`)."""

from __future__ import annotations

import random
import statistics
import time
import tracemalloc

import pytest

from candleviewer.alerts.evaluator import AlertTick
from tests.alerts._evaluator_env import T0, Row, ir, make, row

pytestmark = pytest.mark.perf

ALERTS = 500
SYMBOLS = 20
TICKS = 2000
SEED = 1867
P95_BUDGET_MS = 1000.0
OPS = ("gt", "lt", "crosses_above", "crosses_below")
BASE = 65000


def _rows(rng: random.Random) -> list[Row]:
    rows = []
    for i in range(ALERTS):
        op = OPS[i % len(OPS)]
        rows.append(
            row(
                f"a{i:03d}",
                symbol=f"S{i % SYMBOLS:02d}USDT",
                condition_ir=ir(op, BASE + rng.randint(-600, 600) + (i * 7) % 13),
                trigger_mode="once" if i % 5 == 0 else "every_time",
                cooldown_seconds=0 if i % 3 else 30,
            )
        )
    return rows


async def _run(*, measure: bool) -> list[float]:
    rng = random.Random(SEED)  # noqa: S311 - seeded, deterministic test data, not crypto
    ev, store, src, clock, _m = make(*_rows(rng))
    await ev.warm_up()
    assert len(ev.alerts) == ALERTS
    prices = {f"S{s:02d}USDT": float(BASE) for s in range(SYMBOLS)}
    samples: list[float] = []
    for n in range(TICKS):
        sym = f"S{rng.randrange(SYMBOLS):02d}USDT"
        prices[sym] += rng.gauss(0, 120)
        clock.now = T0 + n * 1000
        src.set("price", f"{prices[sym]:.2f}", clock.now)
        started = time.perf_counter()
        await ev.process(AlertTick("on_price_update", clock.now, sym))
        if measure:
            samples.append((time.perf_counter() - started) * 1000)
    assert store.deliveries  # the stream does cross thresholds: firing is on the measured path
    return samples


async def test_evaluator_500_armed_alerts_p95_tick_latency_stays_inside_budget() -> None:
    samples = await _run(measure=True)
    p95 = statistics.quantiles(samples, n=20)[-1]
    print(
        f"[perf][E40-T03] {ALERTS} armed alerts / {SYMBOLS} symbols / {TICKS} ticks: "
        f"p95 {p95:.3f} ms, p50 {statistics.median(samples):.3f} ms, max {max(samples):.3f} ms "
        f"(budget {P95_BUDGET_MS:.0f} ms)"
    )
    assert p95 < P95_BUDGET_MS


async def test_evaluator_500_armed_alerts_reports_peak_memory() -> None:
    tracemalloc.start()
    try:
        await _run(measure=False)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    print(f"[perf][E40-T03] {ALERTS} armed alerts: tracemalloc peak {peak / 1024 / 1024:.2f} MiB")
    assert peak > 0  # no numeric memory budget exists in the plan: reported, not asserted

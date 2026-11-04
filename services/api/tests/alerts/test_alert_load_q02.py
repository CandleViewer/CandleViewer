"""E40-Q02 load-harness checks that run without a database (fake clock, in-memory stores).

- Subscription sharing at the ticket's scale: 500 alerts over 40 distinct conditions on 20 symbols
  hold exactly 40 subscriptions (`cv_alert_subscriptions` too), and a firing fans out to members.
- Storm conservation (US-ALRT-002 storm scenario, backend half): 25 qualifying firings for one user
  inside 60 s are each recorded exactly once, delivered + suppressed == 25, and
  `cv_alert_suppressed_total{reason="storm"}` equals the suppressed rows. The existing
  `test_evaluator_storm_25_firings_aggregate_without_losing_history` puts all 25 on one tick; these
  spread them over the window, including seeded random arrival times.
- The latency leg itself (`benchmarks.alerts.latency_leg`) on its sqlite store: deterministic, one
  sample per committed row, and the same firings as the E40-K01 harness for the same stream.
"""

from __future__ import annotations

import random
from decimal import Decimal
from typing import Any

import pytest

from benchmarks.alerts.harness import SYMBOLS, corpus, run_option
from benchmarks.alerts.latency_leg import SqliteFiringStore, everyone, leg_alerts, run_leg
from candleviewer.alerts.evaluator import AlertEvaluator, AlertTick
from candleviewer.alerts.gating import STORM_MAX_DELIVERIES, STORM_WINDOW_MS
from candleviewer.rules.evaluator import MetricValue, metric_key
from candleviewer.rules.ir.models import MetricRef
from tests.alerts._evaluator_env import (
    T0,
    Clock,
    Delivery,
    FakeStore,
    Metrics,
    ir,
    make,
    row,
)

N_STORM = 25


def _cond(symbol: str, const: int) -> dict[str, Any]:
    return {
        "ir_version": 1,
        "trigger": {"type": "on_price_update"},
        "conditions": {"node_id": "c1", "op": "gt",
                       "left": {"metric": "price", "symbol": symbol}, "right": {"const": const}},
    }  # fmt: skip


async def test_load_500_alerts_over_40_conditions_hold_exactly_40_subscriptions() -> None:
    conds = [_cond(SYMBOLS[k % 20], 60000 + k // 20) for k in range(40)]  # 2 thresholds a symbol
    rows = [row(f"a{i:03}", owner_user_id=f"u{i % 7}", symbol=SYMBOLS[i % 40 % 20],
                condition_ir=conds[i % 40]) for i in range(500)]  # fmt: skip
    ev, store, src, _clock, m = make(*rows)
    await ev.warm_up()
    assert len({r.condition_hash for r in rows}) == 40
    assert len(ev.subscriptions) == 40 and m.get("cv_alert_subscriptions") == 40
    assert sorted(len(s.members) for s in ev.subscriptions.values()) == [12] * 20 + [13] * 20
    assert m.get("cv_alerts_armed") == 500
    # price 60000.5 on SYM00: only the 60000 condition holds; it fans out to all its members.
    ref = MetricRef(metric="price", symbol=SYMBOLS[0])
    src.values[metric_key(ref)] = MetricValue(Decimal("60000.5"), T0, 0)
    await ev.process(AlertTick("on_price_update", T0, SYMBOLS[0]))
    fired = {d.alert_id for d in store.deliveries}
    assert fired == {r.id for i, r in enumerate(rows) if i % 40 == 0}
    assert len(ev.subscriptions) == 40  # firing never re-keys a subscription


async def _storm(offsets_ms: list[int]) -> tuple[FakeStore, Clock, Metrics, AlertEvaluator]:
    """One user, one alert per symbol S00..S24 sharing one condition; firing `i` is the tick on
    symbol `i` at `T0 + offsets_ms[i]`, so each tick qualifies exactly one alert."""
    rows = [row(f"a{i:02}", symbol=f"S{i:02}USDT", condition_ir=ir()) for i in range(N_STORM)]
    ev, store, src, clock, m = make(*rows)
    await ev.warm_up()
    assert len(ev.subscriptions) == 1
    for i, off in enumerate(offsets_ms):
        clock.now = T0 + off
        src.set("price", 65500, clock.now)
        await ev.process(AlertTick("on_price_update", clock.now, f"S{i:02}USDT"))
    return store, clock, m, ev


def _firings(ds: list[Delivery]) -> list[Delivery]:
    return [d for d in ds if not d.context.get("storm_summary")]


async def test_storm_25_spread_firings_are_conserved_and_counted_exactly() -> None:
    offsets = [i * 2_400 for i in range(N_STORM)]  # every 2.4 s; the last at 57.6 s, inside 60 s
    store, clock, m, ev = await _storm(offsets)
    firings = _firings(store.deliveries)
    delivered = [d for d in firings if d.status == "queued"]
    suppressed = [d for d in firings if d.status == "suppressed"]
    assert len(delivered) + len(suppressed) == N_STORM == len(firings)
    assert len(delivered) == STORM_MAX_DELIVERIES  # the 21st firing inside the window is the first
    assert [d.alert_id for d in suppressed] == [f"a{i:02}" for i in range(20, 25)]
    assert sorted(d.alert_id for d in firings) == [f"a{i:02}" for i in range(N_STORM)]  # history
    assert m.get("cv_alert_suppressed_total", "storm") == len(suppressed) == 5
    assert store.outbox == [d.id for d in delivered]  # suppressed rows are history, never sent
    clock.now = T0 + STORM_WINDOW_MS  # the window lets the first delivery fall out
    await ev.flush_storms()
    [summary] = [d for d in store.deliveries if d.context.get("storm_summary")]
    assert summary.status == "queued" and summary.context["suppressed"] == len(suppressed)
    assert len(_firings(store.deliveries)) == N_STORM  # the summary adds no firing
    assert m.get("cv_alert_suppressed_total", "storm") == 5  # and counts nothing twice


@pytest.mark.parametrize("seed", range(5))
async def test_storm_conservation_holds_for_seeded_arrivals_inside_one_window(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - seeded, non-cryptographic test data
    offsets = sorted(rng.randrange(STORM_WINDOW_MS) for _ in range(N_STORM))
    store, _clock, m, _ev = await _storm(offsets)
    firings = _firings(store.deliveries)
    n_sup = sum(d.status == "suppressed" for d in firings)
    n_del = sum(d.status == "queued" for d in firings)
    assert n_sup + n_del == N_STORM and n_del == STORM_MAX_DELIVERIES
    assert len({d.alert_id for d in firings}) == N_STORM
    assert m.get("cv_alert_suppressed_total", "storm") == n_sup
    assert len(store.outbox) == n_del


async def test_latency_leg_sqlite_is_deterministic_and_matches_the_k01_harness() -> None:
    ticks = 400
    runs = []
    for _ in range(2):
        alerts = leg_alerts()
        store = SqliteFiringStore(alerts)
        res = await run_leg(store, name="sqlite", ticks=ticks, owners=everyone())
        runs.append((res, store))
    (a, store), (b, _) = runs
    assert a.statuses == b.statuses and len(a.samples_s) == len(b.samples_s) > 0
    assert store.count() == len(a.samples_s) == sum(a.statuses.values())
    assert a.eval_hist_count == a.statuses["queued"]
    assert a.subscriptions == len({x.condition_hash for x in leg_alerts()})
    k01 = run_option("separate", corpus(500, 500), ticks)
    assert k01.deliveries == len(a.samples_s)  # same stream, same firings, real evaluator
    assert a.row()["committed_firings"] == len(a.samples_s)

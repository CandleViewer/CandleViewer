"""E35-T15 PR 2 (#5745): the end-to-end pair the ticket exists for.

A bar closes and an armed rule on `delta` fires once; the producer then stops, the metric goes
stale, a lost feed marks it `source_degraded` and the alert disarms loudly. Clocks are fakes.
The rig's recorded ticks are handed to `RuleEvaluationRunner.process` directly, not through
`RulesService.submit_tick` (its queue and task are the service tests'); the runner is the same.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from candleviewer.alerts.evaluator import AlertEvaluator, AlertMetrics, AlertTick
from candleviewer.alerts.gating import StormSuppressor
from candleviewer.bus.bus import Bus
from candleviewer.exchange.bybit.public_ws import stream_for_topic
from candleviewer.rules.evaluator import EvaluationResult, Evaluator, SnapshotBuilder
from candleviewer.rules.evaluator.snapshot import MetricValue
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.manager import EvaluableRule
from candleviewer.rules.producers import SOURCE_DEGRADED
from candleviewer.rules.runner import EvalTick, RuleEvaluationRunner
from candleviewer.rules_producers_wiring import FeedHealthWatch
from tests.alerts._evaluator_env import Clock as AlertClock
from tests.alerts._evaluator_env import FakeStore, row
from tests.alerts._evaluator_env import Metrics as AlertCounters
from tests.alerts._owners_env import allow
from tests.rules.test_evaluator import Clock as EvalClock
from tests.rules.test_instance_binding import SCOPES, ref
from tests.rules.test_producers import Rig
from tests.rules.test_producers_bars import CLOSE_US, _bar, _bar_rule, _close, _producer, _read
from tests.rules.test_producers_composition import _health

CLOSE_MS = CLOSE_US // 1000


async def test_a_live_bars_delta_fires_an_armed_rule_once() -> None:
    """Scenario: A live bar's delta fires an armed rule once."""
    armed = _bar_rule()
    producer = _producer()
    fires: list[EvaluationResult] = []
    async with Rig([armed], producer) as rig:  # type: ignore[arg-type]  # a MetricProducer
        rig.items = [EvaluableRule(armed, "armed", None, "v1", "h")]
        await producer.emit(_close(_bar(delta="12.5")))
        assert _read(rig, "delta") == MetricValue(Decimal("12.5"), CLOSE_US // 1000, 60_000)
        assert rig.ticks == [("on_bar_close", "BTCUSDT", "1m")]

        async def _rules() -> list[EvaluableRule]:
            return rig.items

        def _factory(r: Rule, snaps: SnapshotBuilder) -> Evaluator:
            clk = EvalClock()
            clk.t = CLOSE_US // 1000 + 1_000
            return Evaluator(r, snaps, clk, clk)

        def _on_fire(_item: EvaluableRule, result: EvaluationResult) -> None:
            if result.fired:
                fires.append(result)

        runner = RuleEvaluationRunner(
            _rules, SnapshotBuilder(rig.source, SCOPES), _factory, lambda _r: None,
            on_fire=_on_fire,
        )  # fmt: skip
        for tick in rig.ticks:
            await runner.process(EvalTick(*tick))
    assert len(fires) == 1 and list(fires[0].metric_values.values()) == [Decimal("12.5")]


def _delta_alert() -> Any:
    condition = {
        "ir_version": 1, "trigger": {"type": "on_bar_close", "timeframe": "1m"},
        "conditions": {"node_id": "c1", "op": "gt", "right": {"const": 0},
                       "left": {"metric": "delta", "symbol": "BTCUSDT", "timeframe": "1m"}},
    }  # fmt: skip
    return row("a1", condition_ir=condition)


@pytest.mark.parametrize("lost_by", ["lost_bound", "feed_stale"])
async def test_a_producer_that_stops_makes_its_metric_stale_and_a_lost_feed_disarms_an_alert_loudly(
    lost_by: str,
) -> None:
    """Scenario: A producer that stops makes its metric stale, and a lost feed disarms an alert
    loudly; and the pair: a bar closes and an armed rule on `delta` fires once."""
    armed = _bar_rule()
    producer = _producer()
    results: list[EvaluationResult] = []
    rig = Rig([armed], producer)  # type: ignore[arg-type]  # a MetricProducer
    rig.items = [EvaluableRule(armed, "armed", None, "v1", "h")]
    watch = FeedHealthWatch(Bus(), "demo", rig.bridge.feed_degraded, stream_for_topic)
    rig.bridge.add(watch)
    eval_clock = EvalClock()
    eval_clock.t = CLOSE_MS + 1_000

    async def _rules() -> list[EvaluableRule]:
        return rig.items

    def _factory(r: Rule, snaps: SnapshotBuilder) -> Evaluator:
        return Evaluator(r, snaps, eval_clock, eval_clock)

    runner = RuleEvaluationRunner(
        _rules, SnapshotBuilder(rig.source, rig.bridge.scopes), _factory, lambda _r: None,
        on_fire=lambda _item, result: results.append(result),
    )  # fmt: skip
    store, alert_clock = FakeStore(_delta_alert()), AlertClock(CLOSE_MS + 1_000)
    alerts = AlertEvaluator(
        store, rig.source, owners=allow(), metrics=AlertMetrics(AlertCounters()),
        storm=StormSuppressor(), clock=alert_clock,
    )  # fmt: skip
    await alerts.warm_up()
    async with rig:
        # A bar closes: delta is pushed, one tick, the armed rule fires exactly once.
        await producer.emit(_close(_bar(delta="12.5")))
        assert rig.ticks == [("on_bar_close", "BTCUSDT", "1m")]
        await runner.process(EvalTick(*rig.ticks[0]))
        assert [r.fired for r in results] == [True]
        await alerts.process(AlertTick("on_bar_close", CLOSE_MS, "BTCUSDT"))
        fired = len(store.deliveries)
        assert fired == 1 and store.rows["a1"].enabled

        # The producer stops: past the stale bound (3 x 60 s) the rule skips and the alert holds.
        eval_clock.t = alert_clock.now = CLOSE_MS + 181_000
        await runner.process(EvalTick("on_bar_close", "BTCUSDT", "1m"))
        assert results[-1].skipped_reason == "stale_data" and not results[-1].fired
        await alerts.process(AlertTick("on_bar_close", alert_clock.now, "BTCUSDT"))
        assert len(store.deliveries) == fired and store.rows["a1"].enabled

        # Lost: the lost bound passes (6 x 60 s), or the trade feed reports itself stale.
        if lost_by == "lost_bound":
            rig.clock.t += 361.0
            assert rig.bridge.watch() == 1
        else:
            assert watch.offer(_health("publicTrade.BTCUSDT")) == 1
        delta = ref("delta", symbol="BTCUSDT", timeframe="1m")
        assert rig.source.read(delta) == MetricValue(None, 0, 0, SOURCE_DEGRADED)  # stale at once
        await alerts.process(AlertTick("on_bar_close", alert_clock.now, "BTCUSDT"))
        assert not store.rows["a1"].enabled
        assert store.deliveries[-1].context == {
            "disarmed": True, "reason": "source_unavailable", "metric": "delta",
        }  # fmt: skip

        # The next push overwrites the mark.
        await producer.emit(_close(_bar(delta="3")))
        assert rig.source.read(delta).value == Decimal(3) and rig.source.read(delta).reason is None

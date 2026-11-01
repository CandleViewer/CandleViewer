"""E35-S02-B1 (#1809): create_app() runs the evaluator behind `rules_evaluator_enabled`."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from candleviewer.app import create_app
from candleviewer.rules.executor.metrics import ExecutorMetrics
from candleviewer.rules.ir.models import MetricRef
from candleviewer.rules.manager import Actor, InMemoryRuleStore
from candleviewer.rules.runner import EvalTick, RuleEvaluationRunner
from candleviewer.rules_oms_wiring import RuleActionAudit, RuleAlerts, RuleRunRecords
from candleviewer.settings import Settings

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
OWNER = Actor("u1", "s1", frozenset({"rules:arm_live"}), is_owner=True, step_up_fresh=True)


def _ir() -> dict[str, Any]:
    raw = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"))
    raw["conditions"]["right"]["const"] = 100
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    return dict(raw)


async def _no_hook(*_args: Any) -> None:
    """No audit backend or bus in these rigs: `bind` keeps the app's hooks unless given these."""


async def _until(pred: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not pred():  # noqa: ASYNC110 - polls state owned by the runner task
            await asyncio.sleep(0.005)


async def test_evaluator_not_constructed_when_flag_off() -> None:
    ctx = create_app().state.app_context
    ctx.rules.bind(store=InMemoryRuleStore())
    await ctx.rules.start(ctx)
    try:
        assert ctx.rules.runner is None
    finally:
        await ctx.rules.stop(1.0)


def test_create_app_binds_the_executors_records_alerts_and_metrics() -> None:
    """E35-T09: the composition root binds the action executor's records written ahead (the run
    row and its events, `rules.fired` and `rules.blocked`), its alerts and its five series (24
    §11.5, BQ-7, BQ-8), with E35-T10's breaker trips and auto-disarms. Unbound, every armed
    action would fail closed and nothing be counted."""
    rules = create_app().state.app_context.rules
    assert rules._records is not None
    run_records, action_audit = rules._records
    assert isinstance(run_records, RuleRunRecords) and isinstance(action_audit, RuleActionAudit)
    assert isinstance(rules._alerts, RuleAlerts) and isinstance(rules._metrics, ExecutorMetrics)
    assert set(rules._metrics._series) == {
        "rule_actions_total", "rule_action_duration_seconds", "rule_actions_blocked_total",
        "rule_dispatch_reread_failed_total", "rule_records_shed_total",
        "rule_circuit_breaker_trips_total", "rule_autodisarm_total",
    }  # fmt: skip


async def test_create_rule_feed_snapshot_evaluator_records_result() -> None:
    """create rule -> simulate -> feed snapshot -> evaluator runs -> result recorded."""
    ctx = create_app(Settings(rules_evaluator_enabled=True)).state.app_context
    ctx.rules.bind(store=InMemoryRuleStore(), audit=_no_hook, broadcast=_no_hook)
    await ctx.rules.start(ctx)
    try:
        runner = ctx.rules.runner
        assert isinstance(runner, RuleEvaluationRunner)
        mgr = ctx.rules.manager()
        assert mgr is not None
        created = await mgr.create(_ir(), OWNER)
        rid = created["id"]
        await mgr.set_mode(rid, "simulate", OWNER, "k-sim")
        ref = MetricRef.model_validate({"metric": "price", "params": {"n": 14}})
        src = ctx.rules.metric_source
        assert src is not None
        src.push(ref, Decimal("150"), time.time_ns() // 1_000_000)
        assert ctx.rules.submit_tick("on_price_update", "BTCUSDT")
        await _until(lambda: runner.processed >= 1 and not ctx.rules._tasks)
        row = await mgr._s.get(rid)
        assert row is not None and row.simulation_fires == 1
    finally:
        await ctx.rules.stop(1.0)


async def test_unpushed_metric_skips_stale_never_fires() -> None:
    ctx = create_app(Settings(rules_evaluator_enabled=True)).state.app_context
    ctx.rules.bind(store=InMemoryRuleStore(), audit=_no_hook, broadcast=_no_hook)
    await ctx.rules.start(ctx)
    try:
        mgr = ctx.rules.manager()
        assert mgr is not None and ctx.rules.runner is not None
        rid = (await mgr.create(_ir(), OWNER))["id"]
        await mgr.set_mode(rid, "simulate", OWNER, "k-sim")
        await ctx.rules.runner.process(EvalTick("on_price_update", "BTCUSDT"))
        row = await mgr._s.get(rid)
        assert row is not None and row.simulation_fires == 0
    finally:
        await ctx.rules.stop(1.0)


async def test_queue_is_bounded_and_drops_oldest() -> None:
    async def _none() -> list[Any]:
        return []

    from candleviewer.rules.evaluator import SnapshotBuilder
    from candleviewer.rules.runner import QUEUE_BOUND, PushedMetricSource

    def _factory(rule: Any, snaps: Any) -> Any:
        raise AssertionError("not reached")

    r = RuleEvaluationRunner(
        _none, SnapshotBuilder(PushedMetricSource()), _factory, lambda _r: None
    )
    for _ in range(QUEUE_BOUND + 5):
        r.submit(EvalTick("on_price_update"))
    assert r.dropped == 5


async def test_stop_cancels_task_and_submit_after_stop_is_refused() -> None:
    ctx = create_app(Settings(rules_evaluator_enabled=True)).state.app_context
    ctx.rules.bind(store=InMemoryRuleStore())
    await ctx.rules.start(ctx)
    await ctx.rules.stop(1.0)
    assert ctx.rules.runner is None
    assert not ctx.rules.submit_tick("on_price_update")


async def test_evaluator_error_is_reported_not_swallowed() -> None:
    errors: list[Exception] = []

    async def _boom() -> list[Any]:
        raise RuntimeError("boom")

    from candleviewer.rules.evaluator import SnapshotBuilder
    from candleviewer.rules.runner import PushedMetricSource

    r = RuleEvaluationRunner(
        _boom,
        SnapshotBuilder(PushedMetricSource()),
        lambda *_: None,
        lambda _r: None,
        errors.append,
    )  # type: ignore[arg-type]  # factory never reached: rules() raises first
    r.start()
    r.submit(EvalTick("on_price_update"))
    await _until(lambda: bool(errors))
    await r.stop()
    assert isinstance(errors[0], RuntimeError)

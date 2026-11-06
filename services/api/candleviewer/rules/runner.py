"""Evaluator runner (E35-S02-B1): schedules the deterministic evaluator off the hot path.

Market/bar/snapshot producers call `submit()` (non-blocking, sync). A single tracked task
drains a bounded queue (C-2.18, drop-oldest + counter on overflow) and, per tick, evaluates
each simulate/armed rule whose trigger type matches (C-2.20: per snapshot, never per book
delta). Each evaluator hands its results to its own `on_result` hook, which the factory sets
(`RulesService.evaluation_sink()`); `on_fire` is the one hook the runner calls, with each result
and the stored facts of the work-list entry it was evaluated for (E35-S03, 24 §11.5).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog

from candleviewer.observability import spawn
from candleviewer.rules.evaluator import (
    Evaluator,
    MetricValue,
    SnapshotBuilder,
    metric_key,
)
from candleviewer.rules.evaluator.engine import EvaluationResult, scope_instance
from candleviewer.rules.evaluator.snapshot import Value
from candleviewer.rules.ir.models import MetricRef, Rule
from candleviewer.rules.manager import EvaluableRule


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


QUEUE_BOUND = 1024


def _log_error(exc: Exception) -> None:
    _log().error("rule evaluation failed", exc_info=exc)


@dataclass(frozen=True, slots=True)
class EvalTick:
    trigger_type: str
    symbol: str | None = None
    #: The bar timeframe of an ``on_bar_close`` tick (the IR's `Trigger.timeframe` string); an
    #: ``on_bar_close`` tick without one matches no rule (fail closed). Other triggers ignore it.
    timeframe: str | None = None


EvaluatorFactory = Callable[[Rule, SnapshotBuilder], Evaluator]


def _instances(rule: Rule, tick: EvalTick) -> list[str]:
    symbols: tuple[str | None, ...] = tuple(rule.scope.symbols) or (None,)
    if tick.symbol is not None and rule.scope.symbols:
        symbols = tuple(s for s in symbols if s == tick.symbol)
    elif tick.symbol is not None:
        symbols = (tick.symbol,)
    accounts: tuple[str | None, ...] = tuple(str(a) for a in rule.scope.account_ids) or (None,)
    return [scope_instance(s, a) for s in symbols for a in accounts]


def _same_timeframe(rule: Rule, tick: EvalTick) -> bool:
    """An ``on_bar_close`` rule runs only on a tick of its own timeframe; a bar-close tick that
    names none matches no rule (missing -> skipped, fail closed)."""
    if rule.trigger.type != "on_bar_close":
        return True
    return tick.timeframe is not None and rule.trigger.timeframe == tick.timeframe


class RuleEvaluationRunner:
    def __init__(
        self,
        rules: Callable[[], Awaitable[list[EvaluableRule]]],
        snapshots: SnapshotBuilder,
        factory: EvaluatorFactory,
        on_result: Callable[[EvaluationResult], None],
        on_error: Callable[[Exception], None] = _log_error,
        *,
        on_fire: Callable[[EvaluableRule, EvaluationResult], None] | None = None,
    ) -> None:
        self._rules, self._snapshots, self._factory = rules, snapshots, factory
        self._on_result, self._on_error, self._on_fire = on_result, on_error, on_fire
        self._queue: asyncio.Queue[EvalTick] = asyncio.Queue(maxsize=QUEUE_BOUND)
        self._evaluators: dict[str, Evaluator] = {}
        self._task: asyncio.Task[None] | None = None
        self.dropped = 0
        self.processed = 0

    def submit(self, tick: EvalTick) -> None:
        """Sync, non-blocking. Full queue drops the OLDEST tick (current state wins, E10)."""
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self.dropped += 1
        self._queue.put_nowait(tick)

    def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._run(), name="rule-runner")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})  # its own cancel raises nothing; one aimed at us goes on
        self._evaluators.clear()

    async def _run(self) -> None:
        while True:
            tick = await self._queue.get()
            try:
                await self.process(tick)
                self.processed += 1
            except Exception as exc:  # one bad tick must not kill the evaluator task
                self._on_error(exc)

    async def process(self, tick: EvalTick) -> None:
        items = await self._rules()
        live = {str(i.rule.rule_id) for i in items}
        for rid in set(self._evaluators) - live:
            del self._evaluators[rid]  # disarmed / deleted: state dropped
        self._snapshots.new_tick()
        for item in items:
            rule = item.rule
            if rule.trigger.type != tick.trigger_type or not _same_timeframe(rule, tick):
                continue
            ev = self._evaluators.get(str(rule.rule_id))
            if ev is None:
                ev = self._evaluators[str(rule.rule_id)] = self._factory(rule, self._snapshots)
            else:
                ev.set_active_version(rule)
            for inst in _instances(rule, tick):
                # Sync: no await mid-evaluation (E2). The fire is handed over with this tick's
                # stored facts, never the ones a cached evaluator was built with.
                result = ev.on_trigger(inst, tick.trigger_type)
                if self._on_fire is not None:
                    self._on_fire(item, result)


def default_clocks() -> tuple[Callable[[], int], Callable[[], int]]:
    return (lambda: time.time_ns() // 1_000_000, lambda: time.monotonic_ns() // 1_000_000)


class PushedMetricSource:
    """Production `MetricSource`: values pushed by metric producers (E12/E18-E25 adapters).

    An unpushed metric reads as unavailable and ancient (`reason="warmup"`, ts 0), so the
    evaluator skips as stale rather than acting on a missing value (E3/E7, fail-safe)."""

    def __init__(self) -> None:
        self._values: dict[str, MetricValue] = {}

    def push(self, ref: MetricRef, value: Value, ts_ms: int, cadence_ms: int = 0) -> None:
        self._values[metric_key(ref)] = MetricValue(value, ts_ms, cadence_ms)

    def push_key(self, key: str, value: Value, ts_ms: int, cadence_ms: int) -> None:
        """`push` for a key the caller computed once as ``metric_key(ref)`` (the producers'
        sink, `rules/producers.py`): one dict write and one `MetricValue`, no key per push."""
        self._values[key] = MetricValue(value, ts_ms, cadence_ms)

    def mark(self, ref: MetricRef, reason: str) -> None:
        """Mark `ref` unavailable for `reason` (e.g. ``source_degraded``, the alert evaluator's
        loud disarm, `alerts/evaluator.SOURCE_LOST_REASONS`); the next push overwrites it. Stamped
        at 0, so it reads stale at once: a rule never evaluates its None (``none_of`` would fire,
        E7), and the alert evaluator reads the reason before staleness."""
        self._values[metric_key(ref)] = MetricValue(None, 0, 0, reason)

    def discard(self, key: str) -> None:
        """Forget a key no rule demands any more, so the source stays bounded by the demand."""
        self._values.pop(key, None)

    def read(self, ref: MetricRef) -> MetricValue:
        return self._values.get(metric_key(ref)) or MetricValue(None, 0, 0, "warmup")

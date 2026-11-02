"""Evaluator runner (E35-S02-B1): schedules the deterministic evaluator off the hot path.

Market/bar/snapshot producers call `submit()` (non-blocking, sync). A single tracked task
drains a bounded queue (C-2.18, drop-oldest + counter on overflow) and, per tick, evaluates
each simulate/armed rule whose trigger type matches (C-2.20: per snapshot, never per book
delta). Each evaluator hands its results to its own `on_result` hook, which the factory sets
(`RulesService.evaluation_sink()`); `on_fire` is the one hook the runner calls, with each result
and the stored facts of the work-list entry it was evaluated for (E35-S03, 24 §11.5).

E35-T13 (24 §11.5 "Signals"): the task also takes the signals waiting on the signal bus, a queue
of their own, in turn with the market ticks so that neither starves the other; a signal is an
`on_signal` tick carrying it, evaluated only for the `on_signal` rules of its owner (RE-S3), and
`on_fire` hears the signal that caused each fire.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

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
from candleviewer.rules.executor.signals import Signal
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
    #: E35-T13: the signal an `on_signal` tick carries (its owner, name, payload and depth), `None`
    #: for any other tick; an `on_signal` tick that carries none reaches no rule (RE-S3).
    signal: Signal | None = None


EvaluatorFactory = Callable[[Rule, SnapshotBuilder], Evaluator]


class OnFire(Protocol):
    """Hears each result with its work-list entry and the signal that caused it, if any."""

    def __call__(
        self, item: EvaluableRule, result: EvaluationResult, signal: Signal | None = None, /
    ) -> None: ...


class SignalSource(Protocol):
    """The signal bus as the runner reads it (`rules/executor/signals.py`)."""

    def take(self) -> Signal | None: ...

    def listen(self, wake: Callable[[], None]) -> None: ...


def rule_owner(rule: Rule) -> UUID | None:
    """The rule's owner, its `created_by`, or `None` when it names no owner: the one reading of
    it, by which `RulesService` stamps a fire's owner (so its signal's) and `_delivers` filters
    each signal, so the two never drift apart (RE-S3)."""
    try:
        return UUID(str(rule.created_by)) if rule.created_by else None
    except ValueError:
        return None


def _delivers(tick: EvalTick, rule: Rule) -> bool:
    """RE-S3 (24 §11.5): an `on_signal` rule evaluates only on a signal of its own owner, and
    never on an `on_signal` tick that carries none; every other trigger evaluates as it did."""
    if rule.trigger.type != "on_signal":
        return True
    return tick.signal is not None and rule_owner(rule) == tick.signal.owner


def _instances(rule: Rule, tick: EvalTick) -> list[str]:
    symbols: tuple[str | None, ...] = tuple(rule.scope.symbols) or (None,)
    if tick.symbol is not None and rule.scope.symbols:
        symbols = tuple(s for s in symbols if s == tick.symbol)
    elif tick.symbol is not None:
        symbols = (tick.symbol,)
    accounts: tuple[str | None, ...] = tuple(str(a) for a in rule.scope.account_ids) or (None,)
    return [scope_instance(s, a) for s in symbols for a in accounts]


class RuleEvaluationRunner:
    def __init__(
        self,
        rules: Callable[[], Awaitable[list[EvaluableRule]]],
        snapshots: SnapshotBuilder,
        factory: EvaluatorFactory,
        on_result: Callable[[EvaluationResult], None],
        on_error: Callable[[Exception], None] = _log_error,
        *,
        on_fire: OnFire | None = None,
        signals: SignalSource | None = None,
    ) -> None:
        self._rules, self._snapshots, self._factory = rules, snapshots, factory
        self._on_result, self._on_error, self._on_fire = on_result, on_error, on_fire
        self._queue: asyncio.Queue[EvalTick] = asyncio.Queue(maxsize=QUEUE_BOUND)
        self._signals = signals
        self._ready = asyncio.Event()  # set when a tick or a signal waits
        self._signal_turn = False  # whose turn it is when both wait
        if signals is not None:
            signals.listen(self._ready.set)
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
        self._ready.set()

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
            tick = await self._next()
            try:
                await self.process(tick)
                self.processed += 1
            except Exception as exc:  # one bad tick must not kill the evaluator task
                self._on_error(exc)

    async def _next(self) -> EvalTick:
        """The next tick to evaluate, waiting while none does."""
        while (tick := self._pick()) is None:
            self._ready.clear()
            await self._ready.wait()
        return tick

    def _pick(self) -> EvalTick | None:
        """A waiting signal and a market tick in turn (24 §11.5): a signal burst never starves the
        market, and the market never starves a chain."""
        self._signal_turn = not self._signal_turn
        first, second = (
            (self._signal_tick, self._market_tick)
            if self._signal_turn
            else (self._market_tick, self._signal_tick)
        )
        return first() or second()

    def _market_tick(self) -> EvalTick | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def _signal_tick(self) -> EvalTick | None:
        signal = None if self._signals is None else self._signals.take()
        return None if signal is None else EvalTick("on_signal", signal=signal)

    async def process(self, tick: EvalTick) -> None:
        items = await self._rules()
        live = {str(i.rule.rule_id) for i in items}
        for rid in set(self._evaluators) - live:
            del self._evaluators[rid]  # disarmed / deleted: state dropped
        self._snapshots.new_tick()
        for item in items:
            rule = item.rule
            if rule.trigger.type != tick.trigger_type or not _delivers(tick, rule):
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
                    self._on_fire(item, result, tick.signal)


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

    def read(self, ref: MetricRef) -> MetricValue:
        return self._values.get(metric_key(ref)) or MetricValue(None, 0, 0, "warmup")

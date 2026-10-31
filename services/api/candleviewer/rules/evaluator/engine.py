"""Evaluation pipeline per trigger (11.5): debounce -> snapshot -> fresh? -> limits -> DAG.

Stops at "decide what to do" (``EvaluationResult.fired``); executing actions is E35-S03.
Single-threaded and synchronous per evaluation, so no ``await`` can interleave a market update
mid-evaluation (E2). Time is injected (``Clock``) for determinism.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from candleviewer.rules.evaluator.nodes import (
    EvalContext,
    InstanceState,
    NodeTrace,
    evaluate,
    referenced_metrics,
)
from candleviewer.rules.evaluator.snapshot import SnapshotBuilder, Value
from candleviewer.rules.ir.models import Rule

Clock = Callable[[], int]  # milliseconds (wall for windows, monotonic for deadlines)
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
PAUSED_MESSAGE = "rules paused — feed degraded"


class EvaluationTimeout(Exception):
    """Raised at a node checkpoint once ``evaluation_timeout_ms`` has elapsed (E8)."""


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    rule_id: str
    rule_version: int
    scope_instance: str
    trigger_type: str
    ts_ms: int
    fired: bool
    skipped_reason: str | None
    condition_trace: tuple[NodeTrace, ...] = ()
    metric_values: dict[str, Value] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class EvaluatorStats:
    evaluations: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    missed_triggers: int = 0
    auto_disarmed: int = 0
    errors: int = 0


@dataclass(slots=True)
class _Instance:
    state: InstanceState = field(default_factory=InstanceState)
    fired_once: bool = False
    last_fire_ms: int | None = None
    fires: deque[int] = field(default_factory=deque)
    last_trigger_ms: int | None = None


def scope_instance(symbol: str | None, account: str | None) -> str:
    """``"BTCUSDT@acct-3f2a"`` (E6); global-scoped parts are ``*``."""
    return f"{symbol or '*'}@{account or '*'}"


class Evaluator:
    def __init__(
        self,
        rule: Rule,
        snapshots: SnapshotBuilder,
        wall_clock: Clock,
        monotonic_ms: Clock,
        on_critical: Callable[[str, str], None] = lambda _rid, _msg: None,
        on_result: Callable[[EvaluationResult], None] | None = None,
        scope_gate: Callable[[str], str | None] | None = None,
    ) -> None:
        # Per-evaluation (not per-tick) consumer hook, e.g. the simulation recorder (C-2.20).
        self._on_result = on_result
        self._scope_gate = scope_gate  # E35-S04: second resolution on every fire
        self._snapshots = snapshots
        self._wall = wall_clock
        self._mono = monotonic_ms
        self._on_critical = on_critical
        self.stats = EvaluatorStats()
        self._instances: dict[str, _Instance] = {}
        self._consecutive_errors = 0
        self.disabled_reason: str | None = None
        self.paused = False
        self.rule = rule
        self._refs = referenced_metrics(rule.conditions)

    def set_active_version(self, rule: Rule) -> None:
        """New version: temporal/cross state is dropped, never inherited."""
        if rule.version != self.rule.version:
            self._instances.clear()
        self.rule = rule
        self._refs = referenced_metrics(rule.conditions)

    # --- disconnect guard (11.7) / reconnect replay safety (E10) -------------------------
    def pause(self) -> str:
        self.paused = True
        return PAUSED_MESSAGE

    def resume(self, instance: str, trigger_type: str) -> EvaluationResult:
        """Re-evaluate current state exactly once; missed triggers are never replayed. Its caller
        must hand the result to the runner's fire hook (`on_fire`, E35-S03): this evaluator's own
        `on_result` only records it, and `on_fire` is the one path to the action emitter."""
        self.paused = False
        return self.on_trigger(instance, trigger_type)

    def rearm(self) -> None:
        """Human re-arm after auto-disable."""
        self.disabled_reason = None
        self._consecutive_errors = 0

    def _skip(self, inst: str, trig: str, now: int, reason: str) -> EvaluationResult:
        self.stats.skipped[reason] = self.stats.skipped.get(reason, 0) + 1
        return EvaluationResult(
            str(self.rule.rule_id), self.rule.version, inst, trig, now, False, reason
        )

    def _limit_reason(self, st: _Instance, now: int) -> str | None:
        lim = self.rule.limits
        if (lim.once or lim.once_per is not None) and st.fired_once:
            return "once"
        if st.last_fire_ms is not None and now - st.last_fire_ms < lim.cooldown_ms:
            return "cooldown"
        while st.fires and now - st.fires[0] >= DAY_MS:
            st.fires.popleft()
        if len(st.fires) >= lim.max_fires_per_day:
            return "rate_limit"
        if sum(1 for t in st.fires if now - t < HOUR_MS) >= lim.max_fires_per_hour:
            return "rate_limit"
        return None

    def on_trigger(self, instance: str, trigger_type: str) -> EvaluationResult:
        result = self._evaluate(instance, trigger_type)
        if self._on_result is not None:
            self._on_result(result)
        return result

    def _evaluate(self, instance: str, trigger_type: str) -> EvaluationResult:
        now = self._wall()
        self.stats.evaluations += 1
        if self.disabled_reason is not None:
            return self._skip(instance, trigger_type, now, "disabled")
        if self.paused:
            self.stats.missed_triggers += 1
            return self._skip(instance, trigger_type, now, "paused")
        if self._scope_gate is not None and self._scope_gate(instance) is not None:
            return self._skip(instance, trigger_type, now, "scope")
        st = self._instances.setdefault(instance, _Instance())
        deb = self.rule.trigger.debounce_ms
        if deb and st.last_trigger_ms is not None and now - st.last_trigger_ms < deb:
            return self._skip(instance, trigger_type, now, "debounce")
        st.last_trigger_ms = now
        deadline = self._mono() + self.rule.limits.evaluation_timeout_ms

        def checkpoint() -> None:
            if self._mono() > deadline:
                raise EvaluationTimeout

        ctx: EvalContext | None = None
        try:
            snap = self._snapshots.build(self._refs, now)
            checkpoint()
            if snap.stale_keys():
                return self._skip(instance, trigger_type, now, "stale_data")
            reason = self._limit_reason(st, now)
            if reason is not None:
                return self._skip(instance, trigger_type, now, reason)
            ctx = EvalContext(snap, st.state, now, checkpoint)
            fired = evaluate(self.rule.conditions, ctx)
            checkpoint()
        except EvaluationTimeout:
            return self._error(instance, trigger_type, now, ctx, "evaluation_timeout")
        except Exception as exc:  # every failure feeds the error budget (E8)
            return self._error(instance, trigger_type, now, ctx, type(exc).__name__)
        self._consecutive_errors = 0  # consecutive, not cumulative
        if fired:
            st.fired_once = True
            st.last_fire_ms = now
            st.fires.append(now)
        skipped = None if fired else ctx.skipped_reason
        if skipped is not None:
            self.stats.skipped[skipped] = self.stats.skipped.get(skipped, 0) + 1
        return EvaluationResult(
            str(self.rule.rule_id), self.rule.version, instance, trigger_type, now, fired,
            skipped, tuple(ctx.trace), dict(ctx.metric_values),
        )  # fmt: skip

    def _error(
        self, inst: str, trig: str, now: int, ctx: EvalContext | None, error: str
    ) -> EvaluationResult:
        self.stats.errors += 1
        self._consecutive_errors += 1
        if self._consecutive_errors >= self.rule.limits.kill_switch_on_error_count:
            self.disabled_reason = f"auto_disabled:{error}"
            self.stats.auto_disarmed += 1
            self._on_critical(str(self.rule.rule_id), self.disabled_reason)
        return EvaluationResult(
            str(self.rule.rule_id), self.rule.version, inst, trig, now, False, None,
            tuple(ctx.trace) if ctx else (), dict(ctx.metric_values) if ctx else {}, error,
        )  # fmt: skip

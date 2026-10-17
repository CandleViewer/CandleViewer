"""Lifecycle contract for the rules module (M15).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.rules.evaluator import Evaluator, SnapshotBuilder
from candleviewer.rules.evaluator.engine import EvaluationResult
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.manager import (
    Audit,
    Broadcast,
    InMemoryRuleStore,
    RulesManager,
    RuleStore,
)
from candleviewer.rules.runner import (
    EvalTick,
    PushedMetricSource,
    RuleEvaluationRunner,
    default_clocks,
)
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from candleviewer.rules.vocabulary import MetricRegistry, default_registry


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _owner_uuid(rule: Rule) -> UUID | None:
    try:
        return UUID(str(rule.created_by)) if rule.created_by else None
    except ValueError:
        return None


async def _discard_actions(_req: object) -> None:
    """Default action sink until E35-S03 lands the executor (nothing is executed)."""


if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.rules.scope import ActionSink, AuditSink, ScopedActionEmitter, ScopeResolver
    from candleviewer.rules.scope_state import ScopeSource, SnapshotScopeState


class RulesService:
    """Empty scaffold for the M15 `rules` module lifecycle."""

    def __init__(self) -> None:
        self._started = False
        self._tasks: set[asyncio.Task[bool]] = set()
        self._registry: MetricRegistry | None = None
        self._manager: RulesManager | None = None
        self._store: RuleStore = InMemoryRuleStore()
        self._audit: Audit | None = None
        self._broadcast: Broadcast | None = None
        #: E35-S02-B1: set by `start()` only when `rules_evaluator_enabled` (C-4.13).
        self.metric_source: PushedMetricSource | None = None
        self.runner: RuleEvaluationRunner | None = None
        self.scope_state: SnapshotScopeState | None = None
        self.scope_resolver: ScopeResolver | None = None
        self._scope_audit: AuditSink | None = None
        self._scope_env: str | None = None
        self._action_sink: ActionSink = _discard_actions  # private: only reachable via the gate

    def bind(
        self,
        *,
        store: RuleStore | None = None,
        audit: Audit | None = None,
        broadcast: Broadcast | None = None,
        action_sink: ActionSink | None = None,
    ) -> None:
        """Composition-root wiring (store / audit / WS fan-out / action executor); before `start`.

        `action_sink` is stored privately and only ever invoked by `ScopedActionEmitter`."""
        if action_sink is not None:
            self._action_sink = action_sink
        if store is not None:
            self._store = store
        self._audit, self._broadcast = audit, broadcast

    def manager(self) -> RulesManager | None:
        """The store/version/mode manager while the module runs; `None` otherwise (-> 503)."""
        return self._manager if self._started else None

    def evaluation_sink(self) -> Callable[[EvaluationResult], None]:
        """Sync `Evaluator(on_result=...)` consumer: schedules recording on the manager
        (per evaluation, off the hot path); dropped silently while the module is stopped."""

        def _sink(result: EvaluationResult) -> None:
            m = self.manager()
            if m is None:
                return
            task = spawn(m.consume_evaluation(result), name="rule-consume-evaluation")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        return _sink

    def wire_scope(
        self,
        source: ScopeSource,
        environment: str,
        audit: AuditSink,
        live_gate_open: Callable[[], bool] = lambda: False,
    ) -> None:
        """E35-S04: production scope state + resolver (live gate closed until E34 wires it)."""
        from candleviewer.rules.scope import ScopeResolver
        from candleviewer.rules.scope_state import SnapshotScopeState

        self._scope_audit = audit
        self._scope_env = environment
        self.scope_state = SnapshotScopeState(source, environment, live_gate_open)
        self.scope_resolver = ScopeResolver(self.scope_state, audit)

    async def refresh_scope(self, owner: UUID) -> None:
        if self.scope_state is not None:
            await self.scope_state.refresh(owner)

    async def _refresh_scope_for(self, rules: list[Rule]) -> None:
        """Re-read grants/freeze for each rule owner; a failed refresh fails closed."""
        if self.scope_state is None:
            return
        for owner in {o for o in (_owner_uuid(r) for r in rules) if o is not None}:
            try:
                await self.scope_state.refresh(owner)
            except Exception:
                _log().exception("scope refresh failed; failing closed for owner")
                self.scope_state.invalidate(owner)

    def build_evaluator(
        self,
        rule: Rule,
        snapshots: SnapshotBuilder,
        wall_clock: Callable[[], int],
        monotonic_ms: Callable[[], int],
        *,
        owner: UUID,
        environment: str,
        on_result: Callable[[EvaluationResult], None] | None = None,
    ) -> Evaluator:
        """The ONLY production Evaluator factory; the scope gate is always installed."""
        from candleviewer.rules.evaluator import Evaluator
        from candleviewer.rules.scope import make_scope_gate

        if self.scope_resolver is None:
            raise RuntimeError("rule scope not wired; refusing to build an ungated evaluator")
        holder: list[Evaluator] = []
        gate = make_scope_gate(
            self.scope_resolver, lambda: holder[0].rule.scope, owner, environment
        )
        ev = Evaluator(
            rule, snapshots, wall_clock, monotonic_ms, on_result=on_result, scope_gate=gate
        )
        holder.append(ev)
        return ev

    def action_emitter(self, sink: ActionSink) -> ScopedActionEmitter:
        """Production evaluator-output boundary (C-2.21): gate, audit denials, then the sink."""
        from candleviewer.rules.scope import ScopedActionEmitter

        if self.scope_resolver is None or self._scope_audit is None:
            raise RuntimeError("rule scope not wired; refusing to emit ungated actions")
        return ScopedActionEmitter(self.scope_resolver, self._scope_audit, sink)

    def registry(self) -> MetricRegistry | None:
        """Metric registry while the engine module is running; `None` otherwise (-> 503)."""
        return self._registry if self._started else None

    async def start(self, ctx: AppContext) -> None:
        """Start the module. No-op until the owning epic implements it."""
        self._registry = default_registry()
        self._manager = RulesManager(self._store, self._registry)
        if self._audit is not None:
            self._manager.set_hooks(audit=self._audit)
        if self._broadcast is not None:
            self._manager.set_hooks(broadcast=self._broadcast)
        self._started = True
        # E35-X02 (i): out-of-band tampering with a protected sys.* rule is audited at boot.
        await self._manager.verify_system_rules()
        if ctx is not None and ctx.settings.rules_evaluator_enabled:
            self._start_evaluator()

    def _start_evaluator(self) -> None:
        manager = self._manager
        if manager is None:
            raise RuntimeError("rules manager not built")
        wall, mono = default_clocks()
        self.metric_source = PushedMetricSource()

        scoped = self.scope_resolver is not None and self._scope_audit is not None
        emitter = self.action_emitter(self._action_sink) if scoped else None
        env = self._scope_env

        def _on_result(result: EvaluationResult, rule: Rule) -> None:
            self.evaluation_sink()(result)
            if emitter is None or env is None:
                return
            if not (result.fired or result.skipped_reason == "scope"):
                return
            owner = _owner_uuid(rule)
            if owner is None:
                return  # fail closed: no owner => no scope to resolve => no action
            sym, _, acct = result.scope_instance.partition("@")
            ref = ScopeInstanceRef(
                result.scope_instance, None if sym == "*" else sym,
                None if acct == "*" else UUID(acct),
            )  # fmt: skip
            for action in rule.actions:
                req = ActionRequest(rule.scope, owner, env, ref, action.type, action)
                task = spawn(emitter.emit(req), name="rule-action-emit")
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

        def _factory(rule: Rule, snaps: SnapshotBuilder) -> Evaluator:
            if emitter is None or env is None:
                # No scope wiring: fail closed. Bare evaluator, simulate-only (see below);
                # it records results but no action is ever emitted.
                return Evaluator(rule, snaps, wall, mono, on_result=self.evaluation_sink())
            owner = _owner_uuid(rule)
            return self.build_evaluator(
                rule, snaps, wall, mono, owner=owner or UUID(int=0),
                environment=env, on_result=lambda r: _on_result(r, rule),
            )  # fmt: skip

        async def _evaluable() -> list[Rule]:
            modes = ("simulate", "armed") if emitter is not None else ("simulate",)
            rules = await manager.evaluable_rules(modes)
            await self._refresh_scope_for(rules)  # revocation/freeze reach every tick (AC1/AC5)
            return rules

        def _on_error(exc: Exception) -> None:
            _log().error("rule evaluator tick failed", exc_info=exc)

        self.runner = RuleEvaluationRunner(
            _evaluable, SnapshotBuilder(self.metric_source), _factory,
            self.evaluation_sink(), _on_error,
        )  # fmt: skip
        self.runner.start()

    def submit_tick(self, trigger_type: str, symbol: str | None = None) -> bool:
        """Producer entry point (market/bar/snapshot adapters): queue an evaluation tick.
        Returns False when the evaluator is disabled/stopped."""
        if self.runner is None:
            return False
        self.runner.submit(EvalTick(trigger_type, symbol))
        return True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds: the manager cancels its tick disarms in
        flight and stops the live B9 rule charts."""
        self._started = False
        if self.runner is not None:
            await self.runner.stop()
        self.runner = self.metric_source = None
        if self._manager is not None:
            await self._manager.stop()
        self._registry = None
        self._manager = None

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")

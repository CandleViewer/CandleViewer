"""Lifecycle contract for the rules module (M15).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID, uuid4

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.rules.evaluator import Evaluator, SnapshotBuilder
from candleviewer.rules.evaluator.engine import EvaluationResult
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.manager import (
    Audit,
    Broadcast,
    EvaluableRule,
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
from candleviewer.rules.scope import ActionRequest, EvaluableMode, ScopeInstanceRef
from candleviewer.rules.vocabulary import MetricRegistry, default_registry

#: Bound on a dispatch's re-read of the rule's row (24 §11.5 check 1), the 2 s the manager gives
#: its disarm beside the tick (`TICK_DISARM_TIMEOUT_S`).
REREAD_TIMEOUT_S: Final = 2.0
#: `rule_dispatch_reread_failed_total{reason}`, a closed set: why a dispatch's re-read of the row
#: failed, its action dropped and nothing sent. `timeout`: no answer within `REREAD_TIMEOUT_S` (or
#: the store's own `TimeoutError`); `store_error`: the read raised anything else.
RereadFailure = Literal["timeout", "store_error"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _owner_uuid(rule: Rule) -> UUID | None:
    try:
        return UUID(str(rule.created_by)) if rule.created_by else None
    except ValueError:
        return None


async def _discard_actions(_req: ActionRequest) -> None:
    """A sink that runs nothing: the simulation sink until E35-S05 swaps it, and the executor's
    downstream until E35-T09 to E35-T12 bind the handlers behind it."""


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
        # Private: only reachable through the scope gate, then `_route`.
        self._action_sink: ActionSink = _discard_actions  # the executor's downstream: no OMS yet
        self._simulation_sink: ActionSink = _discard_actions
        #: `rule_actions_blocked_total{reason}` until E35-T09 makes it a metric (24 §11.9): the
        #: armed actions a dispatch dropped, so far only as `mode_changed`.
        self.actions_blocked_total: Counter[str] = Counter()
        #: `rule_dispatch_reread_failed_total{reason}` until E35-T09 makes it a metric: the armed
        #: actions dropped because the dispatch's re-read failed (24 §11.5 names no `blocked_by`).
        self.dispatch_reread_failed_total: Counter[RereadFailure] = Counter()

    def bind(
        self,
        *,
        store: RuleStore | None = None,
        audit: Audit | None = None,
        broadcast: Broadcast | None = None,
        action_sink: ActionSink | None = None,
        simulation_sink: ActionSink | None = None,
    ) -> None:
        """Composition-root wiring (store / audit / WS fan-out / action executor); before `start`.
        Each option is set only when given, so a later call (E35-S05's simulation sink, the
        executor's handlers) keeps what an earlier one set.

        `action_sink` is the executor's downstream and `simulation_sink` where the actions of a
        simulate rule go (E35-S05 swaps it). Both are stored privately and reached only through
        `ScopedActionEmitter`, which routes by the stored row's mode (`_route`)."""
        if action_sink is not None:
            self._action_sink = action_sink
        if simulation_sink is not None:
            self._simulation_sink = simulation_sink
        if store is not None:
            self._store = store
        if audit is not None:
            self._audit = audit
        if broadcast is not None:
            self._broadcast = broadcast

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

    async def _route(self, req: ActionRequest) -> None:
        """Where a gated action goes (24 §11.5): by the mode the stored row had when the rule was
        evaluated, never the IR's own `mode`. An armed rule's action goes to the executor, unless
        it is `dry_run_only`: that one is simulated, as every action of a simulate rule is."""
        if req.mode == "armed" and not req.payload.dry_run_only:
            await self._execute(req)
        else:
            await self._simulation_sink(req)

    async def _execute(self, req: ActionRequest) -> None:
        """The executor sink: nothing is handed on before the stored row is read again (24 §11.5
        check 1), one point read per action, bounded by `REREAD_TIMEOUT_S`, in the task that emits
        it and never on the evaluation tick (C-2.20). A rule that is gone (or a stopped service),
        no longer armed, or on another active version or `ir_hash` than the fire was evaluated
        under drops the action as `skipped`, `mode_changed`. A read that fails or does not answer
        in time drops it under its `RereadFailure`, never raised out of the task. Each drop is
        counted and logged with the rule id until E35-T09 records results; nothing is sent."""
        manager = self._manager
        try:
            async with asyncio.timeout(REREAD_TIMEOUT_S):
                stored = await manager.current_mode(req.rule_id) if manager is not None else None
        except Exception as failed:  # never `CancelledError`, which is no `Exception`
            reason: RereadFailure = "timeout" if isinstance(failed, TimeoutError) else "store_error"
            self.dispatch_reread_failed_total[reason] += 1
            _log().warning("rules.action_skipped", rule_id=req.rule_id, reason=reason)
            return
        if (
            stored is None
            or stored.mode != "armed"
            or stored.version != req.version
            or stored.ir_hash != req.ir_hash
        ):
            self.actions_blocked_total["mode_changed"] += 1
            _log().info("rules.action_skipped", rule_id=req.rule_id, reason="mode_changed")
            return
        await self._action_sink(req)

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
        emitter = self.action_emitter(self._route) if scoped else None
        env = self._scope_env

        def _on_fire(item: EvaluableRule, result: EvaluationResult) -> None:
            """Hand a fire's actions (a scope-skipped evaluation's too, to be audited) to the
            emitter, each stamped with the stored row's mode as read with this tick's work list."""
            if emitter is None or env is None:
                return
            if not (result.fired or result.skipped_reason == "scope"):
                return
            rule = item.rule
            owner = _owner_uuid(rule)
            if owner is None:
                return  # fail closed: no owner => no scope to resolve => no action
            sym, _, acct = result.scope_instance.partition("@")
            ref = ScopeInstanceRef(
                result.scope_instance, None if sym == "*" else sym,
                None if acct == "*" else UUID(acct),
            )  # fmt: skip
            run_id = uuid4()  # the fire's id: its actions share it (24 §11.9)
            for action in rule.actions:
                req = ActionRequest(
                    rule_scope=rule.scope, owner=owner, environment=env, instance=ref,
                    action_type=action.type, payload=action, mode=item.mode,
                    rule_id=str(rule.rule_id), version=rule.version, ir_hash=item.ir_hash,
                    run_id=run_id, armed_by=item.armed_by,
                )  # fmt: skip
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
                environment=env, on_result=self.evaluation_sink(),
            )  # fmt: skip

        async def _evaluable() -> list[EvaluableRule]:
            modes: tuple[EvaluableMode, ...] = (
                ("simulate", "armed") if emitter is not None else ("simulate",)
            )
            items = await manager.evaluable_rules(modes)
            # Revocation/freeze reach every tick (AC1/AC5).
            await self._refresh_scope_for([item.rule for item in items])
            return items

        def _on_error(exc: Exception) -> None:
            _log().error("rule evaluator tick failed", exc_info=exc)

        self.runner = RuleEvaluationRunner(
            _evaluable, SnapshotBuilder(self.metric_source), _factory,
            self.evaluation_sink(), _on_error, on_fire=_on_fire,
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

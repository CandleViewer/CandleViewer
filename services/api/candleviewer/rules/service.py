"""Lifecycle contract for the rules module (M15).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from time import monotonic
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.rules.evaluator import Evaluator, SnapshotBuilder
from candleviewer.rules.evaluator.engine import EvaluationResult
from candleviewer.rules.executor.dispatch import AuditDispatch, Fire, FireDispatch, JobKind
from candleviewer.rules.executor.engine import ActionExecutor, RowVerdict
from candleviewer.rules.executor.metrics import ExecutorMetrics
from candleviewer.rules.executor.metrics import RereadFailure as RereadFailure
from candleviewer.rules.executor.ports import ActionAudit, AlertPort, RunRecords
from candleviewer.rules.executor.results import BlockedBy
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
#: its disarm beside the tick (`TICK_DISARM_TIMEOUT_S`). Why one failed is `RereadFailure`
#: (`rule_dispatch_reread_failed_total{reason}`): `timeout`, no answer within it (or the store's
#: own `TimeoutError`), or `store_error`, the read raised anything else.
REREAD_TIMEOUT_S: Final = 2.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _owner_uuid(rule: Rule) -> UUID | None:
    try:
        return UUID(str(rule.created_by)) if rule.created_by else None
    except ValueError:
        return None


async def _discard_actions(_req: ActionRequest) -> None:
    """A sink that runs nothing: the simulation sink until E35-S05 swaps it. As the executor's
    downstream it is no stand-in: the handler table refuses every action no handler is bound for
    (`unavailable`) until E35-T10 to E35-T13 bind them."""


async def _never_dispatched(_req: ActionRequest) -> None:
    """The audit-only emitter's sink, which no `bind` reaches: a scope-skipped evaluation never
    fired, so its actions are audited (the emitter's denial, per action) and never dispatched,
    whatever the emitter's re-check finds."""


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
        # E35-T09: the executor's records written ahead, its alerts and its metrics (unbound: no
        # record can be written, so no armed action is handed over; no alert; nothing counted).
        self._records: tuple[RunRecords, ActionAudit] | None = None
        self._alerts: AlertPort | None = None
        self._metrics = ExecutorMetrics()
        self._executor: ActionExecutor | None = None  # while the evaluator runs
        self._dispatch: FireDispatch | None = None  # the fire queue, while the evaluator runs
        self._audits: AuditDispatch | None = None  # the record-only jobs' queue, beside it

    def bind(
        self,
        *,
        store: RuleStore | None = None,
        audit: Audit | None = None,
        broadcast: Broadcast | None = None,
        action_sink: ActionSink | None = None,
        simulation_sink: ActionSink | None = None,
        records: tuple[RunRecords, ActionAudit] | None = None,
        alerts: AlertPort | None = None,
        metrics: ExecutorMetrics | None = None,
    ) -> None:
        """Composition-root wiring (store / audit / WS fan-out / action executor); before `start`.
        Each option is set only when given, so a later call (E35-S05's simulation sink, the
        executor's handlers) keeps what an earlier one set.

        `action_sink` is the executor's downstream and `simulation_sink` where the actions of a
        simulate rule go (E35-S05 swaps it). Both are stored privately and reached only through
        `ScopedActionEmitter`, which routes by the stored row's mode (`_route`). A bound
        `action_sink` stands in for the engine-internal handlers no slice has bound, never for an
        action that would reach the OMS (`ActionExecutor`). `records` are the executor's two
        write-ahead ports, `alerts` its partial-fire and write-ahead alerts and `metrics` its
        series (E35-T09, `rules_oms_wiring`)."""
        if action_sink is not None:
            self._action_sink = action_sink
        if simulation_sink is not None:
            self._simulation_sink = simulation_sink
        if records is not None:
            self._records = records
        if alerts is not None:
            self._alerts = alerts
        if metrics is not None:
            self._metrics = metrics
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
        evaluated, never the IR's own `mode`. An armed rule's action goes back to the executor,
        which passed it through the emitter, unless it is `dry_run_only`: that one is simulated,
        as every action of a simulate rule is."""
        if req.mode == "armed" and not req.payload.dry_run_only:
            if self._executor is None:
                raise RuntimeError("an armed action outside a running executor")
            await self._executor.hand_over(req)
        else:
            await self._simulation_sink(req)

    async def _check_one(self, req: ActionRequest) -> RowVerdict:
        """Check 1 (24 §11.5): the stored row read again, one point read per action, bounded by
        `REREAD_TIMEOUT_S`, in a dispatch worker and never on the evaluation tick (C-2.20). A rule
        that is gone (or a stopped service), no longer armed, or on another active version or
        `ir_hash` than the fire was evaluated under is `mode_changed`; a read that fails or does
        not answer in time is `unread`, counted under its `RereadFailure` (BQ-6). Each is logged
        with the rule id; the executor skips the rest of the fire."""
        manager = self._manager
        try:
            async with asyncio.timeout(REREAD_TIMEOUT_S):
                stored = await manager.current_mode(req.rule_id) if manager is not None else None
        except Exception as failed:  # never `CancelledError`, which is no `Exception`
            reason: RereadFailure = "timeout" if isinstance(failed, TimeoutError) else "store_error"
            self._metrics.reread_failed(reason)
            _log().warning("rules.action_skipped", rule_id=req.rule_id, reason=reason)
            return "unread"
        if (
            stored is None
            or stored.mode != "armed"
            or stored.version != req.version
            or stored.ir_hash != req.ir_hash
        ):
            _log().info("rules.action_skipped", rule_id=req.rule_id, reason="mode_changed")
            return "mode_changed"
        return "armed"

    async def _recheck(self, req: ActionRequest) -> BlockedBy | None:
        """The checks that exist, run again before `retry_once`'s retry (24 §11.9): check 1, then
        the scope re-check. E35-T10 adds its checks here."""
        if await self._check_one(req) != "armed":
            return "mode_changed"
        resolver = self.scope_resolver
        if resolver is None:
            return "scope"
        refused = resolver.check_action(req.rule_scope, req.owner, req.environment, req.instance)
        return None if refused is None else "scope"

    def _refused(self, fire: Fire, first: bool) -> None:
        """A fire the full queue refused (24 §11.5), on the tick: each of its actions is counted
        `blocked` (`backpressure`), its rule's first refusal of the episode is logged as
        `rules.blocked` with that reason, and its records go off the tick, as one record-only job
        on the audit queue, offered and never awaited (BQ-4): a full one sheds it (`_shed`)."""
        for req in fire.requests:
            self._metrics.refused(req.action_type, "backpressure")
        if first:
            _log().warning(
                "rules.blocked", rule_id=fire.rule_id, run_id=str(fire.run_id),
                reason="backpressure", actions=len(fire.requests),
            )  # fmt: skip
        if self._audits is not None:
            self._audits.offer(replace(fire, kind="refused_fire"))

    def _shed(self, job: Fire, first: bool) -> None:
        """A record-only job the full audit queue shed, on the tick: counted under its kind
        (`rule_records_shed_total{kind}`), never awaited; its actions were counted when the job was
        offered. Its rule's first of the episode is logged, saying which records were lost."""
        self._metrics.shed("refused_fire" if job.kind == "refused_fire" else "scope_denial")
        if first:
            _log().warning(
                "rules.records_shed", rule_id=job.rule_id, run_id=str(job.run_id),
                kind=job.kind, actions=len(job.requests),
            )  # fmt: skip

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
        audit_only = self.action_emitter(_never_dispatched) if scoped else None
        env = self._scope_env
        run_records, action_audit = self._records or (None, None)
        stand_in = None if self._action_sink is _discard_actions else self._action_sink
        executor = self._executor = ActionExecutor(
            check_one=self._check_one, recheck=self._recheck, records=run_records,
            audit=action_audit, alerts=self._alerts, metrics=self._metrics, stand_in=stand_in,
        )  # fmt: skip
        dispatch = self._dispatch = FireDispatch(self._refused, executor.execute)
        audits = self._audits = AuditDispatch(self._shed, executor.execute)
        dispatch.start()
        audits.start()

        def _on_fire(item: EvaluableRule, result: EvaluationResult) -> None:
            """Offer one evaluation's actions, never awaited (C-2.20), each stamped with the stored
            row's mode as read with this tick's work list. Only a fired result's actions reach the
            routing emitter (`_route`), on the fire queue, with the run row's facts; a
            scope-skipped result's go through the audit-only one, on the audit queue: audited per
            action, never dispatched, whatever the emitter's re-check finds, and never in a fire's
            slot or lane. The tick's scope gate refused them, so each counts under `scope` as it
            is offered, written or shed (BQ-5)."""
            if emitter is None or audit_only is None or env is None:
                return
            kind: JobKind
            if result.fired:
                emit, queue, kind = emitter.emit, dispatch, "fire"
            elif result.skipped_reason == "scope":
                emit, queue, kind = audit_only.emit, audits, "scope_denial"
            else:
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
            reqs = tuple(
                ActionRequest(
                    rule_scope=rule.scope, owner=owner, environment=env, instance=ref,
                    action_type=action.type, payload=action, mode=item.mode,
                    rule_id=str(rule.rule_id), version=rule.version, ir_hash=item.ir_hash,
                    run_id=run_id, armed_by=item.armed_by,
                )
                for action in rule.actions
            )  # fmt: skip
            if kind == "scope_denial":
                for req in reqs:
                    self._metrics.refused(req.action_type, "scope")
            queue.offer(
                Fire(
                    str(rule.rule_id), run_id, reqs, emit, kind=kind, version_id=item.version_id,
                    trigger_type=result.trigger_type, metric_values=result.metric_values,
                )
            )  # fmt: skip

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
        """Stop the module within `grace_s` seconds: the runner first, so no fire is offered
        after it; the workers of the fire queue, then of the audit queue in what is left of that
        one grace, drain them while the manager still answers the re-reads; then the manager
        cancels its tick disarms in flight and stops the live B9 rule charts. A cancel during the
        runner's stop or the fire queue's drain goes on to the caller, and ends both queues'
        workers at once too (#5231's carry RC-02): no queue outlives the module."""
        self._started = False
        deadline, drained = monotonic() + grace_s, False
        try:
            if self.runner is not None:
                await self.runner.stop()
            self.runner = self.metric_source = None
            if self._dispatch is not None:
                await self._dispatch.stop(max(0.0, deadline - monotonic()))
            drained = True
        finally:
            if self._dispatch is not None and not drained:
                await self._dispatch.stop(0.0)  # a no-op once its own stop has begun
            if self._audits is not None:
                await self._audits.stop(max(0.0, deadline - monotonic()) if drained else 0.0)
            self._dispatch = self._audits = self._executor = None
        if self._manager is not None:
            await self._manager.stop()
        self._registry = None
        self._manager = None

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")

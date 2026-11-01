"""The rule action executor's write-ahead adapters, at the composition root (E35-T09 part 1; 24
§11.5 "The records written ahead", §15.5; the E35 threat model's RE-R1).

`rules` imports neither `storage` nor `audit` (`forbidden-M15`), so the executor's two ports are
bound here: `RuleRunRecords` over `SqlAlchemyRulesRepository` (the run row, its events and its
close, under the fire's own id) and `RuleActionAudit` over the audit writer (`rules.fired` and
`rules.blocked`, keyed by the action's `dedupe_key`). A record names the rule as its actor with no
user id and no request id (04 SR-062), and both users' roles as the principal snapshot the action
was checked against gave them, `None` when it was not read (E35-T10, BQ-5).
`RuleAlerts` binds the executor's alerts to the page line and to `system_events` (BQ-7), and
`rule_metrics` its series to the app's metrics facade (BQ-8); `app.py` binds all three. E35-T10's
`rule_switches` binds checks 2 and 3 to the two flag views and the B18 verdict the OMS takes, and
`rule_order_budget` the SR-104 order budget, its counts rebuilt over the rules repository and its
boot settings refused above their hard caps; `RuleAlerts` also pages the circuit breaker's trips.
Outcome and severity go as their values (C-3.3 keeps `audit` from this module, as from
`oms_stream_wiring`). Nothing here logs: the input snapshot is financial and confidential (21
§3.4.3).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.domain.primitives import AccountId
from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter
from candleviewer.observability.metrics import Metrics
from candleviewer.rules.executor.budget import DAY_S, OrderBudget
from candleviewer.rules.executor.handlers import COUNTS_ORDERS
from candleviewer.rules.executor.metrics import ExecutorMetrics
from candleviewer.rules.executor.ports import ActionAuditFields, EventRow, RunRow, RunStatus
from candleviewer.rules.limits import ORDER_BUDGET_CAPS, SIGNAL_MAX_DEPTH_CAP
from candleviewer.storage.repositories.rules_sqlalchemy import (
    RuleEventInsert,
    SqlAlchemyRulesRepository,
)

#: Each alert's `system_events` row: component `rules`, its kind and a fixed message; the ids
#: ride in `details`, so the incident gathers every occurrence under one entry.
AlertKind = Literal["partial_fire", "write_ahead_failed", "circuit_breaker"]
_ALERT_MESSAGES: Final[dict[str, str]] = {
    "partial_fire": "A rule fire partly took effect: one of its actions did not succeed.",
    "write_ahead_failed": "A rule action was not sent: its records could not be written ahead.",
    "circuit_breaker": "A rule's circuit breaker tripped: its order budget was spent.",
}
#: The bound on one alert's `system_events` write, in the dispatch worker.
ALERT_EVENT_TIMEOUT_S: Final = 2.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class KeyedAuditEmitter(Protocol):
    """`AuditWriter.emit_keyed`, as the app's `_LazyAuditEmitter` forwards it."""

    async def emit_keyed(self, action: str, name: str, **fields: Any) -> None: ...


class RunNotPersisted(RuntimeError):
    """The repository wrote no row for a fire's run (it persists matched runs only): the fire
    stops as for a failed write, before any action is handed over."""


def _insert(event: EventRow) -> RuleEventInsert:
    return RuleEventInsert(
        event.seq, event.kind, event.node_ref, dict(event.payload), event.severity
    )


class RuleRunRecords:
    """`RunRecords` over the rules repository: one unit of work per call."""

    def __init__(self, repository: SqlAlchemyRulesRepository) -> None:
        self._repository = repository

    async def begin(self, run: RunRow, first: EventRow) -> None:
        written = await self._repository.record_run(
            run_id=str(run.run_id), rule_id=run.rule_id, version_id=run.version_id,
            mode=run.mode, trigger_reason=run.trigger_reason,
            input_snapshot=dict(run.input_snapshot), status="running", matched=run.matched,
            symbol=run.symbol, account_id=None if run.account_id is None else str(run.account_id),
            events=(_insert(first),),
        )  # fmt: skip
        if written != str(run.run_id):
            raise RunNotPersisted("the fire's run row was not persisted")

    async def append(self, run_id: UUID, events: Sequence[EventRow]) -> None:
        await self._repository.append_events(str(run_id), [_insert(e) for e in events])

    async def close(self, run_id: UUID, status: RunStatus, duration_ms: int) -> None:
        await self._repository.close_run(str(run_id), status=status, duration_ms=duration_ms)


class RuleActionAudit:
    """`ActionAudit` over the audit writer: each record keyed by the action's `dedupe_key`, in its
    action's own namespace, so a retried write of either lands once (24 §15.5)."""

    def __init__(self, emitter: KeyedAuditEmitter) -> None:
        self._emitter = emitter

    async def fired(self, fields: ActionAuditFields) -> None:
        if fields.blocked_by is not None:
            raise ValueError("an admitted action names no blocked_by")
        await self._emitter.emit_keyed(
            "rules.fired", fields.dedupe_key, outcome="success",
            severity="info", reason=None, **_entry(fields),
        )  # fmt: skip

    async def blocked(self, fields: ActionAuditFields) -> None:
        if fields.blocked_by is None:
            raise ValueError("a refusal names its blocked_by")
        await self._emitter.emit_keyed(
            "rules.blocked", fields.dedupe_key, outcome="denied",
            severity="warning", reason=fields.blocked_by, **_entry(fields),
        )  # fmt: skip


def _entry(fields: ActionAuditFields) -> dict[str, Any]:
    """The record's actor, object and `after_state`: ids and names only, under names the writer's
    redactor keeps (it hides a `*_hash` and a `*_key` field), never a parameter or a figure."""
    after: dict[str, Any] = {
        "actor_type": "rule", "rule_id": fields.rule_id, "version": fields.version,
        "ir_sha256": fields.ir_hash, "run_id": str(fields.run_id), "node_id": fields.node_id,
        "action_type": fields.action_type, "scope_instance": fields.scope_instance,
        "account_id": None if fields.account_id is None else str(fields.account_id),
        "owner_user_id": str(fields.owner), "owner_role": fields.owner_role,
        "armed_by_user_id": fields.armed_by, "armed_by_role": fields.armed_by_role,
        "dedupe_sha256": fields.dedupe_key,
    }  # fmt: skip
    if fields.blocked_by is not None:
        after["blocked_by"] = fields.blocked_by
    return {
        "actor_label": f"rule:{fields.rule_id}@v{fields.version}", "actor_user_id": None,
        "object_kind": "rule", "object_id": fields.rule_id, "after_state": after,
        "request_id": None,
    }  # fmt: skip


def rule_action_records(
    repository: SqlAlchemyRulesRepository, emitter: KeyedAuditEmitter
) -> tuple[RuleRunRecords, RuleActionAudit]:
    """The executor's two write-ahead ports, for `RulesService.bind` (E35-T09's dispatch)."""
    return RuleRunRecords(repository), RuleActionAudit(emitter)


class RuleAlerts:
    """`AlertPort` over its two routes (BQ-7): the CRITICAL `cv_page=true` line at most once per
    rule and kind per episode, synchronous and never awaited (the episode ends when that rule's
    next fire ends with no partial outcome, `settled`), and one `system_events` row per occurrence
    (component `rules`, at `critical`, which opens or updates its incident), awaited in the
    dispatch worker under its own bound. A row that is not written is counted and logged, never
    raised, so it never holds the next fire."""

    def __init__(self, events: SystemEventWriter | None) -> None:
        self._events = events
        self._paged: set[tuple[AlertKind, str]] = set()
        self.events_failed_total = 0

    async def partial_fire(self, rule_id: str, run_id: UUID, node_id: str) -> None:
        await self._alert("partial_fire", rule_id, run_id, node_id)

    async def write_ahead_failed(self, rule_id: str, run_id: UUID, node_id: str) -> None:
        await self._alert("write_ahead_failed", rule_id, run_id, node_id)

    def settled(self, rule_id: str) -> None:
        self._paged.discard(("partial_fire", rule_id))
        self._paged.discard(("write_ahead_failed", rule_id))

    def breaker_tripped(self, rule_id: str, run_id: UUID, node_id: str) -> None:
        """The P1 page of a trip (24 §11.7, BQ-8): the `cv_page` CRITICAL line, on every trip,
        never deduplicated by episode."""
        ids = {"rule_id": rule_id, "run_id": str(run_id), "node_id": node_id}
        _log().critical("rules.circuit_breaker_tripped", cv_page=True, **ids)

    async def breaker_moved(self, rule_id: str, run_id: UUID, node_id: str, *, moved: bool) -> None:
        """The trip's one `system_events` row, saying whether the rule was moved; a rule that was
        not moved is paged again."""
        ids = {"rule_id": rule_id, "run_id": str(run_id), "node_id": node_id}
        if not moved:
            _log().critical("rules.circuit_breaker_not_moved", cv_page=True, **ids)
        await self._event("circuit_breaker", ids | {"moved": "true" if moved else "false"})

    async def _alert(self, kind: AlertKind, rule_id: str, run_id: UUID, node_id: str) -> None:
        ids = {"rule_id": rule_id, "run_id": str(run_id), "node_id": node_id}
        if (kind, rule_id) not in self._paged:
            self._paged.add((kind, rule_id))
            _log().critical(f"rules.{kind}", cv_page=True, **ids)
        await self._event(kind, ids)

    async def _event(self, kind: AlertKind, ids: dict[str, str]) -> None:
        if self._events is None:
            return
        event = SystemEvent("rules", kind, "critical", _ALERT_MESSAGES[kind], ids)
        try:
            async with asyncio.timeout(ALERT_EVENT_TIMEOUT_S):
                await self._events.write(event)
        except Exception as exc:  # never `CancelledError`, which is no `Exception`
            self.events_failed_total += 1
            _log().error("rules.alert_event_failed", kind=kind, cause=type(exc).__name__, **ids)


def rule_metrics(metrics: Metrics) -> ExecutorMetrics:
    """The executor's series over the app's metrics facade (BQ-8)."""
    return ExecutorMetrics(metrics)


class RuleBudgetRebuild:
    """`BudgetRebuild` over the rules repository (24 §11.7, BQ-7): the ages of a rule's counted
    `action_start` events of its armed runs of the last 24 h, on the database's clock, which the
    budget places on its own wall clock as it reads them, so two clocks never skew a window."""

    def __init__(self, repository: SqlAlchemyRulesRepository) -> None:
        self._repository = repository

    async def order_ages(self, rule_id: str, *, limit: int) -> tuple[float, ...]:
        types = sorted(COUNTS_ORDERS)
        ages = await self._repository.order_action_ages(rule_id, types, since_s=DAY_S, limit=limit)
        return tuple(float(age) for age in ages)


class OrderBudgetAboveCap(ValueError):
    """A boot setting of the order budget above its hard cap: the app refuses to start."""


def rule_order_budget(
    per_minute: int, per_day: int, repository: SqlAlchemyRulesRepository | None
) -> OrderBudget:
    """The SR-104 order budget from its two boot settings (24 §11.7, §16.1; BQ-6), for
    `RulesService.bind(budget=...)`: `create_app` builds it whatever `rules_evaluator_enabled`
    says, so a setting above its hard cap (`rules.limits.ORDER_BUDGET_CAPS`) refuses start."""
    for setting, value, cap in (
        ("CV_RULES_ORDER_BUDGET_PER_MINUTE", per_minute, ORDER_BUDGET_CAPS["per_minute"]),
        ("CV_RULES_ORDER_BUDGET_PER_DAY", per_day, ORDER_BUDGET_CAPS["per_day"]),
    ):
        if value > cap:
            raise OrderBudgetAboveCap(f"{setting} is above its hard cap of {cap}")
    rebuild = None if repository is None else RuleBudgetRebuild(repository)
    return OrderBudget(per_minute, per_day, rebuild=rebuild)


class SignalDepthAboveCap(ValueError):
    """The signal chain's depth setting above its hard cap: the app refuses to start."""


def rule_signal_depth(value: int) -> int:
    """The signal chain's depth limit from its boot setting (24 §11.5, §16.1; E35-T13 BQ-5), for
    `RulesService.bind(signal_max_depth=...)`: `create_app` reads it whatever
    `rules_evaluator_enabled` says, so a setting above `rules.limits.SIGNAL_MAX_DEPTH_CAP` (interim,
    pending the owner's ratification, #2701) refuses start."""
    if value > SIGNAL_MAX_DEPTH_CAP:
        raise SignalDepthAboveCap(
            f"CV_RULES_SIGNAL_MAX_DEPTH is above its hard cap of {SIGNAL_MAX_DEPTH_CAP}"
        )
    return value


#: The account B18 is asked about for an action that names none (24 §11.5 check 3): no grant names
#: it, so no per-account engagement covers it, and its verdict is the global one. #956's B18 may
#: resolve a scope by lookup: the kill-switch suite's run against it asks this account by name,
#: or the binding moves to B18's global read once one exists.
GLOBAL_ACCOUNT: Final = AccountId(UUID(int=0))


class RuleFlagViews(Protocol):
    """The two flag views of `FeatureFlagsRuntime` checks 2 and 3 read (BQ-2)."""

    @property
    def rules_enabled(self) -> Callable[[], bool]: ...

    @property
    def order_entry_killed(self) -> Callable[[], bool]: ...


class RuleSwitchesBinding:
    """`RuleSwitches` at the composition root (24 §11.5 checks 2 and 3; BQ-2), each a synchronous
    read of memory: the master switch's view (off while unread, latched off if its poll dies), the
    `killswitch.order_entry` view (engaged while unread, latched engaged), never the order-entry
    gate, so maintenance mode stays the OMS's `order_entry`; B18's verdict through the OMS's
    shared port (`HaltingKillSwitch`, #2904: engaged everywhere while the audit-chain break halt
    is, else `InterimKillSwitch`, which admits until #956), asked for `GLOBAL_ACCOUNT` when an
    action names no account; and the rollout port, off until E35-T11 registers
    `rules.oms_actions`."""

    def __init__(
        self, views: RuleFlagViews, kill_switch: Callable[[AccountId], object | None]
    ) -> None:
        self._views, self._kill_switch = views, kill_switch

    def rules_enabled(self) -> bool:
        return self._views.rules_enabled() is True

    def order_entry_killed(self) -> bool:
        return self._views.order_entry_killed() is not False

    def kill_switch_engaged(self, account_id: UUID | None) -> bool:
        asked = GLOBAL_ACCOUNT if account_id is None else AccountId(account_id)
        return self._kill_switch(asked) is not None

    def oms_actions(self) -> bool:
        return False


def rule_switches(
    views: RuleFlagViews, kill_switch: Callable[[AccountId], object | None]
) -> RuleSwitchesBinding:
    """The executor's switches, for `RulesService.bind(switches=...)` (E35-T10)."""
    return RuleSwitchesBinding(views, kill_switch)

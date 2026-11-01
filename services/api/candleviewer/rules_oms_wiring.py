"""The rule action executor's write-ahead adapters, at the composition root (E35-T09 part 1; 24
§11.5 "The records written ahead", §15.5; the E35 threat model's RE-R1).

`rules` imports neither `storage` nor `audit` (`forbidden-M15`), so the executor's two ports are
bound here: `RuleRunRecords` over `SqlAlchemyRulesRepository` (the run row, its events and its
close, under the fire's own id) and `RuleActionAudit` over the audit writer (`rules.fired` and
`rules.blocked`, keyed by the action's `dedupe_key`). Until E35-T10 adds the principal, a record
names the rule as its actor with no user id and no request id, and both roles are `None` (BQ-11).
`RuleAlerts` binds the executor's alerts to the page line and to `system_events` (BQ-7), and
`rule_metrics` its series to the app's metrics facade (BQ-8); `app.py` binds all three.
Outcome and severity go as their values (C-3.3 keeps `audit` from this module, as from
`oms_stream_wiring`). Nothing here logs: the input snapshot is financial and confidential (21
§3.4.3).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter
from candleviewer.observability.metrics import Metrics
from candleviewer.rules.executor.metrics import ExecutorMetrics
from candleviewer.rules.executor.ports import ActionAuditFields, EventRow, RunRow, RunStatus
from candleviewer.storage.repositories.rules_sqlalchemy import (
    RuleEventInsert,
    SqlAlchemyRulesRepository,
)

#: Each alert's `system_events` row: component `rules`, its kind and a fixed message; the ids
#: ride in `details`, so the incident gathers every occurrence under one entry.
AlertKind = Literal["partial_fire", "write_ahead_failed"]
_ALERT_MESSAGES: Final[dict[str, str]] = {
    "partial_fire": "A rule fire partly took effect: one of its actions did not succeed.",
    "write_ahead_failed": "A rule action was not sent: its records could not be written ahead.",
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
        "owner_user_id": str(fields.owner), "owner_role": None,
        "armed_by_user_id": fields.armed_by, "armed_by_role": None,
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

    async def _alert(self, kind: AlertKind, rule_id: str, run_id: UUID, node_id: str) -> None:
        ids = {"rule_id": rule_id, "run_id": str(run_id), "node_id": node_id}
        if (kind, rule_id) not in self._paged:
            self._paged.add((kind, rule_id))
            _log().critical(f"rules.{kind}", cv_page=True, **ids)
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

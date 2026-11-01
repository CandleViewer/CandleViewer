"""The rule action executor (E35-T09; 24 §11.5, §11.9): one fire, its actions in IR order (E5).

For an armed fire, per action: check 1, the row read again, before the scope re-check (BQ-6); then
the routing emitter, still the only path to a sink, whose sink hands the action back here
(`hand_over`); then the handler table (`unavailable` while no handler is bound, `native_sl` for
good for `widen_stop`); then the records written ahead, the hand-over and the answer. `on_error`
decides what follows a result other than `ok`, `simulated` or `skipped`; a failed write, or a row no
longer armed or not confirmed, stops the fire whatever it says. The run row is closed with the
fire's status, every result is counted, a partial fire raises its alert, and nothing is rolled back.

A simulate fire's actions go through the emitter to the simulation sink with no records; a refused
fire's records and a scope-skipped evaluation's audits are record-only jobs (BQ-4). A cancel is
never caught: a fire cut short at stop keeps its run row `running` with its last `action_start`
and no outcome, and nothing is written at shutdown.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

import structlog

from candleviewer.rules.executor import dispatch
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.handlers import HANDLERS, HandlerAnswer, HandlerSpec, refusal
from candleviewer.rules.executor.keys import client_ref, dedupe_key
from candleviewer.rules.executor.metrics import ExecutorMetrics
from candleviewer.rules.executor.ports import (
    ActionAudit,
    ActionAuditFields,
    AlertPort,
    EventRow,
    RunRecords,
    RunRow,
    RunStatus,
    audit_fields,
    input_snapshot,
    trigger_reason,
)
from candleviewer.rules.executor.results import (
    ActionResult,
    BlockedBy,
    Outcome,
    blocked_result,
    skipped_result,
)
from candleviewer.rules.executor.writeahead import WRITE_AHEAD_FAILED, FireRecords, WriteAheadFailed
from candleviewer.rules.scope import ActionRequest, ActionSink

#: What check 1 found (24 §11.5): the row still armed at the fire's version and `ir_hash`, no
#: longer so (`mode_changed`), or not confirmed: its read failed or answered late (BQ-6).
RowVerdict = Literal["armed", "mode_changed", "unread"]
CheckOne = Callable[[ActionRequest], Awaitable[RowVerdict]]
#: The checks that exist, run again before `retry_once`'s retry (24 §11.9): check 1 and the scope
#: re-check; E35-T10 extends this one hook with its checks.
Recheck = Callable[[ActionRequest], Awaitable[BlockedBy | None]]
Stop = Literal["abort", "mode_changed", "unread", "write"]
_DONE: Final = frozenset({"ok", "simulated", "skipped"})
_NOT_DONE: Final = frozenset({"failed", "blocked", "unknown"})
#: The capabilities whose handlers run inside the engine (E35-T13): only these may be served by a
#: bound stand-in sink, so no stand-in ever reaches an OMS path, whatever is bound there.
_STAND_IN: Final = frozenset({"notifications", "journal", "variables", "signals", "rule_control"})
#: The answers `retry_once` may retry: no answer, or a refusal before the anchor existed.
_RETRIED: Final = frozenset({"no_answer", "pre_anchor"})
_OUTCOME_OF: Final[Mapping[str, Outcome]] = {
    "accepted": "ok", "done": "ok", "refused": "failed", "pre_anchor": "failed",
    "no_answer": "unknown", "in_flight": "unknown", "raised": "failed",
}  # fmt: skip


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Unbound:
    """The ports while the composition root has bound none: every write fails, so an armed action
    is never handed over without its records (RE-R1)."""

    async def begin(self, run: RunRow, first: EventRow) -> None:
        raise RuntimeError("rule action records not bound")

    async def append(self, run_id: Any, events: Any) -> None:
        raise RuntimeError("rule action records not bound")

    async def close(self, run_id: Any, status: RunStatus, duration_ms: int) -> None:
        raise RuntimeError("rule action records not bound")

    async def fired(self, fields: ActionAuditFields) -> None:
        raise RuntimeError("rule action audit not bound")

    async def blocked(self, fields: ActionAuditFields) -> None:
        raise RuntimeError("rule action audit not bound")


@dataclass(slots=True)
class _Action:
    """One armed action on its account, shared with `hand_over` through `_CURRENT`."""

    req: ActionRequest
    key: str
    fields: ActionAuditFields
    records: FireRecords
    started: float
    send_it: Callable[[], Awaitable[HandlerAnswer]] | None = None
    sent: bool = False
    answer: HandlerAnswer | None = None
    result: ActionResult | None = None
    write_failed: bool = False
    verdict: RowVerdict = "armed"


_CURRENT: ContextVar[_Action | None] = ContextVar("rule_action", default=None)


def _status(results: list[ActionResult]) -> RunStatus:
    """The run row's close (BQ-9): `error` when any result failed or is unknown, `ok` when every
    one took effect or was simulated, `aborted` for any other end."""
    outcomes = {r.outcome for r in results}
    if outcomes & {"failed", "unknown"}:
        return "error"
    return "ok" if outcomes <= {"ok", "simulated"} else "aborted"


def _run_row(fire: Fire) -> RunRow:
    instance = fire.requests[0].instance
    return RunRow(
        run_id=fire.run_id, rule_id=fire.rule_id, version_id=fire.version_id or "",
        mode="armed", trigger_reason=trigger_reason(fire.trigger_type),
        account_id=instance.account_id, symbol=instance.symbol, matched=True,
        input_snapshot=input_snapshot(fire.metric_values),
    )  # fmt: skip


def _key(req: ActionRequest) -> str:
    return dedupe_key(
        rule_id=req.rule_id, version=req.version, scope_instance=req.instance.key,
        node_id=req.payload.node_id, run_id=req.run_id, account_id=req.instance.account_id,
    )  # fmt: skip


class ActionExecutor:
    """`execute(fire)` from a dispatch worker; `hand_over(req)` from the routing emitter's sink,
    for an armed action the emitter passed. A bound `stand_in` sink (`RulesService.bind`'s
    `action_sink`) stands in for a handler no slice has bound yet, of an engine-internal capability
    only (`_STAND_IN`): an action that would reach the OMS stays `unavailable` until its slice binds
    its handler (C-2.6)."""

    def __init__(
        self,
        *,
        check_one: CheckOne,
        recheck: Recheck,
        records: RunRecords | None = None,
        audit: ActionAudit | None = None,
        alerts: AlertPort | None = None,
        metrics: ExecutorMetrics | None = None,
        stand_in: ActionSink | None = None,
        handlers: Mapping[str, HandlerSpec] = HANDLERS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._check_one, self._recheck = check_one, recheck
        unbound = _Unbound()
        self._records: RunRecords = unbound if records is None else records
        self._audit: ActionAudit = unbound if audit is None else audit
        self._alerts, self._stand_in = alerts, stand_in
        self._metrics = ExecutorMetrics() if metrics is None else metrics
        self._handlers, self._clock = handlers, clock

    async def execute(self, fire: Fire) -> None:
        if fire.kind == "refused_fire":
            await self._throttled(fire)
        elif fire.kind == "fire" and fire.armed:
            await self._armed(fire)
        else:
            await self._emit_only(fire)

    async def _emit_only(self, fire: Fire) -> None:
        """A simulate fire, or a scope-skipped evaluation's audits: through the emitter alone, one
        action after another; one that raises or outlasts its bound stops the rest, logged."""
        for done, req in enumerate(fire.requests):
            try:
                async with asyncio.timeout(dispatch.ACTION_TIMEOUT_S):
                    await fire.emit(req)
            except Exception as exc:  # never `CancelledError`, which is no `Exception`
                self._failed_log(fire, req, exc, not_run=len(fire.requests) - done - 1)
                return

    async def _throttled(self, fire: Fire) -> None:
        """A fire the full fire queue refused, off the tick (BQ-4): its run row closed
        `throttled`, and per action `action_fail` (`blocked`, `backpressure`, no account) and
        `rules.blocked`. Its metrics were counted on the tick."""
        if not fire.requests:
            return
        records = FireRecords(_run_row(fire), self._records, self._audit)
        try:
            for req in fire.requests:
                key = dedupe_key(
                    rule_id=req.rule_id, version=req.version, scope_instance=req.instance.key,
                    node_id=req.payload.node_id, run_id=req.run_id, account_id=None,
                )  # fmt: skip
                result = blocked_result(
                    node_id=req.payload.node_id, action_type=req.action_type, account_id=None,
                    resolved_accounts=(), dedupe_key=key, reason="backpressure",
                )  # fmt: skip
                await records.refused(result, audit_fields(req, account_id=None, dedupe_key=key))
            await records.closed("throttled", 0)
        except WriteAheadFailed as failed:
            _log().error(
                "rules.records_failed", rule_id=fire.rule_id, run_id=str(fire.run_id),
                write=failed.write, cause=failed.cause,
            )  # fmt: skip

    async def _armed(self, fire: Fire) -> None:
        records = FireRecords(_run_row(fire), self._records, self._audit)
        started, results = self._clock(), list[ActionResult]()
        stop: Stop | None = None
        writable, alerted = True, False
        for req in fire.requests:
            key = _key(req)
            fields = audit_fields(req, account_id=req.instance.account_id, dedupe_key=key)
            if stop is not None:
                result = self._skipped(req, key, stop)
            else:
                action = _Action(req, key, fields, records, self._clock())
                result = await self._bounded(fire, action)
                stop = self._stop_after(action, result)
            results.append(result)
            self._metrics.result(result)
            if writable and not await self._keep(records, result, fields):
                writable = False
                if stop in (None, "abort"):
                    stop = "write"  # a write after the answer stops the rest the same way
            if (stop == "write" or not writable) and not alerted:
                alerted = True  # AC-14: once per fire, naming the action whose write failed
                await self._alert_write(fire, req)
        if writable:
            await self._close(fire, records, _status(results), started)
        await self._settle(fire, results, troubled=alerted)

    async def _bounded(self, fire: Fire, action: _Action) -> ActionResult:
        """The action's whole step under `ACTION_TIMEOUT_S`: a timeout after its hand-over began
        is `unknown`; any other timeout, or a raise, is `failed` (logged by class alone)."""
        try:
            async with asyncio.timeout(dispatch.ACTION_TIMEOUT_S):
                return await self._run_action(fire, action)
        except Exception as exc:  # never `CancelledError`, which is no `Exception`
            timed_out = isinstance(exc, TimeoutError)
            self._failed_log(fire, action.req, exc, not_run=None)
            outcome: Outcome = "unknown" if timed_out and action.sent else "failed"
            return self._result(action, outcome, error_code="timeout" if timed_out else "error")

    async def _run_action(self, fire: Fire, action: _Action) -> ActionResult:
        req = action.req
        action.verdict = await self._check_one(req)  # check 1 comes before the scope re-check
        if action.verdict != "armed":
            return self._skipped(req, action.key, action.verdict)
        token = _CURRENT.set(action)
        try:
            passed = await fire.emit(req)
        finally:
            _CURRENT.reset(token)
        if not passed:  # the emitter refused and audited it (`rules.scope_denied`)
            return self._blocked(action, "scope")
        if req.payload.dry_run_only:
            return self._result(action, "simulated")
        if action.result is None:
            raise RuntimeError("an armed action passed the emitter but was not handed over")
        retryable = action.answer is not None and action.answer.answer in _RETRIED
        if retryable and req.payload.on_error == "retry_once" and not action.write_failed:
            await self._retry(action)
        return action.result

    async def hand_over(self, req: ActionRequest) -> None:
        """The routing emitter's sink for an armed action (`RulesService._route`): the handler
        table, then the records written ahead, then the hand-over, once (24 §11.5)."""
        action = _CURRENT.get()
        if action is None or action.req is not req:
            raise RuntimeError("an armed action is handed over only inside its fire")
        spec = self._handlers.get(req.action_type)
        reason = self._refusal(spec)
        if reason is not None or spec is None:
            action.result = self._blocked(action, reason or "unavailable")
            return
        action.send_it = self._sender(spec, action)
        try:
            answer = await action.records.admitted(action.fields, action.send_it)
        except WriteAheadFailed:
            action.write_failed = True
            action.result = self._result(action, "failed", error_code=WRITE_AHEAD_FAILED)
            return
        action.answer, action.result = answer, self._answered(action, answer)

    async def _retry(self, action: _Action) -> None:
        """`retry_once` (24 §11.9): after the checks run again, the same request under the same
        `client_ref`, its write ahead again (one `rules.fired`: the record is keyed). A check that
        refuses now sends nothing, and the first call's result stands."""
        if await self._recheck(action.req) is not None or action.send_it is None:
            return
        try:
            answer = await action.records.admitted(action.fields, action.send_it)
        except WriteAheadFailed:
            action.write_failed = True  # not re-sent: the first call's result stands
            return
        action.answer, action.result = answer, self._answered(action, answer)

    def _refusal(self, spec: HandlerSpec | None) -> BlockedBy | None:
        if spec is None:
            return "unavailable"
        if spec.handler is None and spec.refused_as is None and spec.capability in _STAND_IN:
            return None if self._stand_in is not None else "unavailable"
        return refusal(spec)

    def _sender(self, spec: HandlerSpec, action: _Action) -> Callable[[], Awaitable[HandlerAnswer]]:
        """The hand-over, built once: a retry sends the same request under the same key."""
        handler, req = spec.handler, action.req
        if handler is None:  # `_refusal` admits a handler-less type only with a stand-in bound
            sink = cast(ActionSink, self._stand_in)

            async def via_sink() -> HandlerAnswer:
                action.sent = True
                await sink(req)
                return HandlerAnswer("done")

            return via_sink
        prepared = handler.prepare(req, req.instance.account_id)
        ref = client_ref(action.key)

        async def via_handler() -> HandlerAnswer:
            action.sent = True
            return await handler.send(prepared, client_ref=ref)

        return via_handler

    def _answered(self, action: _Action, answer: HandlerAnswer) -> ActionResult:
        if answer.answer == "refused" and answer.blocked_by is not None:
            return self._blocked(action, answer.blocked_by)
        return self._result(
            action, _OUTCOME_OF[answer.answer], error_code=answer.error_code,
            order_id=answer.order_id, group_id=answer.group_id,
        )  # fmt: skip

    def _stop_after(self, action: _Action, result: ActionResult) -> Stop | None:
        """Why the fire stops after this action: a failed write or an unconfirmed row whatever
        `on_error` says; else `abort_remaining` (and `retry_once` once retried) stop it after a
        result other than `ok`, `simulated` or `skipped`, and `continue` never does."""
        if action.write_failed:
            return "write"
        if action.verdict == "mode_changed":
            return "mode_changed"
        if action.verdict == "unread":
            return "unread"
        if result.outcome in _DONE or action.req.payload.on_error == "continue":
            return None
        return "abort"

    def _ids(self, action: _Action) -> dict[str, Any]:
        account = action.req.instance.account_id
        return {
            "node_id": action.req.payload.node_id, "action_type": action.req.action_type,
            "account_id": account, "resolved_accounts": () if account is None else (account,),
            "dedupe_key": action.key,
        }  # fmt: skip

    def _micros(self, action: _Action) -> int:
        return max(0, int((self._clock() - action.started) * 1_000_000))

    def _result(self, action: _Action, outcome: Outcome, **more: Any) -> ActionResult:
        ids = self._ids(action)
        return ActionResult(**ids, outcome=outcome, duration_us=self._micros(action), **more)

    def _blocked(self, action: _Action, reason: BlockedBy) -> ActionResult:
        return blocked_result(**self._ids(action), reason=reason, duration_us=self._micros(action))

    def _skipped(self, req: ActionRequest, key: str, stop: Stop | RowVerdict) -> ActionResult:
        account = req.instance.account_id
        named = stop in ("mode_changed", "unread")
        return skipped_result(
            node_id=req.payload.node_id, action_type=req.action_type, account_id=account,
            resolved_accounts=() if account is None else (account,), dedupe_key=key,
            reason="mode_changed" if named else None, unread=stop == "unread",
        )  # fmt: skip

    async def _keep(
        self, records: FireRecords, result: ActionResult, fields: ActionAuditFields
    ) -> bool:
        """The result's records: a refusal's `action_fail` and `rules.blocked`, any other's event.
        False when a write failed; the caller then writes nothing more for the fire."""
        try:
            if result.blocked_by is not None:
                await records.refused(result, fields)
            else:
                await records.answered(result)
        except WriteAheadFailed as failed:
            _log().error(
                "rules.records_failed", rule_id=fields.rule_id, run_id=str(fields.run_id),
                write=failed.write, cause=failed.cause,
            )  # fmt: skip
            return False
        return True

    async def _close(
        self, fire: Fire, records: FireRecords, status: RunStatus, started: float
    ) -> None:
        duration_ms = max(0, int((self._clock() - started) * 1000))
        try:
            await records.closed(status, duration_ms)
        except WriteAheadFailed as failed:  # the row stays `running`
            _log().error(
                "rules.run_close_failed", rule_id=fire.rule_id, run_id=str(fire.run_id),
                cause=failed.cause,
            )  # fmt: skip

    async def _alert_write(self, fire: Fire, req: ActionRequest) -> None:
        if self._alerts is not None:  # AC-14
            await self._alerts.write_ahead_failed(fire.rule_id, fire.run_id, req.payload.node_id)

    async def _settle(self, fire: Fire, results: list[ActionResult], *, troubled: bool) -> None:
        """A fire with an `ok` result and one that failed, was blocked or is unknown raises the
        partial-fire alert, naming the rule, the fire and the first action that did not succeed;
        a fire that ends with neither that nor a failed write closes the rule's alert episode
        (BQ-7), so one rule that fails over and over pages once."""
        if self._alerts is None:
            return
        failed = next((r for r in results if r.outcome in _NOT_DONE), None)
        if failed is not None and any(r.outcome == "ok" for r in results):
            await self._alerts.partial_fire(fire.rule_id, fire.run_id, failed.node_id)
        elif not troubled:
            self._alerts.settled(fire.rule_id)

    def _failed_log(
        self, fire: Fire, req: ActionRequest, exc: Exception, *, not_run: int | None
    ) -> None:
        reason = "timeout" if isinstance(exc, TimeoutError) else "error"
        unrun = {} if not_run is None else {"not_run": not_run}  # an armed fire records them
        _log().error(
            "rules.action_failed", queue=fire.queue, rule_id=fire.rule_id,
            run_id=str(fire.run_id), node_id=req.payload.node_id, reason=reason,
            kind=type(exc).__name__, **unrun,
        )  # fmt: skip

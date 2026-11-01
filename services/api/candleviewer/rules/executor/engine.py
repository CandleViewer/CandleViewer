"""The rule action executor (E35-T09; 24 §11.5, §11.9): one fire, its actions in IR order (E5).

For an armed fire, per action, its `targets` resolved, and per resolved account (E35-T10, BQ-4):
check 1, the row read again (BQ-6); checks 2 and 3, synchronous reads with no await (`gates.py`);
then the routing emitter (check 4), still the only path to a sink, whose sink hands the action
back here (`hand_over`); then checks 5 to 8; then the records written ahead, the hand-over and the
answer, so every refusal is decided before `rules.fired` could be written (24 §11.5). The first
account whose result is neither `ok` nor `simulated` stops the action's other accounts
(`abort_on_first`), recorded `skipped`. `on_error`
decides what follows a result other than `ok`, `simulated` or `skipped`; a failed write, or a row no
longer armed or not confirmed, stops the fire whatever it says. The run row is closed with the
fire's status (`error` after a failed write, its close still tried once), every result is counted,
a partial fire raises its alert, and nothing is rolled back.

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
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Final, Literal, NoReturn, cast
from uuid import UUID

import structlog

from candleviewer.rules.executor import dispatch
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.gates import Gates, Halts, scope_refusal
from candleviewer.rules.executor.handlers import HANDLERS, HandlerAnswer, HandlerSpec
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
    SnapshotValue,
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
from candleviewer.rules.ir.canonical import IrValueError
from candleviewer.rules.ir.models import RuleLimits
from candleviewer.rules.scope import ActionRequest, ActionSink, ScopeInstanceRef

#: What check 1 found (24 §11.5): the row still armed at the fire's version and `ir_hash`, no
#: longer so (`mode_changed`), or not confirmed: its read failed or answered late (BQ-6).
RowVerdict = Literal["armed", "mode_changed", "unread"]
CheckOne = Callable[[ActionRequest], Awaitable[RowVerdict]]
#: Check 4 run again before `retry_once`'s retry (24 §11.9), outside the emitter, which hands over:
#: the scope re-check's reason, or `None` when the action is still in scope.
ScopeCheck = Callable[[ActionRequest], str | None]
Stop = Literal["abort", "mode_changed", "unread", "write"]
_DONE: Final = frozenset({"ok", "simulated", "skipped"})
_NOT_DONE: Final = frozenset({"failed", "blocked", "unknown"})
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
    """Ports that refuse every write, so an armed action is never handed over without its
    records (RE-R1): the ports while the composition root has bound none, and (`_Unrecordable`)
    a fire's own when its run row cannot be built."""

    def _refuse(self, port: str) -> NoReturn:
        raise RuntimeError(f"rule action {port} not bound")

    async def begin(self, run: RunRow, first: EventRow) -> None:
        self._refuse("records")

    async def append(self, run_id: Any, events: Any) -> None:
        self._refuse("records")

    async def close(self, run_id: Any, status: RunStatus, duration_ms: int) -> None:
        self._refuse("records")

    async def fired(self, fields: ActionAuditFields) -> None:
        self._refuse("audit")

    async def blocked(self, fields: ActionAuditFields) -> None:
        self._refuse("audit")


class _Unrecordable(_Unbound):
    """A fire's ports when its snapshot holds a value `input_snapshot` refuses (a non-finite or
    over-wide decimal): each write fails with that error, which names no value, so the fire stops
    as one whose write ahead failed, and no record holds the value."""

    def __init__(self, refused: IrValueError) -> None:
        self._loc, self._reason = refused.loc, refused.reason

    def _refuse(self, port: str) -> NoReturn:
        raise IrValueError(self._loc, self._reason)


@dataclass(slots=True)
class _Action:
    """One armed action on one resolved account (`None` for an action that names none), shared
    with `hand_over` through `_CURRENT`: `req` names that account on the firing instance's key."""

    req: ActionRequest
    key: str
    fields: ActionAuditFields
    records: FireRecords
    started: float
    account: UUID | None = None
    resolved: tuple[UUID, ...] = ()
    wide: bool = False  # resolved by `all_accounts`
    position: int = 1  # its 1-based place in the fire's IR order
    limits: RuleLimits = field(default_factory=RuleLimits)  # its fire's
    ceiling: Decimal | None = None  # an entry's notional allowance (check 6)
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


def _run_row(fire: Fire, snapshot: Mapping[str, SnapshotValue] | None = None) -> RunRow:
    """The fire's `rule_runs` row, under the mode its actions carry: the stored row's as the rule
    was evaluated, `simulate` or `armed`, for a fire the full queue refused too."""
    instance = fire.requests[0].instance
    return RunRow(
        run_id=fire.run_id, rule_id=fire.rule_id, version_id=fire.version_id or "",
        mode=fire.requests[0].mode, trigger_reason=trigger_reason(fire.trigger_type),
        account_id=instance.account_id, symbol=instance.symbol, matched=True,
        input_snapshot=input_snapshot(fire.metric_values) if snapshot is None else snapshot,
    )  # fmt: skip


def _key(req: ActionRequest, account: UUID | None) -> str:
    return dedupe_key(
        rule_id=req.rule_id, version=req.version, scope_instance=req.instance.key,
        node_id=req.payload.node_id, run_id=req.run_id, account_id=account,
    )  # fmt: skip


class ActionExecutor:
    """`execute(fire)` from a dispatch worker; `hand_over(req)` from the routing emitter's sink,
    for an armed action the emitter passed. A bound `stand_in` sink (`RulesService.bind`'s
    `action_sink`) stands in for a handler no slice has bound yet, of an engine-internal capability
    only (`handlers.ENGINE_INTERNAL`, check 2): an action that would reach the OMS stays
    `unavailable` until its slice binds its handler (C-2.6). `gates` holds the checks' ports; its
    unbound ports refuse."""

    def __init__(
        self,
        *,
        check_one: CheckOne,
        scope_check: ScopeCheck,
        gates: Gates | None = None,
        records: RunRecords | None = None,
        audit: ActionAudit | None = None,
        alerts: AlertPort | None = None,
        metrics: ExecutorMetrics | None = None,
        stand_in: ActionSink | None = None,
        handlers: Mapping[str, HandlerSpec] = HANDLERS,
        clock: Callable[[], float] = time.monotonic,
        halts: Halts | None = None,
    ) -> None:
        self._check_one, self._scope_check = check_one, scope_check
        self._gates = Gates() if gates is None else gates
        self._halts = Halts() if halts is None else halts  # the trip and kill times (E35-T10)
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
        """A fire refused whole off the tick, as a record-only job (BQ-4): one the full fire queue
        refused (`backpressure`, its run row closed `throttled`), or one the circuit breaker or the
        kill-switch hook dropped from its lane (E35-T10, closed `aborted`); `error` after a failed
        write, its close still tried once (BQ-9). Its metrics were counted where it was refused."""
        throttled = fire.refused_by == "backpressure"
        await self._whole(fire, fire.refused_by, "throttled" if throttled else "aborted")

    async def _whole(
        self, fire: Fire, reason: BlockedBy, status: RunStatus, *, count: bool = False
    ) -> None:
        """A fire refused whole: per action `action_fail` (`blocked`, `reason`, with no account:
        targets are resolved only past these blocks) and `rules.blocked`, never `rules.fired`, each
        counted first when `count` says so; then its run row closed `status`, or `error` after a
        failed write, its close still tried once (BQ-9)."""
        if not fire.requests:
            return
        refused = []
        for req in fire.requests:
            key = _key(req, None)
            result = blocked_result(
                node_id=req.payload.node_id, action_type=req.action_type, account_id=None,
                resolved_accounts=(), dedupe_key=key, reason=reason,
            )  # fmt: skip
            if count:
                self._metrics.result(result)
            refused.append((result, audit_fields(req, account_id=None, dedupe_key=key)))
        records = self._records_for(fire)
        try:
            for result, fields in refused:
                await records.refused(result, fields)
        except WriteAheadFailed as failed:
            status = "error"
            self._records_failed(fire, failed)
        await self._close(fire, records, status, 0)

    async def _armed(self, fire: Fire) -> None:
        """An armed fire: first the blocks that refuse it whole (24 §11.5), a fire offered before
        its rule's trip time (`circuit_breaker`) or kill time (`kill_switch`), then a rule that
        requires confirmation (`confirmation_unavailable`, never executed later); else its actions,
        per resolved account."""
        whole = self._halts.block(fire.rule_id, fire.offered_at)
        if whole is None and fire.limits.require_confirmation:
            whole = "confirmation_unavailable"
        if whole is not None:
            await self._whole(fire, whole, "aborted", count=True)
            return
        try:
            await self._actions(fire)
        finally:
            self._gates.allowance.ended(fire.run_id)

    async def _actions(self, fire: Fire) -> None:
        records = self._records_for(fire)
        started, results = self._clock(), list[ActionResult]()
        stop: Stop | None = None
        writable, alerted = True, False
        for position, req in enumerate(fire.requests, start=1):
            accounts, wide = self._gates.resolve_targets(
                req, self._handlers.get(req.action_type), self._clock()
            )
            resolved = tuple(a for a in accounts if a is not None)
            halted = False  # `abort_on_first`: the action's later accounts are not attempted
            for account in accounts or (None,):
                action = self._action(req, account, resolved, wide, records)
                action.position, action.limits = position, fire.limits
                if stop is not None or halted:
                    result = self._skipped(action, stop)
                elif not accounts:  # `all_accounts` resolved to no account (BQ-4)
                    result = self._blocked(action, "permission")
                    stop = self._stop_after(action, result)
                else:
                    result = await self._bounded(fire, action)
                    stop = self._stop_after(action, result)
                halted = halted or result.outcome not in ("ok", "simulated")
                results.append(result)
                self._metrics.result(result)
                if writable and not await self._keep(fire, records, result, action.fields):
                    writable = False
                    if stop in (None, "abort"):
                        stop = "write"  # a write after the answer stops the rest the same way
                if (stop == "write" or not writable) and not alerted:
                    alerted = True  # AC-14: once per fire, naming the action whose write failed
                    await self._alert_write(fire, req)
        status: RunStatus = _status(results) if writable else "error"  # a failed write: closed too
        await self._close(fire, records, status, max(0, int((self._clock() - started) * 1000)))
        await self._settle(fire, results, troubled=alerted)

    def _records_for(self, fire: Fire) -> FireRecords:
        """The fire's records. One whose run row cannot be built, as its snapshot holds a value
        `input_snapshot` refuses, gets ports that refuse every write: it stops as a fire whose
        write ahead failed, nothing sent, and an armed one raises the alert (AC-14)."""
        try:
            return FireRecords(_run_row(fire), self._records, self._audit)
        except IrValueError as refused:
            unwritable = _Unrecordable(refused)
            return FireRecords(_run_row(fire, snapshot={}), unwritable, unwritable)

    def _action(
        self,
        req: ActionRequest,
        account: UUID | None,
        resolved: tuple[UUID, ...],
        wide: bool,
        records: FireRecords,
    ) -> _Action:
        """The action on one resolved account: the request the checks see names that account on
        the firing instance's key, with its own fire key and audit fields (24 §11.9)."""
        if account is not None and account != req.instance.account_id:
            instance = ScopeInstanceRef(req.instance.key, req.instance.symbol, account)
            req = replace(req, instance=instance)
        key = _key(req, account)
        fields = audit_fields(req, account_id=account, dedupe_key=key)
        return _Action(
            req, key, fields, records, self._clock(), account=account, resolved=resolved,
            wide=wide,
        )  # fmt: skip

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
            return self._skipped(action, action.verdict)
        refused = self._before_scope(action)  # checks 2 and 3: synchronous, never awaited
        if refused is not None:
            return self._blocked(action, refused)
        token = _CURRENT.set(action)
        try:
            refused_as = await fire.emit(req)  # `emit_checked`: its reason, or None once sent on
        finally:
            _CURRENT.reset(token)
        if refused_as is not None:  # the emitter refused and audited it (`rules.scope_denied`)
            return self._blocked(action, scope_refusal(refused_as))
        if req.payload.dry_run_only:
            return self._result(action, "simulated")
        if action.result is None:
            raise RuntimeError("an armed action passed the emitter but was not handed over")
        retryable = action.answer is not None and action.answer.answer in _RETRIED
        if retryable and req.payload.on_error == "retry_once" and not action.write_failed:
            await self._retry(action)
        return action.result

    async def hand_over(self, req: ActionRequest) -> None:
        """The routing emitter's sink for an armed action (`RulesService._route`): checks 5 to 8,
        then the records written ahead, then the hand-over, once (24 §11.5)."""
        action = _CURRENT.get()
        if action is None or action.req is not req:
            raise RuntimeError("an armed action is handed over only inside its fire")
        spec = self._handlers.get(req.action_type)
        reason, limit = (
            ("unavailable", None) if spec is None else await self._after_scope(spec, action)
        )
        if reason is not None or spec is None:
            action.result = self._blocked(action, reason or "unavailable", limit)
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
        """`retry_once` (24 §11.9): after checks 1 to 8 run again, the same request under the same
        `client_ref`, its write ahead again (one `rules.fired`: the record is keyed). A check that
        refuses now sends nothing, and the first call's result stands."""
        if not await self._rechecked(action) or action.send_it is None:
            return
        try:
            answer = await action.records.admitted(action.fields, action.send_it)
        except WriteAheadFailed:
            action.write_failed = True  # not re-sent: the first call's result stands
            return
        action.answer, action.result = answer, self._answered(action, answer)

    def _before_scope(self, action: _Action) -> BlockedBy | None:
        """Checks 2 and 3 on the action's account."""
        spec = self._handlers.get(action.req.action_type)
        return self._gates.before_scope(spec, action.account, stand_in=self._stand_in is not None)

    async def _after_scope(
        self, spec: HandlerSpec, action: _Action
    ) -> tuple[BlockedBy | None, str | None]:
        """Checks 5 to 8 on the action's account, the first refusal with the rule limit a `cap`
        names; the records carry the roles check 5 read, and an entry the allowance it may use."""
        req = action.req
        refused, owner, armer = self._gates.principal(
            req, action.account, all_accounts=action.wide, now=self._clock()
        )
        action.fields = replace(
            action.fields, owner_role=None if owner is None else owner.role,
            armed_by_role=None if armer is None else armer.role,
        )  # fmt: skip
        if refused is not None:
            return refused, None
        limit = self._gates.per_fire(action.position, action.limits)  # check 6
        if limit is None and spec.meets_allowance:
            allowance = self._gates.allowance
            limit, action.ceiling = await allowance.remainder(
                req.rule_id, req.run_id, action.limits
            )
        if limit is not None:
            return "cap", limit
        return self._gates.stop_check(spec, req, action.account), None  # check 8

    async def _rechecked(self, action: _Action) -> bool:
        """Checks 1 to 8 again before a retry (24 §11.9), check 4 through the scope re-check
        alone: True when every one passes. A refusal here is no result of its own."""
        req = action.req
        if await self._check_one(req) != "armed" or self._before_scope(action) is not None:
            return False
        spec = self._handlers.get(req.action_type)
        if spec is None or self._scope_check(req) is not None:
            return False
        return (await self._after_scope(spec, action))[0] is None

    def _sender(self, spec: HandlerSpec, action: _Action) -> Callable[[], Awaitable[HandlerAnswer]]:
        """The hand-over, built once: a retry sends the same request under the same key."""
        handler, req = spec.handler, action.req
        if handler is None:  # check 2 admits a handler-less type only with a stand-in bound
            sink = cast(ActionSink, self._stand_in)

            async def via_sink() -> HandlerAnswer:
                action.sent = True
                await sink(req)
                return HandlerAnswer("done")

            return via_sink
        prepared = handler.prepare(req, action.account, max_notional_usd=action.ceiling)
        ref = client_ref(action.key)

        async def via_handler() -> HandlerAnswer:
            action.sent = True
            return await handler.send(prepared, client_ref=ref)

        return via_handler

    def _answered(self, action: _Action, answer: HandlerAnswer) -> ActionResult:
        if answer.answer == "accepted" and answer.notional_usd is not None:  # the ledger (BQ-11)
            self._gates.allowance.spend(action.req.rule_id, action.req.run_id, answer.notional_usd)
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
        return {
            "node_id": action.req.payload.node_id, "action_type": action.req.action_type,
            "account_id": action.account, "resolved_accounts": action.resolved,
            "dedupe_key": action.key,
        }  # fmt: skip

    def _micros(self, action: _Action) -> int:
        return max(0, int((self._clock() - action.started) * 1_000_000))

    def _result(self, action: _Action, outcome: Outcome, **more: Any) -> ActionResult:
        ids = self._ids(action)
        return ActionResult(**ids, outcome=outcome, duration_us=self._micros(action), **more)

    def _blocked(
        self, action: _Action, reason: BlockedBy, limit: str | None = None
    ) -> ActionResult:
        return blocked_result(
            **self._ids(action), reason=reason, duration_us=self._micros(action), limit=limit
        )

    def _skipped(self, action: _Action, stop: Stop | RowVerdict | None) -> ActionResult:
        named = stop in ("mode_changed", "unread")
        return skipped_result(
            **self._ids(action), reason="mode_changed" if named else None, unread=stop == "unread"
        )

    async def _keep(
        self, fire: Fire, records: FireRecords, result: ActionResult, fields: ActionAuditFields
    ) -> bool:
        """The result's records: a refusal's `action_fail` and `rules.blocked`, any other's event.
        False when a write failed; the caller then writes nothing more for the fire but its
        close."""
        try:
            if result.blocked_by is not None:
                await records.refused(result, fields)
            else:
                await records.answered(result)
        except WriteAheadFailed as failed:
            self._records_failed(fire, failed)
            return False
        return True

    def _records_failed(self, fire: Fire, failed: WriteAheadFailed) -> None:
        _log().error(
            "rules.records_failed", queue=fire.queue, rule_id=fire.rule_id,
            run_id=str(fire.run_id), write=failed.write, cause=failed.cause,
        )  # fmt: skip

    async def _close(
        self, fire: Fire, records: FireRecords, status: RunStatus, duration_ms: int
    ) -> None:
        """The run row's close, tried once whatever was written before (BQ-9)."""
        try:
            await records.closed(status, duration_ms)
        except WriteAheadFailed as failed:  # the row stays `running`
            _log().error(
                "rules.run_close_failed", queue=fire.queue, rule_id=fire.rule_id,
                run_id=str(fire.run_id), cause=failed.cause,
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

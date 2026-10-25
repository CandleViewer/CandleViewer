"""`DELETE /orders/{orderId}`, `cancelOrder` (E29-T04 #913 slice 4, S4-D1; 24 Sec.8.4 "The exit
routes", 22 `cancelOrder`).

After the middleware (CSRF, the session state and the view-as guard, deny-by-default) the route
checks 24 Sec.8.4's exit-route steps, each before the next. A cancel has no body, no arm token and
no switches (steps 5, 6 and 10): it is never gated (C-2.6).

1. the principal, as `POST /orders`' step 1: none is 401, one that cannot be read 503
   `store_unavailable`, no source composed 501; then the order's id, which is not a UUID is
   `400 validation_failed`, unaudited, as it names no order;
2. `enforce(orders:write)`: 403 `forbidden` without it, audited `rbac.denied` naming the order, a
   403 even when that record cannot be written. The trade grant is step 4's: the account is read
   from the order;
3. the runtime: none composed is 501, one whose `state` is not `ok` 503 `oms_not_ready`;
4. the scope (`OrderExits.scope`): the order in the caller's scope, or the exit service's refusal,
   which the service recorded as rulings Q6, Q7 and Q12 say and the route answers as it is: `404
   not_found`, `403 account_scope_denied` or `forbidden`, `503 store_unavailable`;
7. `Idempotency-Key`; 8. the 24 h record of first `2xx` answers, by principal, operation and key,
   whose fingerprint is the method and the order's path (a cancel has no body);
9. the in-flight guard and 11. `OrderExits.cancel_admitted`, through `run_claimed`: the cancel
   runs as the runtime's tracked task, shielded from the client's disconnect. That task renders
   the answer (`exit_response`) and keeps a `202` in the 24 h record, and the guard's claim is
   released when it ends.

A refusal the route makes from step 7 on is recorded through `OrderExits.deny`, naming its step
(`key`, `replay`, `guard`), before it is answered (C-2.9), else `503 audit_unavailable`; the
service records its own (steps 4 and 11). A fault the exit service raises at step 4, or in step
11's task once the client left too, is `exit_fault`'s answer: every such `500` pages, one page
for the fault's class (the orchestrator's ruling of 2026-10-25 02:50Z (2)). Every refusal is
counted in `oms_exit_refused_total{operation="cancel",code}` as it is answered (ruling Q14), the
unaudited ones and the faults included. No log line or problem carries the key or the
fingerprint (C-12.6).
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import Response

from candleviewer.api.idempotency import IdempotencyCache, StoredResponse, request_fingerprint
from candleviewer.api.order_admission import (
    ORDERS_PERMISSION,
    AuditEmitter,
    OrderPrincipals,
    idempotency_key,
    problem,
    rbac_refusal,
    replay_cached,
    replay_key,
    resolve_principal,
)
from candleviewer.api.order_exits_common import (
    exit_caller,
    exit_fault,
    exit_problem,
    exit_refusals,
    exit_response,
    run_claimed,
)
from candleviewer.api.order_problems import order_problem
from candleviewer.api.refusal_session import SessionsLike
from candleviewer.audit.errors import AuditError
from candleviewer.auth.scopes import ForbiddenError, decide, enforce
from candleviewer.domain.primitives import Environment
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import (
    FieldError,
    IdempotencyKeyReuse,
    OmsNotReady,
    OrderInvalid,
    OrderRefused,
    StoreUnavailable,
    problem_for,
)
from candleviewer.oms.exits import (
    CancelReason,
    ExitCaller,
    ExitOperation,
    ExitOutcome,
    ExitStep,
    InFlightGuard,
)
from candleviewer.oms.ports import SubmitActor
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.storage.repositories.orders import OrderRow, ScopedOrder

__all__ = ["CancelRuntime", "make_order_exits_router"]

#: The 24 h record's operation (22's operationId) and the exit the guard and the counter name.
_OPERATION: Final = "cancelOrder"
_CANCEL: Final[ExitOperation] = "cancel"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _CancelExits(Protocol):
    """`oms.exits.OrderExits` as the cancel route drives it."""

    @property
    def guard(self) -> InFlightGuard: ...

    async def scope(self, caller: ExitCaller, order_id: uuid.UUID) -> ScopedOrder | ExitOutcome: ...

    async def deny(
        self, row: OrderRow, operation: ExitOperation, outcome: ExitOutcome, *,
        actor: SubmitActor, request_id: uuid.UUID | None, step: ExitStep | None = None,
    ) -> ExitOutcome: ...  # fmt: skip

    async def cancel_admitted(
        self, row: OrderRow, *, actor: SubmitActor, reason: CancelReason,
        request_id: uuid.UUID | None,
    ) -> ExitOutcome: ...  # fmt: skip


class _RouteReads(Protocol):
    @property
    def environment(self) -> Environment: ...


class CancelRuntime(Protocol):
    """`oms_wiring.OmsRuntime` as the cancel route reads it (20 Sec.6.2)."""

    @property
    def state(self) -> str: ...
    @property
    def exits(self) -> _CancelExits: ...
    @property
    def route(self) -> _RouteReads: ...
    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]: ...


@dataclass(frozen=True, slots=True)
class _OnOrder:
    """`enforce` names no object: step 2's `rbac.denied` names the order asked for (C-2.9), whose
    account is read only at step 4."""

    audit: AuditEmitter
    order_id: uuid.UUID

    async def emit(
        self, action: str, *, request_id: uuid.UUID | None = None, **fields: Any
    ) -> None:
        """The record, its request's id forwarded as the caller named it (#3990)."""
        named = {"object_kind": "order", "object_id": str(self.order_id)}
        await self.audit.emit(action, request_id=request_id, **fields | named)


def _refusal(error: OrderRefused) -> ExitOutcome:
    """A refusal the route makes from step 7 on, as the exit service answers one."""
    found = problem_for(error)
    return ExitOutcome(
        kind="refused", status=found.status, code=found.code, detail=error.detail,
        errors=error.errors,
    )  # fmt: skip


def make_order_exits_router(
    principals: OrderPrincipals | None, runtime: Callable[[], CancelRuntime | None], *,
    audit: AuditEmitter, metrics: Metrics, auth: SessionsLike | None = None,
    replays: IdempotencyCache | None = None, pager: Pager | None = None,
) -> APIRouter:  # fmt: skip
    """`DELETE /orders/{orderId}` (module docstring). No principal source (no identity composed)
    answers 501, as no runtime (the fake backend) does after RBAC. `audit` takes step 2's
    `rbac.denied`; the exit service records the rest. `replays` is the 24 h record of first `2xx`
    answers. Cancel-all is its own router (`api/order_cancel_all.py`), mounted ahead of this one
    (the orchestrator's ruling of 2026-10-24 19:43Z)."""
    router = APIRouter(tags=["trading"])
    kept = replays if replays is not None else IdempotencyCache()
    paging: Pager = LogPager() if pager is None else pager
    refusals = exit_refusals(metrics)

    def counted(code: str, answer: Response) -> Response:
        """Every refusal, counted as it is answered (ruling Q14)."""
        refusals.labels(_CANCEL, code).inc()
        return answer

    def refused(outcome: ExitOutcome) -> Response:
        return counted(outcome.code or "internal_error", exit_problem(outcome))

    def faulted(error: Exception) -> Response:
        """A fault the exit service raised that no outcome answers (`exit_fault`): each `500`
        paged, and counted under its code as it is answered (ruling Q14)."""
        return counted(*exit_fault(error, pager=paging))

    def not_ready() -> Response:
        """Step 3's answer, and a stop begun after it: counted, never audited (24 Sec.8.4)."""
        return counted("oms_not_ready", order_problem(OmsNotReady(), pager=paging))

    async def audit_refusal(
        exits: _CancelExits, row: OrderRow, caller: ExitCaller, step: ExitStep, refusal: ExitOutcome
    ) -> Response:
        """A refusal of step 7, 8 or 9, recorded through the exit service with its step before it
        is answered (C-2.9): its problem, else `503 audit_unavailable`."""
        outcome = await exits.deny(
            row, _CANCEL, refusal, actor=caller.actor, request_id=caller.request_id, step=step
        )
        return refused(outcome)

    async def answer(
        exits: _CancelExits, scoped: ScopedOrder, caller: ExitCaller, held: tuple[str, str],
        digest: str, env: Environment,
    ) -> Response:  # fmt: skip
        """Step 11's task: the exit service's cancel, rendered, and a `202` kept for 24 h, so a
        request cancelled midway still keeps it (24 Sec.8.4); a fault it raises is `faulted`'s
        answer, in this task (`run_claimed`)."""
        outcome = await exits.cancel_admitted(
            scoped.order, actor=caller.actor, reason="user", request_id=caller.request_id
        )
        out = exit_response(outcome, scoped, env)
        if outcome.kind == "refused":  # recorded by the service before it was answered
            return counted(outcome.code or "internal_error", out)
        kept.put(*held, StoredResponse(digest, 202, bytes(out.body), None))
        return out

    @router.delete("/orders/{orderId}", status_code=202)
    async def cancel_order(
        request: Request, order_ref: Annotated[str, Path(alias="orderId")]
    ) -> Response:
        if principals is None:
            message = "No principal source is composed."
            return counted("not_implemented", problem(501, "not_implemented", message))
        try:
            principal = await resolve_principal(principals, request, auth)
        except StoreUnavailable as exc:
            return counted("store_unavailable", order_problem(exc))
        if principal is None:
            message = "No verified session for this request."
            return counted("unauthenticated", problem(401, "unauthenticated", message))
        try:
            order_id = uuid.UUID(order_ref)
        except ValueError:  # it names no order: unaudited, as an unreadable body is
            unread = FieldError("orderId", "uuid", "Name the order by its id (a UUID).")
            return counted("validation_failed", order_problem(OrderInvalid(errors=(unread,))))
        snapshot, caller = principal.snapshot, exit_caller(principal, request)
        try:  # step 2; the trade grant is step 4's, the account read from the order
            await enforce(
                snapshot, ORDERS_PERMISSION, emitter=_OnOrder(audit, order_id),
                actor_ip=caller.actor.ip, session_id=principal.session_id,
                request_id=caller.request_id,
            )  # fmt: skip
        except ForbiddenError as exc:
            return counted("forbidden", rbac_refusal(exc.deny))
        except (AuditError, RuntimeError) as exc:  # counted by `enforce`; its 403 stands
            _log().warning("order_exit_denial_unaudited", step="rbac", error=type(exc).__name__)
            return counted("forbidden", rbac_refusal(decide(snapshot, ORDERS_PERMISSION)))
        oms = runtime()  # step 3: its `state` alone decides (SEC-S3E2-01)
        if oms is None:
            message = "No OMS is composed on this backend."
            return counted("not_implemented", problem(501, "not_implemented", message))
        if oms.state != "ok":
            return not_ready()
        try:
            exits, env = oms.exits, oms.route.environment
        except OmsNotReady:  # the runtime began its stop meanwhile
            return not_ready()
        try:  # step 4
            scoped = await exits.scope(caller, order_id)
        except Exception as exc:  # a fault the service did not answer: the paged `500`
            return faulted(exc)
        if isinstance(scoped, ExitOutcome):  # recorded by the service, rulings Q6, Q7, Q12
            return refused(scoped)
        try:  # step 7
            key = idempotency_key(request)
        except OrderInvalid as exc:
            return await audit_refusal(exits, scoped.order, caller, "key", _refusal(exc))
        held = replay_key(snapshot.user_id, _OPERATION, key)
        digest = request_fingerprint("DELETE", f"/orders/{order_id}", b"")
        try:  # step 8
            cached = replay_cached(kept, held, digest)
        except IdempotencyKeyReuse as exc:
            return await audit_refusal(exits, scoped.order, caller, "replay", _refusal(exc))
        if cached is not None:
            return cached
        guard = functools.partial(audit_refusal, exits, scoped.order, caller, "guard")
        cancel = functools.partial(answer, exits, scoped, caller, held, digest, env)
        try:  # steps 9 and 11
            return await run_claimed(
                oms, snapshot.user_id, _CANCEL, key, cancel, refused=guard, faulted=faulted
            )
        except OmsNotReady:  # the runtime began its stop before it took the cancel
            return not_ready()

    return router

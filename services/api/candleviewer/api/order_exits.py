"""`DELETE /orders/{orderId}`, `cancelOrder`, and `PATCH /orders/{orderId}`, `amendOrder` (E29-T04
#913 slice 4, S4-D1 and S4-D2b; 24 Sec.8.4 "The exit routes", 22 `cancelOrder`, `amendOrder`).

After the middleware (CSRF, the session state and the view-as guard, deny-by-default) each route
checks 24 Sec.8.4's exit-route steps, each before the next. A cancel has no body, no arm token
and no switches (steps 5, 6 and 10): it is never gated (C-2.6).

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
5. an amend's body, read under `MAX_ORDER_BODY_BYTES` and strictly into the exit service's terms
   (22 `AmendOrderRequest`): `400 validation_failed`, each rule that failed named, recorded as it
   names an order in scope; and its class (`risk_increasing`, 24 Sec.8.10), judged on step 4's
   read;
6. a risk-increasing amend's arm token, as `POST /orders` checks it (`403 session_not_armed` where
   the arm records refuse it: a live account without a token); a cut never needs one (C-2.6);
7. `Idempotency-Key`; 8. the 24 h record of first `2xx` answers, by principal, operation and key,
   whose fingerprint is the method, the order's path and the body (a cancel has none); an amend's
   replays its stored `ETag`;
9. the in-flight guard and 11. the exit service's step (`cancel_admitted`, `amend`), through
   `run_claimed`: it runs as the runtime's tracked task, shielded from the client's disconnect.
   That task renders the answer (`exit_response`) and keeps a `202` in the 24 h record, and the
   guard's claim is released when it ends. An amend's `If-Match` (`api.order_etag.expected_seq`;
   every `If-Match` field sent, read as one list, RFC 9110 Sec.5.3) is the service's to compare;
   its `202` carries the order's `ETag`, at the version B1's step gave, else (an `unknown` amend)
   at the facade's version as it stands, none for a final order; and the service's own refusals
   (step 10's flag and switches, step 11's, D2a's re-check of the class included) are answered
   as it gives them, never decided again.

A refusal the route makes from step 5 on is recorded through `OrderExits.deny`, naming its step
(`body`, `arm`, `key`, `replay`, `guard`), before it is answered (C-2.9), else `503
audit_unavailable`; the service records its own (steps 4, 10 and 11). A fault the exit service
raises at step 4, or in step 11's task once the client left too, is `exit_fault`'s answer: every
such `500` pages, one page for the fault's class (the orchestrator's ruling of 2026-10-25 02:50Z
(2)). Every refusal is counted in `oms_exit_refused_total{operation,code}` as it is answered
(ruling Q14), the unaudited ones and the faults included. No log line or problem carries the key,
the fingerprint or the token (C-12.6).
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import Response
from pydantic import ValidationError

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse, request_fingerprint
from candleviewer.api.order_admission import (
    MAX_ORDER_BODY_BYTES,
    ORDERS_PERMISSION,
    AuditEmitter,
    OrderPrincipals,
    arm_token,
    field_errors,
    idempotency_key,
    parse_json_object,
    problem,
    rbac_refusal,
    read_capped,
    replay_cached,
    replay_key,
    resolve_principal,
    stop_offset,
)
from candleviewer.api.order_etag import expected_seq, order_etag
from candleviewer.api.order_exits_common import (
    ExitRuntime,
    exit_caller,
    exit_fault,
    exit_problem,
    exit_refusals,
    exit_response,
    run_claimed,
)
from candleviewer.api.order_principal import TradingPrincipal
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
    SessionNotArmed,
    StoreUnavailable,
    problem_for,
)
from candleviewer.oms.exits import (
    AmendTerms,
    CancelReason,
    ExitCaller,
    ExitOperation,
    ExitOutcome,
    ExitStep,
    InFlightGuard,
    risk_increasing,
)
from candleviewer.oms.ports import FAILED, ArmRecords, StopOffset, SubmitActor
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.storage.repositories.orders import OrderRow, ScopedOrder

__all__ = ["ExitRoutesRuntime", "make_order_exits_router"]

#: The 24 h record's operations (22's operationIds) and the exits the guard and the counter name.
_OPERATION: Final = "cancelOrder"
_AMEND_OPERATION: Final = "amendOrder"
_CANCEL: Final[ExitOperation] = "cancel"
_AMEND: Final[ExitOperation] = "amend"
_SIDES: Final = ("take_profit", "stop_loss")


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Exits(Protocol):
    """`oms.exits.OrderExits` as the exit routes drive it."""

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

    async def amend(
        self, scoped: ScopedOrder, terms: AmendTerms, *, caller: ExitCaller,
        expected_seq: int | None,
    ) -> ExitOutcome: ...  # fmt: skip


class _Versions(Protocol):
    def version(self, order_id: uuid.UUID) -> int | None: ...


class _RouteReads(Protocol):
    @property
    def environment(self) -> Environment: ...
    @property
    def arm_records(self) -> ArmRecords: ...
    @property
    def versions(self) -> _Versions: ...


class ExitRoutesRuntime(ExitRuntime, Protocol):
    """`oms_wiring.OmsRuntime` as the exit routes read it (20 Sec.6.2): `ExitRuntime`'s `run`,
    with the runtime's state, the whole exit service and the route's reads."""

    @property
    def state(self) -> str: ...
    @property
    def exits(self) -> _Exits: ...
    @property
    def route(self) -> _RouteReads: ...


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


@dataclass(frozen=True, slots=True)
class _Admitted:
    """Steps 1 to 4 passed: the principal, its caller, the runtime and its reads, and the order in
    the caller's scope."""

    principal: TradingPrincipal
    caller: ExitCaller
    oms: ExitRoutesRuntime
    exits: _Exits
    reads: _RouteReads
    scoped: ScopedOrder


def _terms(raw: bytes) -> AmendTerms:
    """Step 5: an amend's body, read strictly into the exit service's terms (22
    `AmendOrderRequest`); `OrderInvalid` names each rule that failed. A TP/SL side named `null` is
    asked cleared, which the service refuses; one not named is not amended."""
    body = parse_json_object(raw)
    if body is None:
        unread = FieldError("body", "object", "Send a JSON object of the terms to amend.")
        raise OrderInvalid(errors=(unread,))
    try:
        asked = api.AmendOrderRequest.model_validate(body, strict=True)  # as `placeOrder` reads
    except ValidationError as exc:
        raise OrderInvalid(errors=tuple(field_errors(exc))) from None
    named = asked.model_fields_set
    sides: dict[str, StopOffset | None] = {
        side: stop_offset(getattr(asked, side)) for side in _SIDES if side in named
    }
    return AmendTerms(
        qty=_decimal(asked.qty), price=_decimal(asked.price),
        trigger_price=_decimal(asked.trigger_price), sides=sides or None,
    )  # fmt: skip


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def make_order_exits_router(
    principals: OrderPrincipals | None, runtime: Callable[[], ExitRoutesRuntime | None], *,
    audit: AuditEmitter, metrics: Metrics, auth: SessionsLike | None = None,
    replays: IdempotencyCache | None = None, pager: Pager | None = None,
) -> APIRouter:  # fmt: skip
    """`DELETE` and `PATCH /orders/{orderId}` (module docstring). No principal source (no identity
    composed) answers 501, as no runtime (the fake backend) does after RBAC. `audit` takes step 2's
    `rbac.denied`; the exit service records the rest. `replays` is the 24 h record of first `2xx`
    answers. Cancel-all is its own router (`api/order_cancel_all.py`), mounted ahead of this one
    (the orchestrator's ruling of 2026-10-24 19:43Z)."""
    router = APIRouter(tags=["trading"])
    kept = replays if replays is not None else IdempotencyCache()
    paging: Pager = LogPager() if pager is None else pager
    refusals = exit_refusals(metrics)

    def counted(operation: ExitOperation, code: str, answer: Response) -> Response:
        """Every refusal, counted as it is answered (ruling Q14)."""
        refusals.labels(operation, code).inc()
        return answer

    def refused(operation: ExitOperation, outcome: ExitOutcome) -> Response:
        return counted(operation, outcome.code or "internal_error", exit_problem(outcome))

    def faulted(operation: ExitOperation, error: Exception) -> Response:
        """A fault the exit service raised that no outcome answers (`exit_fault`): each `500`
        paged, and counted under its code as it is answered (ruling Q14)."""
        return counted(operation, *exit_fault(error, pager=paging))

    def not_ready(operation: ExitOperation) -> Response:
        """Step 3's answer, and a stop begun after it: counted, never audited (24 Sec.8.4)."""
        return counted(operation, "oms_not_ready", order_problem(OmsNotReady(), pager=paging))

    async def audit_refusal(
        operation: ExitOperation, exits: _Exits, row: OrderRow, caller: ExitCaller,
        step: ExitStep, refusal: ExitOutcome,
    ) -> Response:  # fmt: skip
        """A refusal of steps 5 to 9, recorded through the exit service with its step before it is
        answered (C-2.9): its problem, else `503 audit_unavailable`."""
        outcome = await exits.deny(
            row, operation, refusal, actor=caller.actor, request_id=caller.request_id, step=step
        )
        return refused(operation, outcome)

    async def admit(
        request: Request, order_ref: str, operation: ExitOperation
    ) -> _Admitted | Response:
        """Steps 1 to 4 (module docstring): the order in the caller's scope, else the answer."""
        if principals is None:
            message = "No principal source is composed."
            return counted(operation, "not_implemented", problem(501, "not_implemented", message))
        try:
            principal = await resolve_principal(principals, request, auth)
        except StoreUnavailable as exc:
            return counted(operation, "store_unavailable", order_problem(exc))
        if principal is None:
            message = "No verified session for this request."
            return counted(operation, "unauthenticated", problem(401, "unauthenticated", message))
        try:
            order_id = uuid.UUID(order_ref)
        except ValueError:  # it names no order: unaudited, as an unreadable body is
            unread = FieldError("orderId", "uuid", "Name the order by its id (a UUID).")
            invalid = order_problem(OrderInvalid(errors=(unread,)))
            return counted(operation, "validation_failed", invalid)
        snapshot, caller = principal.snapshot, exit_caller(principal, request)
        try:  # step 2; the trade grant is step 4's, the account read from the order
            await enforce(
                snapshot, ORDERS_PERMISSION, emitter=_OnOrder(audit, order_id),
                actor_ip=caller.actor.ip, session_id=principal.session_id,
                request_id=caller.request_id,
            )  # fmt: skip
        except ForbiddenError as exc:
            return counted(operation, "forbidden", rbac_refusal(exc.deny))
        except (AuditError, RuntimeError) as exc:  # counted by `enforce`; its 403 stands
            _log().warning("order_exit_denial_unaudited", step="rbac", error=type(exc).__name__)
            decision = decide(snapshot, ORDERS_PERMISSION)
            return counted(operation, "forbidden", rbac_refusal(decision))
        oms = runtime()  # step 3: its `state` alone decides (SEC-S3E2-01)
        if oms is None:
            message = "No OMS is composed on this backend."
            return counted(operation, "not_implemented", problem(501, "not_implemented", message))
        if oms.state != "ok":
            return not_ready(operation)
        try:
            exits, reads = oms.exits, oms.route
        except OmsNotReady:  # the runtime began its stop meanwhile
            return not_ready(operation)
        try:  # step 4
            scoped = await exits.scope(caller, order_id)
        except Exception as exc:  # a fault the service did not answer: the paged `500`
            return faulted(operation, exc)
        if isinstance(scoped, ExitOutcome):  # recorded by the service, rulings Q6, Q7, Q12
            return refused(operation, scoped)
        return _Admitted(principal, caller, oms, exits, reads, scoped)

    async def answer(
        exits: _Exits, scoped: ScopedOrder, caller: ExitCaller, held: tuple[str, str],
        digest: str, env: Environment,
    ) -> Response:  # fmt: skip
        """A cancel's step 11 task: the exit service's cancel, rendered, and a `202` kept for 24 h,
        so a request cancelled midway still keeps it (24 Sec.8.4); a fault it raises is `faulted`'s
        answer, in this task (`run_claimed`)."""
        outcome = await exits.cancel_admitted(
            scoped.order, actor=caller.actor, reason="user", request_id=caller.request_id
        )
        out = exit_response(outcome, scoped, env)
        if outcome.kind == "refused":  # recorded by the service before it was answered
            return counted(_CANCEL, outcome.code or "internal_error", out)
        kept.put(*held, StoredResponse(digest, 202, bytes(out.body), None))
        return out

    async def amended(
        exits: _Exits, scoped: ScopedOrder, terms: AmendTerms, caller: ExitCaller,
        expected: int | None, held: tuple[str, str], digest: str, reads: _RouteReads,
    ) -> Response:  # fmt: skip
        """An amend's step 11 task: the exit service's amend, rendered with the order's `ETag`, and
        a `202` kept for 24 h with it (24 Sec.8.4). The tag names the version B1's step gave, else
        the facade's version as it stands, which an `unknown` amend's order has and a final one
        has not (22 `OrderETag`); a fault it raises is `faulted`'s answer, in this task
        (`run_claimed`)."""
        outcome = await exits.amend(scoped, terms, caller=caller, expected_seq=expected)
        out = exit_response(outcome, scoped, reads.environment)
        if outcome.kind == "refused":  # recorded by the service before it was answered
            return counted(_AMEND, outcome.code or "internal_error", out)
        seq = outcome.version
        seq = reads.versions.version(scoped.order.id) if seq is None else seq
        tag = None if seq is None else order_etag(scoped.order.id, seq)
        if tag is not None:
            out.headers["ETag"] = tag
        kept.put(*held, StoredResponse(digest, 202, bytes(out.body), tag))
        return out

    @router.delete("/orders/{orderId}", status_code=202)
    async def cancel_order(
        request: Request, order_ref: Annotated[str, Path(alias="orderId")]
    ) -> Response:
        got = await admit(request, order_ref, _CANCEL)
        if not isinstance(got, _Admitted):
            return got
        exits, scoped, caller, user = got.exits, got.scoped, got.caller, got.principal.snapshot
        try:  # step 7
            key = idempotency_key(request)
        except OrderInvalid as exc:
            return await audit_refusal(_CANCEL, exits, scoped.order, caller, "key", _refusal(exc))
        held = replay_key(user.user_id, _OPERATION, key)
        digest = request_fingerprint("DELETE", f"/orders/{scoped.order.id}", b"")
        try:  # step 8
            cached = replay_cached(kept, held, digest)
        except IdempotencyKeyReuse as exc:
            return await audit_refusal(
                _CANCEL, exits, scoped.order, caller, "replay", _refusal(exc)
            )
        if cached is not None:
            return cached
        guard = functools.partial(audit_refusal, _CANCEL, exits, scoped.order, caller, "guard")
        env = got.reads.environment
        cancel = functools.partial(answer, exits, scoped, caller, held, digest, env)
        try:  # steps 9 and 11
            return await run_claimed(
                got.oms, user.user_id, _CANCEL, key, cancel, refused=guard,
                faulted=functools.partial(faulted, _CANCEL),
            )  # fmt: skip
        except OmsNotReady:  # the runtime began its stop before it took the cancel
            return not_ready(_CANCEL)

    @router.patch("/orders/{orderId}", status_code=202)
    async def amend_order(
        request: Request, order_ref: Annotated[str, Path(alias="orderId")]
    ) -> Response:
        got = await admit(request, order_ref, _AMEND)
        if not isinstance(got, _Admitted):
            return got
        exits, scoped, caller, user = got.exits, got.scoped, got.caller, got.principal.snapshot
        row = scoped.order
        step: ExitStep = "body"
        try:
            raw = await read_capped(request)  # step 5
            if raw is None:
                message = f"Send a body of at most {MAX_ORDER_BODY_BYTES} bytes."
                raise OrderInvalid(errors=(FieldError("body", "body_too_large", message),))
            terms = _terms(raw)
            step = "arm"
            if risk_increasing(row, terms):  # step 6, judged on step 4's read
                armed = got.reads.arm_records.check(
                    session_id=got.principal.session_id, environment=got.reads.environment,
                    token=arm_token(request),
                )  # fmt: skip
                if armed == FAILED:
                    raise SessionNotArmed
            step = "key"
            key = idempotency_key(request)  # step 7
            step = "replay"
            held = replay_key(user.user_id, _AMEND_OPERATION, key)
            digest = request_fingerprint("PATCH", f"/orders/{row.id}", raw)
            cached = replay_cached(kept, held, digest)  # step 8
        except OrderRefused as exc:
            return await audit_refusal(_AMEND, exits, row, caller, step, _refusal(exc))
        if cached is not None:
            return cached
        named = ", ".join(request.headers.getlist("if-match")) or None  # every field, one list
        expected = expected_seq(named, row.id)
        guard = functools.partial(audit_refusal, _AMEND, exits, row, caller, "guard")
        amend = functools.partial(
            amended, exits, scoped, terms, caller, expected, held, digest, got.reads
        )
        try:  # steps 9 and 11
            return await run_claimed(
                got.oms, user.user_id, _AMEND, key, amend, refused=guard,
                faulted=functools.partial(faulted, _AMEND),
            )  # fmt: skip
        except OmsNotReady:  # the runtime began its stop before it took the amend
            return not_ready(_AMEND)

    return router

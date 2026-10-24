"""`POST /orders`, `placeOrder` (E29-T04 #913 slice 3; 24 Sec.8.4 "The route", 22 `placeOrder`).

After the middleware (CSRF, the session state and the view-as guard, deny-by-default) the route
checks, each before the next (24 Sec.8.4, steps 1 to 12):

1. the principal (`SessionTradingPrincipalResolver`, or a test seam's snapshot with the bearer's
   session): none is 401, one that cannot be read 503 `store_unavailable`, no source composed 501;
   then the body, read under `MAX_ORDER_BODY_BYTES` and parsed once: one past the cap, or whose
   `exchange_account_id` cannot be read, is 400, unaudited;
2. `enforce(orders:write, GRANTED_ACCOUNTS, account, requires_trade)`: 403 `forbidden` or
   `account_scope_denied`, audited `rbac.denied`, a 403 even when its record cannot be written;
3. the runtime: none composed is 501, one whose `state` is not `ok` 503 `oms_not_ready` with
   `Retry-After`, counted and never audited (SEC-S3E2-01: `run` is not reached);
4. the account's existence through the runtime: `account_scope_denied` in step 2's shape;
5. the arm token; 6. `Idempotency-Key`; 7. the 24 h record; 8. the anchor's lookup on the
   runtime's own `AnchorService` (SEC-S3D-02): a replay answers the rows as read now;
9. `trading.oms_enabled`, which an order whose parsed body says `reduce_only: true` passes;
10. the switches B1's `SEND` asks too; 11. the body read strictly into the pipeline's request;
12. `submit`, run by the runtime as a task it tracks and shielded from the client's disconnect:
    the task renders the answer and keeps a first `2xx` in the 24 h record itself.

Every refusal from step 4 on is counted, then audited before it is answered: `orders.submit` with
outcome `denied` and its code, the gate's `account.disabled_by_policy`; one whose record cannot be
written is 503 `audit_unavailable` and binds no key (C-2.9). A replay is the stored answer, not a
refusal. No log line, exception or problem carries a member of the rows the first persist wrote
(SEC-S3D-01), the key or the fingerprint (C-12.6). The admission the order routes share (the
principal, step 2's refusal, the body's cap, the key, the 24 h record) is `api/order_admission.py`.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from candleviewer.accounts.errors import AccountsError
from candleviewer.accounts.selfcheck import DISABLED_BY_POLICY
from candleviewer.accounts.trade_groups import ScopedTradeGroup
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse, request_fingerprint
from candleviewer.api.order_acceptance import first_acceptance, replayed_acceptance
from candleviewer.api.order_admission import (
    MAX_ORDER_BODY_BYTES,
    ORDERS_PERMISSION,
    AuditEmitter,
    OnAccount,
    OrderPrincipals,
    field_errors,
    idempotency_key,
    parse_json_object,
    problem,
    rbac_refusal,
    read_capped,
    replay_cached,
    replay_key,
    resolve_principal,
    submit_actor,
)
from candleviewer.api.order_problems import order_problem, outcome_problem
from candleviewer.api.refusal_session import SessionsLike
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Scope
from candleviewer.auth.metrics import authz_denied_total, normalise_permission
from candleviewer.auth.scopes import (
    DenyReason,
    ForbiddenError,
    PrincipalSnapshot,
    account_scope,
    decide,
    enforce,
)
from candleviewer.domain.primitives import AccountId, Environment, GroupId
from candleviewer.observability.context import current_request_uuid
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.errors import (
    PROBLEMS,
    AccountScopeDenied,
    AuditNotDurable,
    FieldError,
    OmsError,
    OmsNotReady,
    OrderEntryRefused,
    OrderInvalid,
    SessionNotArmed,
    StoreUnavailable,
    TradingDisabled,
    problem_for,
)
from candleviewer.oms.idempotency import InFlight, KeyReuse, Lookup, Replay
from candleviewer.oms.ports import (
    FAILED,
    ArmRecords,
    ArmToken,
    RequestRecord,
    SizingRequest,
    StopOffset,
    SubmitActor,
    SubmitAudit,
    TradingSwitches,
)
from candleviewer.oms.submit import (
    STORE_TIMEOUT_S,
    SUBMIT_ACTION,
    OrderRequest,
    OrderTrigger,
    SubmitContext,
    SubmitOutcome,
    entry_order_id,
)
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.orders import OrderRow, OrderStoreError

__all__ = ["MAX_ORDER_BODY_BYTES", "OrderPrincipals", "OrderRuntime", "make_orders_router"]

_OPERATION: Final = "placeOrder"
_PERMISSION: Final = ORDERS_PERMISSION
#: `rbac.denied`'s reason for an account outside the grants, as `enforce` writes it (step 4).
_NOT_GRANTED: Final = (
    f"{DenyReason.ACCOUNT_NOT_GRANTED.value}:{_PERMISSION.value}:{Scope.GRANTED_ACCOUNTS.value}"
)
_ARM_HEADER_MAX: Final = 256
_UNREAD_ROWS: Final = (TimeoutError, StorageError, OrderStoreError, AccountsError)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Existence(Protocol):
    async def environment_of(self, account_id: AccountId) -> Environment: ...


class _OrderRows(Protocol):
    async def get(self, account_id: uuid.UUID, order_id: uuid.UUID) -> OrderRow | None: ...


class _GroupRows(Protocol):
    async def get(self, scope: AccountScope, group_id: GroupId) -> ScopedTradeGroup: ...


class _RouteReads(Protocol):
    """`oms_wiring.OrderRoute`: what the route reads of the composed OMS."""

    @property
    def accounts(self) -> _Existence: ...
    @property
    def arm_records(self) -> ArmRecords: ...
    @property
    def switches(self) -> TradingSwitches: ...
    @property
    def orders(self) -> _OrderRows: ...
    @property
    def groups(self) -> _GroupRows: ...


class _Pipeline(Protocol):
    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome: ...
    async def answer_replay(self, account_id: AccountId, replay: Replay) -> SubmitOutcome: ...


class _Anchors(Protocol):
    async def lookup(
        self, created_by: uuid.UUID, client_ref: uuid.UUID, request_sha256: str
    ) -> Lookup: ...


class OrderRuntime(Protocol):
    """`oms_wiring.OmsRuntime` as the route reads it (20 Sec.6.2)."""

    @property
    def state(self) -> str: ...
    @property
    def submission(self) -> _Pipeline: ...
    @property
    def anchors(self) -> _Anchors: ...
    @property
    def route(self) -> _RouteReads: ...
    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]: ...


@dataclass(frozen=True, slots=True)
class _Caller:
    """The admitted request: its principal, its records' actor and the account its body names."""

    principal: PrincipalSnapshot
    actor: SubmitActor
    account_id: AccountId
    request_id: uuid.UUID | None


def _parsed(raw: bytes) -> tuple[dict[str, object], AccountId] | None:
    """The body, parsed once, and the account it names; None when either cannot be read (DC-S3A2-01:
    steps 2, 9 and 11 read this one parse, so a repeated key cannot split them)."""
    body = parse_json_object(raw)
    if body is None:
        return None
    value = body.get("exchange_account_id")
    if not isinstance(value, str):
        return None
    try:
        return body, AccountId(uuid.UUID(value))
    except ValueError:
        return None


def _arm_token(request: Request) -> ArmToken | None:
    presented = request.headers.get("x-arm-token")
    if presented is None or not 0 < len(presented) <= _ARM_HEADER_MAX:
        return None
    return ArmToken(presented)


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _offset(offset: api.Offset | None) -> StopOffset | None:
    return None if offset is None else StopOffset(offset.unit, Decimal(offset.value))


def _order_request(body: dict[str, object], account_id: AccountId) -> OrderRequest:
    """Step 11: `PlaceOrderRequest` read strictly, JSON types only (`"true"` is no boolean), then a
    `limit` without `price` and an emulated algo are refused; the account is step 2's."""
    try:
        read = api.PlaceOrderRequest.model_validate_json(json.dumps(body), strict=True)
    except ValidationError as exc:
        raise OrderInvalid(errors=field_errors(exc)) from None
    errors: list[FieldError] = []
    if read.order_type == "limit" and read.price is None:
        errors.append(FieldError("price", "required", "A limit order needs a price."))
    if read.algo is not None and read.algo.kind != "none":
        message = "Emulated algos are not available yet."
        errors.append(FieldError("algo.kind", "algo_unsupported", message))
    if errors:
        raise OrderInvalid(errors=errors)
    sizing, trigger = read.sizing, read.trigger
    return OrderRequest(
        account_id=account_id, symbol=read.symbol, side=read.side, order_type=read.order_type,
        sizing=SizingRequest(sizing.mode, _decimal(sizing.qty), sizing.round_to_lot),
        intent=read.intent, price=_decimal(read.price), time_in_force=read.time_in_force or "GTC",
        reduce_only=read.reduce_only, close_on_trigger=read.close_on_trigger,
        position_idx=read.position_idx or 0,
        trigger=None if trigger is None else OrderTrigger(
            Decimal(trigger.price), trigger.direction, trigger.trigger_by or "LastPrice"
        ),
        stop_loss=_offset(read.stop_loss), take_profit=_offset(read.take_profit),
        tpsl_mode=read.tpsl_mode or "Full", profile_id=read.profile_id, note=read.note,
    )  # fmt: skip


def make_orders_router(
    principals: OrderPrincipals | None, runtime: Callable[[], OrderRuntime | None], *,
    audit: AuditEmitter, records: SubmitAudit, oms_enabled: Callable[[], bool], metrics: Metrics,
    auth: SessionsLike | None = None, replays: IdempotencyCache | None = None,
    pager: Pager | None = None,
) -> APIRouter:  # fmt: skip
    """`POST /orders` (module docstring). No principal source (no identity composed) answers 501,
    as no runtime (the fake backend) does after RBAC. `audit` takes `rbac.denied`, `records` the
    route's other refusals; `replays` is the 24 h record of first `2xx` answers."""
    router = APIRouter(tags=["trading"])
    kept = replays if replays is not None else IdempotencyCache()
    paging: Pager = LogPager() if pager is None else pager
    spec = next(spec for spec in CATALOGUE if spec.name == "oms_submit_rejected_total")
    rejected = metrics.counter(spec.name, spec.help, spec.labels, max_series=spec.max_series)

    def not_ready() -> Response:
        """Step 3's answer: counted, never audited (24 Sec.8.4)."""
        rejected.labels(PROBLEMS[OmsNotReady].code).inc()
        return order_problem(OmsNotReady(), pager=paging)

    def page(summary: str) -> None:
        _log().critical(summary)
        try:
            paging.raise_alert("page", summary, machine_kind="order")
        except Exception as exc:  # the page is lost, never the answer
            _log().critical("oms_pager_failed", summary=summary, error=type(exc).__name__)

    async def audit_refusal(
        error: OmsError, caller: _Caller, step: str, env: str | None
    ) -> Response:
        """A refusal from step 4 on: counted and recorded before it is answered (C-2.9)."""
        problem = problem_for(error)
        gate = error.reason if isinstance(error, OrderEntryRefused) else None
        record = RequestRecord(
            DISABLED_BY_POLICY if gate else SUBMIT_ACTION, caller.account_id, "exchange_account",
            caller.account_id, "denied", "error" if problem.status >= 500 else "warning",
            gate or problem.code, caller.actor,
            {"step": step, "code": problem.code, "environment": env}, caller.request_id,
        )  # fmt: skip
        try:
            async with asyncio.timeout(STORE_TIMEOUT_S):
                await records.write(record)
        except Exception as exc:  # no refusal is answered unrecorded; the key stays unbound
            rejected.labels(PROBLEMS[AuditNotDurable].code).inc()
            failure = type(exc).__name__
            _log().error("orders_refusal_unrecorded", code=problem.code, step=step, error=failure)
            return order_problem(AuditNotDurable("the refusal's record did not land"))
        rejected.labels(problem.code).inc()
        return order_problem(error, pager=paging)

    async def scope_denied(caller: _Caller) -> Response:
        """Step 4's refusal in step 2's shape (no oracle): counted, then `rbac.denied` as `enforce`
        writes it; a 403 even when that record cannot be written, as `testApiKey`'s is."""
        authz_denied_total.labels(permission=normalise_permission(_PERMISSION)).inc()
        user, actor = caller.principal.user_id, caller.actor
        try:
            await OnAccount(audit, caller.account_id).emit(
                "rbac.denied", actor_label=str(user), actor_user_id=user, actor_ip=actor.ip,
                session_id=actor.session_id, outcome="denied",
                severity="warning", reason=_NOT_GRANTED, request_id=caller.request_id,
            )  # fmt: skip
        except (AuditError, RuntimeError) as exc:  # RuntimeError: the writer is not started
            _log().warning("orders_denial_unaudited", step="account", error=type(exc).__name__)
        return order_problem(AccountScopeDenied())

    async def replayed(
        reads: _RouteReads, outcome: SubmitOutcome, caller: _Caller, env: Environment
    ) -> Response:
        """A repeat (steps 8 and 12): its recorded 429 or 502, or a `202` of its rows as read now,
        both `Idempotency-Replayed`; rows that cannot be read are 503, nothing sent."""
        if outcome.status != 202:
            return outcome_problem(outcome)
        group_id = outcome.trade_group_id
        order_id = outcome.order_id if group_id is None else entry_order_id(group_id)
        scope, account_id = account_scope(caller.principal), caller.account_id
        found: ScopedTradeGroup | None = None
        try:
            async with asyncio.timeout(STORE_TIMEOUT_S):
                if group_id is not None:
                    found = await reads.groups.get(scope, GroupId(group_id))
                row = None if order_id is None else await reads.orders.get(account_id, order_id)
        except _UNREAD_ROWS as exc:
            _log().warning("orders_replay_unread", error=type(exc).__name__)
            raise StoreUnavailable from None
        if row is None:  # an anchor never exists without its order (24 Sec.8.4 step 5)
            _log().error("orders_replay_row_missing", anchor_id=str(outcome.anchor_id))
            raise StoreUnavailable
        record = None if found is None else found.record
        try:
            body = replayed_acceptance(row, record, outcome, env)
        except ValueError:  # SEC-S3F2-03: a group other than the outcome's, so fail closed
            page("orders_replay_group_mismatch")
            mismatch = OmsError("a replay read a group other than its outcome's")
            rejected.labels(problem_for(mismatch).code).inc()  # `internal_error`, 20 Sec.12.1
            return order_problem(mismatch)
        return JSONResponse(body, 202, {"Idempotency-Replayed": "true"})

    async def answer(
        pipeline: _Pipeline, reads: _RouteReads, order: OrderRequest, context: SubmitContext,
        caller: _Caller, env: Environment,
    ) -> Response:  # fmt: skip
        """Step 12's task: the pipeline's answer, rendered, and a first `2xx` kept for 24 h, so a
        request cancelled midway still records both (24 Sec.8.4)."""
        try:
            outcome = await pipeline.submit(order, context)
        except OmsError as exc:  # recorded by the pipeline before it was raised
            return order_problem(exc, pager=paging)
        if outcome.status != 202:
            return outcome_problem(outcome)
        if outcome.replayed:  # the key's earlier request answers this one
            try:
                return await replayed(reads, outcome, caller, env)
            except OmsError as exc:
                return await audit_refusal(exc, caller, "replay", env)
        if outcome.written is None:  # CR-S3D-07: no rows to answer from, fail closed
            page("orders_first_answer_unwritten")
            unwritten = OmsError("a first answer carried no written rows")
            rejected.labels(problem_for(unwritten).code).inc()  # `internal_error`, 20 Sec.12.1
            return order_problem(unwritten)
        out = JSONResponse(first_acceptance(outcome, env), 202)
        held = replay_key(caller.principal.user_id, _OPERATION, context.client_ref)
        kept.put(*held, StoredResponse(context.request_sha256, 202, bytes(out.body), None))
        return out

    @router.post("/orders", status_code=202)
    async def place_order(request: Request) -> Response:
        if principals is None:
            return problem(501, "not_implemented", "No principal source is composed.")
        try:
            principal = await resolve_principal(principals, request, auth)
        except StoreUnavailable as exc:
            return order_problem(exc)
        if principal is None:
            return problem(401, "unauthenticated", "No verified session for this request.")
        raw = await read_capped(request)
        if raw is None:  # refused before it is parsed: unaudited, as an unreadable body is
            message = f"Send a body of at most {MAX_ORDER_BODY_BYTES} bytes."
            too_large = FieldError("body", "body_too_large", message)
            return order_problem(OrderInvalid(errors=(too_large,)))
        parsed = _parsed(raw)
        if parsed is None:  # no account to scope: unaudited, as request validation is
            message = "Send a JSON object that names the exchange account by its id."
            unread = FieldError("exchange_account_id", "required", message)
            return order_problem(OrderInvalid(errors=(unread,)))
        body, account_id = parsed
        snapshot, actor = principal.snapshot, submit_actor(principal, request)
        request_id, ip = current_request_uuid(), actor.ip
        caller = _Caller(snapshot, actor, account_id, request_id)
        try:  # step 2
            await enforce(
                snapshot, _PERMISSION, scope=Scope.GRANTED_ACCOUNTS, exchange_account_id=account_id,
                requires_trade=True, emitter=OnAccount(audit, account_id), actor_ip=ip,
                session_id=principal.session_id, request_id=request_id,
            )  # fmt: skip
        except ForbiddenError as exc:
            return rbac_refusal(exc.deny)
        except (AuditError, RuntimeError) as exc:  # counted by `enforce`; its 403 stands
            _log().warning("orders_denial_unaudited", step="rbac", error=type(exc).__name__)
            return rbac_refusal(decide(
                snapshot, _PERMISSION, scope=Scope.GRANTED_ACCOUNTS,
                exchange_account_id=account_id, requires_trade=True,
            ))  # fmt: skip
        oms = runtime()  # step 3: its `state` alone decides (SEC-S3E2-01)
        if oms is None:
            return problem(501, "not_implemented", "No OMS is composed on this backend.")
        if oms.state != "ok":
            return not_ready()
        try:
            reads, anchors, pipeline = oms.route, oms.anchors, oms.submission
            env = await reads.accounts.environment_of(account_id)  # step 4
        except OmsNotReady:  # the runtime began its stop meanwhile
            return not_ready()
        except AccountScopeDenied:
            return await scope_denied(caller)
        except OmsError as exc:
            return await audit_refusal(exc, caller, "account", None)
        step = "arm"
        try:
            armed = reads.arm_records.check(
                session_id=principal.session_id, environment=env, token=_arm_token(request)
            )
            if armed == FAILED:
                raise SessionNotArmed
            step = "key"
            key, digest = idempotency_key(request), request_fingerprint("POST", "/orders", raw)
            step = "replay"
            cached = replay_cached(kept, replay_key(snapshot.user_id, _OPERATION, key), digest)
            if cached is not None:
                return cached
            found = await anchors.lookup(snapshot.user_id, key, digest)
            if isinstance(found, Replay):
                outcome = await pipeline.answer_replay(account_id, found)
                return await replayed(reads, outcome, caller, env)
            if isinstance(found, InFlight | KeyReuse):
                raise found.refusal()
            step = "flag"
            if not oms_enabled() and body.get("reduce_only") is not True:
                raise TradingDisabled
            step = "switches"
            switched = reads.switches.refusal(account_id, env)
            if switched is not None:
                raise switched
            step = "body"
            order = _order_request(body, account_id)
        except OmsNotReady:
            return not_ready()
        except OmsError as exc:
            return await audit_refusal(exc, caller, step, env)
        context = SubmitContext(actor, key, digest, request_id)
        try:
            task = oms.run(answer(pipeline, reads, order, context, caller, env))
        except OmsNotReady:
            return not_ready()
        return await asyncio.shield(task)

    return router

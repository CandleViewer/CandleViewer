"""`POST /orders/cancel-all`, `cancelAllOrders` (E29-T04 #913 slice 4, S4-E; 24 Sec.8.4 "The exit
routes", 22 `cancelAllOrders`; the orchestrator's rulings of 2026-10-24 19:43Z).

Cancel-all's own router, on the admission the order routes share (`api/order_admission.py`) and
the exit routes' shared steps (`api/order_exits_common.py`); `app.py` includes it ahead of the exit
routes' router (the 19:43Z ruling). After the middleware (CSRF, the session state and the view-as
guard, deny-by-default) it checks, each before the next (24 Sec.8.4's numbers):

1. the principal: none is 401, one that cannot be read 503 `store_unavailable`, no source composed
   501;
2. `enforce(orders:write)`, which names no account yet (`Scope.NONE`; step 4 holds the trade
   grants): 403 `forbidden`, audited `rbac.denied`, a 403 even when its record cannot be written;
3. the runtime: none composed is 501, one whose `state` is not `ok` 503 `oms_not_ready`, never
   audited;
4. the body, read under `MAX_ORDER_BODY_BYTES` and strictly (22 `CancelAllRequest`): one it refuses
   is 400 `validation_failed` whatever ids it names, unaudited, as no account it names is in scope
   yet; then the scope, all or nothing (`CancelAll.scope`, SR-E29-13): one listed account the
   caller may not trade, or one that does not exist, refuses the whole request with 403
   `account_scope_denied` and one `rbac.denied` (a 403 even when that record cannot be written); a
   scope that cannot be read is 503 `store_unavailable`; nothing is sent either way;
7. `Idempotency-Key`: missing or not a UUID is 400 `validation_failed`;
8. the 24 h record: the same fingerprint replays the stored `200` (`Idempotency-Replayed: true`),
   another is 409 `idempotency_key_reuse`;
9. the in-flight guard (`run_claimed`, operation `cancel_all`): 409 `idempotency_in_flight`, or
   429 `rate_limited` while the guard is full, each with `Retry-After: 1`;
11. the cancels (`CancelAll.run`), as the runtime's tracked task, shielded from the client's
    disconnect: a `200` (22 `BulkAccountResult`) that the task keeps in the 24 h record itself, so
    a request cancelled midway still records it.

A cancel is never gated (C-2.6): steps 5, 6 and 10 (an amend's class, the arm token, the flag and
the switches) are not a cancel-all's. Each refusal of steps 7 to 9 is recorded before it is
answered, once per account in scope: `orders.cancel` denied, object `exchange_account`, reason its
code, detail `{operation, code, step}` (the 19:43Z ruling, C-2.9); if one does not land, the answer
is 503 `audit_unavailable`, nothing sent. A scope of no account (a caller with no trade grant who
names none) has no record to write. Every refusal, the unaudited ones too, is counted in
`oms_exit_refused_total{operation="cancel_all",code}` (20 Sec.12.1, ruling Q14). No log line,
exception or problem carries the key or the fingerprint (C-12.6).
"""

from __future__ import annotations

import asyncio
import functools
import json
import uuid
from collections.abc import Callable, Sequence
from typing import Any, Final, Literal, Protocol

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse, request_fingerprint
from candleviewer.api.order_admission import (
    MAX_ORDER_BODY_BYTES,
    ORDERS_PERMISSION,
    AuditEmitter,
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
)
from candleviewer.api.order_exits_common import (
    ExitRuntime,
    exit_caller,
    exit_refusals,
    run_claimed,
)
from candleviewer.api.order_problems import order_problem
from candleviewer.api.refusal_session import SessionsLike
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Scope
from candleviewer.auth.metrics import authz_denied_total, normalise_permission
from candleviewer.auth.scopes import Deny, DenyReason, ForbiddenError, decide, enforce
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.cancel_all import CancelAllOutcome, CancelAllRequest
from candleviewer.oms.errors import (
    AccountScopeDenied,
    AuditNotDurable,
    FieldError,
    OmsError,
    OmsNotReady,
    OrderInvalid,
    StoreUnavailable,
    problem_for,
)
from candleviewer.oms.exits import NOT_GRANTED, ExitCaller, ExitOutcome
from candleviewer.oms.ports import RequestRecord, SubmitActor, SubmitAudit
from candleviewer.oms.submit import STORE_TIMEOUT_S
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

__all__ = ["CANCEL_ALL_PATH", "CancelAllRuntime", "CancelAllService", "make_cancel_all_router"]

CANCEL_ALL_PATH: Final = "/orders/cancel-all"
#: The 24 h record's operation (its `operationId`, as `placeOrder`'s is).
_OPERATION: Final = "cancelAllOrders"
#: The in-flight guard's operation, and the counter's.
_EXIT: Final = "cancel_all"
#: Each refusal's record after the scope (the 19:43Z ruling).
_ACTION: Final = "orders.cancel"
#: A message for a code `ERROR_META` does not hold: never one the exchange wrote (SR-E29-09).
_UNNAMED: Final = "The account's selected orders were not all cancelled."

type _Step = Literal["key", "replay", "guard"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class CancelAllService(Protocol):
    """`oms.cancel_all.CancelAll`: the scope (step 4), then the cancels (step 11)."""

    async def scope(
        self, scope: AccountScope, request: CancelAllRequest
    ) -> tuple[uuid.UUID, ...]: ...

    async def run(
        self,
        accounts: Sequence[uuid.UUID],
        request: CancelAllRequest,
        *,
        actor: SubmitActor,
        request_id: uuid.UUID | None,
    ) -> CancelAllOutcome: ...


class CancelAllRuntime(ExitRuntime, Protocol):
    """`oms_wiring.OmsRuntime` as this route reads it: its `state` (step 3) and its cancel-all
    service, beside the exit service's guard and `run` (step 9 and 11)."""

    @property
    def state(self) -> str: ...

    @property
    def cancel_all(self) -> CancelAllService: ...


def _request(raw: bytes) -> CancelAllRequest:
    """Step 4's body, parsed once and read strictly (22 `CancelAllRequest`), else
    `OrderInvalid` (400): an empty `exchange_account_ids` or `intents` is every one."""
    body = parse_json_object(raw)
    if body is None:
        message = "Send a JSON object (CancelAllRequest)."
        raise OrderInvalid(errors=(FieldError("body", "model_type", message),))
    try:
        read = api.CancelAllRequest.model_validate_json(json.dumps(body), strict=True)
    except ValidationError as exc:
        raise OrderInvalid(errors=tuple(field_errors(exc))) from None
    return CancelAllRequest(
        exchange_account_ids=tuple(read.exchange_account_ids or ()),
        symbol=None if read.symbol is None else read.symbol.root,
        intents=frozenset(read.intents or ()),
        exclude_reduce_only=read.exclude_reduce_only,
    )


def _message(code: str) -> str:
    """An account error's `message`: the OMS's own text for its code (SR-E29-09)."""
    try:
        return ERROR_META[ErrorCode(code)].title
    except ValueError:  # every code an account reports is registered (a test pins the list)
        return _UNNAMED


def _result(outcome: CancelAllOutcome) -> dict[str, Any]:
    """22 `BulkAccountResult`, each account in the order the scope answered them."""
    results = [
        api.Result(
            exchange_account_id=entry.exchange_account_id,
            ok=entry.ok,
            affected=entry.affected,
            error=None
            if entry.error is None
            else api.LegError(
                code=entry.error.code,
                message=_message(entry.error.code),
                exchange_ret_code=entry.error.exchange_ret_code,
                retryable=entry.error.retryable,
            ),
        )
        for entry in outcome.accounts
    ]
    body = api.BulkAccountResult(
        results=results, requested=outcome.requested, succeeded=outcome.succeeded
    )
    return body.model_dump(mode="json")


def _guard_problem(outcome: ExitOutcome) -> JSONResponse:
    """The in-flight guard's refusal (22's problem for its code), with its `Retry-After`."""
    code, retry = outcome.code or "rate_limited", outcome.retry_after_s
    detail = outcome.detail or ERROR_META[ErrorCode(code)].title
    if retry is None:
        return problem(outcome.status, code, detail)
    answer = problem(outcome.status, code, detail, retry_after_seconds=retry)
    answer.headers["Retry-After"] = str(retry)
    return answer


def make_cancel_all_router(
    principals: OrderPrincipals | None,
    runtime: Callable[[], CancelAllRuntime | None],
    *,
    audit: AuditEmitter,
    records: SubmitAudit,
    metrics: Metrics,
    auth: SessionsLike | None = None,
    replays: IdempotencyCache | None = None,
    pager: Pager | None = None,
) -> APIRouter:
    """`POST /orders/cancel-all` (module docstring). No principal source (no identity composed)
    answers 501, as no runtime (the fake backend) does after RBAC. `audit` takes `rbac.denied`,
    `records` the refusals after the scope; `replays` is the 24 h record of first `2xx` answers."""
    router = APIRouter(tags=["trading"])
    kept = replays if replays is not None else IdempotencyCache()
    paging: Pager = LogPager() if pager is None else pager
    refusals = exit_refusals(metrics)

    def count(code: str) -> None:
        refusals.labels(_EXIT, code).inc()

    def refused(error: OmsError) -> JSONResponse:
        """`error`'s problem, counted as it is answered (ruling Q14)."""
        count(problem_for(error).code)
        return order_problem(error, pager=paging)

    def unwired(detail: str) -> JSONResponse:
        count("not_implemented")
        return problem(501, "not_implemented", detail)

    def rbac_denied(decision: object) -> JSONResponse:
        """Step 2's 403, counted: `forbidden` without the permission (`rbac_refusal`)."""
        missing = isinstance(decision, Deny) and decision.reason is DenyReason.MISSING_PERMISSION
        count("forbidden" if missing else "account_scope_denied")
        return rbac_refusal(decision)

    def page(summary: str) -> None:
        _log().critical(summary)
        try:
            paging.raise_alert("page", summary, machine_kind="order")
        except Exception as exc:  # the page is lost, never the answer
            _log().critical("oms_pager_failed", summary=summary, error=type(exc).__name__)

    async def scope_denied(caller: ExitCaller, request: CancelAllRequest) -> Response:
        """Step 4's refusal of the whole request: counted, then one `rbac.denied` naming the ids
        it listed, as `enforce` writes one; a 403 even when that record cannot be written."""
        authz_denied_total.labels(permission=normalise_permission(ORDERS_PERMISSION)).inc()
        actor, listed = caller.actor, [str(account) for account in request.exchange_account_ids]
        try:
            await audit.emit(
                "rbac.denied", actor_label=str(actor.user_id), actor_user_id=actor.user_id,
                actor_ip=actor.ip, session_id=actor.session_id, outcome="denied",
                severity="warning", reason=NOT_GRANTED, request_id=caller.request_id,
                after_state={"operation": _EXIT, "exchange_account_ids": listed},
            )  # fmt: skip
        except (AuditError, RuntimeError) as exc:  # RuntimeError: the writer is not started
            _log().warning("orders_cancel_all_denial_unaudited", error=type(exc).__name__)
        return refused(AccountScopeDenied())

    async def recorded(
        accounts: Sequence[uuid.UUID],
        caller: ExitCaller,
        step: _Step,
        code: str,
        status: int,
        answer: Callable[[], JSONResponse],
    ) -> Response:
        """A refusal of steps 7 to 9: one `orders.cancel` denied per account in scope, each
        within the store's bound, before it is answered (C-2.9); 503 when one does not land."""
        severity: Literal["warning", "error"] = "error" if status >= 500 else "warning"
        detail = {"operation": _EXIT, "code": code, "step": step}
        try:
            for account in accounts:
                record = RequestRecord(
                    _ACTION, account, "exchange_account", account, "denied", severity, code,
                    caller.actor, detail, caller.request_id,
                )  # fmt: skip
                async with asyncio.timeout(STORE_TIMEOUT_S):
                    await records.write(record)
        except Exception as exc:  # no refusal is answered unrecorded: nothing was sent
            failure = type(exc).__name__
            _log().error("orders_cancel_all_unrecorded", code=code, step=step, error=failure)
            return refused(AuditNotDurable("the refusal's record did not land"))
        count(code)
        return answer()

    async def refusal(
        accounts: Sequence[uuid.UUID], caller: ExitCaller, step: _Step, error: OmsError
    ) -> Response:
        row, answer = problem_for(error), functools.partial(order_problem, error, pager=paging)
        return await recorded(accounts, caller, step, row.code, row.status, answer)

    @router.post(CANCEL_ALL_PATH, status_code=200)
    async def cancel_all_orders(request: Request) -> Response:
        if principals is None:
            return unwired("No principal source is composed.")
        try:
            principal = await resolve_principal(principals, request, auth)
        except StoreUnavailable as exc:
            return refused(exc)
        if principal is None:
            count("unauthenticated")
            return problem(401, "unauthenticated", "No verified session for this request.")
        snapshot, caller = principal.snapshot, exit_caller(principal, request)
        try:  # step 2: the permission alone; the scope's grants are step 4's
            await enforce(
                snapshot, ORDERS_PERMISSION, scope=Scope.NONE, emitter=audit,
                actor_ip=caller.actor.ip, session_id=principal.session_id,
                request_id=caller.request_id,
            )  # fmt: skip
        except ForbiddenError as exc:
            return rbac_denied(exc.deny)
        except (AuditError, RuntimeError) as exc:  # counted by `enforce`; its 403 stands
            _log().warning("orders_cancel_all_denial_unaudited", error=type(exc).__name__)
            return rbac_denied(decide(snapshot, ORDERS_PERMISSION))
        oms = runtime()  # step 3: its `state` alone decides
        if oms is None:
            return unwired("No OMS is composed on this backend.")
        if oms.state != "ok":
            return refused(OmsNotReady())
        raw = await read_capped(request)  # step 4: the body, then the scope
        if raw is None:  # refused before it is parsed: unaudited, as an unreadable body is
            message = f"Send a body of at most {MAX_ORDER_BODY_BYTES} bytes."
            return refused(OrderInvalid(errors=(FieldError("body", "body_too_large", message),)))
        try:
            asked = _request(raw)
        except OrderInvalid as exc:  # no account it names is in scope yet: unaudited
            return refused(exc)
        try:
            service = oms.cancel_all
            accounts = await service.scope(caller.scope, asked)
        except AccountScopeDenied:
            return await scope_denied(caller, asked)
        except OmsError as exc:  # the scope's 503, or the runtime's stop begun meanwhile
            return refused(exc)
        step: _Step = "key"
        try:
            key = idempotency_key(request)
            digest = request_fingerprint("POST", CANCEL_ALL_PATH, raw)
            step = "replay"
            held = replay_key(snapshot.user_id, _OPERATION, key)
            cached = replay_cached(kept, held, digest)
        except OmsError as exc:
            return await refusal(accounts, caller, step, exc)
        if cached is not None:
            return cached

        async def guard_refused(outcome: ExitOutcome) -> Response:
            answer = functools.partial(_guard_problem, outcome)
            code = outcome.code or "rate_limited"
            return await recorded(accounts, caller, "guard", code, outcome.status, answer)

        async def cancels() -> Response:
            """Step 11's task: the cancels' `200`, kept for 24 h by the task itself."""
            try:
                outcome = await service.run(
                    accounts, asked, actor=caller.actor, request_id=caller.request_id
                )
            except Exception as exc:  # a defect: each cancel already sent stays with B1
                page("orders_cancel_all_failed")
                _log().error("orders_cancel_all_failed", error=type(exc).__name__)
                return refused(OmsError("cancel-all's run failed"))
            out = JSONResponse(_result(outcome), 200)
            kept.put(*held, StoredResponse(digest, 200, bytes(out.body), None))
            return out

        try:
            return await run_claimed(
                oms, snapshot.user_id, _EXIT, key, cancels, refused=guard_refused
            )
        except OmsNotReady:  # the runtime began its stop after step 3: nothing ran
            return refused(OmsNotReady())

    return router

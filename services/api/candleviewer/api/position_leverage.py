"""`PUT /positions/{positionId}/leverage`, `setPositionLeverage` (E29-T07 #915; 22).

After the middleware (CSRF, the session state and the view-as guard, which refuses this write in a
view-as context: it is no protective write) the route checks, each before the next:

1. the principal (`resolve_principal`): none composed is 501, none found 401, one whose store does
   not answer 503 `store_unavailable`; then the path id, which is not a UUID is 400
   `validation_failed`, unaudited, as it names no position;
2. `enforce(positions:write)`, then `enforce(admin:write)`: the change is the Owner's alone (22,
   04 Sec.7.2.2 row 18, ruled on #915 as D7 was for diagnostics), so a Manager or a Viewer is 403
   `forbidden` before any position is read, whatever the id, audited `rbac.denied`, a 403 even
   when that record cannot be written;
3. the caller's rate (ruling BQ-15, on the model of the recording writes' `WriteLimiter`): past
   `rate_per_minute` changes a minute, 429 `rate_limited` with `Retry-After`, unaudited;
4. the body, read under `MAX_LEVERAGE_BODY_BYTES` and strictly (22: `leverage`, a `Decimal`,
   and nothing else): 422 `validation_failed`, each rule named, unaudited;
5. the position, read in the caller's scope in SQL (`OmsReads.position`, C-12.4): none composed is
   503 `store_unavailable`; a foreign id and a missing one are the same 404 `not_found`, the
   foreign one counted and audited `rbac.denied` (SR-E29-13); then the trade grant on its account
   (`enforce` with `requires_trade`): 403 `account_scope_denied`, audited;
6. the runtime: none composed is 501, one whose readiness is not `ok` 503 `oms_not_ready` with
   `Retry-After`, counted and never audited;
7. the arm token (22 `ArmToken`: a leverage change in either direction on a live account): 403
   `session_not_armed`; 8. `Idempotency-Key`; 9. the 24 h record of first `200` answers, by
   principal, operation and key, whose fingerprint is the method, the path and the body: a repeat
   is the stored answer, `Idempotency-Replayed: true`, another body under the key 409
   `idempotency_key_reuse`; 10. the in-flight guard: the key's first request still running is 409
   `idempotency_in_flight` with `Retry-After: 1`, a guard holding `MAX_IN_FLIGHT` keys 429
   `rate_limited`; 11. `trading.oms_enabled`, off: 403 `trading_disabled`;
12. the change (`oms.leverage.PositionLeverage`), run by the runtime as a task it tracks and
    shielded from the client's disconnect: the switches, the bounds (422 `validation_failed`), the
    write-ahead record, the venue's call. Its `200` is 22 `Position`: the row as read at step 5,
    with the leverage the venue now holds (the private stream brings the rest of the row).

Every refusal from step 7 on is recorded (`position.leverage_changed`, outcome `denied`, its code)
before it is answered, else 503 `audit_unavailable`, the key unbound (C-2.9). No log line or
problem carries the key, the fingerprint or the token (C-12.6).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import replace
from decimal import Decimal
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.csrf import source_ip
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse, request_fingerprint
from candleviewer.api.oms_reads import position_document
from candleviewer.api.order_admission import (
    AuditEmitter,
    OnAccount,
    OrderPrincipals,
    arm_token,
    idempotency_key,
    parse_json_object,
    problem,
    read_capped,
    replay_cached,
    replay_key,
    resolve_principal,
    submit_actor,
)
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.order_problems import order_problem
from candleviewer.api.recording_writes import WriteLimiter
from candleviewer.api.refusal_session import SessionsLike
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import ForbiddenError, account_scope, enforce
from candleviewer.domain.primitives import AccountId, Symbol
from candleviewer.observability.context import current_request_uuid
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.errors import (
    PROBLEMS,
    AccountScopeDenied,
    AuditNotDurable,
    FieldError,
    IdempotencyInFlight,
    OmsError,
    OmsNotReady,
    SessionNotArmed,
    StoreUnavailable,
    TradingDisabled,
    problem_for,
)
from candleviewer.oms.leverage import (
    LEVERAGE_ACTION,
    LeverageOutcome,
    LeverageOutOfBounds,
    LeverageRequest,
)
from candleviewer.oms.ports import FAILED, ArmRecords, RequestRecord, SubmitActor, SubmitAudit
from candleviewer.oms.reads import OmsReads
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.storage.repositories.positions import PositionRow

__all__ = [
    "LEVERAGE_PATH", "MAX_IN_FLIGHT", "MAX_LEVERAGE_BODY_BYTES", "RATE_PER_MINUTE",
    "LeverageRuntime", "make_position_leverage_router",
]  # fmt: skip

_OPERATION: Final = "setPositionLeverage"
LEVERAGE_PATH: Final = "/positions/{positionId}/leverage"
_PERMISSION: Final = Permission.POSITIONS_WRITE
#: 22 `x-rbac`: both, in this order; `admin:write` is the Owner's alone (step 2).
_PERMISSIONS: Final = (Permission.POSITIONS_WRITE, Permission.ADMIN_WRITE)
#: The body is `{"leverage": "<decimal>"}`: far under 1 KiB, refused past it before it is parsed.
MAX_LEVERAGE_BODY_BYTES: Final = 1_024
#: Changes a user may make a minute (ruling BQ-15); the venue allows ten a second per account.
RATE_PER_MINUTE: Final = 20
#: Keys the in-flight guard holds at once (C-2.18), as the exit routes' guard bounds its own.
MAX_IN_FLIGHT: Final = 1_024
#: 22 `Decimal`, at most 16 digits a side: a leverage has two places and three integer digits.
_DECIMAL: Final = re.compile(r"[0-9]{1,16}(\.[0-9]{1,16})?")
_MEDIA: Final = "application/problem+json"
_NOT_GRANTED: Final = f"account_not_granted:{_PERMISSION.value}:{Scope.GRANTED_ACCOUNTS.value}"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Changes(Protocol):
    async def apply(
        self, request: LeverageRequest, *, actor: SubmitActor, request_id: uuid.UUID | None
    ) -> LeverageOutcome: ...


class _RouteReads(Protocol):
    @property
    def arm_records(self) -> ArmRecords: ...


class LeverageRuntime(Protocol):
    """`oms_wiring.OmsRuntime` as this route reads it: its readiness (the submit's, `degraded`
    too once its environment's lock is lost), its arm records, the change's service and `run`."""

    @property
    def readiness(self) -> str: ...
    @property
    def route(self) -> _RouteReads: ...
    @property
    def leverage(self) -> _Changes: ...
    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]: ...


def _invalid(*errors: FieldError, status: int = 422) -> JSONResponse:
    """`validation_failed` with each rule named: 422, as 22 declares for this operation's body
    and bounds; 400 for the path id and the key, which name no body."""
    detail = errors[0].message if len(errors) == 1 else f"{len(errors)} rules failed."
    body: dict[str, object] = {
        "type": "https://candleviewer.local/errors/validation_failed", "status": status,
        "title": "Request body or parameters failed schema validation", "code": "validation_failed",
        "detail": detail,
        "errors": [{"field": e.field, "rule": e.rule, "message": e.message} for e in errors],
    }  # fmt: skip
    return JSONResponse(body, status, media_type=_MEDIA)


def leverage_of(raw: bytes) -> Decimal | tuple[FieldError, ...]:
    """Step 4: the body's `leverage`, a `Decimal` read from 22's string (never a float), or the
    rules it breaks: a JSON object with that one member, a string in 22's `Decimal` pattern."""
    body = parse_json_object(raw)
    if body is None:
        return (FieldError("body", "json_object", "Send a JSON object."),)
    unknown = sorted(set(body) - {"leverage"})
    errors = [FieldError(name, "extra_forbidden", "Unknown member.") for name in unknown]
    value = body.get("leverage")
    if isinstance(value, str) and _DECIMAL.fullmatch(value):
        return tuple(errors) if errors else Decimal(value)
    if "leverage" not in body:
        errors.append(FieldError("leverage", "required", "Send the leverage."))
    else:
        message = 'Send the leverage as a decimal string, such as "10".'
        errors.append(FieldError("leverage", "decimal", message))
    return tuple(errors)


def make_position_leverage_router(
    principals: OrderPrincipals | None, runtime: Callable[[], LeverageRuntime | None],
    reads: OmsReads | None, *, audit: AuditEmitter, records: SubmitAudit,
    oms_enabled: Callable[[], bool], metrics: Metrics, auth: SessionsLike | None = None,
    replays: IdempotencyCache | None = None, limiter: WriteLimiter | None = None,
    pager: Pager | None = None,
) -> APIRouter:  # fmt: skip
    """`PUT /positions/{positionId}/leverage` (module docstring). `audit` takes `rbac.denied`,
    `records` the change's refusals; `replays` is the 24 h record of first `200` answers."""
    router = APIRouter(tags=["positions"])
    kept = replays if replays is not None else IdempotencyCache()
    rate = limiter if limiter is not None else WriteLimiter(rate_per_minute=RATE_PER_MINUTE)
    paging: Pager = LogPager() if pager is None else pager
    running: set[tuple[str, str]] = set()
    spec = next(spec for spec in CATALOGUE if spec.name == "oms_submit_rejected_total")
    rejected = metrics.counter(spec.name, spec.help, spec.labels, max_series=spec.max_series)

    def not_ready() -> Response:
        rejected.labels(PROBLEMS[OmsNotReady].code).inc()
        return order_problem(OmsNotReady(), pager=paging)

    async def denied(
        principal: TradingPrincipal, request: Request, named: dict[str, str], account: uuid.UUID
    ) -> None:
        """A scope refusal's `rbac.denied`, best effort: its answer stands (step 5)."""
        count_authz_denial(_PERMISSION, principal.snapshot.roles, route=_OPERATION)
        actor = submit_actor(principal, request)
        try:
            await OnAccount(audit, AccountId(account)).emit(
                "rbac.denied", actor_label=str(actor.user_id), actor_user_id=actor.user_id,
                actor_ip=actor.ip, session_id=actor.session_id, outcome="denied",
                severity="warning", reason=_NOT_GRANTED, request_id=current_request_uuid(),
                after_state=named,
            )  # fmt: skip
        except (AuditError, RuntimeError) as exc:  # RuntimeError: the writer is not started
            _log().warning("oms_leverage_denial_unaudited", error=type(exc).__name__)

    async def refused(error: OmsError, row: PositionRow, actor: SubmitActor, step: str) -> Response:
        """A refusal from step 7 on: recorded before it is answered (C-2.9), else 503."""
        code = problem_for(error).code
        record = RequestRecord(
            LEVERAGE_ACTION, row.exchange_account_id, "position", row.id, "denied",
            "error" if problem_for(error).status >= 500 else "warning", code, actor,
            {"step": step, "code": code, "symbol": row.symbol}, current_request_uuid(),
        )  # fmt: skip
        try:
            async with asyncio.timeout(5.0):
                await records.write(record)
        except Exception as exc:  # no refusal is answered unrecorded; the key stays unbound
            rejected.labels(PROBLEMS[AuditNotDurable].code).inc()
            _log().error("oms_leverage_refusal_unrecorded", step=step, error=type(exc).__name__)
            return order_problem(AuditNotDurable("the refusal's record did not land"))
        rejected.labels(code).inc()
        return order_problem(error, pager=paging)

    def answered(error: OmsError) -> Response:
        """The service's refusal, which it recorded: its problem, a bound 422."""
        if isinstance(error, OmsNotReady):
            return not_ready()
        rejected.labels(problem_for(error).code).inc()
        if isinstance(error, LeverageOutOfBounds):
            return _invalid(*error.errors)
        return order_problem(error, pager=paging)

    async def change(
        oms: LeverageRuntime, row: PositionRow, leverage: Decimal, actor: SubmitActor,
        held: tuple[str, str], digest: str,
    ) -> Response:  # fmt: skip
        """Step 12's task: the change's answer, and a first `200` kept for 24 h."""
        asked = LeverageRequest(
            row.id, AccountId(row.exchange_account_id), Symbol(row.symbol), row.leverage, leverage
        )
        try:
            outcome = await oms.leverage.apply(
                asked, actor=actor, request_id=current_request_uuid()
            )
        except OmsError as exc:
            return answered(exc)
        body = position_document(replace(row, leverage=outcome.leverage))
        out = JSONResponse(body, 200)
        kept.put(*held, StoredResponse(digest, 200, bytes(out.body), None))
        return out

    @router.put(LEVERAGE_PATH)
    async def set_position_leverage(
        request: Request, position_ref: Annotated[str, Path(alias="positionId")]
    ) -> Response:
        if principals is None:
            return problem(501, "not_implemented", "No principal source is composed.")
        try:
            principal = await resolve_principal(principals, request, auth)
        except StoreUnavailable:
            return problem(503, "store_unavailable", "The session could not be read.")
        if principal is None:
            return problem(401, "unauthenticated", "No verified session for this request.")
        try:
            position_id = uuid.UUID(position_ref)
        except ValueError:
            return _invalid(FieldError("positionId", "uuid", "Name it by its id."), status=400)
        snapshot, request_id = principal.snapshot, current_request_uuid()
        try:  # step 2: a capability refusal, before any position is read
            for permission in _PERMISSIONS:
                await enforce(
                    snapshot, permission, emitter=audit, actor_ip=source_ip(request.scope),
                    session_id=principal.session_id, request_id=request_id,
                )  # fmt: skip
        except (ForbiddenError, AuditError, RuntimeError) as exc:
            if not isinstance(exc, ForbiddenError):  # counted by `enforce`; its 403 stands
                _log().warning("oms_leverage_denial_unaudited", error=type(exc).__name__)
            need = [p.value for p in _PERMISSIONS]
            detail = "Requires positions:write and admin:write."
            return problem(403, "forbidden", detail, required_permissions=need)
        wait = rate.admit(str(snapshot.user_id))  # step 3
        if wait is not None:
            body = {"retry_after_seconds": wait}
            out = problem(429, "rate_limited", "Too many leverage changes; retry later.", **body)
            out.headers["Retry-After"] = str(wait)
            return out
        raw = await read_capped(request, MAX_LEVERAGE_BODY_BYTES)  # step 4
        if raw is None:
            message = f"Send a body of at most {MAX_LEVERAGE_BODY_BYTES} bytes."
            return _invalid(FieldError("body", "body_too_large", message))
        leverage = leverage_of(raw)
        if isinstance(leverage, tuple):
            return _invalid(*leverage)
        if reads is None:  # step 5
            return problem(503, "store_unavailable", "The OMS reads are not available here.")
        try:
            found = await reads.position(account_scope(snapshot), position_id)
        except (AccountScopeDenied, StoreUnavailable):
            return problem(503, "store_unavailable", "The OMS store is unavailable.")
        if not isinstance(found, PositionRow):
            if found.account_id is not None:
                named = {"object_kind": "position", "object_id": str(position_id)}
                await denied(principal, request, named, found.account_id)
            return problem(404, "not_found", "No such position.")
        row = found
        try:
            await enforce(
                snapshot, _PERMISSION, scope=Scope.GRANTED_ACCOUNTS,
                exchange_account_id=row.exchange_account_id, requires_trade=True,
                emitter=OnAccount(audit, AccountId(row.exchange_account_id)),
                actor_ip=source_ip(request.scope), session_id=principal.session_id,
                request_id=request_id,
            )  # fmt: skip
        except (ForbiddenError, AuditError, RuntimeError) as exc:
            if not isinstance(exc, ForbiddenError):
                _log().warning("oms_leverage_denial_unaudited", error=type(exc).__name__)
            return order_problem(AccountScopeDenied())
        oms = runtime()  # step 6
        if oms is None:
            return problem(501, "not_implemented", "No OMS is composed on this backend.")
        if oms.readiness != "ok":
            return not_ready()
        actor, step = submit_actor(principal, request), "arm"
        try:
            armed = oms.route.arm_records.check(
                session_id=principal.session_id, environment=reads.environment,
                token=arm_token(request),
            )  # fmt: skip
            if armed == FAILED:
                raise SessionNotArmed
            step = "key"
            key = idempotency_key(request)
            path = LEVERAGE_PATH.replace("{positionId}", str(position_id))
            digest = request_fingerprint("PUT", path, raw)
            step = "replay"
            held = replay_key(snapshot.user_id, _OPERATION, key)
            cached = replay_cached(kept, held, digest)
            if cached is not None:
                return cached
            step = "guard"
            if held in running:
                raise IdempotencyInFlight(retry_after_s=1)
            if len(running) >= MAX_IN_FLIGHT:
                out = problem(429, "rate_limited", "Too many changes in flight; retry later.")
                out.headers["Retry-After"] = "1"
                return out
            step = "flag"
            if not oms_enabled():
                raise TradingDisabled
        except OmsNotReady:
            return not_ready()
        except OmsError as exc:
            return await refused(exc, row, actor, step)
        running.add(held)
        try:
            task = oms.run(change(oms, row, leverage, actor, held, digest))
        except OmsNotReady:
            running.discard(held)
            return not_ready()
        task.add_done_callback(lambda _done: running.discard(held))
        return await asyncio.shield(task)

    return router

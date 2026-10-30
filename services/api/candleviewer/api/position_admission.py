"""The admission the position write routes share (E29-T07 #915; 22 `closePosition`,
`reversePosition`): the steps before any OMS call, each before the next.

1. the principal (`resolve_principal`): none composed is 501, none found 401, one whose store does
   not answer 503 `store_unavailable`; then the path id, which is not a UUID is 400
   `validation_failed`, unaudited, as it names no position;
2. `enforce(positions:write)`: 403 `forbidden` without it, audited `rbac.denied`, a 403 even when
   that record cannot be written;
3. the caller's rate (ruling BQ-15, the recording writes' `WriteLimiter`): past the route's
   changes a minute, 429 `rate_limited` with `Retry-After`, unaudited, nothing bound;
4. the body, read under the route's cap and parsed by the route (`parse`): 422
   `validation_failed`, each rule named, unaudited;
5. the position, read in the caller's scope in SQL (`OmsReads.position`, C-12.4): none composed
   is 503 `store_unavailable`; a foreign id and a missing one are the same 404 `not_found`, the
   foreign one counted and audited `rbac.denied` (SR-E29-13); then the trade grant on its account
   (`enforce` with `requires_trade`): 403 `account_scope_denied`, audited. The scope is
   `scope_for_target`'s: the caller's own, narrowed to the target's trade grants for a protective
   close in a live view-as context (22 "View-as session"); the other routes never carry a target,
   as the view-as guard refuses them first.

No log line or problem carries the key, the fingerprint or a value of the row (C-12.6).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.csrf import source_ip
from candleviewer.api.order_admission import (
    AuditEmitter,
    OnAccount,
    OrderPrincipals,
    problem,
    read_capped,
    resolve_principal,
    submit_actor,
)
from candleviewer.api.order_principal import TradingPrincipal, scope_for_target
from candleviewer.api.order_problems import order_problem
from candleviewer.api.recording_writes import WriteLimiter
from candleviewer.api.refusal_session import SessionsLike
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import ForbiddenError, enforce
from candleviewer.domain.primitives import AccountId
from candleviewer.observability.context import current_request_uuid
from candleviewer.oms.errors import AccountScopeDenied, FieldError, StoreUnavailable
from candleviewer.oms.ports import SubmitActor
from candleviewer.oms.reads import OmsReads
from candleviewer.storage.repositories.positions import PositionRow

__all__ = ["POSITIONS_WRITE", "PositionCaller", "admit_position_write", "invalid", "rate_limited"]

POSITIONS_WRITE: Final = Permission.POSITIONS_WRITE
_MEDIA: Final = "application/problem+json"
_NOT_GRANTED: Final = f"account_not_granted:{POSITIONS_WRITE.value}:{Scope.GRANTED_ACCOUNTS.value}"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PositionCaller[T]:
    """An admitted request: its principal, its records' actor, the position read in its scope,
    the raw body, the body as the route's parser read it, and the correlation id."""

    principal: TradingPrincipal
    actor: SubmitActor
    row: PositionRow
    raw: bytes
    request_id: uuid.UUID | None
    body: T


def invalid(*errors: FieldError, status: int = 422) -> JSONResponse:
    """`validation_failed` with each rule named: 422 for a body, 400 for the path id or the key."""
    detail = errors[0].message if len(errors) == 1 else f"{len(errors)} rules failed."
    body: dict[str, object] = {
        "type": "https://candleviewer.local/errors/validation_failed", "status": status,
        "title": "Request body or parameters failed schema validation", "code": "validation_failed",
        "detail": detail,
        "errors": [{"field": e.field, "rule": e.rule, "message": e.message} for e in errors],
    }  # fmt: skip
    return JSONResponse(body, status, media_type=_MEDIA)


def rate_limited(wait: int, what: str) -> Response:
    """Step 3's 429 (ruling BQ-15), or an in-flight guard that is full."""
    out = problem(429, "rate_limited", f"Too many {what}; retry later.", retry_after_seconds=wait)
    out.headers["Retry-After"] = str(wait)
    return out


async def _denied(
    audit: AuditEmitter, principal: TradingPrincipal, request: Request, account: uuid.UUID,
    position_id: uuid.UUID, operation: str,
) -> None:  # fmt: skip
    """A foreign position's `rbac.denied`, best effort: its 404 stands (step 5)."""
    count_authz_denial(POSITIONS_WRITE, principal.snapshot.roles, route=operation)
    actor = submit_actor(principal, request)
    named = {"object_kind": "position", "object_id": str(position_id)}
    try:
        await OnAccount(audit, AccountId(account)).emit(
            "rbac.denied", actor_label=str(actor.user_id), actor_user_id=actor.user_id,
            actor_ip=actor.ip, session_id=actor.session_id, outcome="denied",
            severity="warning", reason=_NOT_GRANTED, request_id=current_request_uuid(),
            after_state=named,
        )  # fmt: skip
    except (AuditError, RuntimeError) as exc:  # RuntimeError: the writer is not started
        _log().warning("oms_position_denial_unaudited", error=type(exc).__name__)


async def admit_position_write[T](
    request: Request, position_ref: str, *, operation: str, principals: OrderPrincipals | None,
    auth: SessionsLike | None, audit: AuditEmitter, reads: OmsReads | None, limiter: WriteLimiter,
    max_body: int, parse: Callable[[bytes], T | tuple[FieldError, ...]],
) -> PositionCaller[T] | Response:  # fmt: skip
    """Steps 1 to 5 (module docstring): the admitted caller, or the answer that refused it."""
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
        return invalid(FieldError("positionId", "uuid", "Name it by its id."), status=400)
    snapshot, request_id, ip = principal.snapshot, current_request_uuid(), source_ip(request.scope)
    try:  # step 2
        await enforce(
            snapshot, POSITIONS_WRITE, emitter=audit, actor_ip=ip,
            session_id=principal.session_id, request_id=request_id,
        )  # fmt: skip
    except (ForbiddenError, AuditError, RuntimeError) as exc:
        if not isinstance(exc, ForbiddenError):  # counted by `enforce`; its 403 stands
            _log().warning("oms_position_denial_unaudited", error=type(exc).__name__)
        need = [POSITIONS_WRITE.value]
        return problem(403, "forbidden", "Requires positions:write.", required_permissions=need)
    wait = limiter.admit(str(snapshot.user_id))  # step 3
    if wait is not None:
        return rate_limited(wait, "position writes")
    raw = await read_capped(request, max_body)  # step 4
    if raw is None:
        return invalid(FieldError("body", "body_too_large", f"Send at most {max_body} bytes."))
    body = parse(raw)
    if isinstance(body, tuple):  # the rules it breaks; a parsed body is never a tuple
        return invalid(*body)
    if reads is None:  # step 5
        return problem(503, "store_unavailable", "The OMS reads are not available here.")
    try:
        found = await reads.position(scope_for_target(snapshot, principal.target), position_id)
    except (AccountScopeDenied, StoreUnavailable):
        return problem(503, "store_unavailable", "The OMS store is unavailable.")
    if not isinstance(found, PositionRow):
        if found.account_id is not None:
            await _denied(audit, principal, request, found.account_id, position_id, operation)
        return problem(404, "not_found", "No such position.")
    try:
        await enforce(
            snapshot, POSITIONS_WRITE, scope=Scope.GRANTED_ACCOUNTS,
            exchange_account_id=found.exchange_account_id, requires_trade=True,
            emitter=OnAccount(audit, AccountId(found.exchange_account_id)), actor_ip=ip,
            session_id=principal.session_id, request_id=request_id,
        )  # fmt: skip
    except (ForbiddenError, AuditError, RuntimeError) as exc:
        if not isinstance(exc, ForbiddenError):
            _log().warning("oms_position_denial_unaudited", error=type(exc).__name__)
        return order_problem(AccountScopeDenied())
    actor = submit_actor(principal, request)
    return PositionCaller(principal, actor, found, raw, request_id, body)

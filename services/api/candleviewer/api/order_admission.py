"""The admission the order routes share (E29-T04 #913; 24-internal-schemas.md Sec.8.4).

`POST /orders` (`api/orders.py`) and the exit routes (`DELETE` / `PATCH /orders/{orderId}`,
`POST /orders/cancel-all`) admit a request the same way, so these steps live once, here
(#913 slice 4, S4-D1): the principal (`resolve_principal`), step 2's RBAC refusal
(`rbac_refusal`), a body read under its cap and parsed once (`read_capped`, `parse_json_object`),
the `Idempotency-Key` (`idempotency_key`), the 24 h record of first `2xx` answers (`replay_key`,
`replay_cached`; the fingerprint is `api/idempotency.request_fingerprint`), the problems no
`PROBLEMS` row names (`problem`), the records' actor (`submit_actor`) and an `rbac.denied` record
naming the account it concerns (`OnAccount`). No log line, exception or problem carries the key or
the fingerprint (C-12.6).
"""

from __future__ import annotations

import inspect
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Final, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from candleviewer.api.csrf import source_ip
from candleviewer.api.idempotency import IdempotencyCache
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.order_problems import order_problem
from candleviewer.api.refusal_session import SessionsLike, refusal_session
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import Deny, DenyReason, PrincipalSnapshot
from candleviewer.domain.primitives import AccountId
from candleviewer.observability.redaction import redact_text
from candleviewer.oms.errors import (
    AccountScopeDenied,
    FieldError,
    IdempotencyKeyReuse,
    OrderInvalid,
)
from candleviewer.oms.ports import SubmitActor
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

__all__ = [
    "MAX_ORDER_BODY_BYTES", "ORDERS_PERMISSION", "AuditEmitter", "OnAccount", "OrderPrincipals",
    "field_errors", "idempotency_key", "parse_json_object", "problem", "rbac_refusal",
    "read_capped", "replay_cached", "replay_key", "resolve_principal", "submit_actor",
]  # fmt: skip

#: The body's ceiling, held before it is parsed (C-2.18): 16 KiB, as `api/feature_flags.py` and the
#: indicator presets bound theirs. 22's largest request, a 280-character `note` escaped as
#: surrogate pairs (3,360 bytes) beside every other member, fits with room for indentation, which
#: the workspaces' 4 KiB would not leave.
MAX_ORDER_BODY_BYTES: Final = 16 * 1024
#: The permission every order route checks at step 2 (22 `x-rbac`).
ORDERS_PERMISSION: Final = Permission.ORDERS_WRITE
_LENGTH: Final = re.compile(r"[0-9]{1,19}")  # a usable `Content-Length`, as `api/rule_body.py`


class OrderPrincipals(Protocol):
    """`SessionTradingPrincipalResolver`, or a test seam's `SnapshotResolver`."""

    def resolve(self, request: Request) -> object: ...


class AuditEmitter(Protocol):
    """The audit writer's `emit`, as `rbac.denied` is written through it."""

    async def emit(self, action: str, **fields: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class OnAccount:
    """`enforce` names no object: a route's `rbac.denied` names the account it concerns (C-2.9)."""

    audit: AuditEmitter
    account_id: AccountId

    async def emit(
        self, action: str, *, request_id: uuid.UUID | None = None, **fields: Any
    ) -> None:
        """The record, its request's id forwarded as the caller named it (#3990)."""
        named = {"object_kind": "exchange_account", "object_id": str(self.account_id)}
        await self.audit.emit(action, request_id=request_id, **fields | named)


def problem(status: int, code: str, detail: str, **extra: object) -> JSONResponse:
    """A problem no `PROBLEMS` row names: 401, the RBAC 403 `forbidden`, 501."""
    body = {"type": f"https://candleviewer.local/errors/{code}", "status": status, "code": code}
    body |= {"title": ERROR_META[ErrorCode(code)].title, "detail": detail, **extra}
    return JSONResponse(body, status, media_type="application/problem+json")


def rbac_refusal(decision: object) -> JSONResponse:
    """Step 2's 403: `forbidden` without the permission, else `account_scope_denied`."""
    if isinstance(decision, Deny) and decision.reason is DenyReason.MISSING_PERMISSION:
        need = [ORDERS_PERMISSION.value]
        return problem(403, "forbidden", "Requires orders:write.", required_permissions=need)
    return order_problem(AccountScopeDenied())


def _refuse_constant(name: str) -> object:
    raise ValueError(f"{name} is not a JSON number")


async def read_capped(request: Request, limit: int = MAX_ORDER_BODY_BYTES) -> bytes | None:
    """The raw body, or None past `limit`, before it is held whole: a declared `Content-Length`
    over the cap is refused unread, and a stream at its first chunk past the cap (as
    `api/users.py` reads its own)."""
    declared = request.headers.get("content-length", "")
    if _LENGTH.fullmatch(declared) and int(declared) > limit:
        return None
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > limit:
            return None
    return bytes(raw)


def parse_json_object(raw: bytes) -> dict[str, object] | None:
    """The body parsed once as a JSON object, a JSON constant (`NaN`, `Infinity`) refused; None
    when it is not one."""
    try:
        body = json.loads(raw, parse_constant=_refuse_constant)
    except (ValueError, RecursionError):
        return None
    return body if isinstance(body, dict) else None


def idempotency_key(request: Request) -> uuid.UUID:
    """The `Idempotency-Key`, a UUID, else `400 validation_failed`."""
    try:
        return uuid.UUID(request.headers.get("idempotency-key", ""))
    except ValueError:
        message = "Send an Idempotency-Key (UUID)."
        raise OrderInvalid(errors=(FieldError("Idempotency-Key", "uuid", message),)) from None


def replay_key(user_id: uuid.UUID, operation: str, key: uuid.UUID) -> tuple[str, str]:
    """The 24 h record's slot of a principal's request: its user, then the operation and key."""
    return str(user_id), f"{operation}:{key}"


def replay_cached(replays: IdempotencyCache, held: tuple[str, str], digest: str) -> Response | None:
    """The 24 h record's `2xx` for this fingerprint, else none; another fingerprint under the
    key is `409 idempotency_key_reuse`."""
    hit = replays.get(*held)
    if hit is None:
        return None
    if hit.digest != digest:
        raise IdempotencyKeyReuse
    headers = {"Idempotency-Replayed": "true"}
    return Response(hit.body, hit.status, headers, media_type="application/json")


def field_errors(exc: ValidationError) -> list[FieldError]:
    """Each rule that failed, its message through the redaction rules, as the API's 422 is."""
    return [
        FieldError(".".join(str(p) for p in e["loc"]) or "body", e["type"], redact_text(e["msg"]))
        for e in exc.errors(include_url=False, include_input=False, include_context=False)
    ]


async def resolve_principal(
    principals: OrderPrincipals, request: Request, auth: SessionsLike | None
) -> TradingPrincipal | None:
    """Step 1's principal; a test seam's bare snapshot acts in the session its bearer names."""
    got = principals.resolve(request)
    found = await got if inspect.isawaitable(got) else got
    if isinstance(found, PrincipalSnapshot):
        session = await refusal_session(auth, request)
        return None if session is None else TradingPrincipal(session, found)
    return found if isinstance(found, TradingPrincipal) else None


def submit_actor(principal: TradingPrincipal, request: Request) -> SubmitActor:
    """The records' actor of an admitted request: its user, roles, session and source address."""
    snapshot = principal.snapshot
    role = ",".join(sorted(snapshot.roles))
    return SubmitActor(snapshot.user_id, role, principal.session_id, source_ip(request.scope))

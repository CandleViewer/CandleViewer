"""`POST /admin/keys/audit-signing/rotate` (`rotateAuditSigningKey`, #889 S7; ADR-0039 decision 5)
and 22's `AuditSigningKey` view, which it and `listAuditSigningKeys` (`api/audit.py`) answer with:
an M2 record's public members, the constant `alg`, the raw public key in base64 and M2's own
`verified` mark, validated against the contract's model, so nothing else (a seed, a wrap, a
request fingerprint) can be served.

The rotation is the Owner's. `CsrfMiddleware` and the step-up middleware (`DANGEROUS_ROUTES`,
class `keys`, a grace class) answer before the handler, which resolves the caller (none wired:
`501`; no verified session: `401`), checks the body, read up to 1 KiB, against
`RotateAuditSigningKeyRequest`, and the `Idempotency-Key` as a UUID, missing or malformed (`422`,
naming no value), then `keys:manage` and the Owner (`403`, audited as `rbac.denied`, which names
the caller's session as every refusal's does since #4174). `AdminService` has M2 run the rest in
22's order: the stored `200` at any age (`Idempotency-Replayed: true`), `409
idempotency_key_reuse` or `idempotency_in_flight`; `403 kek_unavailable`; `429 rate_limited`,
counted under the audit budget as `queryAuditLog`'s, labelled with the Owner's username as its
own are, and never recorded; `409 conflict` while a rotation or an `audit_export` job (queued or
running) is under way, or with no key to retire; then the rotation, or `503 audit_unavailable` or
`store_unavailable`. Every answer of the router, a replay and a refusal included, carries
`Cache-Control: no-store`. The request's fingerprint covers the contract path, not the served
one. This module imports `admin`, never `secrets` (C-3.2).
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import uuid
from collections.abc import Callable, Mapping
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from candleviewer.admin.errors import SigningKeyRotationError
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.audit_budget import AuditRecordBudget, BudgetActor
from candleviewer.api.csrf import source_ip
from candleviewer.api.idempotency import request_fingerprint
from candleviewer.api.recorder_admin import AUDIT_EXPORT, AdminJobStore, JobConflict
from candleviewer.api.refusal_session import NamesSession, SessionsLike
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.models import UserRecord
from candleviewer.auth.scopes import ForbiddenError, enforce
from candleviewer.observability.context import current_request_uuid
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

PATH: Final = "/admin/keys/audit-signing/rotate"
#: The body is one short member: past this it is refused unread (the contract declares no 413).
MAX_BODY_BYTES: Final = 1024
#: On every answer: a rotation's keys, its replay and each refusal are never kept by a cache.
_NO_STORE: Final = {"Cache-Control": "no-store"}
#: The members served as M2 gives them (`verified` is M2's: decision 4).
_PUBLIC: Final = (
    "key_id", "fingerprint_sha256", "status", "verified", "valid_from", "valid_until",
    "retired_reason",
)  # fmt: skip
#: Every answer but the `200`: its status and fixed detail, never an exception's text.
_ANSWERS: Final[dict[str, tuple[int, str]]] = {
    "unauthenticated": (401, "No verified session for this request."),
    "forbidden": (403, "Only the Owner may rotate the audit export signing key."),
    "kek_unavailable": (403, "No usable credential key is loaded; nothing was rotated."),
    "conflict": (409, "A rotation or an audit export is under way, or no key is active."),
    "idempotency_key_reuse": (409, "The key was first used with another request."),
    "idempotency_in_flight": (409, "A request with this key is still being processed."),
    "validation_failed": (422, "The request is invalid."),
    "rate_limited": (429, "This hour's signing-key rotations are used up."),
    "not_implemented": (501, "No principal resolver is wired."),
    "audit_unavailable": (503, "An audit record could not be written. Send the request again."),
    "store_unavailable": (503, "The signing key store failed. Send the request again."),
}
#: The bound on the `429`'s username read (re-check C2): the count never waits on the user store.
_USER_READ_S: Final = 2.0


class SigningKeyRotating(Protocol):
    """What the route calls: `AdminService.rotate_audit_signing_key` (M21)."""

    async def rotate_audit_signing_key(
        self,
        reason: str,
        *,
        actor_user_id: uuid.UUID,
        client_ref: uuid.UUID,
        client_body_sha256: str,
        export_running: Callable[[], bool],
    ) -> tuple[dict[str, dict[str, Any]], bool]: ...


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _Auth(SessionsLike, Protocol):
    """What the route reads of `AuthService`: the caller's session, which a refusal's record
    names (#4174), and the Owner's username, which labels a `429`'s count."""

    async def find_user(self, user_id: str) -> UserRecord | None: ...


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def signing_key_view(key: Mapping[str, Any]) -> dict[str, Any]:
    """22's `AuditSigningKey` of an M2 record, as JSON: public material only."""
    shown = {name: key[name] for name in _PUBLIC} | {"alg": "ed25519"}
    shown["public_key"] = base64.b64encode(key["public_key"]).decode("ascii")
    return api.AuditSigningKey.model_validate(shown).model_dump(mode="json")


def _problem(code: str, retry_after: int | None = None, **extra: Any) -> JSONResponse:
    """An RFC 9457 problem with the catalogued title; a retryable code carries `Retry-After`."""
    (status, detail), meta = _ANSWERS[code], ERROR_META[ErrorCode(code)]
    body: dict[str, Any] = {"type": f"https://candleviewer.local/errors/{code}"}
    body |= {"title": meta.title, "status": status, "code": code, "detail": detail, **extra}
    headers = dict(_NO_STORE)
    if meta.retryable:
        body["retry_after_seconds"] = wait = retry_after or 1
        headers["Retry-After"] = str(wait)
    return JSONResponse(body, status, headers, media_type="application/problem+json")


def _invalid(field: str, rule: str) -> JSONResponse:
    return _problem("validation_failed", errors=[{"field": field, "rule": rule}])


async def _request(request: Request) -> tuple[bytes, str, uuid.UUID] | JSONResponse:
    """The raw body, its `reason` and the `Idempotency-Key`, checked strictly, or their `422`. No
    value is echoed, nor the name of a member the contract lacks."""
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            return _invalid("", "body_too_large")
    try:
        body = api.RotateAuditSigningKeyRequest.model_validate_json(bytes(raw), strict=True)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = "" if first["type"] == "extra_forbidden" else ".".join(map(str, first["loc"]))
        return _invalid(field, first["type"])
    try:
        ref = uuid.UUID(request.headers.get("idempotency-key", ""))
    except ValueError:
        return _invalid("Idempotency-Key", "uuid")
    return bytes(raw), body.reason, ref


def make_audit_signing_router(
    admin: SigningKeyRotating,
    emitter: _Emitter,
    principal_resolver: SnapshotResolver | None,
    *,
    budget: AuditRecordBudget,
    jobs: AdminJobStore | None = None,
    auth: _Auth | None = None,
) -> APIRouter:
    """`principal_resolver=None` (no identity provider: the fake backend) fails closed with 501.
    `budget` counts a `429`; `jobs` holds the `audit_export` jobs a rotation waits for. A
    refusal's `rbac.denied` names the caller's session, read through `auth` (#4174), which also
    gives the Owner's username for a `429`'s count."""
    router = APIRouter(tags=["admin"])

    async def label(user: uuid.UUID) -> str:
        """The Owner's username, as `queryAuditLog` labels the actor's entry in the budget; the
        id's text when no user store can say (logged): the count is never lost for want of it."""
        try:
            async with asyncio.timeout(_USER_READ_S):  # a hung user store holds no 429 (C2)
                found = None if auth is None else await auth.find_user(str(user))
        except Exception as exc:  # the user store may be down or hung: count under the id
            _log().warning("rotation 429 names no username", error=type(exc).__name__)
            found = None
        return str(user) if found is None else found.username

    def export_running() -> bool:
        try:
            if jobs is not None:
                jobs.ensure_free(AUDIT_EXPORT)
        except JobConflict:
            return True
        return False

    @router.post("/admin/keys/audit-signing/rotate")  # PATH, literal for `cv-admin-route-guarded`
    async def rotate_audit_signing_key(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem("not_implemented")
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _problem("unauthenticated")
        checked = await _request(request)
        if isinstance(checked, JSONResponse):
            return checked
        raw, reason, ref = checked
        who: dict[str, Any] = {"actor_ip": source_ip(request.scope)}
        who["request_id"] = current_request_uuid()
        denials = NamesSession(emitter, auth, request)
        try:
            await enforce(
                principal, Permission.KEYS_MANAGE, scope=Scope.NONE, emitter=denials, **who
            )
            if not principal.is_owner:  # the RBAC seed gives `keys:manage` to the Owner alone
                await denials.emit(
                    "rbac.denied", actor_label=str(principal.user_id),
                    actor_user_id=principal.user_id, outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING, reason="owner_only", **who,
                )  # fmt: skip
                return _problem("forbidden")
        except ForbiddenError:
            return _problem("forbidden")
        except (AuditError, RuntimeError):  # RuntimeError: no writer wired (as after `stop()`)
            return _problem("audit_unavailable")  # a denial that cannot be recorded (C-2.9)
        user, digest = principal.user_id, request_fingerprint("POST", PATH, raw)
        try:
            made, replayed = await admin.rotate_audit_signing_key(
                reason, actor_user_id=user, client_ref=ref, client_body_sha256=digest,
                export_running=export_running,
            )  # fmt: skip
        except SigningKeyRotationError as exc:
            if exc.code == "rate_limited":  # counted, not recorded, as `queryAuditLog`'s is
                budget.count_suppressed(BudgetActor(str(user), await label(user), user, True))
            return _problem(exc.code, exc.retry_after_s)
        shown = {name: signing_key_view(made[name]) for name in ("active", "retired")}
        headers = _NO_STORE | ({"Idempotency-Replayed": "true"} if replayed else {})
        return JSONResponse(shown, headers=headers)

    return router


__all__ = [
    "MAX_BODY_BYTES", "PATH", "SigningKeyRotating", "make_audit_signing_router", "signing_key_view"
]  # fmt: skip

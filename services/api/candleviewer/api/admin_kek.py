"""`POST /admin/keys/kek-rewrap` (`rewrapKek`, #2266): the re-wrap step of a KEK rotation
(`docs/plan/spikes/e27-kek.md` section 5, run as `docs/ops/runbooks/kek-custody.md` says).

Owner only. `CsrfMiddleware` and the step-up middleware (`DANGEROUS_ROUTES`, class `keys`) answer
before this handler runs. It then resolves the caller (none wired: 501; no verified session: 401),
checks the body, read up to 1 KiB, against `KekRewrapRequest` (422), and checks `keys:manage` with
`auth.scopes.enforce`, then the Owner role (403), each denial audited as `rbac.denied` (C-2.9).
The run is `AdminService.rewrap_kek`: M2 checks the staged boot, audits a refusal,
latches order entry and re-wraps. This module imports `admin` only, never `secrets` (C-3.2). The
answer holds counts only, no key id and no KCV; `Idempotency-Key` is never read
(`x-idempotency: ignored`: a repeat resumes the run).
"""

from __future__ import annotations

import dataclasses
import inspect
import uuid
from typing import Any, Final, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from candleviewer.admin.errors import KekRewrapError
from candleviewer.admin.models import KekRewrapResult
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.csrf import source_ip
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, enforce
from candleviewer.observability.context import current_request_id
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
#: The body is two short members: past this it is refused unread (the contract declares no 413).
MAX_BODY_BYTES: Final = 1024
#: Every refusal's status and fixed detail (never an exception's text), by its contract code.
_ANSWERS: Final[dict[str, tuple[int, str]]] = {
    "unauthenticated": (401, "No verified session for this request."),
    "forbidden": (403, "Only the Owner may re-wrap the credential keys."),
    "kek_unavailable": (403, "No usable credential key is loaded; nothing was latched or moved."),
    "kek_rotation_not_staged": (
        409,
        "Restart with the previous KEK handle for this environment and version, as the runbook "
        "says.",
    ),
    "kek_rotation_in_progress": (409, "Wait for the running re-wrap to end, then call again."),
    "validation_failed": (422, "The request body is invalid."),
    "not_implemented": (501, "No principal resolver is wired."),
    "audit_unavailable": (503, "An audit record could not be written. Calling again resumes."),
    "store_unavailable": (503, "The credential store failed. Calling again resumes."),
}


class KekRewrapper(Protocol):
    """What the route calls: `AdminService.rewrap_kek` (M21)."""

    async def rewrap_kek(
        self, environment: str, to_version: int, actor_user_id: str
    ) -> KekRewrapResult: ...


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


def _problem(code: str, **extra: Any) -> JSONResponse:
    """An RFC 9457 problem with the catalogued title; a retryable code carries `Retry-After`."""
    (status, detail), meta = _ANSWERS[code], ERROR_META[ErrorCode(code)]
    body: dict[str, Any] = {"type": f"https://candleviewer.local/errors/{code}"}
    body |= {"title": meta.title, "status": status, "code": code, "detail": detail, **extra}
    headers: dict[str, str] = {}
    if meta.retryable:
        body["retry_after_seconds"] = _RETRY_AFTER_S
        headers["Retry-After"] = str(_RETRY_AFTER_S)
    return JSONResponse(body, status, headers, media_type="application/problem+json")


async def _body(request: Request) -> api.KekRewrapRequest | JSONResponse:
    """The body, checked strictly (`to_version` a JSON integer, no string or float), or its `422`.
    Never echoed: no value, and no name of a member the contract lacks (`field` empty)."""
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            return _problem("validation_failed", errors=[{"field": "", "rule": "body_too_large"}])
    try:
        return api.KekRewrapRequest.model_validate_json(bytes(raw), strict=True)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = "" if first["type"] == "extra_forbidden" else ".".join(map(str, first["loc"]))
        return _problem("validation_failed", errors=[{"field": field, "rule": first["type"]}])


def make_admin_kek_router(
    admin: KekRewrapper, emitter: _Emitter, principal_resolver: SnapshotResolver | None
) -> APIRouter:
    """`principal_resolver=None` (no identity provider: the fake backend) fails closed with 501."""
    router = APIRouter(tags=["admin"])

    @router.post("/admin/keys/kek-rewrap")
    async def rewrap_kek(request: Request) -> JSONResponse:
        if principal_resolver is None:
            return _problem("not_implemented")
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _problem("unauthenticated")
        body = await _body(request)
        if isinstance(body, JSONResponse):
            return body
        ip, rid = source_ip(request.scope), current_request_id()  # the request id: a UUID4
        who: dict[str, Any] = {"actor_ip": ip, "request_id": uuid.UUID(rid) if rid else None}
        try:
            await enforce(
                principal, Permission.KEYS_MANAGE, scope=Scope.NONE, emitter=emitter, **who
            )
            if not principal.is_owner:  # the RBAC seed gives `keys:manage` to the Owner alone
                await emitter.emit(
                    "rbac.denied",
                    actor_label=str(principal.user_id),
                    actor_user_id=principal.user_id,
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason="owner_only",
                    **who,
                )
                return _problem("forbidden")
        except ForbiddenError:
            return _problem("forbidden")
        except AuditError:  # a denial that cannot be recorded is not answered as one (C-2.9)
            return _problem("audit_unavailable")
        try:
            result = await admin.rewrap_kek(
                body.environment, body.to_version, str(principal.user_id)
            )
        except KekRewrapError as exc:
            return _problem(exc.code)
        shown = api.KekRewrapResult.model_validate(dataclasses.asdict(result))
        return JSONResponse(shown.model_dump(mode="json"))

    return router


__all__ = ["MAX_BODY_BYTES", "KekRewrapper", "make_admin_kek_router"]

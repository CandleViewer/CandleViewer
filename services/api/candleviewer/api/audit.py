"""`GET /admin/audit`, `POST /admin/audit/verify`, `POST /admin/audit/export`
(E09-T02 acceptance criteria: "Endpoints ... `GET /admin/audit` ... `POST
/admin/audit/verify` ... `POST /admin/audit/export`").

QA defect #1596 blocker 1: `candleviewer.audit.query.AuditQueryService` and
`candleviewer.audit.access.authorize` existed but no `APIRouter` mounted
them — `grep -rn 'APIRouter' services/api/candleviewer/audit` found
nothing. This module is the thin HTTP adapter `api/auth.py` already
establishes the pattern for: structural Protocols for the injected
services (no import edge beyond what `audit`'s own public surface already
requires), RFC 7807 problem responses, and audit-of-the-audit-denial via
`candleviewer.audit.access.authorize` (ticket AC "Non-owner cannot read the
audit log" — the denial is itself audited, before the 403 is returned).

Principal resolution: `auth`'s session/RBAC-context middleware is out of
this ticket's scope (E09-T02 does not own it; `auth/service.py` is still
the M18 scaffold with no session verification). Per `x-rbac: {scope: none}`
these routes fail closed rather than guess: a caller is resolved via an
injected `PrincipalResolver` (structurally typed, mirrors `AuditServiceLike`
in `api/auth.py`); the composition root wires a real one when M18 lands
session verification. Until then `create_app()` passes `None` for
`principal_resolver`, and every request is refused with `501 Not
Implemented` (never silently allowed) — no session-verification module
exists yet to say yes or no. Once a resolver *is* wired (PR #1608 review
finding 1: `app.py` now passes one) but it reports "no verified session"
for a given request, that is a normal 401 per the resolver's own contract
(finding 4) — `501` is reserved for the "nothing is wired at all" case.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from candleviewer.api.audit_limiter import AuditQueryLimiter, AuditQueryRefused
from candleviewer.audit.access import (
    AuditAccessDenied,
    AuditPrincipal,
    AuditView,
    authorize,
    redact_entry_for_view,
)
from candleviewer.audit.models import (
    AUDIT_QUERY_DEFAULT_LIMIT,
    AuditExportRequest,
    AuditOutcome,
    AuditQueryRequest,
    AuditVerifyRequest,
    Severity,
)
from candleviewer.storage.errors import StorageTierUnavailable


class _Emitter(Protocol):
    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: Any = None,
        actor_ip: str | None = None,
        session_id: Any = None,
        object_kind: str | None = None,
        object_id: str | None = None,
        object_label: str | None = None,
        outcome: Any = ...,
        severity: Any = ...,
        reason: str | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        request_id: Any = None,
        env: Any = None,
    ) -> None: ...


class AuditQueryServiceLike(Protocol):
    """Structural type for `candleviewer.audit.query.AuditQueryService`."""

    async def query(
        self,
        *,
        actor_user_id: str | None = None,
        actions: list[str] | None = None,
        subject_type: str | None = None,
        severity: str | None = None,
        outcome: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        cursor: int | None = None,
        limit: int = AUDIT_QUERY_DEFAULT_LIMIT,
        ip: str | None = None,
        timeout_ms: int | None = None,
    ) -> Any: ...

    async def verify(
        self, *, from_id: int | None = None, to_id: int | None = None, batch_size: int = 5_000
    ) -> Any: ...

    async def schedule_export(self, *, from_ts: datetime, to_ts: datetime) -> Any: ...


class AuditWriterLike(_Emitter, Protocol):
    """Only the `emit()` subset `authorize()` needs to record a denial."""


class AuditServiceLike(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def query(self) -> AuditQueryServiceLike: ...

    @property
    def writer(self) -> AuditWriterLike: ...


class PrincipalResolver(Protocol):
    """Resolves the authenticated caller for an `/admin/audit*` request.

    Structurally typed so this router never imports a concrete session
    module; the composition root injects the real implementation once M18
    exposes one. Returning `None` means "no verified session" (401) — a
    resolver being wired at all vs. it finding no session are distinct
    (PR #1608 review finding 4): a *missing* resolver (`make_audit_router`'s
    own `principal_resolver=None` default) is `501`, since that means
    session verification is not implemented yet, not that this particular
    caller is unauthenticated."""

    async def resolve(self, request: Request) -> AuditPrincipal | None: ...


#: `errors[]` is bounded and names only the field and the rule: a validation message can
#: quote the rejected value (`ipaddress` does), so none is returned.
_MAX_ERRORS = 10
#: Contract parameter names where they differ from the `AuditQueryRequest` field names.
_PARAM_NAMES = {"actions": "action", "from_ts": "from", "to_ts": "to"}


def _problem(
    status_code: int,
    title: str,
    detail: str,
    *,
    code: str | None = None,
    retry_after_s: int | None = None,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        "type": f"https://candleviewer.local/errors/{code}" if code else "about:blank",
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if code is not None:
        content["code"] = code
    if errors is not None:
        content["errors"] = errors
    response = JSONResponse(
        status_code=status_code, content=content, media_type="application/problem+json"
    )
    if retry_after_s is not None:
        response.headers["Retry-After"] = str(retry_after_s)
    return response


def _invalid(exc: ValidationError, model: type[BaseModel], status_code: int = 422) -> JSONResponse:
    """`validation_failed` without echoing the input. A field the model does not declare
    (an unknown body key) is reported as `(unknown)`, never by its client-chosen name."""
    known = set(model.model_fields) | {f.alias for f in model.model_fields.values() if f.alias}
    errors = []
    for err in exc.errors(include_url=False, include_context=False, include_input=False):
        name = str(err["loc"][0]) if err["loc"] else ""
        field = _PARAM_NAMES.get(name, name) if name in known or not name else "(unknown)"
        errors.append({"field": field, "rule": err["type"]})
    return _problem(
        status_code,
        "Request validation failed",
        f"{exc.error_count()} field(s) failed validation",
        code="validation_failed",
        errors=errors[:_MAX_ERRORS],
    )


def _unavailable(detail: str) -> JSONResponse:
    return _problem(503, "Service unavailable", detail, code="store_unavailable", retry_after_s=1)


def make_audit_router(
    audit_service: AuditServiceLike | None,
    principal_resolver: PrincipalResolver | None = None,
    *,
    limiter: AuditQueryLimiter | None = None,
    query_timeout_ms: int = 4000,
) -> APIRouter:
    """Bind `/admin/audit*` to a concrete `AuditService` instance.

    `audit_service=None` (fake/CI-default backend, mirrors `AuthService`'s
    own optionality) and `principal_resolver=None` (no session module wired
    yet) both degrade to `503`/`501` responses rather than raising at import
    time, so `create_app()` stays constructible with fakes only (C-2.16-
    adjacent: the router itself never touches a datastore or the network).
    """
    router = APIRouter(prefix="/admin/audit", tags=["admin"])
    query_limiter = limiter if limiter is not None else AuditQueryLimiter()

    class _HttpProblem(Exception):
        def __init__(self, response: JSONResponse) -> None:
            self.response = response

    async def _authorize_or_raise(
        request: Request, operation: str
    ) -> tuple[AuditServiceLike, AuditPrincipal, AuditView]:
        if audit_service is None or not audit_service.is_active:
            raise _HttpProblem(_problem(503, "Service unavailable", "audit backend is not wired"))
        if principal_resolver is None:
            raise _HttpProblem(
                _problem(
                    501,
                    "Not implemented",
                    "no principal resolver wired — session verification is out of this "
                    "ticket's scope",
                )
            )
        principal = await principal_resolver.resolve(request)
        if principal is None:
            raise _HttpProblem(
                _problem(401, "Unauthorized", "no verified session for this request")
            )
        try:
            view = await authorize(principal, operation, audit_service.writer)
        except AuditAccessDenied as exc:
            raise _HttpProblem(_problem(403, "Forbidden", str(exc))) from exc
        return audit_service, principal, view

    @router.get("")
    async def query_audit_log(
        request: Request,
        actor_user_id: str | None = None,
        # Without `Query()` a list parameter is read from a JSON body, even on a GET.
        action: Annotated[list[str] | None, Query()] = None,
        subject_type: str | None = None,
        outcome: str | None = None,
        severity: str | None = None,
        # `from` is a Python keyword; the OpenAPI contract (22-api-openapi.yaml) names
        # the query parameter `from`, so alias it — without the alias `?from=` was
        # silently ignored and the lower time bound dropped.
        from_: Annotated[datetime | None, Query(alias="from")] = None,
        to: datetime | None = None,
        cursor: int | None = None,
        limit: int = AUDIT_QUERY_DEFAULT_LIMIT,
        ip: str | None = None,
    ) -> JSONResponse:
        try:
            service, principal, view = await _authorize_or_raise(request, "query")
        except _HttpProblem as problem:
            return problem.response
        if view is AuditView.OWN_REDACTED and ip is not None:
            # Contract: `ip` is Owner only. The redacted projection hides it, so filtering
            # on it would reveal it one query at a time.
            return await _refuse(service.writer, principal, "filter_not_permitted:ip")
        try:
            req = AuditQueryRequest.model_validate(
                {
                    "actor_user_id": actor_user_id,
                    "actions": action,
                    "subject_type": subject_type,
                    "ip": ip,
                    "severity": severity,
                    "outcome": outcome,
                    "from_ts": from_,
                    "to_ts": to,
                    "cursor": cursor,
                    "limit": limit,
                }
            )
        except ValidationError as exc:
            return _invalid(exc, AuditQueryRequest)
        key = str(principal.user_id)
        filters = req.model_dump(exclude={"cursor"})
        if view is AuditView.OWN_REDACTED:
            # SR-067: a non-owner reads only its own events; the filter is
            # forced server-side, whatever `actor_user_id` the caller sent.
            filters["actor_user_id"] = key
        try:
            lease = query_limiter.acquire(key)
        except AuditQueryRefused as exc:
            return _problem(
                429,
                "Too many requests",
                "audit query limit reached",
                code="rate_limited",
                retry_after_s=exc.retry_after_s,
            )
        try:
            return await _run_query(service, key, view, filters, req.cursor)
        finally:
            lease.release()

    async def _refuse(
        writer: AuditWriterLike, principal: AuditPrincipal, reason: str
    ) -> JSONResponse:
        await writer.emit(
            "admin.audit_denied",
            actor_label=principal.username,
            actor_user_id=principal.user_id,
            actor_ip=principal.ip,
            session_id=principal.session_id,
            object_kind="audit_log",
            outcome=AuditOutcome.DENIED,
            severity=Severity.WARNING,
            reason=reason,
            request_id=principal.request_id,
        )
        return _problem(403, "Forbidden", "filter not permitted for this caller", code="forbidden")

    async def _run_query(
        service: AuditServiceLike,
        key: str,
        view: AuditView,
        filters: dict[str, Any],
        cursor: int | None,
    ) -> JSONResponse:
        try:
            page = await service.query.query(**filters, cursor=cursor, timeout_ms=query_timeout_ms)
        except ValidationError as exc:
            return _invalid(exc, AuditQueryRequest)
        except TimeoutError:
            return _unavailable("audit query exceeded its time budget")
        except StorageTierUnavailable:
            # The store error carries only its SQLSTATE; it is logged where it is raised.
            return _unavailable("audit store unavailable")
        if view is AuditView.OWN_REDACTED:
            items = [
                redact_entry_for_view(e, view) for e in page.items if str(e.actor_user_id) == key
            ]
            page = page.model_copy(update={"items": items, "count": len(items)})
        return JSONResponse(status_code=200, content=_jsonable(page))

    @router.post("/verify")
    async def verify_audit_chain(
        request: Request,
        body: dict[str, Any] | None = None,
    ) -> JSONResponse:
        try:
            service, _, _ = await _authorize_or_raise(request, "verify")
        except _HttpProblem as problem:
            return problem.response
        try:
            req = AuditVerifyRequest.model_validate(body or {})
        except ValidationError as exc:
            return _invalid(exc, AuditVerifyRequest, 400)
        result = await service.query.verify(from_id=req.from_id, to_id=req.to_id)
        return JSONResponse(status_code=200, content=_jsonable(result))

    @router.post("/export")
    async def export_audit_log(request: Request, body: dict[str, Any]) -> JSONResponse:
        try:
            service, _, _ = await _authorize_or_raise(request, "export")
        except _HttpProblem as problem:
            return problem.response
        try:
            req = AuditExportRequest.model_validate(body)
        except ValidationError as exc:
            return _invalid(exc, AuditExportRequest, 400)
        result = await service.query.schedule_export(from_ts=req.from_ts, to_ts=req.to_ts)
        return JSONResponse(status_code=202, content=_jsonable(result))

    return router


def _jsonable(model: Any) -> dict[str, Any]:
    """`model_dump(mode="json")` renders `datetime`/`UUID`/enum fields as
    plain JSON-safe types (`JSONResponse` does not run pydantic's encoder)."""
    dumped: dict[str, Any] = model.model_dump(mode="json")
    return dumped


__all__ = ["PrincipalResolver", "make_audit_router"]

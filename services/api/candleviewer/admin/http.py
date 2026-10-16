"""The audited admin-area guard (E42-T01): one router-level dependency for every `/admin/*`
route of the admin read models, reused by the E42-T03/T05/T07 routes.

`admin_router(permission, resolver=..., audit=...)` returns an `APIRouter` (prefix `/admin`)
whose dependency runs before every handler, so a route added to it cannot skip the check (RBAC
server-side, deny-by-default, C-12.4):
- no principal resolver wired: 501; no verified session: 401; no audit writer: 503 for every
  caller (fail closed);
- otherwise a caller without `permission` is counted in `authz_denied_total` (SR-125), as
  `auth.scopes.enforce` does, before anything is written, so an audit failure cannot hide the
  denial; then `admin.area_entered` is written first (write-ahead, C-2.9), allowed or denied, with
  `{route, reauth_age_s}`, and that caller gets 403 (the record is the denial's audit row: there
  is no second `rbac.denied`);
- if that record cannot be written the area stays shut: 503 for an allowed caller, while a
  denied caller still gets its 403, never a 500; a cancellation is never swallowed;
- an allowed caller's verified principal is left on `request.state.admin_principal`, so a write
  route can audit its actor without resolving the session again.

`reauth_age_s` is the whole seconds from the caller's last step-up on this session to the
injected clock (`AuditPrincipal.reauth_age_s`, #2754), or `null` before any step-up; a `token`
key would be masked by `audit/redact.py`. It is observability only, never a gate: step-up
(SR-025) is not this guard's job. It stays enforced by the `DANGEROUS_ROUTES` middleware in
`candleviewer/api/step_up.py`, so a route on this router must not assume elevation is checked.
Refusals are RFC 9457 problem documents carrying the contract's `code` (C-6.5), rendered by
`admin_area_refused_handler` (registered in `create_app`).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.metrics import authz_denied_total, normalise_permission

AREA_ENTERED: Final = "admin.area_entered"
_ERRORS: Final = "https://candleviewer.local/errors/"
#: status -> (`code`, title) of every refusal this guard renders.
_REFUSALS: Final = {
    401: ("unauthenticated", "Unauthorized"),
    403: ("forbidden", "Forbidden"),
    500: ("internal_error", "Internal error"),
    501: ("not_implemented", "Not implemented"),
    503: ("audit_unavailable", "Service unavailable"),
}


def _log() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


class PrincipalResolver(Protocol):
    async def resolve(self, request: Request) -> AuditPrincipal | None: ...


class AuditEmitter(Protocol):
    """The `AuditWriter.emit` keywords this guard writes (the writer itself satisfies it)."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        session_id: uuid.UUID | None,
        object_kind: str,
        object_id: str,
        outcome: AuditOutcome,
        severity: Severity,
        reason: str | None,
        after_state: dict[str, Any],
        request_id: uuid.UUID | None,
    ) -> None: ...


class AdminAreaRefused(Exception):
    """Raised by the guard; rendered as a problem document."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail
        self.code, self.title = _REFUSALS[status]


async def admin_area_refused_handler(_request: Request, exc: Exception) -> JSONResponse:
    refused = exc if isinstance(exc, AdminAreaRefused) else AdminAreaRefused(500, "check failed")
    status, code = refused.status, refused.code
    body = {"type": _ERRORS + code, "title": refused.title, "status": status, "code": code}
    body["detail"] = refused.detail
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def admin_area(
    permission: Permission,
    resolver: PrincipalResolver | None,
    audit: AuditEmitter | None,
    clock: Callable[[], datetime] = _utc_now,
) -> Callable[[Request], Awaitable[AuditPrincipal]]:
    """The dependency itself: the verified principal, or an `AdminAreaRefused`. `clock` is the
    injected time source the record's `reauth_age_s` is measured against."""

    async def enter(request: Request) -> AuditPrincipal:
        if resolver is None:
            raise AdminAreaRefused(501, "no principal resolver wired")
        principal = await resolver.resolve(request)
        if principal is None:
            raise AdminAreaRefused(401, "no verified session for this request")
        if audit is None:
            raise AdminAreaRefused(503, "audit backend is not wired")
        route = str(getattr(request.scope.get("route"), "path", request.url.path))
        allowed = principal.has(permission)
        if not allowed:  # SR-125, counted before the audit write as in `auth.scopes.enforce`
            authz_denied_total.labels(permission=normalise_permission(permission)).inc()
        try:
            await audit.emit(
                AREA_ENTERED,
                actor_label=principal.username,
                actor_user_id=principal.user_id,
                actor_ip=principal.ip,
                session_id=principal.session_id,
                object_kind="admin_route",
                object_id=route,
                outcome=AuditOutcome.SUCCESS if allowed else AuditOutcome.DENIED,
                severity=Severity.INFO if allowed else Severity.WARNING,
                reason=None if allowed else f"missing_permission:{permission}",
                after_state={"route": route, "reauth_age_s": principal.reauth_age_s(clock())},
                request_id=principal.request_id,
            )
        except Exception as exc:  # any audit failure shuts the area (write-ahead, C-2.9)
            _log().error(
                "admin.area_entered.audit_failed",
                route=route,
                actor_user_id=principal.user_id,
                request_id=principal.request_id,
                error=type(exc).__name__,
            )
            if allowed:
                raise AdminAreaRefused(503, "audit record could not be written") from exc
        if not allowed:
            raise AdminAreaRefused(403, f"requires {permission}")
        request.state.admin_principal = principal
        return principal

    return enter


def admin_router(
    permission: Permission,
    *,
    resolver: PrincipalResolver | None,
    audit: AuditEmitter | None,
    clock: Callable[[], datetime] = _utc_now,
) -> APIRouter:
    """An `/admin` router whose every route passes the audited admin-area check first."""
    guard = Depends(admin_area(permission, resolver, audit, clock))
    return APIRouter(prefix="/admin", tags=["admin"], dependencies=[guard])

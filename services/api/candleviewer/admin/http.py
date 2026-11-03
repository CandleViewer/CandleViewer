"""The audited admin-area guard (E42-T01): one router-level dependency for every `/admin/*`
route of the admin read models, reused by the E42-T03/T05/T07 routes.

`admin_router(permission, resolver=..., audit=..., clock=...)` returns an `APIRouter` (prefix
`/admin`) whose dependency runs before every handler, so a route added to it cannot skip the
check (RBAC server-side, deny-by-default, C-12.4):
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

Reads are coalesced (#5331, `admin/area_coalescer.py`): with a `coalescer`, an allowed `GET`/`HEAD`
opens a window: the first read of each window is recorded and later reads are counted
(`admin_area_coalesce_seconds`); the counted reads are carried into the next entry
(`after_state.prior_window`) or a `coalesced_summary` entry. Writes and every refusal are still
written ahead, one per request, and a refusal closes the key's window. A coalesced read needs the
audit writer ready, else it takes the write path above (503). With `coalescer=None` every request is
recorded, as before.

`reauth_age_s` is the whole seconds from the last step-up the caller's session row records to
the guard's `clock` (`AuditPrincipal.reauth_age_s`, #2754). It is `null` when the row records
none: never stepped up, or the grant is gone (a spent one-shot grant, a lapsed window, an idle
lock or read-only downgrade, a refreshed token's new row). `clock` defaults to the UTC wall
clock; the app does not pass its auth clock yet (#2924). The key avoids `token` because
`audit/redact.py` masks such names. It is observability only, never a gate: step-up (SR-025) is
not this guard's job. It stays enforced by the `DANGEROUS_ROUTES` middleware in
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

from candleviewer.admin.area_coalescer import AreaEntryCoalescer, Key
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.metrics import count_authz_denial

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


async def _audit_failed(
    exc: Exception, route: str, principal: AuditPrincipal, allowed: bool
) -> None:
    """Any audit failure shuts the area for an allowed caller (write-ahead, C-2.9)."""
    _log().error(
        "admin.area_entered.audit_failed",
        route=route,
        actor_user_id=principal.actor_id,
        request_id=principal.request_id,
        error=type(exc).__name__,
    )
    if allowed:
        raise AdminAreaRefused(503, "audit record could not be written") from exc


def admin_area(
    permission: Permission,
    resolver: PrincipalResolver | None,
    audit: AuditEmitter | None,
    clock: Callable[[], datetime] = _utc_now,
    coalescer: AreaEntryCoalescer | None = None,
) -> Callable[[Request], Awaitable[AuditPrincipal]]:
    """The dependency itself: the verified principal, or an `AdminAreaRefused`. `clock` is the
    injected time source the record's `reauth_age_s` is measured against; `coalescer` coalesces
    the repeated safe reads (None: every request is recorded)."""

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
            count_authz_denial(permission, ("owner",) if principal.is_owner else ())
        method = str(request.scope.get("method", "")).upper()  # unknown: not a safe read
        plan: tuple[AreaEntryCoalescer, Key] | None = None  # set for a read that may coalesce
        if coalescer is not None and coalescer.enabled:
            key: Key = (
                principal.actor_id, principal.user_id, principal.session_id, method, route,
                principal.ip, principal.last_step_up_at,
            )  # fmt: skip
            if not allowed:
                coalescer.close(key)  # the next allowed read writes a full row after this one
            elif coalescer.eligible(method, principal.session_id):
                if coalescer.coalesce(key):
                    request.state.admin_principal = principal
                    return principal
                plan = (coalescer, key)
        taken = plan[0].take_prior(plan[1]) if plan is not None else None
        try:
            after_state: dict[str, Any] = {
                "route": route,
                "reauth_age_s": principal.reauth_age_s(clock()),
            }
            if plan is not None:
                after_state["window_s"] = plan[0].window_s
                prior = plan[0].prior_state(taken)
                if prior is not None:
                    after_state["prior_window"] = prior
            await audit.emit(
                AREA_ENTERED,
                actor_label=principal.actor_name,
                actor_user_id=principal.actor_id,
                actor_ip=principal.ip,
                session_id=principal.session_id,
                object_kind="admin_route",
                object_id=route,
                outcome=AuditOutcome.SUCCESS if allowed else AuditOutcome.DENIED,
                severity=Severity.INFO if allowed else Severity.WARNING,
                reason=None if allowed else f"missing_permission:{permission}",
                after_state=after_state,
                request_id=principal.request_id,
            )
            taken = None  # the row carried its count: a later cancel must not give it back
            if plan is not None:
                await plan[0].open(
                    plan[1],
                    plan[0].new_window(
                        actor_label=principal.actor_name,
                        actor_user_id=principal.actor_id,
                        ip=principal.ip,
                        session_id=principal.session_id,
                        route=route,
                    ),
                )
        except BaseException as exc:
            if plan is not None:
                plan[0].restore(plan[1], taken)  # its count was not carried: give it back
            if not isinstance(exc, Exception):
                raise  # a cancellation is never swallowed
            await _audit_failed(exc, route, principal, allowed)
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
    coalescer: AreaEntryCoalescer | None = None,
) -> APIRouter:
    """An `/admin` router whose every route passes the audited admin-area check first; `clock`
    dates the record's `reauth_age_s`; `coalescer` coalesces its repeated safe reads (#5331)."""
    guard = Depends(admin_area(permission, resolver, audit, clock, coalescer))
    return APIRouter(prefix="/admin", tags=["admin"], dependencies=[guard])

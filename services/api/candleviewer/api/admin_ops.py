"""`GET /admin/health` (E42-T05; contract `getHealth`, `x-rbac: admin:read`, scope none), on the
audited admin router (`candleviewer.admin.http`).

The handler maps the read model to the generated `HealthReport` model and serialises with
`exclude_unset`, so a field the source did not read is omitted, never defaulted. A refusal is a
problem document with a registered code: `not_implemented` (501) when no registry is wired,
`store_unavailable` (503, retryable) while it has no snapshot yet. Its detail is the read model's
fixed literal: no exception text, query or path ever leaves.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from candleviewer.admin.errors import AdminError, OpsNotWired, OpsUnavailable
from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.admin.ops.health import AdminHealthService, HealthReading
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.health_report import render_report
from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
#: Each refusal the read models raise: its status and registered code. A subclass of one
#: answers as it does.
_REFUSALS: Final = {
    OpsNotWired: (501, ErrorCode.NOT_IMPLEMENTED),
    OpsUnavailable: (503, ErrorCode.STORE_UNAVAILABLE),
}


def health_payload(reading: HealthReading) -> dict[str, Any]:
    body = render_report(
        reading.snapshot,
        version=reading.version,
        git_sha=reading.git_sha,
        environment=reading.environment,
        uptime_seconds=reading.uptime_seconds,
        clock_offset_ms=None,  # until exchange time sync (E08): a null, never a fabricated 0
    )
    return api.HealthReport.model_validate(body).model_dump(mode="json", exclude_unset=True)


def _refusal(exc: AdminError) -> JSONResponse:
    status, code = next(v for k, v in _REFUSALS.items() if isinstance(exc, k))
    meta = ERROR_META[code]
    body: dict[str, Any] = {
        "type": f"https://candleviewer.local/errors/{code.value}",
        "title": meta.title,
        "status": status,
        "code": code.value,
        "detail": str(exc),
    }
    headers: dict[str, str] = {}
    if meta.retryable:
        body["retry_after_seconds"] = _RETRY_AFTER_S
        headers["Retry-After"] = str(_RETRY_AFTER_S)
    return JSONResponse(body, status, headers, "application/problem+json")


def make_admin_ops_router(
    health: AdminHealthService,
    *,
    resolver: PrincipalResolver | None,
    audit: AuditEmitter | None,
) -> APIRouter:
    router = admin_router(Permission.ADMIN_READ, resolver=resolver, audit=audit)

    @router.get("/health")
    async def get_health() -> JSONResponse:
        try:
            return JSONResponse(health_payload(health.report()))
        except (OpsNotWired, OpsUnavailable) as exc:
            return _refusal(exc)

    return router

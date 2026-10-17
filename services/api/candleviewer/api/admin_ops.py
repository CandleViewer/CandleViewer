"""`GET /admin/health` and `GET /admin/incidents` (E42-T05; contract `getHealth`, `listIncidents`,
`x-rbac: admin:read`, scope none), on the audited admin router (`candleviewer.admin.http`).

The handlers map the read models to the generated `HealthReport` / `Incident` models and serialise
with `exclude_unset`, so a field the source did not read is omitted, never defaulted. A refusal is
a problem document with a registered code: `not_implemented` (501) when no provider is wired,
`store_unavailable` (503, retryable) when the source failed, had nothing yet or outlasted its
budget, `invalid_cursor` (400). Its detail is the read model's fixed literal: no exception text,
query or path ever leaves.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from candleviewer.admin.errors import AdminError, InvalidCursor, OpsNotWired, OpsUnavailable
from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.admin.ops.health import AdminHealthService, HealthReading
from candleviewer.admin.ops.incidents import CURSOR_MAX, AdminIncidentsService
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.health_report import render_report
from candleviewer.auth.generated_permissions import Permission
from candleviewer.storage.repositories.incidents import IncidentRow
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
#: Each refusal the read models raise: its status and registered code. A subclass of one
#: answers as it does.
_REFUSALS: Final = {
    InvalidCursor: (400, ErrorCode.INVALID_CURSOR),
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


def incident_payload(row: IncidentRow) -> dict[str, Any]:
    fields = asdict(row)
    if row.title is None:  # its redaction failed: the optional field is left out
        del fields["title"]
    return api.Incident.model_validate(fields).model_dump(mode="json", exclude_unset=True)


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
    incidents: AdminIncidentsService,
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

    @router.get("/incidents")
    async def list_incidents(
        status: Literal["open", "acknowledged", "resolved"] | None = None,
        cursor: Annotated[str | None, Query(max_length=CURSOR_MAX)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> JSONResponse:
        try:
            page = await incidents.page(status=status, cursor=cursor, limit=limit)
        except (InvalidCursor, OpsNotWired, OpsUnavailable) as exc:
            return _refusal(exc)
        more = page.next_cursor is not None
        meta = api.PageMeta(next_cursor=page.next_cursor, has_more=more, count=len(page.items))
        body = {
            "items": [incident_payload(row) for row in page.items],
            "meta": meta.model_dump(mode="json", exclude_unset=True),
        }
        return JSONResponse(body)

    return router

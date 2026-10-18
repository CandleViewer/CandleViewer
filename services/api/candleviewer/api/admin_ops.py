"""`GET /admin/health`, `GET /admin/incidents` and `POST /admin/incidents/{incidentId}/acknowledge`
(E42-T05; contract `getHealth`, `listIncidents`, `acknowledgeIncident`; `x-rbac` `admin:read`, and
`admin:write` for the acknowledge; scope none), on the audited admin router (`admin.http`).

The handlers map the read models to the generated `HealthReport` / `Incident` models and serialise
with `exclude_unset`, so a field the source did not read is omitted, never defaulted. A refusal is
a problem document with a registered code: `not_implemented` (501) when no provider is wired,
`store_unavailable` (503, retryable) when the source failed, had nothing yet or outlasted its
budget, `audit_unavailable` (503) when the acknowledge's record could not be written,
`invalid_cursor` (400), `not_found` (404), `conflict` (409, a resolved incident). Its detail is the
read model's fixed literal: no exception text, query or path ever leaves.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Final, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from candleviewer.admin.errors import (
    AdminError,
    IncidentNotFound,
    IncidentResolved,
    InvalidCursor,
    OpsAuditUnavailable,
    OpsNotWired,
    OpsUnavailable,
)
from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.admin.ops.health import AdminHealthService, HealthReading
from candleviewer.admin.ops.incidents import CURSOR_MAX, AdminIncidentsService
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.health_report import render_report
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.storage.repositories.incidents import IncidentRow
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
#: Each refusal the read models raise: its status and registered code. A subclass of one
#: answers as it does.
_REFUSALS: Final = {
    InvalidCursor: (400, ErrorCode.INVALID_CURSOR),
    IncidentNotFound: (404, ErrorCode.NOT_FOUND),
    IncidentResolved: (409, ErrorCode.CONFLICT),
    OpsNotWired: (501, ErrorCode.NOT_IMPLEMENTED),
    OpsUnavailable: (503, ErrorCode.STORE_UNAVAILABLE),
    OpsAuditUnavailable: (503, ErrorCode.AUDIT_UNAVAILABLE),
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


class _Emitter(Protocol):  # `AuditWriter.emit`, as the routes hold it
    async def emit(self, action: str, **kwargs: Any) -> None: ...


def make_admin_incident_ack_router(
    incidents: AdminIncidentsService, *, resolver: PrincipalResolver | None, audit: _Emitter
) -> APIRouter:
    """A write (`admin:write`), so its own audited router: the guard checks RBAC before the id is
    read and leaves the verified principal, who is the record's actor."""
    router = admin_router(Permission.ADMIN_WRITE, resolver=resolver, audit=audit)

    @router.post("/incidents/{incidentId}/acknowledge")
    async def acknowledge_incident(
        request: Request, incident_id: Annotated[UUID, Path(alias="incidentId")]
    ) -> JSONResponse:
        principal: AuditPrincipal = request.state.admin_principal  # left there by the guard

        async def write_ahead(before: IncidentRow, after: IncidentRow) -> None:
            # The handler itself writes the audit record (C-2.9), under the row lock, before the
            # commit: facts only, never `title` or `detail`. Only a transition gets here.
            await audit.emit(
                "incident.acknowledged",  # registered in `audit/actions.py` (SR-E42-11)
                actor_label=principal.username,
                actor_user_id=principal.user_id,
                actor_ip=principal.ip,
                session_id=principal.session_id,
                object_kind="incident",
                object_id=str(after.id),
                outcome=AuditOutcome.SUCCESS,
                severity=Severity.INFO,
                before_state={"status": before.status},
                after_state={
                    "status": after.status,
                    "component": after.component,
                    "severity": after.severity,
                    "occurrences": after.occurrences,
                },
                request_id=principal.request_id,
            )

        try:
            row = await incidents.acknowledge(
                incident_id, by=principal.user_id, write_ahead=write_ahead
            )
        except tuple(_REFUSALS) as exc:  # every refusal the read models raise
            return _refusal(exc)
        return JSONResponse(incident_payload(row))

    return router

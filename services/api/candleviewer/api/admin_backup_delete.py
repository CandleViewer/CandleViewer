"""`DELETE /admin/backups/{backupId}` (E42-T05 #966 BK-12; contract `deleteBackup`, `backups:write`,
scope none) on its own audited admin router: a caller without `backups:write` is counted, recorded
as a denied `admin.area_entered` and refused with 403, never challenged. CSRF is the global
middleware's.

In the contract's order: the row (`501` while nothing is catalogued, `503` on an outage, `404` for
an unknown backup), then `501` while no artefact remover is wired, both before any challenge. Then
the no-grace `backups` grant bound to this request (method and raw target, no body): without one,
the challenge restating `Delete the artefact of backup '<backupId>' (<kind>)`, `target` null;
another request's grant is a recorded mismatch and stays bound. Then `BackupDeletion.delete` under
the admission lock, each `backup.deleted` record through its own `audit_delete`: `409 conflict`
with rule `backup_deleted`, `backup_in_use` or `last_usable_backup`, `503 store_unavailable` or
`audit_unavailable`, the grant staying spent. Last, `204`: the artefact is gone, the row kept with
`deleted_at` (`getBackup`)."""

from __future__ import annotations

from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.deletion import (
    BackupDeletion,
    DeleteRecord,
    DeleteRefused,
    DeleteRule,
)
from candleviewer.admin.errors import AdminError, OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.admin.http import PrincipalResolver, admin_router
from candleviewer.api.step_up import SpentGrant, StepUpAuth, StepUpEmitter, require_bound_elevation
from candleviewer.api.step_up_challenge import (
    ChallengeText,
    quote_label,
    raw_request_target,
    request_fingerprint,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
#: Each refusal of the services, by class: its status and registered code.
_REFUSALS: Final[dict[type[AdminError], tuple[int, ErrorCode]]] = {
    OpsNotWired: (501, ErrorCode.NOT_IMPLEMENTED),
    OpsUnavailable: (503, ErrorCode.STORE_UNAVAILABLE),
    OpsAuditUnavailable: (503, ErrorCode.AUDIT_UNAVAILABLE),
}
#: A `409 conflict`'s message, by its rule.
_CONFLICTS: Final[dict[DeleteRule, str]] = {
    "backup_deleted": "This backup's artefact was already deleted.",
    "backup_in_use": "This backup is running, or a job uses it.",
    "last_usable_backup": "This is the last verified backup of its kind.",
}


def _problem(status: int, code: ErrorCode, detail: str, **extra: Any) -> JSONResponse:
    meta = ERROR_META[code]
    body: dict[str, Any] = {"type": f"https://candleviewer.local/errors/{code.value}"}
    body |= {"title": meta.title, "status": status, "code": code.value, "detail": detail, **extra}
    headers: dict[str, str] = {}
    if meta.retryable:
        body["retry_after_seconds"] = _RETRY_AFTER_S
        headers["Retry-After"] = str(_RETRY_AFTER_S)
    return JSONResponse(body, status, headers, "application/problem+json")


def _refusal(exc: AdminError) -> JSONResponse:
    if isinstance(exc, DeleteRefused) and exc.rule in _CONFLICTS:
        message = _CONFLICTS[exc.rule]
        rule = {"field": "", "rule": exc.rule, "message": message}
        return _problem(409, ErrorCode.CONFLICT, message, errors=[rule])
    if isinstance(exc, DeleteRefused):  # `not_found`: the row the route read is gone
        return _problem(404, ErrorCode.NOT_FOUND, "no such backup")
    status, code = next(v for k, v in _REFUSALS.items() if isinstance(exc, k))
    return _problem(status, code, str(exc))  # the service's fixed literal


def make_admin_backup_delete_router(
    catalogue: BackupCatalogue,
    deletion: BackupDeletion | None,
    *,
    auth: StepUpAuth,
    resolver: PrincipalResolver | None,
    audit: StepUpEmitter,
) -> APIRouter:
    router = admin_router(Permission.BACKUPS_WRITE, resolver=resolver, audit=audit)

    @router.delete("/backups/{backupId}", status_code=204)
    async def delete_backup(
        request: Request, backup_id: Annotated[UUID, Path(alias="backupId")]
    ) -> Response:
        who: AuditPrincipal = request.state.admin_principal  # left there by the guard
        try:
            row = await catalogue.get(backup_id)
        except (OpsNotWired, OpsUnavailable) as exc:
            return _refusal(exc)
        if row is None:
            return _problem(404, ErrorCode.NOT_FOUND, "no such backup")
        if deletion is None:
            return _problem(501, ErrorCode.NOT_IMPLEMENTED, "backups: no artefact remover wired")
        service, target = deletion, f"backup {quote_label(str(row.id))} ({row.kind})"
        spent = await require_bound_elevation(
            auth,
            who.session_id,
            "backups",
            fingerprint=request_fingerprint(request.method, raw_request_target(request), None),
            emitter=audit,
            text=ChallengeText(f"Delete the artefact of {target}"),
        )
        if not isinstance(spent, SpentGrant):
            return spent

        # Each record is the service's own `audit_delete`; the call stays in the handler so the
        # audit-write-required rule (SR-112) sees it.
        async def write_ahead(record: DeleteRecord) -> None:
            await service.audit_delete(who, record)

        try:
            await service.delete(row.id, who, spent.challenge_id, write_ahead)
        except (DeleteRefused, OpsUnavailable, OpsAuditUnavailable) as exc:
            return _refusal(exc)
        return Response(status_code=204)

    return router

"""`POST /admin/backups/{backupId}/verify` (E42-T05 #966 BK-9; contract `verifyBackup`,
`backups:write`, scope none) on its own audited admin router: a caller without `backups:write` is
counted, recorded as a denied `admin.area_entered` and refused with 403. CSRF is the global
middleware's; it is never step-up gated (`_NOT_DANGEROUS`, 04 §7.2.2 row 52).

After the guard, `BackupVerifications.start`, the handler's `write_ahead` writing the
`requested` record through `audit_requested` (C-2.9, SR-112): `202 {job_id}`, the `backup_verify`
job (`GET /admin/jobs/{jobId}`). A refusal is a registered problem: `404 not_found`;
`409 conflict` with its rule (`backup_not_usable`, `verify_running`, `backup_or_restore_running`);
`429 rate_limited` with the limiter's `Retry-After`; `501 not_implemented` until a verifier is
wired (#3319); `503 store_unavailable` with `Retry-After` (a busy admission lock among them,
before any record) or `503 audit_unavailable`. A malformed `backupId` is the app's 422."""

from __future__ import annotations

from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from candleviewer.admin.backups.gate import BackupConflict
from candleviewer.admin.backups.verify import BackupVerifications, VerifiesLimited, VerifyNotUsable
from candleviewer.admin.errors import AdminError, OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
#: Each refusal of the service: its status and registered code.
_REFUSALS: Final[dict[type[AdminError], tuple[int, ErrorCode]]] = {
    OpsNotWired: (501, ErrorCode.NOT_IMPLEMENTED),
    OpsUnavailable: (503, ErrorCode.STORE_UNAVAILABLE),
    OpsAuditUnavailable: (503, ErrorCode.AUDIT_UNAVAILABLE),
    VerifiesLimited: (429, ErrorCode.RATE_LIMITED),
}
#: A `409 conflict`'s rule and message, as `createBackup`'s and the link issue's.
_CONFLICTS: Final = {
    "backup_not_usable": "the backup is not usable",
    "verify_running": "a verification is running",
    "backup_or_restore_running": "a backup or a restore is running",
}


def _problem(
    status: int, code: ErrorCode, detail: str, retry_s: int = _RETRY_AFTER_S, **extra: Any
) -> JSONResponse:
    meta = ERROR_META[code]
    body: dict[str, Any] = {"type": f"https://candleviewer.local/errors/{code.value}"}
    body |= {"title": meta.title, "status": status, "code": code.value, "detail": detail, **extra}
    headers: dict[str, str] = {}
    if meta.retryable:
        body["retry_after_seconds"] = retry_s
        headers["Retry-After"] = str(retry_s)
    return JSONResponse(body, status, headers, "application/problem+json")


def _conflict(rule: str) -> JSONResponse:
    message = _CONFLICTS[rule]
    errors = [{"field": "", "rule": rule, "message": message}]
    return _problem(409, ErrorCode.CONFLICT, f"{message.capitalize()}.", errors=errors)


def make_admin_backup_verify_router(
    verifications: BackupVerifications,
    *,
    resolver: PrincipalResolver | None,
    audit: AuditEmitter | None,
) -> APIRouter:
    router = admin_router(Permission.BACKUPS_WRITE, resolver=resolver, audit=audit)

    @router.post("/backups/{backupId}/verify", status_code=202)
    async def verify_backup(
        request: Request, backup_id: Annotated[UUID, Path(alias="backupId")]
    ) -> JSONResponse:
        who: AuditPrincipal = request.state.admin_principal  # left there by the guard

        # The `requested` record (C-2.9): `start` awaits it, bounded, ahead of the job.
        async def write_ahead(backup: UUID, job_id: UUID) -> None:
            await verifications.audit_requested(who, backup, job_id)

        try:
            job_id = await verifications.start(who, backup_id, write_ahead=write_ahead)
        except VerifyNotUsable:
            return _conflict("backup_not_usable")
        except BackupConflict as exc:
            return _conflict(exc.rule)
        except tuple(_REFUSALS) as exc:
            status, code = next(v for k, v in _REFUSALS.items() if isinstance(exc, k))
            retry = exc.retry_after_s if isinstance(exc, VerifiesLimited) else _RETRY_AFTER_S
            return _problem(status, code, str(exc), retry)  # the service's fixed literal
        if job_id is None:
            return _problem(404, ErrorCode.NOT_FOUND, "no such backup")
        return JSONResponse({"job_id": str(job_id)}, 202)

    return router

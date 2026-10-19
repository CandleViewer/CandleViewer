"""`POST /admin/backups/{backupId}/download` (E42-T05 #966 BK-10; contract `issueBackupDownload`,
`backups:write`, scope none) on its own audited admin router: a caller without `backups:write` is
counted, recorded as a denied `admin.area_entered` and refused with 403, never challenged.

In the contract's order: the row (`501` while nothing is catalogued, `503` on an outage, `404`
for an unknown backup), `501` while no artefact store is wired, then the caller's rolling hour
(`LINKS_PER_HOUR`, `429` with `Retry-After`; the place is taken at the check, so links in flight
count, and a refusal frees it: SR-BK10B-01), all before any challenge. Then the no-grace `backups`
grant bound to this request (method and raw target, no body): without one, the challenge restating
`Issue a 5-minute download link for backup '<backupId>' (<kind>)`, `target` null; another
backup's grant is a recorded mismatch and stays bound. Then `BackupDownloads.issue`, each
`backup.downloaded` record through its own `audit_issue`: `409 conflict` (`backup_not_usable`),
`503 store_unavailable` or `audit_unavailable`. Last, `200 {download_url, expires_at}`,
`Cache-Control: no-store`: the fetch's relative path, the one place the token goes (BK-11)."""

from __future__ import annotations

from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.downloads import BackupDownloads, LinkNotUsable, LinkRecord
from candleviewer.admin.backups.limits import LINKS_PER_HOUR
from candleviewer.admin.backups.links import LinksFull
from candleviewer.admin.errors import AdminError, OpsAuditUnavailable, OpsNotWired, OpsUnavailable
from candleviewer.admin.http import PrincipalResolver, admin_router
from candleviewer.api.audit_limiter import AuditVerifyLimiter
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
_FETCH: Final = "/api/v1/admin/backups/{backup_id}/download/{token}"  # `downloadBackup`
#: Each refusal of the services, by class: its status and registered code.
_REFUSALS: Final[dict[type[AdminError], tuple[int, ErrorCode]]] = {
    OpsNotWired: (501, ErrorCode.NOT_IMPLEMENTED),
    OpsUnavailable: (503, ErrorCode.STORE_UNAVAILABLE),
    LinksFull: (503, ErrorCode.STORE_UNAVAILABLE),
    OpsAuditUnavailable: (503, ErrorCode.AUDIT_UNAVAILABLE),
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


def _refusal(exc: AdminError) -> JSONResponse:
    status, code = next(v for k, v in _REFUSALS.items() if isinstance(exc, k))
    return _problem(status, code, str(exc))  # the service's fixed literal


def make_admin_backup_links_router(
    catalogue: BackupCatalogue,
    downloads: BackupDownloads | None,
    *,
    auth: StepUpAuth,
    resolver: PrincipalResolver | None,
    audit: StepUpEmitter,
    limit: AuditVerifyLimiter | None = None,
) -> APIRouter:
    router = admin_router(Permission.BACKUPS_WRITE, resolver=resolver, audit=audit)
    hourly = AuditVerifyLimiter(rate_per_hour=LINKS_PER_HOUR) if limit is None else limit

    @router.post("/backups/{backupId}/download")
    async def issue_backup_download(
        request: Request, backup_id: Annotated[UUID, Path(alias="backupId")]
    ) -> JSONResponse:
        who: AuditPrincipal = request.state.admin_principal  # left there by the guard
        try:
            row = await catalogue.get(backup_id)
        except (OpsNotWired, OpsUnavailable) as exc:
            return _refusal(exc)
        if row is None:
            return _problem(404, ErrorCode.NOT_FOUND, "no such backup")
        if downloads is None:
            return _problem(501, ErrorCode.NOT_IMPLEMENTED, "backups: no artefact store wired")
        issuer, user = downloads, str(who.user_id)
        if (wait := hourly.retry_after(user)) is not None:
            detail = f"At most {LINKS_PER_HOUR} download links an hour."
            return _problem(429, ErrorCode.RATE_LIMITED, detail, wait)
        hourly.record_start(user)  # the place is taken at the check: links in flight count
        issued = False
        try:
            target = f"backup {quote_label(str(row.id))} ({row.kind})"
            spent = await require_bound_elevation(
                auth,
                who.session_id,
                "backups",
                fingerprint=request_fingerprint(request.method, raw_request_target(request), None),
                emitter=audit,
                text=ChallengeText(f"Issue a 5-minute download link for {target}"),
            )
            if not isinstance(spent, SpentGrant):
                return spent

            # Each record is the service's own `audit_issue`; the call stays in the handler so the
            # audit-write-required rule (SR-112) sees it.
            async def write_ahead(record: LinkRecord) -> None:
                await issuer.audit_issue(who, record)

            token, link = await issuer.issue(row.id, who, spent.challenge_id, write_ahead)
            issued = True
        except LinkNotUsable:
            rule = {"field": "", "rule": "backup_not_usable", "message": "the backup is not usable"}
            detail = "This backup cannot be downloaded."
            return _problem(409, ErrorCode.CONFLICT, detail, errors=[rule])
        except (OpsUnavailable, LinksFull, OpsAuditUnavailable) as exc:
            return _refusal(exc)
        finally:
            if not issued:
                hourly.release(user)  # a refusal frees its place
        url = _FETCH.format(backup_id=row.id, token=token)
        body = {"download_url": url, "expires_at": link.expires_at.isoformat()}
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    return router

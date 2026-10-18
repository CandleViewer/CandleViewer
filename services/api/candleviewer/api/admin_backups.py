"""`GET /admin/backups` and `GET /admin/backups/{backupId}` (E42-T05 #966 BK-4; contract
`listBackups`, `getBackup`; `x-rbac` `backups:read`, scope none) on the audited admin router: a
caller without `backups:read` is counted, recorded as a denied `admin.area_entered` and refused
with 403 before anything is read. Reads: no CSRF token, no step-up.

`backup_payload` serves a row as the contract's `Backup` from an allow-list: `location` from
`target_path`, `error` from `error_message` (a code of the closed set; any other text is served as
`internal_error`), and `deleted_at`; who deleted it, `covers_to`, `triggered_by` and the key alias
are never served. A refusal is a registered problem with the read model's fixed detail:
`invalid_cursor` (400), `not_found` (404), `not_implemented` (501) until an engine records runs,
`store_unavailable` (503, `Retry-After`) for an outage. A malformed `backupId`, `kind`, `status`,
`limit` or `cursor` is the app's 422 (after the guard); a refused statement, its redacted 500.
"""

from __future__ import annotations

from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.errors import AdminError, InvalidCursor, OpsNotWired, OpsUnavailable
from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.admin.ops.incidents import CURSOR_MAX
from candleviewer.api._generated import openapi_models as api
from candleviewer.auth.generated_permissions import Permission
from candleviewer.storage.repositories.backups import BACKUP_ERROR_CODES as _CODES
from candleviewer.storage.repositories.backups import BackupKind, BackupRow, BackupStatus
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
_ERRORS: Final = {code: code for code in (*_CODES, None)}  # `Backup.error`: a code, or null
#: Each refusal the read model raises: its status and registered code. A subclass of one
#: answers as it does.
_REFUSALS: Final[dict[type[AdminError], tuple[int, ErrorCode]]] = {
    InvalidCursor: (400, ErrorCode.INVALID_CURSOR),
    OpsNotWired: (501, ErrorCode.NOT_IMPLEMENTED),
    OpsUnavailable: (503, ErrorCode.STORE_UNAVAILABLE),
}


def backup_payload(row: BackupRow) -> dict[str, Any]:
    fields = {
        "id": row.id, "kind": row.kind, "status": row.status, "started_at": row.started_at,
        "finished_at": row.finished_at, "size_bytes": row.size_bytes, "location": row.target_path,
        "checksum_sha256": row.checksum_sha256, "encrypted": row.encrypted,
        "retention_until": row.retention_until, "verified_at": row.verified_at,
        "error": _ERRORS.get(row.error_message, "internal_error"), "deleted_at": row.deleted_at,
    }  # fmt: skip
    return api.Backup.model_validate(fields).model_dump(mode="json", exclude_unset=True)


def _problem(status: int, code: ErrorCode, detail: str) -> JSONResponse:
    meta = ERROR_META[code]
    body: dict[str, Any] = {"type": f"https://candleviewer.local/errors/{code.value}"}
    body |= {"title": meta.title, "status": status, "code": code.value, "detail": detail}
    headers: dict[str, str] = {}
    if meta.retryable:
        body["retry_after_seconds"] = _RETRY_AFTER_S
        headers["Retry-After"] = str(_RETRY_AFTER_S)
    return JSONResponse(body, status, headers, "application/problem+json")


def _refusal(exc: AdminError) -> JSONResponse:
    status, code = next(v for k, v in _REFUSALS.items() if isinstance(exc, k))
    return _problem(status, code, str(exc))  # the read model's fixed literal


def make_admin_backups_router(
    catalogue: BackupCatalogue, *, resolver: PrincipalResolver | None, audit: AuditEmitter | None
) -> APIRouter:
    router = admin_router(Permission.BACKUPS_READ, resolver=resolver, audit=audit)

    @router.get("/backups")
    async def list_backups(
        kind: BackupKind | None = None,
        status: BackupStatus | None = None,
        cursor: Annotated[str | None, Query(max_length=CURSOR_MAX)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> JSONResponse:
        try:
            page = await catalogue.page(kind=kind, status=status, cursor=cursor, limit=limit)
        except (InvalidCursor, OpsNotWired, OpsUnavailable) as exc:
            return _refusal(exc)
        more, count = page.next_cursor is not None, len(page.items)
        meta = api.PageMeta(next_cursor=page.next_cursor, has_more=more, count=count)
        items = [backup_payload(row) for row in page.items]  # `total` is never computed
        return JSONResponse({"items": items, "meta": meta.model_dump(exclude_unset=True)})

    @router.get("/backups/{backupId}")
    async def get_backup(backup_id: Annotated[UUID, Path(alias="backupId")]) -> JSONResponse:
        try:
            row = await catalogue.get(backup_id)
        except (OpsNotWired, OpsUnavailable) as exc:
            return _refusal(exc)
        if row is None:
            return _problem(404, ErrorCode.NOT_FOUND, "no such backup")
        return JSONResponse(backup_payload(row))

    return router

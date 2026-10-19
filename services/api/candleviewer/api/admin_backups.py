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

`POST /admin/backups` (BK-8; `createBackup`, `backups:write`, scope none) is on a router of its own:
CSRF is the global middleware's, and no step-up (`_NOT_DANGEROUS`). After the guard: the closed body
(`kind`, `verify`, `note` up to 280 characters, storable text; capped at `MAX_BODY_BYTES`) and a
UUID `Idempotency-Key`, else 422 naming no value and no unknown member; then the key: a stored
`202` for the same body is replayed, another body under it is `409 idempotency_key_reuse`; then
`BackupRuns.start`, the handler's `write_ahead` writing the run's `requested` record (C-2.9,
SR-112): `202` with the new `Backup`, whose `id` is its job's, kept under the key. A refusal is
never kept, so the same key is evaluated afresh once its cause clears; an engine that plans an
unencrypted run is `503 backup_engine_invalid`, not retryable, once its failure record is written.
"""

from __future__ import annotations

from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.gate import BackupConflict, ConflictRule
from candleviewer.admin.backups.runs import BackupEngineInvalid, BackupRuns, RunsLimited
from candleviewer.admin.errors import (
    AdminError,
    InvalidCursor,
    OpsAuditUnavailable,
    OpsNotWired,
    OpsUnavailable,
)
from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.admin.ops.incidents import CURSOR_MAX
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.idempotency import (
    IdempotencyCache,
    IdempotencyKeyReuse,
    idempotency_key,
    remember,
    replay,
    request_fingerprint,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.domain.text import refuse_unstorable_text
from candleviewer.observability.redaction import redact_structure, redact_text
from candleviewer.storage.repositories.backups import BACKUP_ERROR_CODES as _CODES
from candleviewer.storage.repositories.backups import BackupKind, BackupRow, BackupStatus
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_RETRY_AFTER_S: Final = 5
_ERRORS: Final = {code: code for code in (*_CODES, None)}  # `Backup.error`: a code, or null
#: Each refusal the read model or the run service raises: its status and registered code. A
#: subclass of one answers as it does.
_REFUSALS: Final[dict[type[AdminError], tuple[int, ErrorCode]]] = {
    InvalidCursor: (400, ErrorCode.INVALID_CURSOR),
    OpsNotWired: (501, ErrorCode.NOT_IMPLEMENTED),
    OpsUnavailable: (503, ErrorCode.STORE_UNAVAILABLE),
    RunsLimited: (429, ErrorCode.RATE_LIMITED),
    BackupConflict: (409, ErrorCode.CONFLICT),
    OpsAuditUnavailable: (503, ErrorCode.AUDIT_UNAVAILABLE),
    BackupEngineInvalid: (503, ErrorCode.BACKUP_ENGINE_INVALID),
}
#: A `409 conflict`'s message, by its rule (BK-9 and BK-12 answer the other two).
_CONFLICTS: Final[dict[ConflictRule, str]] = {
    "backup_or_restore_running": "a backup or a restore is running",
    "verify_running": "a verification is running",
    "backup_in_use": "a job is running on this backup",
}
#: The largest valid body, a 280-character note of 12-byte JSON escapes, is under 4 KiB.
MAX_BODY_BYTES: Final = 4096


# `createBackup`'s closed body: `additionalProperties: false`, `kind` required, `note` a string.
# (No docstring: pydantic would publish it as the schema's `description`.)
class RunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    kind: BackupKind
    verify: bool = True
    note: str | None = Field(default=None, max_length=280)

    @field_validator("note")
    @classmethod
    def _storable_note(cls, note: str | None) -> str:
        if note is None:  # sent as `null`: the contract's `note` is a string
            raise ValueError("must be a string")
        return refuse_unstorable_text(note)


def backup_payload(row: BackupRow) -> dict[str, Any]:
    fields = {
        "id": row.id, "kind": row.kind, "status": row.status, "started_at": row.started_at,
        "finished_at": row.finished_at, "size_bytes": row.size_bytes, "location": row.target_path,
        "checksum_sha256": row.checksum_sha256, "encrypted": row.encrypted,
        "retention_until": row.retention_until, "verified_at": row.verified_at,
        "error": _ERRORS.get(row.error_message, "internal_error"), "deleted_at": row.deleted_at,
    }  # fmt: skip
    return api.Backup.model_validate(fields).model_dump(mode="json", exclude_unset=True)


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
    if isinstance(exc, BackupConflict):
        message = _CONFLICTS[exc.rule]
        rule = {"field": "", "rule": exc.rule, "message": message}
        return _problem(status, code, f"{message.capitalize()}.", errors=[rule])
    retry = exc.retry_after_s if isinstance(exc, RunsLimited) else _RETRY_AFTER_S
    return _problem(status, code, str(exc), retry)  # the service's fixed literal


def _invalid(field: str, rule: str, message: str) -> JSONResponse:
    errors = redact_structure([{"field": field, "rule": rule, "message": redact_text(message)}])
    return _problem(422, ErrorCode.VALIDATION_FAILED, "The request is invalid.", errors=errors)


async def _run_request(request: Request) -> tuple[bytes, RunRequest] | JSONResponse:
    """The body, read only up to the cap, and checked; a wrong one is never echoed back, an
    unknown member's name included (`field` is then the body's, empty)."""
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            return _invalid("", "body_too_large", f"The body exceeds {MAX_BODY_BYTES} bytes.")
    try:
        return bytes(raw), RunRequest.model_validate_json(bytes(raw))
    except ValidationError as exc:
        first = exc.errors()[0]
        field = "" if first["type"] == "extra_forbidden" else ".".join(map(str, first["loc"]))
        return _invalid(field, first["type"], first["msg"])


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


def make_admin_backup_runs_router(
    runs: BackupRuns,
    *,
    resolver: PrincipalResolver | None,
    audit: AuditEmitter | None,
    idempotency: IdempotencyCache | None = None,
) -> APIRouter:
    router = admin_router(Permission.BACKUPS_WRITE, resolver=resolver, audit=audit)
    cache = IdempotencyCache() if idempotency is None else idempotency

    @router.post("/backups", status_code=202)
    async def create_backup(request: Request) -> Response:
        who: AuditPrincipal = request.state.admin_principal  # left there by the guard
        parsed = await _run_request(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        raw, body = parsed
        try:
            key = idempotency_key(request, "createBackup")
        except ValueError:
            return _invalid("Idempotency-Key", "uuid", "Idempotency-Key must be a UUID.")
        owner, digest = str(who.user_id), request_fingerprint(request.method, request.url.path, raw)
        try:
            if (hit := replay(cache, owner, key, digest)) is not None:
                return hit
        except IdempotencyKeyReuse:
            detail = "The key was first used with another request."
            return _problem(409, ErrorCode.IDEMPOTENCY_KEY_REUSE, detail)

        # The run's `requested` record (C-2.9): `start` awaits it, bounded, ahead of the row.
        async def write_ahead(backup_id: UUID, kind: BackupKind) -> None:
            verify, note = body.verify, body.note
            await runs.audit_requested(who, backup_id, kind=kind, verify=verify, note=note)

        try:
            row = await runs.start(who, kind=body.kind, write_ahead=write_ahead)
        except tuple(_REFUSALS) as exc:
            return _refusal(exc)
        return remember(cache, owner, key, digest, JSONResponse(backup_payload(row), 202))

    return router

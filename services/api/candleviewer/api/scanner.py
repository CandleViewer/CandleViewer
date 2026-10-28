"""`/scanner/criteria` and `/scanner/presets*` routes (E08-T09 PR 2a, #4708): contract
`22-api-openapi.yaml` (`listScannerCriteria`, `listScannerPresets`, `createScannerPreset`,
`updateScannerPreset`, `deleteScannerPreset`). There is no preset GET by id: that path answers
any other method 405, the same for every id. `runScanner` (`GET /scanner`) is PR 2b's.

Callers come from the session (`SessionAuditPrincipalResolver`, as `/indicator-presets`); RBAC
(C-12.4) runs per request through `auth.scopes.enforce()`, each denial audited `rbac.denied`:
`marketdata:read` for the two reads (the criteria `scope: none`, the presets `scope: self`),
`workspaces:write` `scope: self` for the writes, whose CSRF token the middleware checks first.
Then 22's evaluation order: the body cap (413, 8 KiB, before anything parses the body), the
path and the query (SR-026: no operation declares a query parameter, so any is refused), the
body (422: UTF-8, nesting depth, the closed DTO, the filter), and the service
(`scanner_presets_service`): the target (404 for a missing or another user's preset), 409, the
write-ahead audit records and the write. A storage failure, or no store wired (the fake
backend), is 503 `store_unavailable`; an audit record the writer refuses is 503
`audit_unavailable` and nothing is stored (C-2.9).

No body content is logged. A problem carries `field`, `rule` and a bounded, redacted message,
never SQL, a file path or the submitted JSON.
"""

import inspect
import re
import time
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Protocol
from uuid import UUID

import structlog
from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError

from candleviewer.api.drawings_models import MAX_JSON_DEPTH, format_errors
from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.api.scanner_criteria import CRITERIA, describe, sort_keys, split_stored
from candleviewer.api.scanner_presets_models import (
    SCANNER_PRESET_BODY_MAX_BYTES,
    ScannerPresetInput,
    ScannerPresetInvalidError,
)
from candleviewer.api.scanner_presets_service import (
    AuditEmitter,
    ScannerPresetService,
    ScannerPresetStoreUnavailableError,
)
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.ingestion.ticker_stream import uuid7
from candleviewer.observability.redaction import redact_structure, redact_text
from candleviewer.storage.repositories.scanner_presets import (
    FILTER_MAX_BYTES,
    ScannerPresetConflictError,
    ScannerPresetNotFoundError,
    ScannerPresetRepository,
    ScannerPresetRow,
    ScannerPresetShapeError,
)
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.limits import json_depth_exceeds

#: The registered `x-error-codes` this router emits: code -> HTTP status.
_STATUS: Final[dict[str, int]] = {
    "unauthenticated": 401,
    "forbidden": 403,
    "not_found": 404,
    "conflict": 409,
    "payload_too_large": 413,
    "validation_failed": 422,
    "store_unavailable": 503,
    "audit_unavailable": 503,
}
#: 503s carry the contract's `Retry-After` (`ServiceUnavailable`).
_RETRY_AFTER_S: Final = 5
#: No `/scanner/criteria` or `/scanner/presets*` operation declares a query parameter (SR-026).
_NO_QUERY: Final[frozenset[str]] = frozenset()
_PERMISSIONS: Final = {p.value: p for p in Permission}
_LENGTH: Final = re.compile(r"[0-9]{1,19}")
_CONFLICTS: Final = {
    "name_taken": "You already have a scanner preset with this name.",
    "limit_reached": "You have reached the limit of saved scanner presets.",
    "conflict": "Another default preset was saved at the same time; try again.",
}
_UNAVAILABLE: Final = "The scanner preset store is unavailable."


class _Resolver(Protocol):
    """`SessionAuditPrincipalResolver`: bearer -> `AuditPrincipal`; `None` = no verified session."""

    def resolve(
        self, request: Request
    ) -> AuditPrincipal | Awaitable[AuditPrincipal | None] | None: ...


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.scanner_presets")


def _snapshot(p: AuditPrincipal) -> PrincipalSnapshot:
    """Known permission codes only (a wildcard grants nothing) and the owner flag."""
    perms = frozenset(_PERMISSIONS[c] for c in p.permissions if c in _PERMISSIONS)
    return PrincipalSnapshot(p.user_id, frozenset({"owner"} if p.is_owner else ()), perms)


def _rule(field: str, rule: str, message: str) -> dict[str, str]:
    return {"field": field, "rule": rule, "message": message}


class _Problem(Exception):
    """RFC 9457 problem for a registered code: its status from `_STATUS`, its title from the
    registry."""

    def __init__(self, code: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.title = _STATUS[code], ERROR_META[ErrorCode(code)].title
        self.code, self.detail, self.extra = code, detail, extra

    def response(self) -> JSONResponse:
        body = {"type": f"https://candleviewer.local/errors/{self.code}", "title": self.title,
                "status": self.status, "code": self.code, "detail": self.detail}  # fmt: skip
        headers = {"Retry-After": str(_RETRY_AFTER_S)} if self.status == 503 else {}
        return JSONResponse(body | self.extra, self.status, headers, "application/problem+json")


def _invalid(errors: list[dict[str, str]]) -> _Problem:
    """422 with at most 20 field errors, passed through the shared redaction rule set."""
    return _Problem("validation_failed", "The request is invalid.",
                    errors=redact_structure(errors[:20]))  # fmt: skip


def _checked(errors: list[dict[str, str]]) -> _Problem:
    """422 for the server's own rules: `rule` comes from a closed server-side set and stays
    verbatim; `field` and `message` still pass through the redaction."""
    items = [{"field": redact_text(e["field"]), "rule": e["rule"],
              "message": redact_text(e["message"])} for e in errors[:20]]  # fmt: skip
    return _Problem("validation_failed", "The request is invalid.", errors=items)


def _refusal(exc: Exception) -> _Problem | None:
    """The problem a service or store refusal is answered with; None for anything else."""
    if isinstance(exc, ScannerPresetInvalidError):
        return _checked(exc.errors)
    if isinstance(exc, ScannerPresetShapeError):  # the DB CHECK behind the API's own size check
        message = f"filter must be at most {FILTER_MAX_BYTES} bytes."
        return _checked([_rule("filter", "filter_too_large", message)])
    if isinstance(exc, ScannerPresetNotFoundError):
        return _Problem("not_found", "No such scanner preset.")
    if isinstance(exc, ScannerPresetConflictError):
        item = {"rule": exc.rule, "message": _CONFLICTS[exc.rule]}
        item = item if exc.field is None else {"field": exc.field} | item
        return _Problem("conflict", item["message"], errors=[item])
    if isinstance(exc, ScannerPresetStoreUnavailableError):
        return _Problem("store_unavailable", _UNAVAILABLE)
    return None


class _Refused(Exception):
    """A ready refusal (the shared SR-026 one), sent as it is."""

    def __init__(self, response: JSONResponse) -> None:
        super().__init__(response.status_code)
        self.response = response


class _ProblemRoute(APIRoute):
    """`_Problem` and the service's refusals -> their responses; an audit record the writer
    refuses -> 503 `audit_unavailable`; a store I/O failure -> 503 `store_unavailable`."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await inner(request)
            except _Problem as p:
                return p.response()
            except _Refused as r:
                return r.response
            except (AuditUnavailable, AuditWriterStopped) as exc:  # fails closed: logged apart
                _log().error("scanner_presets_audit_unavailable", error=type(exc).__name__)
                detail = "The audit record could not be written; nothing was changed."
                return _Problem("audit_unavailable", detail).response()
            except Exception as exc:  # re-raised below unless it is a refusal or an outage
                refusal = _refusal(exc)
                if refusal is not None:
                    return refusal.response()
                if not is_storage_outage(exc):
                    raise
                # class name only: str(exc) of a SQLAlchemy error embeds bound parameters
                _log().error("scanner_presets_store_unavailable", error=type(exc).__name__)
            return _Problem("store_unavailable", _UNAVAILABLE).response()

        return handler


async def _read_capped(request: Request, cap: int) -> bytes:
    """The raw body, refused with 413 past `cap` bytes before it is fully buffered: a declared
    length over the cap is refused at once, and a stream stops one chunk past it."""
    too_large = _Problem("payload_too_large", f"The request body exceeds {cap} bytes.")
    declared = request.headers.get("content-length", "")
    if _LENGTH.fullmatch(declared) and int(declared) > cap:
        raise too_large
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > cap:
            raise too_large
    return bytes(raw)


def _no_query(request: Request, *, self_service: bool = True) -> None:
    """SR-026: any query parameter is refused with the shared 422, after the permission check
    and before anything is read."""
    refused = undeclared_query_refusal(request, _NO_QUERY, self_service=self_service)
    if refused is not None:
        raise _Refused(refused)


def _parse(raw: bytes) -> ScannerPresetInput:
    """UTF-8 text nested at most `MAX_JSON_DEPTH` deep (checked before anything decodes it),
    then the closed DTO."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _invalid([_rule("", "json_invalid", "The body is not UTF-8 JSON.")]) from None
    if json_depth_exceeds(text, MAX_JSON_DEPTH):
        message = f"JSON nesting is deeper than {MAX_JSON_DEPTH} levels."
        raise _invalid([_rule("", "json_too_deep", message)])
    try:
        return ScannerPresetInput.model_validate_json(text)
    except ValidationError as exc:
        raise _invalid(format_errors(exc)) from None


def _preset_id(raw: str) -> str:
    """Canonical lowercase uuid; anything else violates the `PresetId` parameter (422)."""
    try:
        return str(UUID(raw))
    except ValueError:
        raise _invalid([_rule("presetId", "uuid_parsing", "presetId must be a UUID.")]) from None


def _stamp(value: datetime) -> str:
    """UTC, six fractional digits and a `Z`, as the presets and workspaces tokens are."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def dump(row: ScannerPresetRow) -> dict[str, Any]:
    """`ScannerPreset`: exactly the contract's properties, the criteria the server no longer
    knows or lists unavailable moved out of `filter` into `unavailable_criteria`, with an
    unavailable stored `sort` (never dropped from the row; `sort` served as stored)."""
    known, unavailable = split_stored(row.filter, sort=row.sort)
    return {
        "id": row.id, "name": row.name, "filter": known, "sort": row.sort,
        "is_default": row.is_default, "unavailable_criteria": unavailable,
        "version": row.version, "created_at": _stamp(row.created_at),
        "updated_at": _stamp(row.updated_at),
    }  # fmt: skip


def _new_id() -> UUID:
    return uuid7(time.time_ns() // 1_000_000)


def make_scanner_router(
    repo_provider: Callable[[], ScannerPresetRepository | None],
    principal_resolver: _Resolver | None,
    audit: AuditEmitter,
    *,
    new_id: Callable[[], UUID] = _new_id,
) -> APIRouter:
    """`audit` is mandatory (every write and every denial leaves its record). No resolver (no
    identity store: nothing can verify a session) fails closed with 401; no store with 503."""
    if audit is None:
        raise TypeError("make_scanner_router: an audit emitter is required")
    service = ScannerPresetService(repo_provider, audit, new_id=new_id)
    router = APIRouter(route_class=_ProblemRoute)

    async def caller(request: Request, permission: Permission, scope: Scope) -> AuditPrincipal:
        got: object = None if principal_resolver is None else principal_resolver.resolve(request)
        if inspect.isawaitable(got):
            got = await got
        if not isinstance(got, AuditPrincipal):
            raise _Problem("unauthenticated", "No verified session for this request.")
        try:
            await enforce(
                _snapshot(got),
                permission,
                scope=scope,
                emitter=audit,
                actor_ip=got.ip,
                session_id=got.session_id,
                request_id=got.request_id,
            )
        except ForbiddenError:
            raise _Problem("forbidden", f"Requires {permission.value}.",
                           required_permissions=[permission.value]) from None  # fmt: skip
        return got

    @router.get("/scanner/criteria", tags=["market-data"])
    async def list_scanner_criteria(request: Request) -> Response:
        await caller(request, Permission.MARKETDATA_READ, Scope.NONE)
        _no_query(request, self_service=False)
        return JSONResponse({"items": [describe(c) for c in CRITERIA], "sort_keys": sort_keys()})

    @router.get("/scanner/presets", tags=["workspaces"])
    async def list_scanner_presets(request: Request) -> Response:
        principal = await caller(request, Permission.MARKETDATA_READ, Scope.SELF)
        _no_query(request)
        rows = await service.list_own(str(principal.user_id))
        return JSONResponse({"items": [dump(r) for r in rows]})

    @router.post("/scanner/presets", tags=["workspaces"])  # nosem: audit-write-required reason=audited-below-the-handler-in-ScannerPresetService-scanner_preset.created-write-ahead-#4708 owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def create_scanner_preset(request: Request) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE, Scope.SELF)
        raw = await _read_capped(request, SCANNER_PRESET_BODY_MAX_BYTES)
        _no_query(request)
        row = await service.create(principal, _parse(raw))
        return JSONResponse(dump(row), 201)

    @router.put("/scanner/presets/{presetId}", tags=["workspaces"])  # nosem: audit-write-required reason=audited-below-the-handler-in-ScannerPresetService-scanner_preset.updated-write-ahead-and-rbac.denied-refusals-#4708 owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def update_scanner_preset(
        request: Request, preset_id: Annotated[str, Path(alias="presetId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE, Scope.SELF)
        raw = await _read_capped(request, SCANNER_PRESET_BODY_MAX_BYTES)
        pid = _preset_id(preset_id)
        _no_query(request)
        row = await service.replace(principal, pid, _parse(raw))
        return JSONResponse(dump(row))

    @router.delete("/scanner/presets/{presetId}", tags=["workspaces"])  # nosem: audit-write-required reason=audited-below-the-handler-in-ScannerPresetService-scanner_preset.deleted-write-ahead-and-rbac.denied-refusals-#4708 owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def delete_scanner_preset(
        request: Request, preset_id: Annotated[str, Path(alias="presetId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE, Scope.SELF)
        pid = _preset_id(preset_id)
        _no_query(request)
        await service.delete(principal, pid)
        return Response(status_code=204)

    return router


__all__ = ["dump", "make_scanner_router"]

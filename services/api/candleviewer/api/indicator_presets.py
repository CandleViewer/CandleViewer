"""`/indicator-presets` routes (E13-T03, #427): contract `22-api-openapi.yaml`
(`listIndicatorPresets`, `createIndicatorPreset`, `updateIndicatorPreset`,
`deleteIndicatorPreset`). There is no GET by id (ruling Q3): that path answers any other
method 405, the same for every id.

Callers come from the session (`SessionAuditPrincipalResolver`, as `/drawings`); RBAC (C-12.4,
IR-40) runs per request through `auth.scopes.enforce()`, each denial audited `rbac.denied`:
`workspaces:read` to list, `workspaces:write` to write, `scope: self`. Then 22's evaluation
order: the body cap (413, before anything parses the body), the path and the query (SR-026: no
operation declares a query parameter, so any is refused), the body (422), and the service
(`indicator_presets_service`): the target (404 / 403 `builtin_immutable`), `immutable_field`,
409, the write-ahead audit record and the write. A storage failure, or no store wired (the fake
backend), is 503 `store_unavailable`; an audit record the writer refuses is 503
`audit_unavailable` and nothing is stored (C-2.9).

Bodies are read raw so the 16 KiB cap and the UTF-8 and nesting checks run before pydantic; no
body content is logged. A problem carries `field`, `rule` and a bounded, redacted message, never
SQL, a file path or the submitted JSON (IR-24).
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
from candleviewer.api.indicator_presets_models import PresetInput, PresetInvalidError
from candleviewer.api.indicator_presets_service import (
    AuditEmitter,
    IndicatorPresetMetricsLike,
    IndicatorPresetService,
    PresetBuiltinImmutableError,
    PresetStoreUnavailableError,
)
from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.ingestion.ticker_stream import uuid7
from candleviewer.observability.redaction import redact_structure, redact_text
from candleviewer.orderflow.indicators.catalogue import IndicatorCatalogue
from candleviewer.orderflow.indicators.limits import PRESET_BODY_MAX_BYTES
from candleviewer.storage.repositories.indicator_presets import (
    IndicatorPresetRepository,
    PresetConflictError,
    PresetNotFoundError,
    PresetRow,
    PresetShapeError,
)
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.limits import json_depth_exceeds

#: The registered `x-error-codes` this router emits: code -> HTTP status. A problem's `title` is
#: the registry's own (`ERROR_META`, generated from 22), as every other router answers it.
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
#: No `/indicator-presets*` operation declares a query parameter (SR-026).
_NO_QUERY: Final[frozenset[str]] = frozenset()
_PERMISSIONS: Final = {p.value: p for p in Permission}
_LENGTH: Final = re.compile(r"[0-9]{1,19}")
_CONFLICTS: Final = {
    "name_taken": "You already have a preset with this name for this indicator.",
    "limit_reached": "You have reached the limit of saved indicator presets.",
}
_SHAPE_RULES: Final = {"params": "params_too_large", "style": "style_not_allowed"}


class _Resolver(Protocol):
    """`SessionAuditPrincipalResolver`: bearer -> `AuditPrincipal`; `None` = no verified session."""

    def resolve(
        self, request: Request
    ) -> AuditPrincipal | Awaitable[AuditPrincipal | None] | None: ...


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.indicator_presets")


def _snapshot(p: AuditPrincipal) -> PrincipalSnapshot:
    """Known permission codes only (a wildcard grants nothing: the Owner's "*" is expanded to
    explicit codes at seed time) and the owner flag the session resolver derived."""
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
    """422 for the service's own refusals. `rule` comes from a closed server-side set and stays
    verbatim (the shared rules would take `additionalProperties` for a key and redact it);
    `field` and `message` still pass through the redaction."""
    items = [{"field": redact_text(e["field"]), "rule": e["rule"],
              "message": redact_text(e["message"])} for e in errors[:20]]  # fmt: skip
    return _Problem("validation_failed", "The request is invalid.", errors=items)


def _refusal(exc: Exception) -> _Problem | None:
    """The problem a service or store refusal is answered with; None for anything else."""
    if isinstance(exc, PresetInvalidError):
        return _checked(exc.errors)
    if isinstance(exc, PresetShapeError):  # the DB CHECK behind the API's own size check
        message = f"{exc.field} is larger than a preset may store."
        return _checked([_rule(exc.field, _SHAPE_RULES[exc.field], message)])
    if isinstance(exc, PresetNotFoundError):
        return _Problem("not_found", "No such indicator preset.")
    if isinstance(exc, PresetBuiltinImmutableError):
        message = "Built-in presets cannot be changed; save a copy instead."
        errors = [_rule("presetId", "builtin_immutable", message)]
        return _Problem("forbidden", message, errors=errors)
    if isinstance(exc, PresetConflictError):
        item = {"rule": exc.rule, "message": _CONFLICTS[exc.rule]}
        item = item if exc.field is None else {"field": exc.field} | item
        return _Problem("conflict", item["message"], errors=[item])
    if isinstance(exc, PresetStoreUnavailableError):
        return _Problem("store_unavailable", "The indicator preset store is unavailable.")
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
                _log().error("indicator_presets_audit_unavailable", error=type(exc).__name__)
                detail = "The audit record could not be written; nothing was changed."
                return _Problem("audit_unavailable", detail).response()
            except Exception as exc:  # re-raised below unless it is a refusal or an outage
                refusal = _refusal(exc)
                if refusal is not None:
                    return refusal.response()
                if not is_storage_outage(exc):
                    raise
                # class name only: str(exc) of a SQLAlchemy error embeds bound parameters
                _log().error("indicator_presets_store_unavailable", error=type(exc).__name__)
            return _Problem(
                "store_unavailable", "The indicator preset store is unavailable."
            ).response()

        return handler


def _declared_length(raw: str) -> int | None:
    """`Content-Length` when it is 1..19 ASCII digits, else None (only the streaming cap then)."""
    return int(raw) if _LENGTH.fullmatch(raw) else None


async def _read_capped(request: Request, cap: int) -> bytes:
    """The raw body, refused with 413 past `cap` bytes before it is fully buffered: a declared
    length over the cap is refused at once, and a stream stops one chunk past it."""
    too_large = _Problem("payload_too_large", f"The request body exceeds {cap} bytes.")
    declared = _declared_length(request.headers.get("content-length", ""))
    if declared is not None and declared > cap:
        raise too_large
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > cap:
            raise too_large
    return bytes(raw)


def _no_query(request: Request) -> None:
    """SR-026: any query parameter is refused with the shared 422, after the permission check
    and before anything is read."""
    refused = undeclared_query_refusal(request, _NO_QUERY)
    if refused is not None:
        raise _Refused(refused)


def _parse(raw: bytes) -> PresetInput:
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
        return PresetInput.model_validate_json(text)
    except ValidationError as exc:
        raise _invalid(format_errors(exc)) from None


def _preset_id(raw: str) -> str:
    """Canonical lowercase uuid; anything else violates the `PresetId` parameter (422)."""
    try:
        return str(UUID(raw))
    except ValueError:
        raise _invalid([_rule("presetId", "uuid_parsing", "presetId must be a UUID.")]) from None


def _stamp(value: datetime) -> str:
    """UTC, six fractional digits and a `Z`, as the drawings and workspaces tokens are."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def dump(row: PresetRow) -> dict[str, Any]:
    """`IndicatorPreset`: exactly the contract's properties (never `deleted_at`)."""
    return {
        "id": row.id, "owner_user_id": row.owner_user_id, "indicator_code": row.indicator_code,
        "name": row.name, "params": row.params, "style": row.style,
        "pane_target": row.pane_target, "is_builtin": row.is_builtin,
        "is_favourite": row.is_favourite, "created_at": _stamp(row.created_at),
        "updated_at": _stamp(row.updated_at),
    }  # fmt: skip


def _new_id() -> UUID:
    return uuid7(time.time_ns() // 1_000_000)


def make_indicator_presets_router(
    repo_provider: Callable[[], IndicatorPresetRepository | None],
    principal_resolver: _Resolver | None,
    audit: AuditEmitter,
    catalogue: IndicatorCatalogue,
    *,
    metrics: IndicatorPresetMetricsLike | None = None,
    new_id: Callable[[], UUID] = _new_id,
) -> APIRouter:
    """`audit` is mandatory (every write and every denial leaves its record). No resolver (no
    identity store: nothing can verify a session) fails closed with 401; no store with 503.
    `catalogue` is the one `/indicators` serves, so a preset validates against what a client
    renders; `metrics` records the two E13-T03 series, `None` records nothing."""
    if audit is None:
        raise TypeError("make_indicator_presets_router: an audit emitter is required")
    service = IndicatorPresetService(
        repo_provider, catalogue, audit, new_id=new_id, metrics=metrics
    )
    router = APIRouter(tags=["workspaces"], route_class=_ProblemRoute)

    async def caller(request: Request, permission: Permission) -> AuditPrincipal:
        got: object = None if principal_resolver is None else principal_resolver.resolve(request)
        if inspect.isawaitable(got):
            got = await got
        if not isinstance(got, AuditPrincipal):
            raise _Problem("unauthenticated", "No verified session for this request.")
        try:
            await enforce(
                _snapshot(got),
                permission,
                scope=Scope.SELF,
                emitter=audit,
                actor_ip=got.ip,
                session_id=got.session_id,
                request_id=got.request_id,
            )
        except ForbiddenError:
            raise _Problem("forbidden", f"Requires {permission.value}.",
                           required_permissions=[permission.value]) from None  # fmt: skip
        return got

    @router.get("/indicator-presets")
    async def list_indicator_presets(request: Request) -> Response:
        principal = await caller(request, Permission.WORKSPACES_READ)
        _no_query(request)
        rows = await service.list_visible(str(principal.user_id))
        return JSONResponse({"items": [dump(r) for r in rows]})

    @router.post("/indicator-presets")  # nosem: audit-write-required reason=audited-below-the-handler-in-IndicatorPresetService-indicator_preset.created-write-ahead-#427 owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def create_indicator_preset(request: Request) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        raw = await _read_capped(request, PRESET_BODY_MAX_BYTES)
        _no_query(request)
        row = await service.create(principal, _parse(raw))
        return JSONResponse(dump(row), 201)

    @router.put("/indicator-presets/{presetId}")  # nosem: audit-write-required reason=audited-below-the-handler-in-IndicatorPresetService-indicator_preset.updated-write-ahead-and-rbac.denied-refusals-#427 owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def update_indicator_preset(
        request: Request, preset_id: Annotated[str, Path(alias="presetId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        raw = await _read_capped(request, PRESET_BODY_MAX_BYTES)
        pid = _preset_id(preset_id)
        _no_query(request)
        row = await service.replace(principal, pid, _parse(raw))
        return JSONResponse(dump(row))

    @router.delete("/indicator-presets/{presetId}")  # nosem: audit-write-required reason=audited-below-the-handler-in-IndicatorPresetService-indicator_preset.deleted-write-ahead-and-rbac.denied-refusals-#427 owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def delete_indicator_preset(
        request: Request, preset_id: Annotated[str, Path(alias="presetId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        pid = _preset_id(preset_id)
        _no_query(request)
        await service.soft_delete(principal, pid)
        return Response(status_code=204)

    return router


__all__ = ["dump", "make_indicator_presets_router"]

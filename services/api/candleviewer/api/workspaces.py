"""`/workspaces*` routes (E15-T01, #402): contract `22-api-openapi.yaml`, decision record on #402.

Callers come from the session (`SessionAuditPrincipalResolver`); RBAC (C-12.4) runs per request
through `auth.scopes.enforce()`, each denial audited as `rbac.denied`: `workspaces:read` to read,
`workspaces:write` to write, `scope: self`. A missing, deleted or foreign workspace/layout is the
same 404 (D18); a live foreign id is also audited (`object_kind` workspace|layout), on reads too.
Writes are not audited (D20). Bodies are read raw so the byte and depth caps run before pydantic.
Evaluation order (D13): 401, 403, 413, 422, 400, 404, no-op 200, 412, 409, write (the last four
are the repository's, in one transaction). Logs carry ids, counts and outcomes, never content.
"""

import base64
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal, Protocol
from uuid import UUID

import structlog
from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from candleviewer.api.drawings_models import MAX_JSON_DEPTH, format_errors
from candleviewer.api.workspaces_models import (
    MAX_LAYOUT_BODY_BYTES,
    MAX_WORKSPACE_BODY_BYTES,
    LayoutIn,
    WorkspaceIn,
)
from candleviewer.api.workspaces_presets import LAYOUT_PRESETS
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.ingestion.ticker_stream import uuid7
from candleviewer.observability.redaction import redact_structure
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.workspaces import (
    LayoutFields,
    LayoutRow,
    PaneFields,
    WorkspaceConflictError,
    WorkspaceFields,
    WorkspaceNotFoundError,
    WorkspaceRepository,
    WorkspaceRow,
    WorkspaceVersionConflictError,
)
from candleviewer.ws.limits import json_depth_exceeds

#: The registered `x-error-codes` this router emits: code -> (status, catalogue title).
_CODES: Final[dict[str, tuple[int, str]]] = {
    "invalid_cursor": (400, "Pagination cursor is malformed or expired"),
    "unauthenticated": (401, "Missing, malformed or expired access token"),
    "forbidden": (403, "Authenticated but lacking the required permission"),
    "not_found": (404, "Resource does not exist or is out of the caller's scope"),
    "conflict": (409, "Concurrent modification or state conflict"),
    "version_conflict": (412, "If-Match / ETag precondition failed"),
    "payload_too_large": (413, "Request body or batch exceeds the operation's size ceiling"),
    "validation_failed": (422, "Request body or parameters failed schema validation"),
    "store_unavailable": (503, "QuestDB / Postgres / Parquet tier unavailable"),
}
_TOKEN: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
_PERMISSIONS: Final = {p.value: p for p in Permission}
CURSOR_TTL_S: Final = 3600
_MAX_CURSOR: Final = 512
_LENGTH: Final = re.compile(r"[0-9]{1,19}")
#: A token no stored `updated_at` can equal: an unparseable `If-Match` is "stale" (D12, D13).
_RETRY_AFTER_S: Final = 5
#: Driver errors that mean "the database is unreachable or timed out". `api` may not import a
#: storage driver (ADR-0003), so they are recognised by class identity, not imported; the
#: repository does not translate them (S3). Integrity/Programming/Data errors are bugs: 500.
_OUTAGE_CLASSES: Final = frozenset(
    {
        "sqlalchemy.exc.OperationalError",
        "sqlalchemy.exc.InterfaceError",
        "sqlalchemy.exc.TimeoutError",  # pool checkout timeout
    }
)
_DBAPI_ERROR: Final = "sqlalchemy.exc.DBAPIError"


#: SQLSTATE classes that mean "the database cannot serve this now, retry": connection (08),
#: transaction rollback incl. deadlock/serialization (40), resources (53), operator
#: intervention incl. statement timeout 57014 (57), system (58); plus lock_not_available 55P03.
#: Data (22), integrity (23) and syntax/access (42) errors are bugs: 500. Anything else, and a
#: missing SQLSTATE, stays 500 so it fails visibly.
_OUTAGE_SQLSTATE_CLASSES: Final = frozenset({"08", "40", "53", "57", "58"})


def _sqlstate(exc: Exception) -> str | None:
    """The SQLSTATE a DBAPI error carries, read like the repository's `map_integrity`: the
    wrapped driver error (`orig`), then its cause; `.sqlstate` (asyncpg) or `.pgcode`."""
    orig = getattr(exc, "orig", None)
    for src in (orig, getattr(orig, "__cause__", None), exc.__cause__):
        for attr in ("sqlstate", "pgcode"):
            code = getattr(src, attr, None)
            if isinstance(code, str) and len(code) == 5:
                return code
    return None


def _is_outage(exc: Exception) -> bool:
    if isinstance(exc, OSError | StorageTierUnavailable):
        return True
    names = {f"{c.__module__}.{c.__qualname__}" for c in type(exc).__mro__}
    if names & _OUTAGE_CLASSES:
        return True
    if _DBAPI_ERROR not in names:
        return False
    if getattr(exc, "connection_invalidated", False) is True:
        return True
    state = _sqlstate(exc)  # a generic DBAPIError: real timeouts and deadlocks arrive this way
    return state is not None and (state[:2] in _OUTAGE_SQLSTATE_CLASSES or state == "55P03")


_NEVER_MATCHES: Final = datetime(1, 1, 1, tzinfo=UTC)
_CONFLICTS: Final = {
    "name_taken": "That name is already in use.",
    "hotkey_slot_taken": "That hotkey is held by another layout.",
    "limit_reached": "The limit has been reached.",
    "last_workspace": "You need at least one workspace.",
    "concurrent_update": "A concurrent change raced this request; retry.",
}
_Kind = Literal["workspace", "layout"]


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _Resolver(Protocol):
    """`SessionAuditPrincipalResolver`: bearer -> `AuditPrincipal`; `None` = no verified session."""

    def resolve(
        self, request: Request
    ) -> AuditPrincipal | Awaitable[AuditPrincipal | None] | None: ...


def _snapshot(p: AuditPrincipal) -> PrincipalSnapshot:
    """Known permission codes only (a wildcard grants nothing: the Owner's "*" is expanded to
    explicit codes at seed time) and the owner flag the session resolver derived."""
    perms = frozenset(_PERMISSIONS[c] for c in p.permissions if c in _PERMISSIONS)
    return PrincipalSnapshot(p.user_id, frozenset({"owner"} if p.is_owner else ()), perms)


class _Problem(Exception):
    """RFC 9457 problem for a registered code; status and title come from `_CODES`."""

    def __init__(self, code: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.title = _CODES[code]
        self.code, self.detail, self.extra = code, detail, extra

    def response(self) -> JSONResponse:
        body = {"type": f"https://candleviewer.local/errors/{self.code}", "title": self.title,
                "status": self.status, "code": self.code, "detail": self.detail}  # fmt: skip
        headers = {"Retry-After": str(_RETRY_AFTER_S)} if self.code == "store_unavailable" else {}
        return JSONResponse(body | self.extra, self.status, headers, "application/problem+json")


class _ProblemRoute(APIRoute):
    """`_Problem` -> its response; a store I/O failure -> 503 `store_unavailable`."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await inner(request)
            except _Problem as p:
                return p.response()
            except Exception as exc:  # re-raised below unless it is a store outage
                if not _is_outage(exc):
                    raise
                # class name only: str(exc) of a SQLAlchemy error embeds bound parameters
                _log().error(
                    "workspaces_store_unavailable",
                    error=type(exc).__name__,
                    sqlstate=_sqlstate(exc),
                )
                return _Problem(
                    "store_unavailable", "The workspace store is unavailable."
                ).response()

        return handler


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.workspaces")


def _rule(field: str, rule: str, message: str) -> dict[str, str]:
    return {"field": field, "rule": rule, "message": message}


def _invalid(errors: list[dict[str, str]]) -> _Problem:
    """422 with at most 20 field errors, passed through the shared redaction rule set."""
    return _Problem("validation_failed", "The request is invalid.",
                    errors=redact_structure(errors[:20]))  # fmt: skip


def _not_found(kind: _Kind) -> _Problem:
    return _Problem("not_found", f"No such {kind}.")


def _stale(kind: _Kind) -> _Problem:
    return _Problem("version_conflict", f"The {kind} was changed by another session; reload.")


def _conflict(exc: WorkspaceConflictError) -> _Problem:
    item = {"rule": exc.rule, "message": _CONFLICTS.get(exc.rule, "State conflict.")}
    if exc.field is not None:
        item = {"field": exc.field} | item
    return _Problem("conflict", item["message"], errors=[item])


def _declared_length(raw: str) -> int | None:
    """`Content-Length` when it is 1..19 ASCII digits, else None (only the streaming cap then)."""
    return int(raw) if _LENGTH.fullmatch(raw) else None


async def _read_capped(request: Request, cap: int) -> bytes:
    """The raw body, refused with 413 past `cap` bytes before it is fully buffered."""
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


def _text(raw: bytes) -> str:
    """UTF-8 text nested at most `MAX_JSON_DEPTH` deep (checked before anything decodes it)."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _invalid([_rule("", "json_invalid", "The body is not UTF-8 JSON.")]) from None
    if json_depth_exceeds(text, MAX_JSON_DEPTH):
        msg = f"JSON nesting is deeper than {MAX_JSON_DEPTH} levels."
        raise _invalid([_rule("", "json_too_deep", msg)])
    return text


def _parse[M: BaseModel](model: type[M], text: str) -> M:
    try:
        return model.model_validate_json(text)
    except ValidationError as exc:
        raise _invalid(format_errors(exc)) from None


def _uuid(name: str, raw: str) -> str:
    """Canonical lowercase uuid; anything else violates the path parameter (422)."""
    try:
        return str(UUID(raw))
    except ValueError:
        raise _invalid([_rule(name, "uuid_parsing", f"{name} must be a UUID.")]) from None


def _if_match(request: Request) -> datetime | None:
    """`If-Match`: the exact `updated_at` token, quoted, `W/`-prefixed or bare; absent -> None
    (last write wins). Anything else, `*` and tag lists included, can never match: 412 unless
    the repository finds the body a no-op first (D13)."""
    lines = request.headers.getlist("if-match")
    if not lines:
        return None
    if len(lines) > 1:  # two header lines: ambiguous, so unparseable (never matches)
        return _NEVER_MATCHES
    value = lines[0].strip().removeprefix("W/")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    if _TOKEN.fullmatch(value) is None:
        return _NEVER_MATCHES
    try:
        return datetime.fromisoformat(value)
    except ValueError:  # well-formed but impossible (month 13, Feb 30): stale like any other junk
        return _NEVER_MATCHES


def encode_cursor(kind: str, scope: str, after: object, iat: int) -> str:
    """Opaque keyset cursor (D22): base64url JSON bound to its listing and issue time."""
    raw = json.dumps({"v": 1, "k": kind, "s": scope, "a": after, "iat": iat})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, kind: str, scope: str, now: int) -> Any:
    """The after key of a cursor issued for this listing less than an hour ago, else 400."""
    bad = _Problem("invalid_cursor", "The cursor is malformed, expired or for another listing.")
    try:
        if len(cursor) > _MAX_CURSOR:
            raise ValueError(cursor)
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(data, dict) or set(data) != {"v", "k", "s", "a", "iat"}:
            raise ValueError(cursor)
    except ValueError:
        raise bad from None
    iat = data["iat"]
    if type(data["v"]) is not int or (data["v"], data["k"], data["s"]) != (1, kind, scope):
        raise bad
    if type(iat) is not int or not 0 <= now - iat <= CURSOR_TTL_S:
        raise bad
    return data["a"]


def _after_workspace(raw: Any) -> tuple[int, str]:
    try:
        order, wid = raw
        if type(order) is not int or not 0 <= order <= 32767:
            raise ValueError(raw)
        return order, str(UUID(str(wid)))
    except (TypeError, ValueError):
        raise _Problem("invalid_cursor", "The cursor is malformed.") from None


def _after_id(raw: Any) -> str:
    try:
        return str(UUID(str(raw)))
    except ValueError:
        raise _Problem("invalid_cursor", "The cursor is malformed.") from None


def _dump_workspace(row: WorkspaceRow) -> dict[str, Any]:
    """`Workspace`: exactly the documented fields (never a spread row); tokens at 6 digits."""
    return {
        "id": row.id, "user_id": row.user_id, "name": row.name, "is_default": row.is_default,
        "icon_token": row.icon_token, "sort_order": row.sort_order,
        "layout_count": row.layout_count, "created_at": _fmt(row.created_at),
        "updated_at": row.token,
    }  # fmt: skip


def _dump_layout(row: LayoutRow) -> dict[str, Any]:
    """`Layout` with its panes (by slot), exactly the documented fields; a named preset serves
    `grid_spec: null`."""
    panes = [
        {
            "slot_index": p.slot_index, "pane_kind": p.pane_kind, "symbol": p.symbol,
            "interval_code": p.interval_code, "chart_template_id": p.chart_template_id,
            "indicator_preset_ids": list(p.indicator_preset_ids), "pane_config": p.pane_config,
            "scale_mode": p.scale_mode,
        }
        for p in row.panes
    ]  # fmt: skip
    return {
        "id": row.id, "workspace_id": row.workspace_id, "name": row.name,
        "grid_preset": row.grid_preset, "grid_spec": row.grid_spec,
        "crosshair_sync": row.crosshair_sync, "level_sync": row.level_sync,
        "symbol_sync": row.symbol_sync, "hotkey_slot": row.hotkey_slot,
        "is_default": row.is_default, "panes": panes, "created_at": _fmt(row.created_at),
        "updated_at": row.token,
    }  # fmt: skip


def _layout_fields(body: LayoutIn) -> LayoutFields:
    values = body.db_values()
    panes = tuple(PaneFields(**pane) for pane in values.pop("panes"))
    return LayoutFields(**values, panes=panes)


def _dump_preset(index: int) -> dict[str, Any]:
    """`LayoutPreset`: the catalogue entry with a complete `LayoutInput` (defaults materialised)."""
    entry = LAYOUT_PRESETS[index]
    layout = entry.layout.db_values()
    layout["panes"] = [p | {"indicator_preset_ids": list(p["indicator_preset_ids"])}
                       for p in layout["panes"]]  # fmt: skip
    return {
        "id": str(entry.id), "name": entry.name, "description": entry.description,
        "is_builtin": entry.is_builtin, "pane_count": entry.pane_count, "layout": layout,
    }  # fmt: skip


def _fmt(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _respond(body: dict[str, Any], token: str, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status, headers={"ETag": f'"{token}"'})


class _ListQuery(BaseModel):  # `Cursor` + `Limit` parameters
    model_config = ConfigDict(frozen=True, extra="ignore")  # unknown params ignored, like FastAPI
    cursor: str | None = None
    limit: Annotated[int, Field(ge=1, le=500)] = 100


def _query(request: Request) -> _ListQuery:
    try:
        return _ListQuery.model_validate(dict(request.query_params))
    except ValidationError as exc:
        raise _invalid(format_errors(exc)) from None


def _new_id() -> UUID:
    return uuid7(time.time_ns() // 1_000_000)


def _workspace_fields(body: WorkspaceIn) -> WorkspaceFields:
    return WorkspaceFields(**body.db_values())


def make_workspaces_router(
    repo_provider: Callable[[], WorkspaceRepository | None],
    principal_resolver: _Resolver | None,
    audit: _Emitter,
    *,
    clock: Callable[[], float] = time.time,
    new_id: Callable[[], UUID] = _new_id,
) -> APIRouter:
    """`audit` is mandatory (a denial must leave its `rbac.denied` record). No resolver (no
    identity store: nothing can verify a session) fails closed with 401; no store with 503."""
    if audit is None:
        raise TypeError("make_workspaces_router: an audit emitter is required")
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

    def store() -> WorkspaceRepository:
        repo = repo_provider()
        if repo is None:
            raise _Problem("store_unavailable", "The workspace store is unavailable.")
        return repo

    async def not_found(p: AuditPrincipal, kind: _Kind, oid: str, mode: str) -> _Problem:
        """Same 404 for a missing, deleted or foreign id; a foreign live id is audited once."""
        owner = str(p.user_id)
        if await store().exists_for_other_owner(owner, kind, oid):
            await audit.emit(
                "rbac.denied", actor_label=owner, actor_user_id=p.user_id, actor_ip=p.ip,
                session_id=p.session_id, request_id=p.request_id, object_kind=kind,
                object_id=oid, outcome=AuditOutcome.DENIED, severity=Severity.WARNING,
                reason=f"not_owner:workspaces:{mode}:self",
            )  # fmt: skip
        return _not_found(kind)

    @router.get("/workspaces")
    async def list_workspaces(request: Request) -> Response:
        owner = str((await caller(request, Permission.WORKSPACES_READ)).user_id)
        q, now = _query(request), int(clock())
        after = (
            None
            if q.cursor is None
            else _after_workspace(decode_cursor(q.cursor, "ws", owner, now))
        )
        rows = await store().list_workspaces(owner, after=after, limit=q.limit + 1)
        items, more = rows[: q.limit], len(rows) > q.limit
        nxt = None
        if more:
            nxt = encode_cursor("ws", owner, [items[-1].sort_order, items[-1].id], now)
        meta = {"next_cursor": nxt, "has_more": more, "count": len(items)}
        return JSONResponse({"items": [_dump_workspace(r) for r in items], "meta": meta})

    @router.get("/workspaces/{workspaceId}")
    async def get_workspace(
        request: Request, workspace_id: Annotated[str, Path(alias="workspaceId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_READ)
        owner, wid = str(principal.user_id), _uuid("workspaceId", workspace_id)
        found = await store().get_workspace_detail(owner, wid)
        if found is None:
            raise await not_found(principal, "workspace", wid, "read")
        body = _dump_workspace(found.workspace) | {
            "layouts": [_dump_layout(r) for r in sorted(found.layouts, key=lambda r: r.id)]
        }
        return JSONResponse(body)  # no ETag: the body mixes tokens (D12)

    @router.post("/workspaces")
    async def create_workspace(request: Request) -> Response:
        owner = str((await caller(request, Permission.WORKSPACES_WRITE)).user_id)
        body = _parse(WorkspaceIn, _text(await _read_capped(request, MAX_WORKSPACE_BODY_BYTES)))
        _idempotency_key(request)  # replay arrives with the shared cache (ruling Q5)
        try:
            row = await store().create_workspace(owner, str(new_id()), _workspace_fields(body))
        except WorkspaceConflictError as exc:
            raise _conflict(exc) from None
        _log().info("workspace_created", user_id=owner, workspace_id=row.id)
        return _respond(_dump_workspace(row), row.token, 201)

    @router.put("/workspaces/{workspaceId}")
    async def update_workspace(
        request: Request, workspace_id: Annotated[str, Path(alias="workspaceId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        owner = str(principal.user_id)
        raw = await _read_capped(request, MAX_WORKSPACE_BODY_BYTES)
        wid = _uuid("workspaceId", workspace_id)
        body = _parse(WorkspaceIn, _text(raw))
        try:
            done = await store().update_workspace(
                owner,
                wid,
                _workspace_fields(body),
                if_match=_if_match(request),
            )
        except WorkspaceNotFoundError:
            raise await not_found(principal, "workspace", wid, "write") from None
        except WorkspaceVersionConflictError:
            raise _stale("workspace") from None
        except WorkspaceConflictError as exc:
            raise _conflict(exc) from None
        _log().info("workspace_updated", user_id=owner, workspace_id=wid, changed=done.changed)
        return _respond(_dump_workspace(done.row), done.row.token)

    @router.delete("/workspaces/{workspaceId}")
    async def delete_workspace(
        request: Request, workspace_id: Annotated[str, Path(alias="workspaceId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        owner, wid = str(principal.user_id), _uuid("workspaceId", workspace_id)
        _idempotency_key(request)
        try:
            await store().soft_delete_workspace(owner, wid)
        except WorkspaceNotFoundError:
            raise await not_found(principal, "workspace", wid, "write") from None
        except WorkspaceConflictError as exc:
            raise _conflict(exc) from None
        _log().info("workspace_deleted", user_id=owner, workspace_id=wid)
        return Response(status_code=204)

    async def miss(p: AuditPrincipal, wid: str, lid: str | None, mode: str) -> _Problem:
        """The same 404 whatever is wrong with the path; the first live foreign object on it
        (layout, then workspace) is audited once. A layout under another workspace of the
        caller's own is not a foreign hit (D18)."""
        owner = str(p.user_id)
        found: tuple[_Kind, str] | None = None
        if lid is not None and await store().exists_for_other_owner(owner, "layout", lid):
            found = ("layout", lid)
        elif await store().exists_for_other_owner(owner, "workspace", wid):
            found = ("workspace", wid)
        if found is not None:
            await audit.emit(
                "rbac.denied", actor_label=owner, actor_user_id=p.user_id, actor_ip=p.ip,
                session_id=p.session_id, request_id=p.request_id, object_kind=found[0],
                object_id=found[1], outcome=AuditOutcome.DENIED, severity=Severity.WARNING,
                reason=f"not_owner:workspaces:{mode}:self",
            )  # fmt: skip
        return _not_found("workspace" if lid is None else "layout")

    @router.get("/layout-presets")
    async def list_layout_presets(request: Request) -> Response:
        await caller(request, Permission.WORKSPACES_READ)
        q, now = _query(request), int(clock())
        start = 0
        if q.cursor is not None:
            after = decode_cursor(q.cursor, "pre", "-", now)
            if type(after) is not int or not 0 <= after < len(LAYOUT_PRESETS):
                raise _Problem("invalid_cursor", "The cursor is malformed.")
            start = after + 1
        page = range(start, min(start + q.limit, len(LAYOUT_PRESETS)))
        more = page.stop < len(LAYOUT_PRESETS)
        nxt = encode_cursor("pre", "-", page[-1], now) if more else None
        meta = {"next_cursor": nxt, "has_more": more, "count": len(page)}
        return JSONResponse({"items": [_dump_preset(i) for i in page], "meta": meta})

    @router.get("/workspaces/{workspaceId}/layouts")
    async def list_layouts(
        request: Request, workspace_id: Annotated[str, Path(alias="workspaceId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_READ)
        owner, wid = str(principal.user_id), _uuid("workspaceId", workspace_id)
        q, now = _query(request), int(clock())
        scope = f"{owner}:{wid}"
        after = None
        if q.cursor is not None:
            after = _after_id(decode_cursor(q.cursor, "lay", scope, now))
        rows = await store().list_layouts(owner, wid, after_id=after, limit=q.limit + 1)
        if rows is None:
            raise await miss(principal, wid, None, "read")
        items, more = rows[: q.limit], len(rows) > q.limit
        nxt = encode_cursor("lay", scope, items[-1].id, now) if more else None
        meta = {"next_cursor": nxt, "has_more": more, "count": len(items)}
        return JSONResponse({"items": [_dump_layout(r) for r in items], "meta": meta})

    @router.post("/workspaces/{workspaceId}/layouts")
    async def create_layout(
        request: Request, workspace_id: Annotated[str, Path(alias="workspaceId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        owner = str(principal.user_id)
        raw = await _read_capped(request, MAX_LAYOUT_BODY_BYTES)
        wid = _uuid("workspaceId", workspace_id)
        body = _parse(LayoutIn, _text(raw))
        _idempotency_key(request)  # replay arrives with the shared cache (ruling Q5)
        try:
            row = await store().create_layout(owner, wid, str(new_id()), _layout_fields(body))
        except WorkspaceNotFoundError:
            raise await miss(principal, wid, None, "write") from None
        except WorkspaceConflictError as exc:
            raise _conflict(exc) from None
        _log().info("layout_created", user_id=owner, workspace_id=wid, layout_id=row.id,
                    pane_count=len(row.panes))  # fmt: skip
        return _respond(_dump_layout(row), row.token, 201)

    @router.get("/workspaces/{workspaceId}/layouts/{layoutId}")
    async def get_layout(
        request: Request,
        workspace_id: Annotated[str, Path(alias="workspaceId")],
        layout_id: Annotated[str, Path(alias="layoutId")],
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_READ)
        owner, wid = str(principal.user_id), _uuid("workspaceId", workspace_id)
        lid = _uuid("layoutId", layout_id)
        row = await store().get_layout(owner, wid, lid)
        if row is None:
            raise await miss(principal, wid, lid, "read")
        return _respond(_dump_layout(row), row.token)

    @router.put("/workspaces/{workspaceId}/layouts/{layoutId}")
    async def update_layout(
        request: Request,
        workspace_id: Annotated[str, Path(alias="workspaceId")],
        layout_id: Annotated[str, Path(alias="layoutId")],
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        owner = str(principal.user_id)
        raw = await _read_capped(request, MAX_LAYOUT_BODY_BYTES)
        wid, lid = _uuid("workspaceId", workspace_id), _uuid("layoutId", layout_id)
        body = _parse(LayoutIn, _text(raw))
        if_match = _if_match(request)
        try:
            done = await store().replace_layout(
                owner, wid, lid, _layout_fields(body), if_match=if_match
            )
        except WorkspaceNotFoundError:
            raise await miss(principal, wid, lid, "write") from None
        except WorkspaceVersionConflictError:
            raise _stale("layout") from None
        except WorkspaceConflictError as exc:
            raise _conflict(exc) from None
        _log().info("layout_updated", user_id=owner, workspace_id=wid, layout_id=lid,
                    pane_count=len(done.row.panes), changed=done.changed)  # fmt: skip
        return _respond(_dump_layout(done.row), done.row.token)

    @router.delete("/workspaces/{workspaceId}/layouts/{layoutId}")
    async def delete_layout(
        request: Request,
        workspace_id: Annotated[str, Path(alias="workspaceId")],
        layout_id: Annotated[str, Path(alias="layoutId")],
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        owner, wid = str(principal.user_id), _uuid("workspaceId", workspace_id)
        lid = _uuid("layoutId", layout_id)
        _idempotency_key(request)
        try:
            await store().soft_delete_layout(owner, wid, lid)
        except WorkspaceNotFoundError:
            raise await miss(principal, wid, lid, "write") from None
        _log().info("layout_deleted", user_id=owner, workspace_id=wid, layout_id=lid)
        return Response(status_code=204)

    return router


def _idempotency_key(request: Request) -> None:
    """Accepted, never required; a malformed value violates the parameter (422). Replay needs the
    shared cache (ruling Q5) and is a later slice, so a valid key is currently ignored."""
    raw = request.headers.get("idempotency-key")
    if raw is not None:
        _uuid("Idempotency-Key", raw)


__all__ = ["CURSOR_TTL_S", "decode_cursor", "encode_cursor", "make_workspaces_router"]

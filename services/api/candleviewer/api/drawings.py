"""`/drawings` routes (E14-T01, #357): contract `22-api-openapi.yaml`, decision record on #357.

Callers come from the session (`SessionAuditPrincipalResolver`, as `/admin/audit`); RBAC (C-12.4)
runs per request through `auth.scopes.enforce()`, each denial audited as `rbac.denied` (SR-062):
`workspaces:read` to list, `workspaces:write` to write. `scope: self`: every statement is filtered
by the caller; a missing, deleted or foreign drawing is the same 404, and a foreign live id on
PUT/DELETE is also audited (`object_kind="drawing"`). A batch update/delete whose target is not the
caller's, foreign and missing alike, is the same 409 `target_unavailable` as the caller's own
soft-deleted target but is audited too: telling them apart would need a second lookup and a timing
difference. Drawing writes are not audited (not a C-2.9 action). Bodies are read raw so byte, depth
and batch-size caps run before pydantic; no content is logged. POST and batch replay an
`Idempotency-Key` from a bounded per-user cache.

A denial whose `rbac.denied` record cannot be made durable is answered 503 `store_unavailable`
with no state change, never 403/404/409; an allowed request on the caller's own rows never
reaches the audit writer, while a foreign-id probe does (DR18).
"""

import base64
import hashlib
import inspect
import json
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final, Protocol
from uuid import UUID

import structlog
from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from candleviewer.api.drawings_models import (
    MAX_BATCH_BODY_BYTES,
    MAX_BATCH_OPS,
    MAX_JSON_DEPTH,
    MAX_SINGLE_BODY_BYTES,
    BatchCreateIn,
    BatchDeleteIn,
    BatchIn,
    BatchUpdateIn,
    DrawingIn,
    format_errors,
)
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.ingestion.ticker_stream import uuid7
from candleviewer.observability.metrics import BoundedMetric
from candleviewer.observability.redaction import redact_structure
from candleviewer.storage.repositories.drawings import (
    BatchOp,
    BatchOpFailed,
    CreateOp,
    DeleteOp,
    DrawingFields,
    DrawingIdUnavailableError,
    DrawingNotFoundError,
    DrawingRepository,
    DrawingRow,
    DrawingVersionConflictError,
    UpdateOp,
    format_token,
)
from candleviewer.ws.limits import json_depth_exceeds

#: The registered `x-error-codes` this router emits: code -> (status, catalogue title).
_CODES: Final[dict[str, tuple[int, str]]] = {
    "invalid_cursor": (400, "Pagination cursor is malformed or expired"),
    "unauthenticated": (401, "Missing, malformed or expired access token"),
    "forbidden": (403, "Authenticated but lacking the required permission"),
    "not_found": (404, "Resource does not exist or is out of the caller's scope"),
    "conflict": (409, "Concurrent modification or state conflict"),
    "idempotency_key_reuse": (409, "Idempotency-Key reused with a different request payload"),
    "version_conflict": (412, "If-Match / ETag precondition failed"),
    "payload_too_large": (413, "Request body or batch exceeds the operation's size ceiling"),
    "validation_failed": (422, "Request body or parameters failed schema validation"),
    "store_unavailable": (503, "QuestDB / Postgres / Parquet tier unavailable"),
}
CURSOR_TTL_S: Final = 3600
_MAX_CURSOR: Final = 512
_TOKEN: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
_PERMISSIONS: Final = {p.value: p for p in Permission}
_LENGTH: Final = re.compile(r"[0-9]{1,19}")
_BATCH_RULES: Final = {
    "target_unavailable": "The target drawing is missing, deleted or not yours.",
    "version_conflict": "The drawing was changed by another session; reload and retry.",
    "id_unavailable": "This id is already used; create the drawing under a new id.",
}


IDEMPOTENCY_MAX_ENTRIES: Final = 4096
IDEMPOTENCY_MAX_BYTES: Final = 32 * 1024 * 1024
IDEMPOTENCY_USER_MAX_ENTRIES: Final = 256
IDEMPOTENCY_USER_MAX_BYTES: Final = 4 * 1024 * 1024
IDEMPOTENCY_MAX_ENTRY_BYTES: Final = 256 * 1024
IDEMPOTENCY_TTL_S: Final = 86_400
#: Bytes charged per entry on top of len(body) + len(key): digest, ETag, entry tuple, LRU slots.
IDEMPOTENCY_ENTRY_OVERHEAD: Final = 512


@dataclass(frozen=True, slots=True)
class StoredResponse:
    digest: str  # sha256 of the raw request body
    status: int
    body: bytes
    etag: str | None


class IdempotencyCache:
    """Best-effort `Idempotency-Key` replay (#357 decision record 8: a bounded per-user LRU) of 2xx
    responses, keyed (user_id, "operationId:key"). Losing an entry only re-runs the request.

    Bounds (C-2.18): 4096 entries / 32 MiB in total and 256 entries / 4 MiB per user, an entry
    costing len(body) + len(key) + IDEMPOTENCY_ENTRY_OVERHEAD; a body over 256 KiB is never stored.
    A user over its caps loses its own oldest entry, so no user can evict another while the global
    caps hold; over the global caps the least recently used entry goes. Entries live
    IDEMPOTENCY_TTL_S on the injected monotonic clock; an expired hit is a miss and is dropped.
    Every operation is O(1) amortised (no scans).
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_entry_bytes: int = IDEMPOTENCY_MAX_ENTRY_BYTES,
    ) -> None:
        self._clock, self._max_entry = clock, max_entry_bytes
        self._lru: OrderedDict[tuple[str, str], tuple[StoredResponse, int, float]] = OrderedDict()
        self._users: dict[str, OrderedDict[str, None]] = {}  # per user, oldest first
        self._user_bytes: dict[str, int] = {}
        self.stored_bytes = 0

    def __len__(self) -> int:
        return len(self._lru)

    def get(self, user: str, key: str) -> StoredResponse | None:
        hit = self._lru.get((user, key))
        if hit is None:
            return None
        if self._clock() >= hit[2]:  # expired: a miss
            self._drop(user, key)
            return None
        self._lru.move_to_end((user, key))
        self._users[user].move_to_end(key)
        return hit[0]

    def put(self, user: str, key: str, value: StoredResponse) -> None:
        if len(value.body) > self._max_entry:
            return  # never stored: a retry simply runs again
        if (user, key) in self._lru:
            self._drop(user, key)
        size = len(value.body) + len(key) + IDEMPOTENCY_ENTRY_OVERHEAD
        self._lru[(user, key)] = (value, size, self._clock() + IDEMPOTENCY_TTL_S)
        self._users.setdefault(user, OrderedDict())[key] = None
        self._user_bytes[user] = self._user_bytes.get(user, 0) + size
        self.stored_bytes += size
        while user in self._users and (
            len(self._users[user]) > IDEMPOTENCY_USER_MAX_ENTRIES
            or self._user_bytes[user] > IDEMPOTENCY_USER_MAX_BYTES
        ):
            self._drop(user, next(iter(self._users[user])))
        while len(self._lru) > IDEMPOTENCY_MAX_ENTRIES or self.stored_bytes > IDEMPOTENCY_MAX_BYTES:
            self._drop(*next(iter(self._lru)))

    def _drop(self, user: str, key: str) -> None:
        size = self._lru.pop((user, key))[1]
        mine = self._users[user]
        del mine[key]
        self.stored_bytes -= size
        self._user_bytes[user] -= size
        if not mine:
            del self._users[user], self._user_bytes[user]


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class DrawingsMetricsLike(Protocol):
    """C4's `DrawingsMetrics` (`app.state.drawings_metrics`); the router records these two."""

    @property
    def batch_ops(self) -> BoundedMetric: ...  # cv_drawings_batch_ops (histogram)

    @property
    def conflicts(self) -> BoundedMetric: ...  # cv_drawings_conflicts_total{rule}


class _Resolver(Protocol):
    """`SessionAuditPrincipalResolver`: bearer -> `AuditPrincipal`; `None` = no verified session."""

    def resolve(
        self, request: Request
    ) -> AuditPrincipal | Awaitable[AuditPrincipal | None] | None: ...


def _snapshot(p: AuditPrincipal) -> PrincipalSnapshot:
    """The decision point's view of the caller: known permission codes only (anything else,
    a wildcard included, grants nothing) and the owner flag the session resolver derived."""
    # "*" grants nothing here: the Owner's "*" is expanded to explicit codes at seed time
    # (migration 0001 :348, `db/seed.py:90`), so a real owner always carries the codes.
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
        return JSONResponse(body | self.extra, self.status, media_type="application/problem+json")


class _ProblemRoute(APIRoute):
    """`_Problem` -> its response; a store I/O failure, or an audit write the sink refuses
    (`AuditUnavailable`, `AuditWriterStopped`: the request fails closed) -> 503 `store_unavailable`.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await inner(request)
            except _Problem as p:
                return p.response()
            except (AuditUnavailable, AuditWriterStopped) as exc:  # fails closed: logged apart
                _log().error("drawings_audit_unavailable", error=type(exc).__name__)
            except Exception as exc:
                if not is_storage_outage(exc):
                    raise
                _log().error("drawings_store_unavailable", error=type(exc).__name__)
            return _Problem("store_unavailable", "The drawings store is unavailable.").response()

        return handler


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.drawings")


def _rule(field: str, rule: str, message: str) -> dict[str, str]:
    return {"field": field, "rule": rule, "message": message}


def _invalid(errors: list[dict[str, str]]) -> _Problem:
    """422 with at most 20 field errors, passed through the shared redaction rule set."""
    return _Problem("validation_failed", "The request is invalid.",
                    errors=redact_structure(errors[:20]))  # fmt: skip


def _not_found(what: str = "drawing") -> _Problem:
    return _Problem("not_found", f"No such {what}.")


def _stale() -> _Problem:
    return _Problem("version_conflict", "The drawing was changed by another session; reload.")


def _declared_length(raw: str) -> int | None:
    """`Content-Length` when it is 1..19 ASCII digits, else None (no usable length: only the
    streaming cap applies). `str.isdigit()` accepts "²" and `int()` refuses > 4300 digits."""
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


def _count_ops(text: str) -> None:
    """413 past `MAX_BATCH_OPS` operations, counted before any per-operation validation."""
    try:
        decoded = json.loads(text)
    except ValueError:
        return  # not JSON: the model reports it as a 422
    ops = decoded.get("operations") if isinstance(decoded, dict) else None
    if isinstance(ops, list) and len(ops) > MAX_BATCH_OPS:
        msg = f"Batch carries {len(ops)} operations; the maximum is {MAX_BATCH_OPS}."
        raise _Problem("payload_too_large", msg)


def _op(op: BatchCreateIn | BatchUpdateIn | BatchDeleteIn, new_id: Callable[[], UUID]) -> BatchOp:
    if isinstance(op, BatchCreateIn):
        return CreateOp(str(op.id or new_id()), _fields(op.drawing))
    if isinstance(op, BatchUpdateIn):
        return UpdateOp(str(op.id), op.if_match, _fields(op.drawing))
    return DeleteOp(str(op.id), op.if_match)


def _drawing_id(raw: str) -> str:
    """Canonical lowercase uuid; anything else violates the `DrawingId` parameter (422)."""
    try:
        return str(UUID(raw))
    except ValueError:
        raise _invalid([_rule("drawingId", "uuid_parsing", "drawingId must be a UUID.")]) from None


def _if_match(raw: str | None) -> datetime | None:
    """`If-Match`: the exact `updated_at` token (as the batch `if_match`), quoted, `W/`-prefixed
    or bare; absent -> None (last write wins). Another spelling of that instant is 412."""
    if raw is None:
        return None
    value = raw.strip().removeprefix("W/")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    try:
        if _TOKEN.fullmatch(value) is None:
            raise ValueError(value)
        return datetime.fromisoformat(value)
    except ValueError:
        raise _stale() from None


def encode_cursor(symbol: str, layout_id: str | None, after_id: str, iat: int) -> str:
    """Opaque keyset cursor: base64url JSON bound to its scope and issue time (unsigned)."""
    raw = json.dumps({"v": 1, "s": symbol, "l": layout_id, "a": after_id, "iat": iat})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, symbol: str, layout_id: str | None, now: int) -> str:
    """The `after_id` of a cursor issued for this scope less than an hour ago, else 400."""
    bad = _Problem("invalid_cursor", "The cursor is malformed, expired or for another query.")
    try:
        if len(cursor) > _MAX_CURSOR:
            raise ValueError(cursor)
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(data, dict) or set(data) != {"v", "s", "l", "a", "iat"}:
            raise ValueError(cursor)
        iat, after = data["iat"], str(UUID(str(data["a"])))
    except ValueError:
        raise bad from None
    if (data["v"], data["s"], data["l"]) != (1, symbol, layout_id) or type(data["v"]) is not int:
        raise bad
    if type(iat) is not int or not 0 <= now - iat <= CURSOR_TTL_S:
        raise bad
    return after


def _dump(row: DrawingRow) -> dict[str, Any]:
    """`Drawing`: every property present; both timestamps in the 6-digit token format."""
    return {
        "id": row.id, "owner_user_id": row.owner_user_id, "symbol": row.symbol,
        "tool": row.tool, "layout_id": row.layout_id, "geometry": row.geometry,
        "style": row.style, "label": row.label, "locked": row.locked, "visible": row.visible,
        "z_index": row.z_index, "created_at": format_token(row.created_at),
        "updated_at": row.token,
    }  # fmt: skip


def _respond(row: DrawingRow, status: int = 200) -> JSONResponse:
    return JSONResponse(_dump(row), status, headers={"ETag": f'"{row.token}"'})


def _fields(body: DrawingIn) -> DrawingFields:
    values = body.db_values()
    layout = values["layout_id"]
    return DrawingFields(**(values | {"layout_id": None if layout is None else str(layout)}))


async def _layout_owned(owner: str, layout_id: UUID) -> bool:
    # TODO(#402): E15-T01 creates `layouts`; replace with the owner-scoped live-layout lookup.
    return False


class _ListQuery(BaseModel):  # `listDrawings` query
    model_config = ConfigDict(frozen=True, extra="ignore")  # unknown params ignored, like FastAPI
    symbol: Annotated[str, Field(pattern=r"^[A-Z0-9]{2,16}USDT$")]  # <= 20: the DB domain
    layout_id: UUID | None = None
    cursor: str | None = None
    limit: Annotated[int, Field(ge=1, le=500)] = 100


def _new_id() -> UUID:
    return uuid7(time.time_ns() // 1_000_000)


def make_drawings_router(
    repo_provider: Callable[[], DrawingRepository | None],
    principal_resolver: _Resolver | None,
    audit: _Emitter,
    *,
    clock: Callable[[], float] = time.time,
    new_id: Callable[[], UUID] = _new_id,
    metrics: DrawingsMetricsLike | None = None,
    idempotency: IdempotencyCache | None = None,
) -> APIRouter:
    """`audit` is mandatory (a denial must leave its `rbac.denied` record). No resolver (no
    identity store: nothing can verify a session) fails closed with 401; no store with 503.
    `metrics` (C4) records batch sizes and conflicts by rule; `None` records nothing."""
    if audit is None:
        raise TypeError("make_drawings_router: an audit emitter is required")
    router = APIRouter(tags=["workspaces"], route_class=_ProblemRoute)
    cache = IdempotencyCache() if idempotency is None else idempotency

    def conflict(rule: str) -> None:
        if metrics is not None:
            metrics.conflicts.labels(rule).inc()

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

    def store() -> DrawingRepository:
        repo = repo_provider()
        if repo is None:
            raise _Problem("store_unavailable", "The drawings store is unavailable.")
        return repo

    async def audit_not_owner(p: AuditPrincipal, did: str) -> None:
        """`rbac.denied` for a write aimed at a drawing id that is not the caller's (SR-062)."""
        await audit.emit(
            "rbac.denied", actor_label=str(p.user_id), actor_user_id=p.user_id, actor_ip=p.ip,
            session_id=p.session_id, request_id=p.request_id, object_kind="drawing",
            object_id=did, outcome=AuditOutcome.DENIED, severity=Severity.WARNING,
            reason="not_owner:workspaces:write:self",
        )  # fmt: skip

    async def not_found(p: AuditPrincipal, did: str) -> _Problem:
        """Same 404 for a missing, deleted or foreign id; a foreign live id is audited."""
        if await store().exists_for_other_owner(str(p.user_id), did):
            await audit_not_owner(p, did)
        return _not_found()

    def idempotency_key(request: Request, operation: str) -> str | None:
        raw = request.headers.get("idempotency-key")
        if raw is None:
            return None
        try:
            return f"{operation}:{UUID(raw)}"
        except ValueError:
            msg = "Idempotency-Key must be a UUID."
            raise _invalid([_rule("Idempotency-Key", "uuid_parsing", msg)]) from None

    def replay(owner: str, key: str | None, digest: str) -> Response | None:
        """The stored 2xx for this key and body; the same key with another body is a 409."""
        hit = None if key is None else cache.get(owner, key)
        if hit is None:
            return None
        if hit.digest != digest:
            conflict("idempotency_key_reuse")
            raise _Problem("idempotency_key_reuse", "The key was first used with another body.")
        headers = {"Idempotency-Replayed": "true"} | ({"ETag": hit.etag} if hit.etag else {})
        return Response(hit.body, hit.status, headers, media_type="application/json")

    def remember(owner: str, key: str | None, digest: str, out: JSONResponse) -> JSONResponse:
        if key is not None:
            stored = StoredResponse(
                digest, out.status_code, bytes(out.body), out.headers.get("etag")
            )
            cache.put(owner, key, stored)
        return out

    async def no_layouts(owner: str, refs: list[tuple[str, UUID | None]]) -> None:
        errs = [
            _rule(field, "layout_not_found", "No such layout.")
            for field, layout in refs
            if layout is not None and not await _layout_owned(owner, layout)
        ]
        if errs:
            raise _invalid(errs)

    @router.get("/drawings")
    async def list_drawings(request: Request) -> Response:
        owner = str((await caller(request, Permission.WORKSPACES_READ)).user_id)
        try:
            q = _ListQuery.model_validate(dict(request.query_params))
        except ValidationError as exc:
            raise _invalid(format_errors(exc)) from None
        if q.layout_id is not None and not await _layout_owned(owner, q.layout_id):
            raise _not_found("layout")
        layout = None if q.layout_id is None else str(q.layout_id)
        now = int(clock())
        after = None if q.cursor is None else decode_cursor(q.cursor, q.symbol, layout, now)
        rows = await store().list_page(
            owner, symbol=q.symbol, layout_id=layout, after_id=after, limit=q.limit + 1
        )
        items, more = rows[: q.limit], len(rows) > q.limit
        nxt = encode_cursor(q.symbol, layout, items[-1].id, now) if more else None
        meta = {"next_cursor": nxt, "has_more": more, "count": len(items)}
        return JSONResponse({"items": [_dump(r) for r in items], "meta": meta})

    @router.post("/drawings")
    async def create_drawing(request: Request) -> Response:
        owner = str((await caller(request, Permission.WORKSPACES_WRITE)).user_id)
        key = idempotency_key(request, "createDrawing")
        raw = await _read_capped(request, MAX_SINGLE_BODY_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if (hit := replay(owner, key, digest)) is not None:
            return hit
        body = _parse(DrawingIn, _text(raw))
        await no_layouts(owner, [("layout_id", body.layout_id)])
        try:
            row = await store().create(owner, str(new_id()), _fields(body))
        except DrawingIdUnavailableError:
            conflict("id_unavailable")
            raise _Problem("conflict", "Id collision; retry the request.") from None
        _log().info("drawing_created", user_id=owner, symbol=row.symbol, op_count=1)
        return remember(owner, key, digest, _respond(row, 201))

    @router.put("/drawings/{drawingId}")
    async def update_drawing(
        request: Request, drawing_id: Annotated[str, Path(alias="drawingId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        owner, did = str(principal.user_id), _drawing_id(drawing_id)
        body = _parse(DrawingIn, _text(await _read_capped(request, MAX_SINGLE_BODY_BYTES)))
        if_match = _if_match(request.headers.get("if-match"))
        await no_layouts(owner, [("layout_id", body.layout_id)])
        row = await store().get(owner, did)
        if row is None:
            raise await not_found(principal, did)
        if if_match is not None and if_match != row.updated_at:
            conflict("version_conflict")
            raise _stale()  # the store re-checks atomically
        moved = [f for f in ("symbol", "tool") if getattr(body, f) != getattr(row, f)]
        if moved:
            raise _invalid([_rule(f, "immutable_field", f"{f} cannot be changed") for f in moved])
        try:
            new = await store().update(owner, did, _fields(body), if_match=if_match)
        except DrawingVersionConflictError:
            conflict("version_conflict")
            raise _stale() from None
        except DrawingNotFoundError:
            raise _not_found() from None
        _log().info("drawing_updated", user_id=owner, symbol=new.symbol, op_count=1)
        return _respond(new)

    @router.delete("/drawings/{drawingId}")
    async def delete_drawing(
        request: Request, drawing_id: Annotated[str, Path(alias="drawingId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        owner, did = str(principal.user_id), _drawing_id(drawing_id)
        if not await store().soft_delete(owner, did):
            raise await not_found(principal, did)
        _log().info("drawing_deleted", user_id=owner, op_count=1)
        return Response(status_code=204)

    @router.post("/drawings/batch")
    async def batch_drawings(request: Request) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        owner = str(principal.user_id)
        key = idempotency_key(request, "batchUpsertDrawings")
        raw = await _read_capped(request, MAX_BATCH_BODY_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if (hit := replay(owner, key, digest)) is not None:
            return hit
        text = _text(raw)
        _count_ops(text)
        body = _parse(BatchIn, text)
        await no_layouts(owner, [
            (f"operations.{i}.drawing.layout_id", op.drawing.layout_id)
            for i, op in enumerate(body.operations) if not isinstance(op, BatchDeleteIn)
        ])  # fmt: skip
        ops = [_op(op, new_id) for op in body.operations]
        if metrics is not None:
            metrics.batch_ops.child().observe(len(ops))
        failed: tuple[int, str] | None = None  # (index, rule): the exception would pin this frame
        try:
            res = await store().apply_batch(owner, ops)
        except BatchOpFailed as exc:
            failed = (exc.index, exc.rule)  # answered below, outside the `except`: nothing chains
        if failed is not None:
            index, internal = failed
            field = f"operations.{index}"
            if internal == "immutable_field":  # as on PUT; checked under the row lock (C2)
                msg = "symbol and tool cannot change"
                raise _invalid([_rule(f"{field}.drawing", internal, msg)])
            not_owned = internal == "target_not_owned"  # foreign or missing: not told apart
            rule = "target_unavailable" if not_owned else internal  # the wire rule and label
            conflict(rule)  # counted and logged before the audit write, as `enforce()` (SR-125)
            _log().info("drawings_batch_conflict", user_id=owner, op_count=len(ops), rule=rule)
            if not_owned:  # `rbac.denied` first; a refused audit write fails the request closed
                await audit_not_owner(principal, ops[index].id)
            msg = _BATCH_RULES.get(rule, "This operation cannot be applied.")
            errs = [_rule(field, rule, msg)]
            raise _Problem("conflict", "The batch was rolled back.", errors=errs)
        _log().info("drawings_batch_applied", user_id=owner, op_count=len(ops))
        created, updated = [_dump(r) for r in res.created], [_dump(r) for r in res.updated]
        out = {"created": created, "updated": updated, "deleted": list(res.deleted)}
        return remember(owner, key, digest, JSONResponse(out))

    return router


__all__ = [
    "CURSOR_TTL_S", "IDEMPOTENCY_ENTRY_OVERHEAD", "IDEMPOTENCY_MAX_BYTES",
    "IDEMPOTENCY_MAX_ENTRIES", "IDEMPOTENCY_MAX_ENTRY_BYTES", "IDEMPOTENCY_TTL_S",
    "IDEMPOTENCY_USER_MAX_BYTES", "IDEMPOTENCY_USER_MAX_ENTRIES", "DrawingsMetricsLike",
    "IdempotencyCache", "StoredResponse", "decode_cursor", "encode_cursor", "make_drawings_router",
]  # fmt: skip

"""`/watchlists` routes (E08-T07, #4706): contract `22-api-openapi.yaml` (`listWatchlists`,
`createWatchlist`, `updateWatchlist`, `deleteWatchlist`); the table is 21 Sec.3.8.6.

Callers come from the session (`SessionAuditPrincipalResolver`). RBAC (C-12.4) runs per request
through `auth.scopes.enforce()`, before any store read, each denial audited `rbac.denied`:
`workspaces:read` to list, `workspaces:write` to write, `scope: self`. Every store call names the
caller, so another user's list is answered as an id that does not exist, `404`, never `403`, and
the listing never shows it. A replace or a delete that meets another user's list is audited
`rbac.denied` first, as `/workspaces` and the presets audit theirs; the answer stays that `404`,
also when the record cannot be written (logged), so no answer tells the two apart. No store wired
(the fake backend) is `503 store_unavailable`.

A write answers its refusals in 22's order: `413 payload_too_large` for a body past
`MAX_BODY_BYTES`; for a replace, `404` (also a path id that is no UUID), then `428
precondition_required` without `If-Match` or `412 version_conflict` with a tag that does not name
the list's current version (its `ETag` names the current one); then `422 validation_failed` for
the rules that need no catalogue (`WatchlistIn`, `duplicate_errors`); then, only for symbols the
list does not hold yet, `503 instrument_cache_unavailable` while no catalogue is loaded (never a
guess) and `422 unknown_symbol`; then `409 conflict` (`name_taken`, as `ux_wl_name` decides). A
write with no new symbol (a create with none; a rename, a reorder, a removal or a change of
columns) reads no catalogue, as a narrowing profile write reads no listing. `columns` left out or
`null` stores `DEFAULT_COLUMNS`. The store compares the version under the row's lock and writes in
one statement guarded by it, so of two writers holding one version exactly one wins. Every 503
carries `Retry-After` and `retry_after_seconds`: 2 for the catalogue, as the profile writes
answer it, else 5.

Each write is audited ahead (C-2.9): the store awaits the record in the write's transaction before
it commits, so a record that is not written is `503 audit_unavailable` and nothing changes. A
record carries the list's name, symbol count and version, never the symbols (24 Sec.15.5). Logs
carry ids, counts and versions, never a name or a symbol. Each `412` counts once in
`watchlist_write_conflicts_total`.
"""

from __future__ import annotations

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

from candleviewer.accounts.profiles import is_trading_usdt_perpetual
from candleviewer.api.drawings_models import format_errors
from candleviewer.api.profile_body import IfMatchMissing, IfMatchRefused, if_match_version
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.api.watchlists_models import (
    MAX_BODY_BYTES,
    WatchlistIn,
    duplicate_errors,
    unknown_errors,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.domain.events import Instrument, uuid7
from candleviewer.observability.redaction import redact_structure
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.watchlists import (
    WatchlistFields,
    WatchlistNameTakenError,
    WatchlistNotFoundError,
    WatchlistRow,
    WatchlistStaleError,
    WatchlistStore,
    WatchlistWriteAhead,
)
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_STATUS: Final = {
    "unauthenticated": 401, "forbidden": 403, "not_found": 404, "conflict": 409,
    "version_conflict": 412, "validation_failed": 422, "precondition_required": 428,
    "store_unavailable": 503, "audit_unavailable": 503, "instrument_cache_unavailable": 503,
    "payload_too_large": 413,
}  # fmt: skip
_RETRY_AFTER_S: Final = 5
_PERMISSIONS: Final = {p.value: p for p in Permission}
_LENGTH: Final = re.compile(r"[0-9]{1,19}")
_INT4_MAX: Final = 2**31 - 1  # `watchlists.version` is an `integer`


class AuditEmitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class InstrumentLookup(Protocol):
    """The instrument catalogue's snapshot (`CatalogueSnapshot`)."""

    def get(self, symbol: str) -> Instrument | None: ...


class _Resolver(Protocol):
    def resolve(
        self, request: Request
    ) -> AuditPrincipal | Awaitable[AuditPrincipal | None] | None: ...


class _Counter(Protocol):
    def inc(self, amount: float = 1) -> None: ...


class WatchlistAuditRefused(Exception):
    """A watchlist record was not written (refused, or no writer): the write rolls back."""


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.watchlists")


class _Problem(Exception):
    """RFC 9457 problem for a registered code: its status from `_STATUS`, its title the
    registry's; a 503 says when to retry (`Retry-After` and `retry_after_seconds`)."""

    def __init__(
        self, code: str, detail: str, *, etag: str | None = None, retry_s: int = _RETRY_AFTER_S,
        **extra: Any,
    ) -> None:  # fmt: skip
        super().__init__(detail)
        self.status, self.title = _STATUS[code], ERROR_META[ErrorCode(code)].title
        self.code, self.detail, self.extra, self.etag = code, detail, extra, etag
        self.retry_s = retry_s

    def response(self) -> JSONResponse:
        body = {"type": f"https://candleviewer.local/errors/{self.code}", "title": self.title,
                "status": self.status, "code": self.code, "detail": self.detail}  # fmt: skip
        headers: dict[str, str] = {}
        if self.status == 503:
            body["retry_after_seconds"], headers["Retry-After"] = self.retry_s, str(self.retry_s)
        if self.etag is not None:
            headers["ETag"] = self.etag
        return JSONResponse(body | self.extra, self.status, headers, "application/problem+json")


class _ProblemRoute(APIRoute):
    """`_Problem` -> its response; a record not written -> 503 `audit_unavailable`; a store
    outage -> 503 `store_unavailable`; anything else is a defect and propagates."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await inner(request)
            except _Problem as p:
                return p.response()
            except (WatchlistAuditRefused, WriteAheadTimeout, AuditError) as exc:
                _log().error("watchlists_audit_unavailable", error=type(exc).__name__)
                detail = "The audit record could not be written; nothing was changed."
                return _Problem("audit_unavailable", detail).response()
            except Exception as exc:  # re-raised below unless it is a store outage
                if not is_storage_outage(exc):
                    raise
                # class name only: str(exc) of a SQLAlchemy error embeds bound parameters
                _log().error("watchlists_store_unavailable", error=type(exc).__name__)
            return _Problem("store_unavailable", "The watchlist store is unavailable.").response()

        return handler


def _snapshot(p: AuditPrincipal) -> PrincipalSnapshot:
    """Known permission codes only, and the owner flag the session resolver derived."""
    perms = frozenset(_PERMISSIONS[c] for c in p.permissions if c in _PERMISSIONS)
    return PrincipalSnapshot(p.user_id, frozenset({"owner"} if p.is_owner else ()), perms)


def _invalid(errors: list[dict[str, str]], *, redacted: bool = True) -> _Problem:
    """422 with at most 20 field errors. Those `format_errors` built pass through the shared
    redaction rule set, since a key the client sent can reach their `field`; the list rules'
    own entries do not, since they name only a symbol the `Symbol` pattern has admitted, which
    that set would take for a key past 17 characters (`10000000AIDOGEUSDT`)."""
    entries = errors[:20]
    return _Problem("validation_failed", "The request is invalid.",
                    errors=redact_structure(entries) if redacted else entries)  # fmt: skip


async def _read_body(request: Request) -> bytes:
    """The raw body, refused `413` past `MAX_BODY_BYTES`: a declared length over it is not read, a
    stream stops one chunk past it."""
    too_large = _Problem("payload_too_large", f"The request body exceeds {MAX_BODY_BYTES} bytes.")
    declared = request.headers.get("content-length", "")
    if _LENGTH.fullmatch(declared) and int(declared) > MAX_BODY_BYTES:
        raise too_large
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            raise too_large
    return bytes(raw)


def _expected(request: Request, watchlist_id: UUID) -> int | None:
    """The version `If-Match` names of this list; None for any tag that can name none of its
    versions (22: `*`, a list, another list's tag, an unparseable value), which never matches.
    No `If-Match` raises `IfMatchMissing`."""
    try:
        version = if_match_version(request, str(watchlist_id))
    except IfMatchRefused:
        return None
    return version if version <= _INT4_MAX else None


def _path_id(raw: str) -> UUID:
    """The path's list id; one that is no UUID names no list (404, as 22 orders it first)."""
    try:
        return UUID(raw)
    except ValueError:
        raise _not_found() from None


def _not_found() -> _Problem:
    return _Problem("not_found", "No such watchlist.")


def etag(watchlist_id: UUID, version: int) -> str:
    """22 `WatchlistETag`."""
    return f'W/"{watchlist_id}:{version}"'


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def dump(row: WatchlistRow) -> dict[str, Any]:
    """22 `Watchlist`: exactly its properties."""
    return {
        "id": str(row.id), "name": row.name, "symbols": list(row.symbols),
        "columns": list(row.columns), "version": row.version,
        "created_at": _stamp(row.created_at), "updated_at": _stamp(row.updated_at),
    }  # fmt: skip


def _state(row: WatchlistRow) -> dict[str, object]:
    """What a record holds of a list (24 Sec.15.5): never its symbols or its columns."""
    return {"name": row.name, "symbol_count": len(row.symbols), "version": row.version}


def _new_id() -> UUID:
    return uuid7(time.time_ns() // 1_000_000)


def make_watchlists_router(
    store_provider: Callable[[], WatchlistStore | None],
    principal_resolver: _Resolver | None,
    audit: AuditEmitter,
    catalogue: Callable[[], InstrumentLookup | None],
    *,
    conflicts: _Counter | None = None,
    new_id: Callable[[], UUID] = _new_id,
) -> APIRouter:
    """`audit` is mandatory (every write and every denial leaves its record). No resolver fails
    closed with 401, no store with 503. `catalogue` answers the instrument snapshot a symbol is
    judged by (None while none is attached); `conflicts` counts each 412."""
    if audit is None:
        raise TypeError("make_watchlists_router: an audit emitter is required")
    router = APIRouter(tags=["workspaces"], route_class=_ProblemRoute)

    async def caller(request: Request, permission: Permission) -> AuditPrincipal:
        got: object = None if principal_resolver is None else principal_resolver.resolve(request)
        if inspect.isawaitable(got):
            got = await got
        if not isinstance(got, AuditPrincipal):
            raise _Problem("unauthenticated", "No verified session for this request.")
        try:
            await enforce(
                _snapshot(got), permission, scope=Scope.SELF, emitter=audit, actor_ip=got.ip,
                session_id=got.session_id, request_id=got.request_id,
            )  # fmt: skip
        except ForbiddenError:
            raise _Problem("forbidden", f"Requires {permission.value}.",
                           required_permissions=[permission.value]) from None  # fmt: skip
        except RuntimeError as exc:  # no audit writer: the denial's record cannot be written
            raise WatchlistAuditRefused from exc
        return got

    def store() -> WatchlistStore:
        repo = store_provider()
        if repo is None:
            raise _Problem("store_unavailable", "The watchlist store is unavailable.")
        return repo

    def judge(raw: bytes, held: frozenset[str] = frozenset()) -> WatchlistFields:
        """The body as the fields a write stores, or its refusal in 22's order: `422` for the
        rules that need no catalogue, then, for the symbols the list does not hold yet (`held`:
        the stored ones), `503 instrument_cache_unavailable` while no catalogue is loaded, then
        `422 unknown_symbol`. A body with no new symbol reads no catalogue."""
        try:
            body = WatchlistIn.model_validate_json(raw)
        except ValidationError as exc:
            raise _invalid(format_errors(exc)) from None
        if errors := duplicate_errors(body.symbols):
            raise _invalid(errors, redacted=False)
        if new := [symbol for symbol in body.symbols if symbol not in held]:
            snap = catalogue()
            if snap is None:
                detail = "The instrument catalogue is not loaded; nothing was saved."
                raise _Problem("instrument_cache_unavailable", detail, retry_s=2)

            def listed(symbol: str) -> bool:
                found = snap.get(symbol)
                return found is not None and is_trading_usdt_perpetual(found)

            if errors := unknown_errors(new, listed):
                raise _invalid(errors, redacted=False)
        return WatchlistFields(body.name, tuple(body.symbols), body.stored_columns())

    def stale(watchlist_id: UUID, version: int) -> _Problem:
        if conflicts is not None:
            conflicts.inc()
        detail = "If-Match does not name this list's current version. Nothing was changed."
        return _Problem("version_conflict", detail, etag=etag(watchlist_id, version))

    def name_taken() -> _Problem:
        message = "Another of your watchlists already uses this name, in any letter case."
        item = {"field": "name", "rule": "name_taken", "message": message}
        return _Problem("conflict", message, errors=[item])

    async def not_found(p: AuditPrincipal, repo: WatchlistStore, watchlist_id: UUID) -> _Problem:
        """The one 404 of a missing list and of another user's. A probe of another user's is
        audited `rbac.denied` first, in the shape `/workspaces` and the presets write; a record
        that cannot be written is logged by its ids and error class, and the 404 stands."""
        if await repo.exists_for_other_owner(p.user_id, watchlist_id):
            try:
                await audit.emit(  # the viewer acts while viewing (#3085)
                    "rbac.denied", actor_label=str(p.actor_id), actor_user_id=p.actor_id,
                    actor_ip=p.ip, session_id=p.session_id, request_id=p.request_id,
                    object_kind="watchlist", object_id=str(watchlist_id),
                    outcome=AuditOutcome.DENIED, severity=Severity.WARNING,
                    reason="not_owner:workspaces:write:self",
                )  # fmt: skip
            except (AuditError, RuntimeError) as exc:  # RuntimeError: no writer started
                ids = {"user_id": str(p.actor_id), "watchlist_id": str(watchlist_id)}
                _log().warning("watchlist_denial_unaudited", **ids, error=type(exc).__name__)
        return _not_found()

    def audit_hook(action: str, p: AuditPrincipal) -> WatchlistWriteAhead:
        """The write-ahead record of one write, awaited by the store before it commits."""

        async def record(before: WatchlistRow | None, after: WatchlistRow | None) -> None:
            row = after if after is not None else before  # a write has one or both
            try:
                await audit.emit(
                    action, actor_label=str(p.actor_id), actor_user_id=p.actor_id,
                    actor_ip=p.ip, session_id=p.session_id, request_id=p.request_id,
                    object_kind="watchlist", object_id=None if row is None else str(row.id),
                    outcome=AuditOutcome.SUCCESS, severity=Severity.INFO,
                    before_state=None if before is None else _state(before),
                    after_state=None if after is None else _state(after),
                )  # fmt: skip
            except (AuditError, RuntimeError) as exc:  # RuntimeError: no writer started
                raise WatchlistAuditRefused from exc

        return record

    @router.get("/watchlists")
    async def list_watchlists(request: Request) -> Response:
        principal = await caller(request, Permission.WORKSPACES_READ)
        rows = await store().list_own(principal.user_id)
        return JSONResponse({"items": [dump(r) for r in rows]})

    @router.post("/watchlists")
    async def create_watchlist(request: Request) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        repo, owner = store(), principal.user_id
        fields = judge(await _read_body(request))
        hook = audit_hook("watchlist.created", principal)
        try:
            row = await repo.create(owner, new_id(), fields, write_ahead=hook)
        except WatchlistNameTakenError:
            raise name_taken() from None
        _log().info("watchlist_created", user_id=str(owner), watchlist_id=str(row.id),
                    symbol_count=len(row.symbols), version=row.version)  # fmt: skip
        return JSONResponse(dump(row), 201, {"ETag": etag(row.id, row.version)})

    @router.put("/watchlists/{watchlistId}")
    async def update_watchlist(
        request: Request, watchlist_id: Annotated[str, Path(alias="watchlistId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        repo, owner = store(), principal.user_id
        raw = await _read_body(request)  # 22's order: 413 first
        wid = _path_id(watchlist_id)
        current = await repo.get_own(owner, wid)
        if current is None:
            raise await not_found(principal, repo, wid)
        try:
            expected = _expected(request, wid)
        except IfMatchMissing:
            detail = "A replace needs the list's current ETag as If-Match. Nothing was changed."
            raise _Problem("precondition_required", detail) from None
        if expected != current.version:
            raise stale(wid, current.version)
        fields = judge(raw, frozenset(current.symbols))
        hook = audit_hook("watchlist.updated", principal)
        try:
            row = await repo.replace(owner, wid, fields, expected_version=expected,
                                     write_ahead=hook)  # fmt: skip
        except WatchlistNotFoundError:
            raise await not_found(principal, repo, wid) from None
        except WatchlistStaleError as exc:
            raise stale(wid, exc.version) from None
        except WatchlistNameTakenError:
            raise name_taken() from None
        _log().info("watchlist_updated", user_id=str(owner), watchlist_id=str(wid),
                    symbol_count=len(row.symbols), version=row.version)  # fmt: skip
        return JSONResponse(dump(row), headers={"ETag": etag(row.id, row.version)})

    @router.delete("/watchlists/{watchlistId}")
    async def delete_watchlist(
        request: Request, watchlist_id: Annotated[str, Path(alias="watchlistId")]
    ) -> Response:
        principal = await caller(request, Permission.WORKSPACES_WRITE)
        repo, owner, wid = store(), principal.user_id, _path_id(watchlist_id)
        hook = audit_hook("watchlist.deleted", principal)
        try:
            row = await repo.delete(owner, wid, write_ahead=hook)
        except WatchlistNotFoundError:
            raise await not_found(principal, repo, wid) from None
        _log().info("watchlist_deleted", user_id=str(owner), watchlist_id=str(wid),
                    version=row.version)  # fmt: skip
        return Response(status_code=204)

    return router


__all__ = ["InstrumentLookup", "WatchlistAuditRefused", "dump", "etag", "make_watchlists_router"]

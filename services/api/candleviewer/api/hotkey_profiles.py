"""`/settings/hotkeys*` (E10-T05, #5211): contract `22-api-openapi.yaml` (`listHotkeyProfiles`,
`createHotkeyProfile`, `updateHotkeyProfile`, `deleteHotkeyProfile`, `activateHotkeyProfile`).
The table is 21 Sec.3.8.5, the store `storage.repositories.hotkey_profiles`, the binding rules
`api.hotkey_rules` and the closed bodies `api.hotkey_profiles_models`.

Callers come from the session (`SessionAuditPrincipalResolver`). RBAC (C-12.4) runs per request
through `auth.scopes.enforce()`, before any store read, each denial audited `rbac.denied`:
`settings:read` to list, `settings:write` to write, `scope: self`. Every store call names the
caller, so another user's profile is answered as an id that does not exist, `404`, never `403`,
and the list never names it. A replace, a delete or an activation that meets another user's
profile is audited `rbac.denied` first (`not_owner:settings:write:self`, 24 Sec.15.5); the answer
stays that `404`, also when the record cannot be written (logged), so no answer tells the two
apart. A path id that is no UUID names no profile: `404`, with no record. No store wired (the
fake backend) is `503 store_unavailable`.

Under a view-as context a read answers the target's profiles (the principal is the target's,
#3085), and a write never reaches this router: the view-as guard refuses it `403
view_as_read_only` first. One that arrives all the same (a router mounted without the guard) is
refused the same way, before anything is read. CSRF guards the writes at the edge
(`CsrfMiddleware`, SR-041).

A write answers its refusals in 22's order: `413 payload_too_large` for a body past
`MAX_BODY_BYTES`, refused before it is parsed; for a replace, `404`, then `412 version_conflict`
for an `If-Match` that names no current version of the profile (its `ETag` names the current
one; with no `If-Match` the replace is last-write-wins); then `422 validation_failed` and `409
conflict` `binding_conflict` (`hotkey_rules.judge`); then the store's `409`s, `limit_reached` (a
create past `MAX_PROFILES`) and `name_taken` (`ux_hk_name`). A delete answers `404` before `409
profile_active`. An activation of the profile that is already active changes nothing, writes no
record and answers the profile as it is. A create, a replace and an activation answer the
profile's weak `ETag`; a create or a replace that rewrote an action's `requires_arm` or `confirm`
names it in `Hotkey-Bindings-Rewritten` (BQ-3). Every 503 carries `Retry-After` and
`retry_after_seconds` (5).

Each write is audited ahead (C-2.9): the store awaits the record in the write's transaction
before it commits, so a record that is not written is `503 audit_unavailable` and nothing
changes. A record carries the profile's `name`, `binding_count` and `is_active`, and an
activation's before state the `previous_active_id`, never a binding (24 Sec.15.5). Logs carry
ids, counts, versions, the operation and a refusal's code and rule, never a name or a binding.
Each `409` and `422` counts once in `hotkey_profile_refusals_total{code,rule}`: a `409` by its
rule, a `422` by the rule of its first `errors[]` item. A rule outside the closed set of its code
(a `422` schema refusal's) counts as that code's fixed label, `binding_conflict` or `schema`, so
no rule can add a series.
"""

from __future__ import annotations

import inspect
import re
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Annotated, Any, Final, Protocol
from uuid import UUID

import structlog
from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from candleviewer.api.hotkey_profiles_models import (
    MAX_BODY_BYTES,
    JudgedProfile,
    dump,
    etag,
    judge_body,
    rewritten_header,
)
from candleviewer.api.hotkey_rules import HotkeyBindingConflict, HotkeyBindingsInvalid
from candleviewer.api.profile_body import IfMatchMissing, IfMatchRefused, if_match_version
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.domain.events import uuid7
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.hotkey_profiles import (
    HotkeyActivationWriteAhead,
    HotkeyProfileActiveError,
    HotkeyProfileLimitError,
    HotkeyProfileNameTakenError,
    HotkeyProfileNotFoundError,
    HotkeyProfileRow,
    HotkeyProfileStaleError,
    HotkeyProfileStore,
    HotkeyProfileWriteAhead,
)
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_STATUS: Final = {
    "unauthenticated": 401, "forbidden": 403, "view_as_read_only": 403, "not_found": 404,
    "conflict": 409, "version_conflict": 412, "payload_too_large": 413, "validation_failed": 422,
    "store_unavailable": 503, "audit_unavailable": 503,
}  # fmt: skip
_RETRY_AFTER_S: Final = 5
_PERMISSIONS: Final = {p.value: p for p in Permission}
_LENGTH: Final = re.compile(r"[0-9]{1,19}")
_INT4_MAX: Final = 2**31 - 1  # `hotkey_profiles.version` is an `integer`
#: A version no profile holds (each starts at 1): an `If-Match` that names none never matches.
_NO_VERSION: Final = 0
#: The detail of the `503 store_unavailable` for a profile store not wired or not serving.
STORE_UNAVAILABLE_DETAIL: Final = "The hotkey profile store is unavailable."
#: `hotkey_profile_refusals_total{code,rule}`'s closed label sets: a `409 conflict` by its rule,
#: a `422 validation_failed` by its first item's rule. A rule outside its code's set counts as that
#: code's fixed label (`binding_conflict`, `schema`), so no rule can add a series.
CONFLICT_RULES: Final = ("binding_conflict", "limit_reached", "name_taken", "profile_active")
INVALID_RULES: Final = (
    "unknown_action", "duplicate_action", "scope_mismatch", "params_not_allowed", "invalid_keys",
    "shape_mismatch", "bare_letter_dangerous", "reserved_key", "locked_command",
    "invalid_character", "schema",
)  # fmt: skip
#: Every series the counter can hold: its catalogue `max_series`.
REFUSAL_SERIES: Final = len(CONFLICT_RULES) + len(INVALID_RULES)


class AuditEmitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _Resolver(Protocol):
    def resolve(
        self, request: Request
    ) -> AuditPrincipal | Awaitable[AuditPrincipal | None] | None: ...


class _Child(Protocol):
    def inc(self, amount: float = 1) -> None: ...


class RefusalCounter(Protocol):
    """`hotkey_profile_refusals_total` (a `BoundedMetric`): its child for (code, rule)."""

    def labels(self, *values: str) -> _Child: ...


class HotkeyAuditRefused(Exception):
    """A hotkey profile record was not written (refused, or no writer): the write rolls back."""


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.hotkey_profiles")


class _Problem(Exception):
    """RFC 9457 problem for a registered code: its status from `_STATUS`, its title the
    registry's; a 503 says when to retry (`Retry-After` and `retry_after_seconds`)."""

    def __init__(self, code: str, detail: str, *, etag: str | None = None, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.title = _STATUS[code], ERROR_META[ErrorCode(code)].title
        self.code, self.detail, self.extra, self.etag = code, detail, extra, etag

    def response(self) -> JSONResponse:
        body = {"type": f"https://candleviewer.local/errors/{self.code}", "title": self.title,
                "status": self.status, "code": self.code, "detail": self.detail}  # fmt: skip
        headers: dict[str, str] = {}
        if self.status == 503:
            body["retry_after_seconds"] = _RETRY_AFTER_S
            headers["Retry-After"] = str(_RETRY_AFTER_S)
        if self.etag is not None:
            headers["ETag"] = self.etag
        return JSONResponse(body | self.extra, self.status, headers, "application/problem+json")


def hotkey_store_unavailable() -> JSONResponse:
    """`503 store_unavailable` for a profile store that is not wired or cannot serve the call:
    the registry's title, `STORE_UNAVAILABLE_DETAIL`, and when to retry. `GET /me/keymap`
    answers this same problem for its store."""
    return _Problem("store_unavailable", STORE_UNAVAILABLE_DETAIL).response()


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
            except (HotkeyAuditRefused, WriteAheadTimeout, AuditError) as exc:
                _log().error("hotkey_profiles_audit_unavailable", error=type(exc).__name__)
                detail = "The audit record could not be written; nothing was changed."
                return _Problem("audit_unavailable", detail).response()
            except Exception as exc:  # re-raised below unless it is a store outage
                if not is_storage_outage(exc):
                    raise
                # class name only: str(exc) of a SQLAlchemy error embeds bound parameters
                _log().error("hotkey_profiles_store_unavailable", error=type(exc).__name__)
            return hotkey_store_unavailable()

        return handler


def _snapshot(p: AuditPrincipal) -> PrincipalSnapshot:
    """Known permission codes only, and the owner flag the session resolver derived."""
    perms = frozenset(_PERMISSIONS[c] for c in p.permissions if c in _PERMISSIONS)
    return PrincipalSnapshot(p.user_id, frozenset({"owner"} if p.is_owner else ()), perms)


def _viewing(p: AuditPrincipal) -> bool:
    """The session views as another user (#3085): the principal is the target's, the actor not."""
    return p.actor_id != p.user_id


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


def _expected(request: Request, profile_id: UUID) -> int | None:
    """The version `If-Match` names of this profile: None with no `If-Match` (last write wins),
    `_NO_VERSION` for a tag that can name none of its versions (22: `*`, a list, another
    profile's tag, an unparseable value), which never matches."""
    try:
        version = if_match_version(request, str(profile_id))
    except IfMatchMissing:
        return None
    except IfMatchRefused:
        return _NO_VERSION
    return version if version <= _INT4_MAX else _NO_VERSION


def _path_id(raw: str) -> UUID:
    """The path's profile id; one that is no UUID names no profile (404, as 22 orders it)."""
    try:
        return UUID(raw)
    except ValueError:
        raise _not_found() from None


def _not_found() -> _Problem:
    return _Problem("not_found", "No such hotkey profile.")


def _state(row: HotkeyProfileRow) -> dict[str, object]:
    """What a record holds of a profile (24 Sec.15.5): never its bindings."""
    return {"name": row.name, "binding_count": len(row.bindings), "is_active": row.is_active}


def _new_id() -> UUID:
    return uuid7(time.time_ns() // 1_000_000)


async def _written(record: Awaitable[None]) -> None:
    """A write-ahead record awaited; one not written rolls the write back."""
    try:
        await record
    except (AuditError, RuntimeError) as exc:  # RuntimeError: no writer started
        raise HotkeyAuditRefused from exc


def make_hotkey_profiles_router(
    store_provider: Callable[[], HotkeyProfileStore | None],
    principal_resolver: _Resolver | None,
    audit: AuditEmitter,
    *,
    refusals: RefusalCounter | None = None,
    new_id: Callable[[], UUID] = _new_id,
) -> APIRouter:
    """`audit` is mandatory (every write and every denial leaves its record). No resolver fails
    closed with 401, no store with 503. `refusals` counts each `409` and `422` it answers."""
    if audit is None:
        raise TypeError("make_hotkey_profiles_router: an audit emitter is required")
    router = APIRouter(tags=["settings"], route_class=_ProblemRoute)

    async def caller(request: Request, permission: Permission) -> AuditPrincipal:
        got: object = None if principal_resolver is None else principal_resolver.resolve(request)
        if inspect.isawaitable(got):
            got = await got
        if not isinstance(got, AuditPrincipal):
            raise _Problem("unauthenticated", "No verified session for this request.")
        writes = permission is Permission.SETTINGS_WRITE
        if writes and _viewing(got):  # the view-as guard refuses this first
            raise _Problem("view_as_read_only", "This session is viewing as another user.")
        try:
            await enforce(
                _snapshot(got), permission, scope=Scope.SELF, emitter=audit, actor_ip=got.ip,
                session_id=got.session_id, request_id=got.request_id,
            )  # fmt: skip
        except ForbiddenError:
            raise _Problem("forbidden", f"Requires {permission.value}.",
                           required_permissions=[permission.value]) from None  # fmt: skip
        except RuntimeError as exc:  # no audit writer: the denial's record cannot be written
            raise HotkeyAuditRefused from exc
        return got

    def store() -> HotkeyProfileStore:
        repo = store_provider()
        if repo is None:
            raise _Problem("store_unavailable", STORE_UNAVAILABLE_DETAIL)
        return repo

    def refused(operation: str, code: str, detail: str, errors: list[dict[str, str]]) -> _Problem:
        """A `409` or `422`, counted and logged by its code and rule (never a value)."""
        rule = errors[0].get("rule", "")  # never empty: a refusal names at least one
        if code == "validation_failed" and rule not in INVALID_RULES:
            rule = "schema"
        elif code == "conflict" and rule not in CONFLICT_RULES:
            rule = "binding_conflict"  # a rule the router does not know adds no series
        if refusals is not None:
            refusals.labels(code, rule).inc()
        _log().info("hotkey_profile_refused", operation=operation, code=code, rule=rule)
        return _Problem(code, detail, errors=errors)

    def conflict(operation: str, rule: str, message: str, **field: str) -> _Problem:
        """A store's `409 conflict` with one `errors[]` item: its rule, and its `field` if any."""
        return refused(operation, "conflict", message, [field | {"rule": rule, "message": message}])

    def judge(operation: str, raw: bytes) -> JudgedProfile:
        """The body as a write stores it, or its `422`, then its `409 binding_conflict`."""
        try:
            return judge_body(raw)
        except HotkeyBindingsInvalid as exc:
            raise refused(operation, "validation_failed", "The request is invalid.",
                          exc.errors) from None  # fmt: skip
        except HotkeyBindingConflict as exc:
            detail = "Two bindings share a key while both can be live; nothing was saved."
            raise refused(operation, "conflict", detail, exc.errors) from None

    def name_taken(operation: str) -> _Problem:
        message = "Another of your hotkey profiles already uses this name, in any letter case."
        return conflict(operation, "name_taken", message, field="name")

    def stale(profile_id: UUID, version: int) -> _Problem:
        detail = "If-Match does not name this profile's current version. Nothing was changed."
        return _Problem("version_conflict", detail, etag=etag(profile_id, version))

    async def not_found(p: AuditPrincipal, repo: HotkeyProfileStore, profile_id: UUID) -> _Problem:
        """The one 404 of a missing profile and of another user's. A probe of another user's is
        audited `rbac.denied` first; a record that cannot be written is logged by its ids and
        error class, and the 404 stands."""
        if await repo.exists_for_other_owner(p.user_id, profile_id):
            try:
                await audit.emit(  # the viewer acts while viewing (#3085)
                    "rbac.denied", actor_label=str(p.actor_id), actor_user_id=p.actor_id,
                    actor_ip=p.ip, session_id=p.session_id, request_id=p.request_id,
                    object_kind="hotkey_profile", object_id=str(profile_id),
                    outcome=AuditOutcome.DENIED, severity=Severity.WARNING,
                    reason="not_owner:settings:write:self",
                )  # fmt: skip
            except (AuditError, RuntimeError) as exc:  # RuntimeError: no writer started
                ids = {"user_id": str(p.actor_id), "hotkey_profile_id": str(profile_id)}
                _log().warning("hotkey_profile_denial_unaudited", **ids, error=type(exc).__name__)
        return _not_found()

    def on(
        p: AuditPrincipal, before: HotkeyProfileRow | None, after: HotkeyProfileRow | None
    ) -> dict[str, Any]:
        """A write-ahead record's fields: the profile written, as it was and is."""
        row = after if after is not None else before  # a write has one or both
        return {
            "actor_label": str(p.actor_id), "actor_user_id": p.actor_id, "actor_ip": p.ip,
            "session_id": p.session_id, "request_id": p.request_id,
            "object_kind": "hotkey_profile", "object_id": None if row is None else str(row.id),
            "outcome": AuditOutcome.SUCCESS, "severity": Severity.INFO,
            "before_state": None if before is None else _state(before),
            "after_state": None if after is None else _state(after),
        }  # fmt: skip

    def audit_created(p: AuditPrincipal) -> HotkeyProfileWriteAhead:
        async def created(before: HotkeyProfileRow | None, after: HotkeyProfileRow | None) -> None:
            await _written(audit.emit("hotkey_profile.created", **on(p, before, after)))

        return created

    def audit_updated(p: AuditPrincipal) -> HotkeyProfileWriteAhead:
        async def updated(before: HotkeyProfileRow | None, after: HotkeyProfileRow | None) -> None:
            await _written(audit.emit("hotkey_profile.updated", **on(p, before, after)))

        return updated

    def audit_deleted(p: AuditPrincipal) -> HotkeyProfileWriteAhead:
        async def deleted(before: HotkeyProfileRow | None, after: HotkeyProfileRow | None) -> None:
            await _written(audit.emit("hotkey_profile.deleted", **on(p, before, after)))

        return deleted

    def audit_activated(
        p: AuditPrincipal, previous: list[UUID | None]
    ) -> HotkeyActivationWriteAhead:
        """One record, for the profile made active; `previous` gets the id it deactivated."""

        async def activated(
            before: HotkeyProfileRow, after: HotkeyProfileRow, was: UUID | None
        ) -> None:
            fields = on(p, before, after)
            fields["before_state"] = _state(before) | {
                "previous_active_id": None if was is None else str(was)
            }
            await _written(audit.emit("hotkey_profile.activated", **fields))
            previous.append(was)

        return activated

    @router.get("/settings/hotkeys")
    async def list_hotkey_profiles(request: Request) -> Response:
        principal = await caller(request, Permission.SETTINGS_READ)
        rows = await store().list_own(principal.user_id)
        return JSONResponse({"items": [dump(r) for r in rows]})

    @router.post("/settings/hotkeys")
    async def create_hotkey_profile(request: Request) -> Response:
        principal = await caller(request, Permission.SETTINGS_WRITE)
        repo, owner = store(), principal.user_id
        judged = judge("create", await _read_body(request))
        try:
            row = await repo.create(owner, new_id(), judged.fields,
                                    write_ahead=audit_created(principal))  # fmt: skip
        except HotkeyProfileLimitError:
            message = "You already hold the most hotkey profiles allowed; delete one first."
            raise conflict("create", "limit_reached", message) from None
        except HotkeyProfileNameTakenError:
            raise name_taken("create") from None
        _log().info("hotkey_profile_created", user_id=str(owner), hotkey_profile_id=str(row.id),
                    binding_count=len(row.bindings), version=row.version)  # fmt: skip
        headers = {"ETag": etag(row.id, row.version)} | rewritten_header(judged.rewritten)
        return JSONResponse(dump(row), 201, headers)

    @router.put("/settings/hotkeys/{hotkeyProfileId}")
    async def update_hotkey_profile(
        request: Request, profile_id: Annotated[str, Path(alias="hotkeyProfileId")]
    ) -> Response:
        principal = await caller(request, Permission.SETTINGS_WRITE)
        repo, owner = store(), principal.user_id
        raw = await _read_body(request)  # 22's order: 413 first
        pid = _path_id(profile_id)
        current = await repo.get_own(owner, pid)
        if current is None:
            raise await not_found(principal, repo, pid)
        expected = _expected(request, pid)
        if expected is not None and expected != current.version:
            raise stale(pid, current.version)
        judged = judge("update", raw)
        try:
            row = await repo.replace(owner, pid, judged.fields, expected_version=expected,
                                     write_ahead=audit_updated(principal))  # fmt: skip
        except HotkeyProfileNotFoundError:
            raise await not_found(principal, repo, pid) from None
        except HotkeyProfileStaleError as exc:
            raise stale(pid, exc.version) from None
        except HotkeyProfileNameTakenError:
            raise name_taken("update") from None
        _log().info("hotkey_profile_updated", user_id=str(owner), hotkey_profile_id=str(pid),
                    binding_count=len(row.bindings), version=row.version)  # fmt: skip
        headers = {"ETag": etag(row.id, row.version)} | rewritten_header(judged.rewritten)
        return JSONResponse(dump(row), headers=headers)

    @router.delete("/settings/hotkeys/{hotkeyProfileId}")
    async def delete_hotkey_profile(
        request: Request, profile_id: Annotated[str, Path(alias="hotkeyProfileId")]
    ) -> Response:
        principal = await caller(request, Permission.SETTINGS_WRITE)
        repo, owner, pid = store(), principal.user_id, _path_id(profile_id)
        try:
            row = await repo.delete(owner, pid, write_ahead=audit_deleted(principal))
        except HotkeyProfileNotFoundError:
            raise await not_found(principal, repo, pid) from None
        except HotkeyProfileActiveError:
            message = "The active hotkey profile cannot be deleted; activate another first."
            raise conflict("delete", "profile_active", message) from None
        _log().info("hotkey_profile_deleted", user_id=str(owner), hotkey_profile_id=str(pid),
                    version=row.version)  # fmt: skip
        return Response(status_code=204)

    @router.post("/settings/hotkeys/{hotkeyProfileId}/activate")
    async def activate_hotkey_profile(
        request: Request, profile_id: Annotated[str, Path(alias="hotkeyProfileId")]
    ) -> Response:
        principal = await caller(request, Permission.SETTINGS_WRITE)
        repo, owner, pid = store(), principal.user_id, _path_id(profile_id)
        previous: list[UUID | None] = []
        try:
            row = await repo.activate(owner, pid, write_ahead=audit_activated(principal, previous))
        except HotkeyProfileNotFoundError:
            raise await not_found(principal, repo, pid) from None
        if previous:  # the store recorded a change; an already active profile records none
            was = None if previous[0] is None else str(previous[0])
            _log().info("hotkey_profile_activated", user_id=str(owner),
                        hotkey_profile_id=str(pid), previous_active_id=was)  # fmt: skip
        return JSONResponse(dump(row), headers={"ETag": etag(row.id, row.version)})

    return router


__all__ = [
    "CONFLICT_RULES", "INVALID_RULES", "REFUSAL_SERIES", "STORE_UNAVAILABLE_DETAIL",
    "HotkeyAuditRefused", "RefusalCounter", "hotkey_store_unavailable",
    "make_hotkey_profiles_router",
]  # fmt: skip

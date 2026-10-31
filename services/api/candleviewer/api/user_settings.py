"""`GET /settings` and `PATCH /settings` (E02-T13, #5181): contract `getSettings` and
`updateSettings` in `22-api-openapi.yaml`, the caller's own settings (`scope: self`) over the
per-user rows of the `settings` table (`UserSettings`, 21 Sec.3.9).

Callers come from the session (`SessionAuditPrincipalResolver`). RBAC (C-12.4) runs per request
through `auth.scopes.enforce()`, before any store read, each denial audited `rbac.denied`:
`settings:read` to read (the Owner, Managers and Viewers), `settings:write` to write (the Owner and
Managers; a Viewer's `PATCH` is `403`, 21 Sec.10.1). No resolver (the fake backend) is `401`, and
no store wired `503 store_unavailable`. Neither operation declares a query parameter, so any one,
a target user under any spelling included, is refused with SR-026's shared `422`
(`api.query_allowlist`), after the permission check and before anything is read or written: a
refused `PATCH` reads no body and writes no record. Every store call names the principal's user,
re-derived from the session on every call. Under a view-as context a read answers the target's
settings (the principal is the target's, #3085), and a write never reaches this router: the view-as
guard refuses it `403 view_as_read_only` first. One that arrives all the same (a router mounted
without the guard) is refused the same way, unwritten. CSRF guards the write at the edge
(`CsrfMiddleware`, SR-041); no step-up is asked (22 has none).

`PATCH` is a partial deep merge (`user_settings_models`). The body is read up to `MAX_BODY_BYTES`
(`422 body_too_large`: the contract declares no `413`) and judged whole against 22's `Settings`
(`422 validation_failed`, nothing written). One store transaction then applies it under the
user's lock and, before the commit, writes `settings.change` (C-2.9). Reading Q2 of #5181: one
record per request that changes a leaf, `object_kind` `setting` with the user as the object,
naming the actor, the role (`user:<role>`), the session and the address, its state only the leaves
the request changed, each with its value before and after (`null`: no override; a credential-class
leaf masked, below). A record that cannot be written is `503 audit_unavailable`, nothing changed;
a patch that changes nothing writes no record. The answer is the effective settings after the
merge, as `GET` would answer them.

Q3 of #5181, as ruled: `notifications.webhook_url` is a credential-bearing URL (21 Sec.12), stored
as a plain row and answered in full to its owner only. The record's before and after carry its
masked form (`user_settings_models.masked`: scheme and host), and a read under a view-as context
answers that form too, its reader not being the owner. Logs carry the changed keys, never a value.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.api.user_settings_models import (
    MAX_BODY_BYTES,
    PatchRefused,
    effective,
    judge_patch,
    masked,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.user_settings import (
    LeafChange,
    UserSettings,
    UserSettingsWriteAhead,
)
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_STATUS: Final = {
    "unauthenticated": 401, "forbidden": 403, "view_as_read_only": 403, "validation_failed": 422,
    "store_unavailable": 503, "audit_unavailable": 503,
}  # fmt: skip
_RETRY_AFTER_S: Final = 5
_PERMISSIONS: Final = {p.value: p for p in Permission}
#: SR-026: the query parameters each operation declares (22): none, so any key is refused.
GET_SETTINGS_QUERY: frozenset[str] = frozenset()
UPDATE_SETTINGS_QUERY: frozenset[str] = frozenset()
_LENGTH: Final = re.compile(r"[0-9]{1,19}")


class AuditEmitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _Resolver(Protocol):
    def resolve(
        self, request: Request
    ) -> AuditPrincipal | Awaitable[AuditPrincipal | None] | None: ...


class SettingsAuditRefused(Exception):
    """The `settings.change` record was not written (refused, or no writer): nothing changes."""


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.user_settings")


class _Problem(Exception):
    """RFC 9457 problem for a registered code: its status from `_STATUS`, its title the
    registry's; a 503 says when to retry (`Retry-After` and `retry_after_seconds`)."""

    def __init__(self, code: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.title = _STATUS[code], ERROR_META[ErrorCode(code)].title
        self.code, self.detail, self.extra = code, detail, extra

    def response(self) -> JSONResponse:
        body = {"type": f"https://candleviewer.local/errors/{self.code}", "title": self.title,
                "status": self.status, "code": self.code, "detail": self.detail}  # fmt: skip
        headers: dict[str, str] = {}
        if self.status == 503:
            body["retry_after_seconds"] = _RETRY_AFTER_S
            headers["Retry-After"] = str(_RETRY_AFTER_S)
        return JSONResponse(body | self.extra, self.status, headers, "application/problem+json")


class _Answered(Exception):
    """A refusal answered as its shared helper made it (SR-026's `422`, `api.query_allowlist`)."""

    def __init__(self, answer: Response) -> None:
        super().__init__(answer.status_code)
        self.answer = answer


class _ProblemRoute(APIRoute):
    """`_Problem` -> its response, `_Answered` -> its answer; a record not written -> 503
    `audit_unavailable`; a store outage -> 503 `store_unavailable`; anything else is a defect and
    propagates."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await inner(request)
            except _Problem as p:
                return p.response()
            except _Answered as refused:
                return refused.answer
            except (SettingsAuditRefused, WriteAheadTimeout, AuditError) as exc:
                _log().error("user_settings_audit_unavailable", error=type(exc).__name__)
                detail = "The audit record could not be written; nothing was changed."
                return _Problem("audit_unavailable", detail).response()
            except Exception as exc:  # re-raised below unless it is a store outage
                if not is_storage_outage(exc):
                    raise
                # class name only: str(exc) of a SQLAlchemy error embeds bound parameters
                _log().error("user_settings_store_unavailable", error=type(exc).__name__)
            return _Problem("store_unavailable", "The settings store is unavailable.").response()

        return handler


def _snapshot(p: AuditPrincipal) -> PrincipalSnapshot:
    """Known permission codes only, and the owner flag the session resolver derived."""
    perms = frozenset(_PERMISSIONS[c] for c in p.permissions if c in _PERMISSIONS)
    return PrincipalSnapshot(p.user_id, frozenset({"owner"} if p.is_owner else ()), perms)


def _viewing(p: AuditPrincipal) -> bool:
    """The session views as another user (#3085): the principal is the target's, the actor not."""
    return p.actor_id != p.user_id


def _role(p: AuditPrincipal) -> str:
    """The writer's role for its record. Only the Owner and Managers hold `settings:write`
    (21 Sec.10.1, 22 `x-permissions`; a test pins it), and a writer has passed `enforce`."""
    return "owner" if p.is_owner else "manager"


async def _read_body(request: Request) -> bytes:
    """The raw body, refused past `MAX_BODY_BYTES`: a declared length over it is not read, a
    stream stops one chunk past it."""
    entry = {"field": "", "rule": "body_too_large", "message": f"Over {MAX_BODY_BYTES} bytes."}
    too_large = _Problem("validation_failed", "The request is invalid.", errors=[entry])
    declared = request.headers.get("content-length", "")
    if _LENGTH.fullmatch(declared) and int(declared) > MAX_BODY_BYTES:
        raise too_large
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BODY_BYTES:
            raise too_large
    return bytes(raw)


def make_user_settings_router(
    store_provider: Callable[[], UserSettings | None],
    principal_resolver: _Resolver | None,
    audit: AuditEmitter,
) -> APIRouter:
    """`audit` is mandatory (every change and every denial leaves its record). No resolver fails
    closed with 401, no store with 503."""
    router = APIRouter(tags=["settings"], route_class=_ProblemRoute)

    async def caller(
        request: Request, permission: Permission, query: frozenset[str]
    ) -> AuditPrincipal:
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
            raise SettingsAuditRefused from exc
        if (refusal := undeclared_query_refusal(request, query)) is not None:
            raise _Answered(refusal)  # SR-026: before the store or the body is read
        return got

    def store() -> UserSettings:
        repo = store_provider()
        if repo is None:
            raise _Problem("store_unavailable", "The settings store is unavailable.")
        return repo

    def record(p: AuditPrincipal, changed: list[str]) -> UserSettingsWriteAhead:
        """The write-ahead `settings.change` of one request, awaited before the commit."""

        async def hook(changes: tuple[LeafChange, ...]) -> None:
            try:
                await audit.emit(  # a literal, so the registered-action scan reads it (#2144)
                    "settings.change", actor_label=f"user:{_role(p)}", actor_user_id=p.actor_id,
                    actor_ip=p.ip, session_id=p.session_id, request_id=p.request_id,
                    object_kind="setting", object_id=str(p.user_id),
                    outcome=AuditOutcome.SUCCESS, severity=Severity.INFO,
                    before_state={c.key: masked(c.key, c.before) for c in changes},
                    after_state={c.key: masked(c.key, c.after) for c in changes},
                )  # fmt: skip
            except (AuditError, RuntimeError) as exc:  # RuntimeError: no writer started
                raise SettingsAuditRefused from exc
            changed.extend(c.key for c in changes)

        return hook

    @router.get("/settings")
    async def get_settings(request: Request) -> Response:
        principal = await caller(request, Permission.SETTINGS_READ, GET_SETTINGS_QUERY)
        rows = await store().read(principal.user_id)
        return JSONResponse(effective(rows, viewing=_viewing(principal)))

    @router.patch("/settings")
    async def update_settings(request: Request) -> Response:
        principal = await caller(request, Permission.SETTINGS_WRITE, UPDATE_SETTINGS_QUERY)
        repo = store()
        try:
            patch = judge_patch(await _read_body(request))
        except PatchRefused as refused:
            raise _Problem("validation_failed", "The request is invalid.",
                           errors=refused.errors) from None  # fmt: skip
        changed: list[str] = []
        rows = await repo.apply(principal.user_id, patch, write_ahead=record(principal, changed))
        if changed:
            _log().info("user_settings_changed", user_id=str(principal.user_id), keys=changed)
        return JSONResponse(effective(rows, viewing=_viewing(principal)))

    return router


__all__ = ["SettingsAuditRefused", "make_user_settings_router"]

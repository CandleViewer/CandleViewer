"""`GET` and `DELETE /auth/session/view-as` (#3085; 22-api-openapi.yaml `getViewAs`, `endViewAs`
and "View-as session"): the viewer reads and ends its own session's view-as context.

Both act on the caller's own session, as the viewer (`x-rbac` scope `self`, SR-026): no
permission, no step-up, and the view-as guard passes them live or held (`OWN_OPERATIONS`). Both
stay behind the idle lock (Q6): `api.idle_lock` exempts neither, and each authenticates with the
routes' own acceptance rule, which refuses a locked session too. Neither is activity (contract
"Idle lock"). Neither reads the query string: neither operation declares a `422` (as
`authExtendSession`), and the target is only ever the one the session's row names.

GET evaluates the context at the auth clock (`ViewAsService.evaluate`), which ends one whose
viewer or target is no longer eligible and answers it held: `204` with none or a cleared one,
else `200` with its `ViewAsContext`, `active` while live and `expired` once held. The target's
names come from its users row whatever its status (Q12, `TargetNames`): an anonymised target
answers its surrogate username and a null display name.

DELETE leaves it (`ViewAsService.leave`): one conditional write ends a live context and clears
it, or clears a held one, and only an end writes `admin.view_as_ended`, which the service writes
and never waits on. These routes write no audit record of their own: a clear has none, and
neither has a call with nothing to leave (C-2.9). `leave` answers `None` when nothing applied, so
the route re-reads the session: one revoked since (a refresh rotated it away, or a logout)
answers `401`, never `204`, for a rotated session's successor still carries the context (the
client re-authenticates onto it and retries); any other answers `204`, nothing to leave.

Every failure is a problem: `401 unauthenticated` for no live session (one answer, no session
oracle), `401 session_idle_locked`, and `503 store_unavailable` for a session, view-as or users
read that fails (never a fallback) and on the fake backend, which has no view-as service: after
authenticating, as `GET /me` answers an unwired backend (before, when no session backend is
wired at all). A `503` on DELETE changed nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.idle_lock import idle_locked_problem, problem
from candleviewer.api.step_up import _bearer  # the guard's parse: one rule for both
from candleviewer.auth.errors import AuthError, SessionIdleLocked
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsBinding, ViewAsPhase
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

PATH: Final = "/auth/session/view-as"


class _Sessions(Protocol):
    async def authenticate_access_token(
        self, raw_access_token: str, *, touch: bool = False, allow_locked: bool = False
    ) -> SessionRecord: ...

    async def require_active(
        self, session_id: str, *, allow_locked: bool = False
    ) -> SessionRecord: ...


class AuthLike(Protocol):
    """The part of `AuthService` these routes use."""

    @property
    def sessions_is_active(self) -> bool: ...

    @property
    def sessions(self) -> _Sessions: ...


class OwnViewAs(Protocol):
    """`ViewAsService`'s part these routes use (`admin/view_as.py`)."""

    async def evaluate(self, record: SessionRecord, *, now: datetime) -> ViewAsBinding | None: ...

    async def leave(self, record: SessionRecord, *, now: datetime) -> SessionRecord | None: ...


class TargetNames(Protocol):
    """`SqlAlchemyIdentityProvider.names`: `(username, display_name)` of a users row whatever its
    status; `LookupError` for no row."""

    async def names(self, user_id: str) -> tuple[str, str | None]: ...


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _problem(code: ErrorCode, status: int, detail: str) -> JSONResponse:
    return problem(status, code.value, ERROR_META[code].title, detail)


def _unauthenticated() -> JSONResponse:
    return _problem(ErrorCode.UNAUTHENTICATED, 401, "Authentication is required.")


def _unwired() -> JSONResponse:
    return _problem(ErrorCode.STORE_UNAVAILABLE, 503, "No view-as backend is wired.")


def _unavailable(read: str, exc: Exception) -> JSONResponse:
    """A read that failed: logged by what it read and the error's class, never a session id."""
    _log().error("auth.view_as_route_failed", read=read, error=type(exc).__name__)
    detail = "The view-as context could not be read; try again shortly."
    return _problem(ErrorCode.STORE_UNAVAILABLE, 503, detail)


def make_view_as_router(
    auth: AuthLike,
    *,
    views: Callable[[], OwnViewAs | None],
    names: TargetNames | None,
    clock: Callable[[], datetime],
) -> APIRouter:
    """*views* is read per request (`create_app` builds the service after the routers; `None` on
    the fake backend). *names* reads the target's users row; *clock* is the auth clock."""
    router = APIRouter(tags=["auth"])

    async def _caller(request: Request) -> SessionRecord | Response:
        """The bearer's live session, as the routes' acceptance rule finds it: never activity, and
        a locked one is refused."""
        if not auth.sessions_is_active:
            return _unwired()
        token = _bearer(request)
        if token is None:
            return _unauthenticated()
        try:
            return await auth.sessions.authenticate_access_token(token)
        except SessionIdleLocked as exc:
            return idle_locked_problem(exc.idle_locked_at)
        except AuthError:  # unknown, expired or revoked: one answer
            return _unauthenticated()
        except Exception as exc:  # never a fallback
            return _unavailable("session", exc)

    @router.get(PATH)
    async def get_view_as(request: Request) -> Response:
        record = await _caller(request)
        if isinstance(record, Response):
            return record
        service = views()
        if service is None or names is None:
            return _unwired()
        try:
            binding = await service.evaluate(record, now=clock())  # ends an ineligible one
        except Exception as exc:
            return _unavailable("view_as", exc)
        state = record.view_as
        if binding is None or state is None:  # none, or a cleared one
            return Response(status_code=204)
        try:
            username, display_name = await names.names(str(binding.target_user_id))
        except Exception as exc:  # `LookupError` too: the session's row keeps its target's
            return _unavailable("users", exc)
        context = api.ViewAsContext(
            target_user_id=binding.target_user_id,
            target_username=username,
            target_display_name=display_name,
            started_at=state.started_at,
            expires_at=state.expires_at,
            read_only=True,
            state="active" if binding.phase is ViewAsPhase.LIVE else "expired",
        )
        return JSONResponse(context.model_dump(mode="json"))

    @router.delete(PATH)
    async def end_view_as(request: Request) -> Response:
        record = await _caller(request)
        if isinstance(record, Response):
            return record
        service = views()
        if service is None:
            return _unwired()
        try:
            left = await service.leave(record, now=clock())
        except Exception as exc:  # the write did not apply: nothing changed
            return _unavailable("view_as", exc)
        if left is None:  # nothing applied: a revoked row's successor still carries the context
            try:
                await auth.sessions.require_active(str(record.id), allow_locked=True)
            except AuthError:
                return _unauthenticated()
            except Exception as exc:
                return _unavailable("session", exc)
        return Response(status_code=204)

    return router

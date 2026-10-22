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

from collections.abc import Callable, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Protocol
from uuid import UUID

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from candleviewer.admin.errors import ViewAsStartUnavailable
from candleviewer.admin.http import AuditEmitter, PrincipalResolver, admin_router
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.idle_lock import idle_locked_problem, problem
from candleviewer.api.step_up import (
    StepUpAuth,
    _bearer,  # the guard's parse: one rule for both
    require_elevation_for,
)
from candleviewer.api.step_up_challenge import ChallengeText, quote_label
from candleviewer.api.view_as_refusals import StartReason, ViewAsRefusalUnrecorded, Viewer
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.errors import AuthError, SessionIdleLocked
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsBinding, ViewAsPhase, ViewAsStartResult, ViewAsState
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


#: A `DELETE`'s 503: the leave did not apply, or its outcome could not be read back.
_NOT_LEFT: Final = "The view-as context could not be left; nothing changed."


def _unwired() -> JSONResponse:
    return _problem(ErrorCode.STORE_UNAVAILABLE, 503, "No view-as backend is wired.")


def _unavailable(
    read: str, exc: Exception, detail: str = "The view-as context could not be read."
) -> JSONResponse:
    """A read that failed: logged by what it read, the error's class and a traceback (which the
    redaction filter scans), never a session id. The catches are broad, so a defect would hide
    behind the 503 without the traceback, as `/me` logs its own."""
    _log().error("auth.view_as_route_failed", read=read, error=type(exc).__name__, exc_info=exc)
    return _problem(ErrorCode.STORE_UNAVAILABLE, 503, f"{detail} Try again shortly.")


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
        # None, or a cleared one (`evaluate` answers no binding then); `state` is never None
        # with a binding, and the test only narrows it for the type checker.
        if binding is None or state is None:
            return Response(status_code=204)
        try:
            username, display_name = await names.names(str(binding.target_user_id))
        except Exception as exc:  # `LookupError` too: the row's foreign key keeps the target's
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

    @router.delete(PATH)  # nosem: audit-write-required reason=audited-below-the-handler-in-ViewAsService-admin.view_as_ended owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def end_view_as(request: Request) -> Response:
        record = await _caller(request)
        if isinstance(record, Response):
            return record
        service = views()
        if service is None:
            return _unwired()
        try:
            left = await service.leave(record, now=clock())
        except Exception as exc:  # a store failure: the leave did not apply
            return _unavailable("view_as", exc, _NOT_LEFT)
        if left is None:  # nothing applied: a revoked row's successor still carries the context
            try:
                await auth.sessions.require_active(str(record.id), allow_locked=True)
            except AuthError:
                return _unauthenticated()
            except Exception as exc:
                return _unavailable("session", exc, _NOT_LEFT)
        return Response(status_code=204)

    return router


# -- #3085 S13b: `POST /admin/view-as` (`startViewAs`) ---------------------------------------------

START_PATH: Final = "/view-as"  # under the admin router's `/admin`
#: A start's body: a 500-character reason, every character escaped, fits with room to spare.
MAX_START_BODY_BYTES: Final = 8192
#: The refusals before the step-up gate, in the contract's order, and their statuses.
START_REFUSALS: Final[Mapping[StartReason, int]] = MappingProxyType(
    {
        "view_as_active": 409,
        "view_as_self_target": 403,
        "not_found": 404,
        "conflict": 409,
        "view_as_owner_target": 403,
    }
)
#: The statuses a target cannot be viewed in: a `locked` user is only locked out of signing in.
_UNVIEWABLE: Final = frozenset({"invited", "disabled"})


class StartViewAs(Protocol):
    """`ViewAsService.start` (`admin/view_as.py`)."""

    async def start(
        self, record: SessionRecord, target_user_id: UUID, *, reason: str, now: datetime
    ) -> ViewAsStartResult: ...


class StartRefusals(Protocol):
    """`ViewAsRefusalRecorder.refuse_start` (`api/view_as_refusals.py`)."""

    async def refuse_start(
        self,
        viewer: Viewer,
        reason: StartReason,
        *,
        target_user_id: UUID,
        held: ViewAsState | None = None,
        ip: str | None = None,
        request_id: str | UUID | None = None,
    ) -> bool: ...


class TargetUsers(Protocol):
    """`SqlAlchemyIdentityProvider.user`: an undeleted user's `User`; `LookupError` for none."""

    async def user(self, user_id: str) -> dict[str, Any]: ...


def _invalid(field: str, rule: str) -> JSONResponse:
    detail = "The body does not match StartViewAsRequest."
    errors = [{"field": field, "rule": rule}]
    code = ErrorCode.VALIDATION_FAILED
    return problem(422, code.value, ERROR_META[code].title, detail, errors=errors)


async def _start_body(request: Request) -> api.StartViewAsRequest | JSONResponse:
    """The body, or its `422`, which writes no record (22). Never echoed: no value, and no name of
    a member the contract lacks (`field` empty), so a reason reaches no answer and no log."""
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_START_BODY_BYTES:
            return _invalid("", "body_too_large")
    try:
        return api.StartViewAsRequest.model_validate_json(bytes(raw))
    except ValidationError as exc:
        first = exc.errors()[0]
        field = "" if first["type"] == "extra_forbidden" else ".".join(map(str, first["loc"]))
        return _invalid(field, first["type"])


def make_view_as_start_router(
    auth: StepUpAuth,
    *,
    resolver: PrincipalResolver | None,
    audit: AuditEmitter | None,
    views: Callable[[], StartViewAs | None],
    refusals: Callable[[], StartRefusals | None],
    users: TargetUsers | None,
    clock: Callable[[], datetime],
) -> APIRouter:
    """`POST /admin/view-as` (22 `startViewAs`) behind the admin-area guard (`users:write`), which
    records a caller without it as a denied `admin.area_entered` and answers `403 forbidden`.
    Then, in the contract's order and before the step-up gate (class `users`), so a refused start
    is never a challenge: `422` (no record), and each of `START_REFUSALS`, recorded as one
    `admin.view_as_refused` ahead of its answer within the viewer's own cap (`refusals`; one that
    cannot be written answers `503 audit_unavailable`). The start itself is `ViewAsService.start`'s
    one unit of work: `201` with the context, `409 view_as_active` (recorded) when a concurrent
    start won, `401` when the session went meanwhile, `503` when its records cannot be written.
    *views* and *refusals* are read per request (`None` on the fake backend: `503`)."""
    router = admin_router(Permission.USERS_WRITE, resolver=resolver, audit=audit)

    async def refused(
        recorder: StartRefusals,
        viewer: Viewer,
        reason: StartReason,
        target: UUID,
        who: AuditPrincipal,
        held: ViewAsState | None = None,
    ) -> JSONResponse:
        try:
            await recorder.refuse_start(
                viewer,
                reason,
                target_user_id=target,
                held=held,
                ip=who.ip,
                request_id=who.request_id,
            )
        except ViewAsRefusalUnrecorded:
            detail = "The refusal could not be recorded."
            return _problem(ErrorCode.AUDIT_UNAVAILABLE, 503, detail)
        code = ErrorCode(reason)
        return _problem(code, START_REFUSALS[reason], ERROR_META[code].title)

    @router.post(START_PATH, status_code=201)  # nosem: audit-write-required reason=write-ahead-inside-start_view_as_unit-under-the-row-lock-admin.view_as_started owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def start_view_as(request: Request) -> Response:
        who: AuditPrincipal = request.state.admin_principal  # left there by the guard
        body = await _start_body(request)
        if isinstance(body, JSONResponse):
            return body
        recorder = refusals()
        if recorder is None or users is None:
            return _unwired()
        try:  # the row itself: the guard authenticated it, and it may have gone since
            record: SessionRecord = await auth.sessions.authenticate_access_token(
                _bearer(request) or ""
            )
        except AuthError:
            return _unauthenticated()
        except Exception as exc:
            return _unavailable("session", exc)
        viewer, target = Viewer(record.user_id, record.id, who.actor_name), body.target_user_id
        held = record.view_as
        if held is not None and held.cleared_at is None:  # live or held, never replaced here
            return await refused(recorder, viewer, "view_as_active", target, who, held)
        if target == record.user_id:
            return await refused(recorder, viewer, "view_as_self_target", target, who)
        try:
            user = await users.user(str(target))
        except LookupError:
            return await refused(recorder, viewer, "not_found", target, who)
        except Exception as exc:
            return _unavailable("users", exc)
        if user["status"] in _UNVIEWABLE:
            return await refused(recorder, viewer, "conflict", target, who)
        if "owner" in user["roles"]:
            return await refused(recorder, viewer, "view_as_owner_target", target, who)
        if not auth.step_up_is_active:
            return _unwired()
        username = str(user["username"])
        summary = ChallengeText(f"View as user {quote_label(username)}, read-only")
        gate = await require_elevation_for(auth, str(record.id), "users", text=summary)
        if gate is not None:
            return gate
        service = views()
        if service is None:  # the fake backend: no context can start
            return _unwired()
        try:
            result = await service.start(record, target, reason=body.reason, now=clock())
        except ViewAsStartUnavailable as exc:
            return _problem(ErrorCode(exc.code), 503, "Nothing started; try again shortly.")
        started = result.started.view_as if result.started is not None else None
        if started is None:
            if result.held is not None and result.held.view_as is not None:  # a concurrent start
                return await refused(
                    recorder, viewer, "view_as_active", target, who, result.held.view_as
                )
            return _unauthenticated()  # the session was revoked or expired meanwhile
        context = api.ViewAsContext(
            target_user_id=target,
            target_username=username,
            target_display_name=user["display_name"],
            started_at=started.started_at,
            expires_at=started.expires_at,
            read_only=True,
            state="active",
        )
        return JSONResponse(context.model_dump(mode="json"), status_code=201)

    return router

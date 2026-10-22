"""The view-as guard (#3085; 22-api-openapi.yaml "View-as session"): the HTTP middleware that
makes a session viewing as another user read-only, and a session holding an ended context answer
nothing but its own operations.

`create_app` registers it inside CSRF, the idle lock and the enrolment check, and outside the
read-only/step-up guard: HttpDuration -> Correlation -> MeshOnly -> Csrf -> IdleLock -> Enrolment
-> ViewAs -> ReadOnly/StepUp -> routes. So it decides before authorisation, request validation,
the step-up gate and any idempotency binding: a refusal is never a step-up challenge and binds no
key, and a cross-site page cannot cause one.

For a request whose bearer names a session holding a context (`ViewAsPhase` not `NONE`):

| the operation                        | live                        | held                  |
|--------------------------------------|-----------------------------|-----------------------|
| the viewer's own (`OWN_OPERATIONS`)  | passes, as the viewer       | passes, as the viewer |
| protective, its handler registered   | passes to it, as the viewer | the same              |
| GET, HEAD or OPTIONS                 | passes, as the target       | `view_as_expired`     |
| any other                            | `view_as_read_only`         | `view_as_expired`     |

A protective write whose handler is not registered is refused as any write (the tripwire,
`ProtectiveWrites`). A live context is evaluated as a request's would be
(`ViewAsService.evaluate`): one whose viewer or target is no longer eligible ends there, and the
request answers `view_as_expired`. Before refusing a write, a read-only session gets the read-only
guard's own `session_read_only` (`assert_writable`, at most once a request), because the contract
decides the session state before view-as. Each refusal is counted, budgeted and recorded ahead
(`ViewAsRefusalRecorder.refuse_operation`); a due record that cannot be written answers
`503 audit_unavailable` and changes nothing. A session, eligibility or label read that fails
answers `503 store_unavailable`: never a fallback scope; only the viewer's own operations (leave,
logout) fall back to the viewer's id for a label they cannot read, as the end's record does. A
request that passes is stamped with its
`ViewAsRequestContext` (`request.scope["state"]["cv.view_as"]` and `bound_view_as`, reset when it
ends): the target is its subject only for a live read. With no context, a cleared one, no bearer,
a bearer that does not authenticate (the route answers 401), or no view-as service (the fake
backend), the request passes untouched. Inert until the start (#3085 S13b): no context can exist
before it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from typing import Any, Final, Protocol

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette._utils import get_route_path

from candleviewer.api.csrf import _compile_operations, bounded_method, match_operation, source_ip
from candleviewer.api.step_up import (
    _SAFE_METHODS,
    _WRITE_EXEMPT_PATHS,
    StepUpAuth,
    _bearer,
    readonly_problem,
)
from candleviewer.api.view_as_policy import OWN_OPERATIONS, ProtectiveWrites
from candleviewer.api.view_as_refusals import (
    OperationReason,
    ViewAsRefusalRecorder,
    ViewAsRefusalUnrecorded,
)
from candleviewer.api.view_as_subject import STATE_KEY as STATE_KEY
from candleviewer.api.view_as_subject import ViewAsUnstamped as ViewAsUnstamped
from candleviewer.auth.errors import AuthError, SessionReadOnly
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import (
    ViewAsBinding,
    ViewAsPhase,
    ViewAsRequestContext,
    bound_view_as,
    view_as_phase,
)
from candleviewer.observability.context import current_request_uuid
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_DETAILS: Final[dict[str, str]] = {
    "view_as_read_only": "This session is viewing as another user and changes nothing; "
    "end view-as to make changes.",
    "view_as_expired": "The view-as context has ended; clear it with DELETE /auth/session/view-as.",
    "audit_unavailable": "The refusal could not be recorded; nothing changed. Try again shortly.",
    "store_unavailable": "The session could not be checked; try again shortly.",
}

CallNext = Callable[[Request], Awaitable[Response]]


class ViewAsViews(Protocol):
    """`ViewAsService`'s part the guard uses (`admin/view_as.py`)."""

    async def evaluate(self, record: SessionRecord, *, now: datetime) -> ViewAsBinding | None: ...

    async def viewer_label(self, record: SessionRecord) -> str: ...


def _log() -> Any:
    return structlog.get_logger(__name__)


def _problem(code: ErrorCode, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://candleviewer.local/errors/{code.value}",
            "title": ERROR_META[code].title,
            "status": status,
            "code": code.value,
            "detail": _DETAILS[code.value],
        },
        media_type="application/problem+json",
    )


def _unavailable(read: str, exc: BaseException) -> JSONResponse:
    _log().error("auth.view_as_guard_failed", read=read, error=type(exc).__name__)
    return _problem(ErrorCode.STORE_UNAVAILABLE, 503)


async def view_as_unstamped_handler(request: Request, exc: Exception) -> Response:
    """`ViewAsUnstamped` -> `503 store_unavailable` (fail closed)."""
    return _unavailable("stamp", exc)


def make_view_as_guard(
    auth: StepUpAuth,
    *,
    views: Callable[[], ViewAsViews | None],
    refusals: Callable[[], ViewAsRefusalRecorder | None],
    protective: ProtectiveWrites,
    operations: Iterable[tuple[str, str]],
    clock: Callable[[], datetime],
) -> Callable[[Request, CallNext], Awaitable[Response]]:
    """HTTP middleware body; see the module docstring. *views* and *refusals* are read per request
    (`create_app` builds them after the middleware stack); *operations* are the contract's
    declared operations, which name a refused one (`match_operation`, never the raw path); *clock*
    is the auth clock."""
    declared = frozenset(operations)
    if not OWN_OPERATIONS <= declared:
        raise ValueError(f"undeclared own operations: {sorted(OWN_OPERATIONS - declared)}")
    templates = _compile_operations(declared)

    async def view_as_guard(request: Request, call_next: CallNext) -> Response:
        service, token = views(), _bearer(request)
        if service is None or token is None or not auth.sessions_is_active:
            return await call_next(request)
        method, path = bounded_method(request.method), get_route_path(request.scope)
        operation = (method, match_operation(method, path, templates))
        try:
            record = await auth.sessions.authenticate_access_token(token, allow_locked=True)
        except AuthError:
            return await call_next(request)  # no live session: the route answers itself
        except Exception as exc:  # fail closed: a session that cannot be read reaches nothing
            return _unavailable("session", exc)
        now = clock()
        if view_as_phase(record.view_as, now=now) is ViewAsPhase.NONE:
            return await call_next(request)
        own = operation in OWN_OPERATIONS
        as_viewer = own or protective.is_registered(operation)
        try:
            label = await service.viewer_label(record)
        except Exception as exc:
            if not own:  # never a fallback scope
                return _unavailable("view_as", exc)
            _log().warning("auth.view_as_label_unread", error=type(exc).__name__)
            label = str(record.user_id)  # leaving and logging out never wait on the users row
        try:
            if not as_viewer:
                binding = await service.evaluate(record, now=now)  # ends an ineligible one
            else:  # these act as the viewer: no eligibility read
                binding = None if record.view_as is None else record.view_as.binding(now=now)
        except Exception as exc:  # never a fallback scope
            return _unavailable("view_as", exc)
        if binding is None:  # only a revoked row reads `None` here: never "no context" (S4-SEC-02)
            return _unavailable("view_as", LookupError("unbound"))
        reads = binding.phase is ViewAsPhase.LIVE and method in _SAFE_METHODS
        context = ViewAsRequestContext(
            viewer_user_id=record.user_id,
            viewer_session_id=record.id,
            viewer_label=label,
            target_user_id=binding.target_user_id,
            context_id=binding.context_id,
            subject_user_id=binding.target_user_id if reads and not as_viewer else record.user_id,
            phase=binding.phase,
        )
        if as_viewer or reads:
            request.scope.setdefault("state", {})[STATE_KEY] = context
            with bound_view_as(context):
                return await call_next(request)
        if method not in _SAFE_METHODS and path not in _WRITE_EXEMPT_PATHS:
            readonly = await _session_read_only(auth, record)
            if readonly is not None:
                return readonly
        reason: OperationReason = (
            "view_as_read_only" if binding.phase is ViewAsPhase.LIVE else "view_as_expired"
        )
        return await _refuse(refusals(), context, reason, operation, source_ip(request.scope))

    return view_as_guard


async def _session_read_only(auth: StepUpAuth, record: SessionRecord) -> Response | None:
    """The read-only guard's `session_read_only`, first (22: the session state comes before
    view-as). Without step-up there is no downgrade, and the write is refused all the same."""
    if not auth.step_up_is_active:
        return None
    try:
        await auth.step_up.assert_writable(str(record.id))
    except SessionReadOnly as exc:
        return readonly_problem(exc)
    except AuthError:
        return None  # as the read-only guard: no downgrade to report, and the write is refused
    except Exception as exc:
        return _unavailable("read_only", exc)
    return None


async def _refuse(
    recorder: ViewAsRefusalRecorder | None,
    context: ViewAsRequestContext,
    reason: OperationReason,
    operation: tuple[str, str],
    ip: str | None,
) -> Response:
    """Count, budget and record the refusal ahead of its `403`; no recorder, or a due record that
    cannot be written, answers `503 audit_unavailable` (C-2.9)."""
    if recorder is None:
        return _problem(ErrorCode.AUDIT_UNAVAILABLE, 503)
    method, template = operation
    try:
        await recorder.refuse_operation(
            context,
            reason,
            method=method,
            template=template,
            ip=ip,
            request_id=current_request_uuid(),
        )
    except ViewAsRefusalUnrecorded:
        return _problem(ErrorCode.AUDIT_UNAVAILABLE, 503)
    return _problem(ErrorCode(reason), 403)

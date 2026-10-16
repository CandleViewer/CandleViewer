"""The enrolment-only session at the HTTP edge (#2295; `22-api-openapi.yaml` "Enrolment-only
session").

A session whose user has `mfa_required` and no confirmed MFA method may call exactly
`ENROLMENT_OPERATIONS`; every other request it makes answers `403 mfa_enrollment_required` here,
before any handler, audit write or state change. The class is `AuthService.classify`, read from
the user's state on every request (no session flag). A request without a bearer, or whose bearer
has no live session, is left to the route (401, or a pre-session operation). A classification
that raises answers `503 store_unavailable`: deny by default (C-12.4). An enrolment-only session
that would outlive `ENROLMENT_ONLY_LIFETIME` was not minted as one (Q7) and gets 401 like an
expired session, except on `POST /auth/logout`.

Requests are matched on the routed path (`get_route_path`, as `api/step_up.py`; #2752).
`create_app` mounts this inside the CSRF guard and outside the read-only/step-up guard, so a
refused request never records a step-up challenge. The WebSocket refuses such a session at
`auth` (`app._session_authenticator`, `23-ws-protocol.md` §4.3).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, Response

# The router's own path function (see `api/step_up.py`, #2752): a move upstream fails the
# import, never open.
from starlette._utils import get_route_path

from candleviewer.auth.errors import AuthError
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import SessionClass

#: The only operations an enrolment-only session may call (decision on #2295, contract).
ENROLMENT_OPERATIONS: Final = frozenset(
    {
        ("POST", "/auth/mfa/enroll"),
        ("POST", "/auth/mfa/enroll/confirm"),
        ("GET", "/auth/session"),
        ("POST", "/auth/refresh"),
        ("POST", "/auth/logout"),
    }
)
#: Ending the session stays possible even when the session itself is refused.
_SIGN_OUT: Final = ("POST", "/auth/logout")
_RETRY_AFTER_S = 5
#: (status, code, title from `x-error-codes`, detail) of each answer.
_REFUSED = (
    403,
    "mfa_enrollment_required",
    "Session is enrolment-only; enrol and confirm a TOTP method first",
    "Set up two-factor authentication to continue.",
)
_EXPIRED = (
    401,
    "unauthenticated",
    "Missing, malformed or expired access token",
    "The enrolment-only session has expired; sign in again.",
)
_UNCLASSIFIED = (
    503,
    "store_unavailable",
    "QuestDB / Postgres / Parquet tier unavailable",
    "The session could not be checked; try again shortly.",
)

CallNext = Callable[[Request], Awaitable[Response]]


class _Sessions(Protocol):
    async def authenticate_access_token(
        self, raw_access_token: str, *, allow_locked: bool = ...
    ) -> SessionRecord: ...


class _Auth(Protocol):
    @property
    def enrolment_gate_is_active(self) -> bool: ...

    @property
    def sessions(self) -> _Sessions: ...

    async def classify(self, session: SessionRecord) -> SessionClass: ...


def _log() -> Any:
    return structlog.get_logger(__name__)


def _problem(answer: tuple[int, str, str, str], **extra: Any) -> JSONResponse:
    status, code, title, detail = answer
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://candleviewer.local/errors/{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
            **extra,
        },
        media_type="application/problem+json",
    )


def _bearer(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def make_enrolment_only_guard(auth: _Auth) -> Callable[[Request, CallNext], Awaitable[Response]]:
    """HTTP middleware body; see the module docstring."""

    async def guard(request: Request, call_next: CallNext) -> Response:
        token = _bearer(request)
        if token is None or not auth.enrolment_gate_is_active:
            return await call_next(request)
        try:
            # An idle-locked session is classified too: a route that accepts one
            # (`DELETE /me/sessions/{sessionId}`) must not serve an enrolment-only session.
            record = await auth.sessions.authenticate_access_token(token, allow_locked=True)
        except AuthError:
            return await call_next(request)  # no live session: the route answers itself
        try:
            verdict = await auth.classify(record)
        except Exception as exc:  # fail closed: an unclassified session reaches no handler
            _log().error("auth.enrolment_guard.unclassified", error=type(exc).__name__)
            response = _problem(_UNCLASSIFIED, retry_after_seconds=_RETRY_AFTER_S)
            response.headers["Retry-After"] = str(_RETRY_AFTER_S)
            return response
        operation = (request.method, get_route_path(request.scope))
        if verdict is SessionClass.FULL:
            return await call_next(request)
        if verdict is SessionClass.ENROLMENT_ONLY_EXPIRED and operation != _SIGN_OUT:
            return _problem(_EXPIRED)
        if operation in ENROLMENT_OPERATIONS:
            return await call_next(request)
        _log().info("auth.enrolment_guard.refused", session_id=str(record.id))
        return _problem(_REFUSED)

    return guard


__all__ = ["ENROLMENT_OPERATIONS", "make_enrolment_only_guard"]

"""The idle lock at the HTTP edge (#2300; E09-D06 ruling on PR #2290).

Contract: `docs/plan/22-api-openapi.yaml` info "Idle lock", `x-error-codes`
`session_idle_locked` / `unlock_invalid` / `session_revoked`, `SessionState`.

A session past its `idle_deadline` is idle-locked, not revoked: WS frames keep
flowing (ADR-0020 section 4) and the session can be unlocked with the password
(`POST /auth/unlock`) or signed out. Every other authenticated operation answers
a request from a locked session with `401 session_idle_locked` (problem field
`idle_locked_at`) and changes nothing.

`IdleLockMiddleware` enforces that once, for every route, so no router can
forget it: a pure ASGI middleware mounted inside `CsrfMiddleware` that never
reads a body. It authenticates the bearer with the routes' own acceptance rule
(`authenticate_access_token`, never activity) and refuses only the request that
rule refuses as idle-locked (`SessionIdleLocked`: access token inside its
lifetime, session neither revoked nor past its absolute lifetime). Any other
refusal passes through untouched, so the route answers its own uniform `401`
(no session oracle), and an expired access token stays `unauthenticated`. A
store failing under the call (`RuntimeError`) leaves the lock unchecked: the gate
fails closed with `GET /me`'s `503 store_unavailable` and log line (#3300), which
also names the route; any other store error reaches the boundary handler (`500`),
as for `GET /me`. No route runs either way. It does not gate the operations
allowed while locked, nor the ones the contract does not authenticate with a
bearer (public ones, and `POST /auth/refresh`, which refuses a locked session
itself). Those match their exact path; anything else is gated (fail closed).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

import structlog
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from candleviewer.api.csrf import _compile_operations, bounded_method, match_operation, route_path
from candleviewer.api.deny_by_default import declared_operations
from candleviewer.auth.errors import AuthError, SessionIdleLocked
from candleviewer.auth.models import SessionRecord

#: The operations an idle-locked session may call (#2290 ruling, rule 3a).
LOCKED_OK_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {("POST", "/auth/unlock"), ("POST", "/auth/logout"), ("GET", "/auth/session")}
)
_ERRORS = "https://candleviewer.local/errors/"
_HTTP_METHODS = frozenset({"get", "put", "post", "patch", "delete", "head", "options", "trace"})
#: `Problem.revoked_reason`: any other revocation is `revoked`, its cause undisclosed.
_DISCLOSED_REVOCATIONS = frozenset({"expired", "unlock_attempts_exceeded"})


class SessionsLike(Protocol):
    async def authenticate_access_token(self, raw_access_token: str) -> SessionRecord: ...


def problem(status: int, code: str, title: str, detail: str, **extra: Any) -> JSONResponse:
    """An RFC 7807 problem for a registered `x-error-codes` entry."""
    return JSONResponse(
        status_code=status,
        content={
            "type": _ERRORS + code,
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
            **extra,
        },
        media_type="application/problem+json",
    )


def idle_locked_problem(idle_locked_at: datetime | None) -> JSONResponse:
    """`401 session_idle_locked`; `idle_locked_at` is the moment the session locked."""
    extra = {} if idle_locked_at is None else {"idle_locked_at": idle_locked_at.isoformat()}
    return problem(
        401,
        "session_idle_locked",
        "Session is idle-locked; unlock it with the password (POST /auth/unlock)",
        "Unlock with your password to continue.",
        **extra,
    )


def unlock_invalid_problem() -> JSONResponse:
    """`401 unlock_invalid`: the same generic `detail` for every wrong password."""
    return problem(401, "unlock_invalid", "Unlock password rejected", "The password is incorrect.")


def session_revoked_problem(reason: str) -> JSONResponse:
    """`401 session_revoked` for a revocation *reason* (`sessions.revoked_reason`)."""
    revoked_reason = reason if reason in _DISCLOSED_REVOCATIONS else "revoked"
    expired = revoked_reason == "expired"
    return problem(
        401,
        "session_revoked",
        "Session revoked or past its absolute lifetime; sign in again",
        "Your session expired. Sign in again." if expired else "Your session ended. Sign in again.",
        revoked_reason=revoked_reason,
    )


def not_locked_problem() -> JSONResponse:
    """`409 conflict`: unlock of a live session that is not idle-locked."""
    return problem(
        409,
        "conflict",
        "Concurrent modification or state conflict",
        "The session is not locked.",
    )


def store_unavailable_problem() -> JSONResponse:
    """`503 store_unavailable`: the session store failed under a bearer check (`GET /me`, #3300)."""
    return problem(503, "store_unavailable", "Session store unavailable", "No session backend.")


def session_state(record: SessionRecord, *, now: datetime) -> dict[str, Any]:
    """`SessionState`: the server truth CMP-098 and SCR-005 time against."""
    return {
        "id": str(record.id),
        "issued_at": record.issued_at.isoformat(),
        "expires_at": record.expires_at.isoformat(),
        "idle_deadline": record.idle_deadline().isoformat(),
        "idle_timeout_s": record.idle_timeout_s,
        "locked": record.is_idle_locked(now=now),
    }


def ungated_operations(spec: dict[str, Any]) -> frozenset[tuple[str, str]]:
    """(METHOD, path) the gate passes: the operations allowed while locked, and
    every operation whose contract `security` does not include `bearerAuth`.

    An operation without its own `security` takes the document's root default. The packaged
    contract subset that `create_app()` reads (#2555) carries no root default, so there such
    an operation stays gated: the gate fails closed and passes nothing the YAML protects."""
    default = spec.get("security")
    out = set(LOCKED_OK_OPERATIONS)
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            security = op.get("security", default)
            if security is not None and not any(
                "bearerAuth" in requirement for requirement in security
            ):
                out.add((method.upper(), path))
    return frozenset(out)


def _bearer(headers: Headers) -> str | None:
    scheme, _, value = headers.get("authorization", "").partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class IdleLockMiddleware:
    """Pure ASGI idle-lock gate; see the module docstring."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        sessions: Callable[[], SessionsLike | None],
        spec: dict[str, Any],
    ) -> None:
        self._app = app
        self._sessions = sessions
        self._ungated = ungated_operations(spec)
        self._operations = _compile_operations(frozenset(declared_operations(spec)))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self._is_ungated(scope):
            refusal = await self._idle_lock_refusal(scope)
            if refusal is not None:
                await refusal(scope, receive, send)
                return
        await self._app(scope, receive, send)

    def _is_ungated(self, scope: Scope) -> bool:
        return (str(scope["method"]).upper(), route_path(scope["path"])) in self._ungated

    async def _idle_lock_refusal(self, scope: Scope) -> JSONResponse | None:
        """The `session_idle_locked` 401 when the bearer's own authentication refuses
        it as idle-locked (`require_active` counts `auth_idle_locks_total`)."""
        token = _bearer(Headers(scope=scope))
        sessions = self._sessions()
        if token is None or sessions is None:
            return None
        try:
            await sessions.authenticate_access_token(token)
        except SessionIdleLocked as exc:
            return idle_locked_problem(exc.idle_locked_at)
        except AuthError:
            return None  # unknown, expired, revoked: the route answers its own 401
        except RuntimeError as exc:
            # Fail closed (C-12.4): a store failing under the call leaves the lock unchecked, so
            # no route runs. `GET /me`'s answer and log line (#3300, #3053 item 2): the class name
            # and a traceback, which the redaction filter scans; the message gets no field. The
            # route is its contract template, never the raw path (a path may carry a credential).
            path = match_operation(scope["method"], route_path(scope["path"]), self._operations)
            log = _log().bind(method=bounded_method(scope["method"]), path=path)
            log.error("auth.me.session_backend_error", error=type(exc).__name__, exc_info=exc)
            return store_unavailable_problem()
        return None


__all__ = [
    "LOCKED_OK_OPERATIONS",
    "IdleLockMiddleware",
    "idle_locked_problem",
    "not_locked_problem",
    "problem",
    "session_revoked_problem",
    "session_state",
    "store_unavailable_problem",
    "ungated_operations",
    "unlock_invalid_problem",
]

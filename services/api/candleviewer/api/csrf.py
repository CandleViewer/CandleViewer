"""SR-041 double-submit CSRF enforcement at the HTTP edge (#2090).

Contract: `docs/plan/22-api-openapi.yaml` info "CSRF", `components.parameters.
CsrfToken`, `components.responses.CsrfTokenInvalid`.

`CsrfMiddleware` is a pure ASGI middleware (no blocking calls). On every
`POST`/`PUT`/`PATCH`/`DELETE` except the five pre-session operations it
requires, in order:

1. the `X-CSRF-Token` header and the `__Host-cv_csrf` cookie (`missing`);
2. header == cookie, constant time (`mismatch`);
3. a well-formed ``<nonce>.<mac>`` token (`bad_mac`);
4. a session the server resolves itself: the bearer access token's session,
   or for `POST /auth/refresh` the session bound to the presented refresh
   token. The MAC must verify for *that* session id (`wrong_session`). A
   request with no resolvable session is refused too, so header == cookie is
   never sufficient on its own.

There is no bearer exemption, no flag and no test bypass (C-4.14). A refusal
is `403 csrf_token_invalid`, an `auth.csrf_refused` audit record (C-2.9) and
`auth_csrf_refused_total{reason}`; neither the body nor the log nor the audit
record carries a token or cookie value.

The cookie helpers are used by the auth/session routers: issue on session
mint, rotate on refresh, re-issue on `GET /auth/session`, expire on logout.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from enum import StrEnum
from http.cookies import SimpleCookie
from typing import Any, Protocol

import structlog
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec, CsrfVerdict, tokens_equal
from candleviewer.auth.errors import AuthError
from candleviewer.auth.metrics import auth_csrf_refused_total
from candleviewer.auth.models import SessionRecord

CSRF_ERROR_CODE = "csrf_token_invalid"
CSRF_PROBLEM_TYPE = f"https://candleviewer.local/errors/{CSRF_ERROR_CODE}"
_TITLE = "CSRF token missing, not matching the __Host-cv_csrf cookie, or not bound to this session"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_API_PREFIX = "/api/v1"
#: The pre-session operations (contract info "CSRF", "Exempt"). POST only.
_EXEMPT_PATH = re.compile(
    r"^/(?:auth/login|auth/mfa/verify|auth/mfa/recovery|invites/[^/]+(?:/confirm)?)$"
)
_REFRESH_PATH = "/auth/refresh"
_REFRESH_COOKIE = "cv_refresh"
#: `POST /auth/refresh` bodies are `{"refresh_token": "..."}`; anything larger
#: cannot name a session and is refused without buffering further (C-2.18).
_MAX_REFRESH_BODY = 4096
#: Any non-empty id: used only to run the shape checks of `CsrfCodec.verify`.
_PROBE_SID = "-"


class CsrfRefusal(StrEnum):
    """Closed reason set: audit `reason` and the metric label."""

    MISSING = "missing"
    MISMATCH = "mismatch"
    BAD_MAC = "bad_mac"
    WRONG_SESSION = "wrong_session"


_DETAIL = {
    CsrfRefusal.MISSING: "X-CSRF-Token header or __Host-cv_csrf cookie is missing.",
    CsrfRefusal.MISMATCH: "X-CSRF-Token header does not match the __Host-cv_csrf cookie.",
    CsrfRefusal.BAD_MAC: "X-CSRF-Token is malformed.",
    CsrfRefusal.WRONG_SESSION: "X-CSRF-Token is not bound to the current session.",
}


class SessionsLike(Protocol):
    async def authenticate_access_token(
        self, raw_access_token: str, *, touch: bool = False, allow_locked: bool = False
    ) -> SessionRecord: ...

    async def peek_refresh(self, raw_refresh_token: str) -> SessionRecord | None: ...


class AuditEmitterLike(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


def _log() -> Any:
    return structlog.get_logger(__name__)


def route_path(path: str) -> str:
    """Contract-relative path: the `/api/v1` server prefix is optional."""
    if path == _API_PREFIX or path.startswith(_API_PREFIX + "/"):
        return path[len(_API_PREFIX) :] or "/"
    return path


def is_exempt(method: str, path: str) -> bool:
    if method.upper() not in _UNSAFE_METHODS:
        return True
    return method.upper() == "POST" and _EXEMPT_PATH.match(route_path(path)) is not None


def set_csrf_cookie(response: Response, token: str, *, max_age: int) -> None:
    """`__Host-` prefix: Secure, Path=/, no Domain. Not HttpOnly: the client reads it."""
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=False,
        samesite="strict",
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, httponly=False, samesite="strict")


def csrf_problem(reason: CsrfRefusal) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "type": CSRF_PROBLEM_TYPE,
            "title": _TITLE,
            "status": 403,
            "code": CSRF_ERROR_CODE,
            "detail": _DETAIL[reason],
        },
        media_type="application/problem+json",
    )


def _cookies(headers: Headers) -> dict[str, str]:
    jar: SimpleCookie = SimpleCookie()
    out: dict[str, str] = {}
    for raw in headers.getlist("cookie"):
        try:
            jar.load(raw)
        except Exception:  # noqa: S112 -- a malformed cookie header is simply absent
            continue
    for name, morsel in jar.items():
        out[name] = morsel.value
    return out


def _bearer(headers: Headers) -> str | None:
    scheme, _, value = headers.get("authorization", "").partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


class CsrfMiddleware:
    """Pure ASGI SR-041 guard; see the module docstring."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        codec: CsrfCodec,
        sessions: Callable[[], SessionsLike | None],
        audit: AuditEmitterLike,
    ) -> None:
        self._app = app
        self._codec = codec
        self._sessions = sessions
        self._audit = audit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or is_exempt(scope["method"], scope["path"]):
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        cookies = _cookies(headers)
        header = headers.get(CSRF_HEADER)
        cookie = cookies.get(CSRF_COOKIE)
        if not header or not cookie:
            await self._refuse(scope, receive, send, CsrfRefusal.MISSING, None)
            return
        if not tokens_equal(header, cookie):
            await self._refuse(scope, receive, send, CsrfRefusal.MISMATCH, None)
            return
        record, receive = await self._resolve(scope, receive, headers, cookies)
        if record is None:
            # No session resolves: the request holds no session authority (no
            # ambient credential exists besides `cv_refresh`, resolved above)
            # and the route answers 401 itself, which keeps the client's
            # 401 -> refresh path intact. The token must still be well formed.
            if self._codec.verify(header, _PROBE_SID) is CsrfVerdict.BAD_MAC:
                await self._refuse(scope, receive, send, CsrfRefusal.BAD_MAC, None)
                return
            await self._app(scope, receive, send)
            return
        verdict = self._codec.verify(header, str(record.id))
        if verdict is not CsrfVerdict.OK:
            reason = (
                CsrfRefusal.BAD_MAC if verdict is CsrfVerdict.BAD_MAC else CsrfRefusal.WRONG_SESSION
            )
            await self._refuse(scope, receive, send, reason, record)
            return
        await self._app(scope, receive, send)

    async def _resolve(
        self, scope: Scope, receive: Receive, headers: Headers, cookies: dict[str, str]
    ) -> tuple[SessionRecord | None, Receive]:
        sessions = self._sessions()
        if sessions is None:
            return None, receive
        if route_path(scope["path"]) == _REFRESH_PATH:
            raw = cookies.get(_REFRESH_COOKIE)
            if not raw:
                raw, receive = await _refresh_token_from_body(receive)
            return (await sessions.peek_refresh(raw) if raw else None), receive
        token = _bearer(headers)
        if token is None:
            return None, receive
        try:
            # allow_locked: no touch, no state change; logout must work while locked.
            return await sessions.authenticate_access_token(token, allow_locked=True), receive
        except AuthError:
            return None, receive

    async def _refuse(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        reason: CsrfRefusal,
        record: SessionRecord | None,
    ) -> None:
        auth_csrf_refused_total.labels(reason=reason.value).inc()
        client = scope.get("client")
        ip = client[0] if client else None
        path = route_path(scope["path"])
        _log().warning("auth.csrf_refused", reason=reason.value, method=scope["method"], path=path)
        try:
            await self._audit.emit(
                "auth.csrf_refused",
                actor_label=str(record.user_id) if record is not None else "(unknown)",
                actor_user_id=record.user_id if record is not None else None,
                actor_ip=ip,
                session_id=record.id if record is not None else None,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason=reason.value,
                after_state={"method": scope["method"], "path": path},
            )
        except Exception:
            # The request is refused regardless (fail closed); only the record is lost.
            _log().error("auth.csrf_refused.audit_unavailable", reason=reason.value)
        await csrf_problem(reason)(scope, receive, send)


async def _refresh_token_from_body(receive: Receive) -> tuple[str | None, Receive]:
    """Read at most `_MAX_REFRESH_BODY` bytes of a refresh body to find
    `refresh_token`; every consumed message is replayed to the route unchanged."""
    consumed: list[Message] = []
    size = 0
    complete = False
    while not complete and size <= _MAX_REFRESH_BODY:
        message = await receive()
        consumed.append(message)
        if message["type"] != "http.request":
            break
        size += len(message.get("body", b""))
        complete = not message.get("more_body", False)

    async def replay() -> Message:
        if consumed:
            return consumed.pop(0)
        return await receive()

    if not complete or size > _MAX_REFRESH_BODY:
        return None, replay
    buffered = b"".join(m.get("body", b"") for m in consumed if m["type"] == "http.request")
    try:
        parsed = json.loads(buffered) if buffered else None
    except ValueError:
        parsed = None
    token: str | None = None
    if isinstance(parsed, dict) and isinstance(parsed.get("refresh_token"), str):
        token = parsed["refresh_token"] or None
    return token, replay

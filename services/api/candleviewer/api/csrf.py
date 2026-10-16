"""SR-041 double-submit CSRF and SR-042 Origin enforcement at the HTTP edge (#2090).

Contract: `docs/plan/22-api-openapi.yaml` info "CSRF", `components.parameters.
CsrfToken`, `components.responses.CsrfTokenInvalid`.

`CsrfMiddleware` is a pure ASGI middleware (no blocking calls) mounted inside
`MeshOnlyMiddleware`, so off-mesh traffic never reaches it. Every method except
`GET`/`HEAD`/`OPTIONS` (the contract's safe set) is state-changing. For those requests, in order:

0. a path containing a control character is refused with 400 before anything
   else (Starlette's `$` route regex tolerates a trailing newline; exact
   matching here must never disagree with the router);
1. SR-042: `Sec-Fetch-Site: cross-site` is refused, and a present `Origin`
   must be in `Settings.allowed_origins`. This also covers the 5 exempt
   pre-session operations. A missing `Origin` is allowed (non-browser
   clients); the double-submit token below is what binds those.

Then, except for the five pre-session operations (contract "Exempt"):

2. `X-CSRF-Token` and the `__Host-cv_csrf` cookie are both present (`missing`);
3. header == cookie, constant time (`mismatch`);
4. a well-formed ``<nonce>.<mac>`` token (`bad_mac`);
5. a session the server resolves itself: the session the bearer handle was
   issued for (looked up even when the access token has expired, so an expired
   bearer still gets its MAC verified before the route answers 401). The MAC
   must verify for that session id (`wrong_session`). If no session resolves,
   or the sessions backend is not wired, the request is refused
   (`wrong_session`): header == cookie is never sufficient on its own.

`POST /auth/refresh` and `POST /auth/unlock` (exact paths) are the exceptions to
steps 2-5: each acts on a session the route itself loads. Refresh's is the one
bound to the presented refresh token. Unlock's is the access token's, or the
`cv_refresh` cookie's when no access token is inside its lifetime (contract
"Idle lock", #2300). After its throttles (and, for refresh, reuse detection: a
rotated-out token only revokes, never mints), the route runs the full check with
`verify_refresh_csrf()` against that session before it audits or changes
anything. `POST /auth/logout` (exact path) is a partial exception, only when
that cookie identifies it: the cookie is present and no access token inside its
lifetime is (no bearer, or one past `ACCESS_TOKEN_TTL`). Steps 2-4 still run
here; step 5, the binding, is the route's, against the cookie's session. A
logout identified by its access token is bound here, like every other bearer
request. The middleware never reads a request body, so a body it cannot read
can never weaken the check.

A refusal is always `403 csrf_token_invalid` (`detail` never echoes a value),
`auth_csrf_refused_total{reason}`, and an `auth.csrf_refused` audit record
(C-2.9) with a bounded path (the contract route template or `(unmatched)`), up to
a budget: per session for refusals bound to a live session, per source IP for the
rest, plus a global cap on audits in flight (C-2.18). Over a budget the reply is
the same 403 with `Retry-After` and no audit write; the metric keeps counting
(`audit_throttled`). The audit write is never cancelled mid-append (see
`RefusalAuditTracker`); a slow or failed write still refuses the request.
There is no bearer exemption, no flag and no test bypass (C-4.14).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

import structlog
from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec, CsrfVerdict, tokens_equal
from candleviewer.auth.metrics import auth_csrf_refused_total
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL, is_live_session
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.net import RESOLVED_SOURCE_KEY
from candleviewer.observability.context import spawn

CSRF_ERROR_CODE = "csrf_token_invalid"
CSRF_PROBLEM_TYPE = f"https://candleviewer.local/errors/{CSRF_ERROR_CODE}"
#: The refresh-token cookie (contract `refreshCookie`), `Path=/api/v1/auth`.
REFRESH_COOKIE = "cv_refresh"
_TITLE = "CSRF token missing, not matching the __Host-cv_csrf cookie, or not bound to this session"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})  # contract "Exempt"; TRACE is guarded
_API_PREFIX = "/api/v1"
#: The five pre-session operations (contract info "CSRF", "Exempt"), POST only.
#: One invite-token path segment: no `/`, no `%2F`-decoded separators.
_EXEMPT_PATH = re.compile(
    r"/(?:auth/login|auth/mfa/verify|auth/mfa/recovery|invites/[^/]+|invites/[^/]+/confirm)"
)
REFRESH_PATH = "/auth/refresh"
UNLOCK_PATH = "/auth/unlock"
LOGOUT_PATH = "/auth/logout"
#: POSTs whose route runs the SR-041 check itself, against the session it loads.
_ROUTE_CHECKED_PATHS = frozenset({REFRESH_PATH, UNLOCK_PATH})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_UNMATCHED = "(unmatched)"
#: Refusals not bound to a live session, per source IP per window, that are
#: audited; beyond that the reply is the same 403 + Retry-After with no audit row.
ANON_REFUSALS_PER_WINDOW = 20
ANON_REFUSAL_WINDOW_S = 60.0
AUDIT_TIMEOUT_S = 2.0
#: Refusals bound to a live session, per session per window, that are audited.
SESSION_REFUSALS_PER_WINDOW = 20
#: Hard cap on refusal audits in flight (C-2.18): during a WAL stall the shielded
#: writes would otherwise pile up behind `_wal_lock` ahead of order-path audits.
MAX_INFLIGHT_AUDITS = 64


class CsrfRefusal(StrEnum):
    """Closed reason set: audit `reason` and the metric label."""

    MISSING = "missing"
    MISMATCH = "mismatch"
    BAD_MAC = "bad_mac"
    WRONG_SESSION = "wrong_session"
    CROSS_ORIGIN = "cross_origin"


_DETAIL = {
    CsrfRefusal.MISSING: "X-CSRF-Token header or __Host-cv_csrf cookie is missing.",
    CsrfRefusal.MISMATCH: "X-CSRF-Token header does not match the __Host-cv_csrf cookie.",
    CsrfRefusal.BAD_MAC: "X-CSRF-Token is malformed.",
    CsrfRefusal.WRONG_SESSION: "X-CSRF-Token is not bound to the current session.",
    CsrfRefusal.CROSS_ORIGIN: "Cross-origin state-changing request refused.",
}


class SessionsLike(Protocol):
    async def peek_access_token(self, raw_access_token: str) -> SessionRecord | None: ...


class AuditEmitterLike(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


def _log() -> Any:
    return structlog.get_logger(__name__)


def route_path(path: str) -> str:
    """Contract-relative path: the `/api/v1` server prefix is optional."""
    if path == _API_PREFIX or path.startswith(_API_PREFIX + "/"):
        return path[len(_API_PREFIX) :] or "/"
    return path


def is_unsafe(method: str) -> bool:
    return method.upper() not in _SAFE_METHODS


def is_exempt(method: str, path: str) -> bool:
    """True for safe methods and the five pre-session POSTs (exact match)."""
    if not is_unsafe(method):
        return True
    return method.upper() == "POST" and _EXEMPT_PATH.fullmatch(route_path(path)) is not None


def set_csrf_cookie(response: Response, token: str, *, max_age: int) -> None:
    """`__Host-` prefix: Secure, Path=/, no Domain. Deliberately NOT HttpOnly: the client
    must read it (contract `csrfCookie`, SR-041). The value is a session-bound MAC, not a
    credential, so it is the one documented exception to SR-012's HttpOnly rule."""
    response.set_cookie(CSRF_COOKIE, token, max_age=max_age, path="/", secure=True, httponly=False, samesite="strict")  # nosem: cookie-flags reason=SR-041-double-submit-cookie-must-be-script-readable owner=@CandleViewer/security review=2027-03-31  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip


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


def verify_refresh_csrf(
    codec: CsrfCodec, header: str | None, cookie: str | None, session_id: str
) -> CsrfRefusal | None:
    """SR-041 check for `POST /auth/refresh`, run by the route against the exact
    session it is about to rotate. `None` means OK."""
    if not header or not cookie:
        return CsrfRefusal.MISSING
    if not tokens_equal(header, cookie):
        return CsrfRefusal.MISMATCH
    verdict = codec.verify(header, session_id)
    if verdict is CsrfVerdict.OK:
        return None
    return CsrfRefusal.BAD_MAC if verdict is CsrfVerdict.BAD_MAC else CsrfRefusal.WRONG_SESSION


def _cookies(headers: Headers) -> dict[str, str]:
    """Same lenient parser Starlette uses for `Request.cookies`, so the guard and
    the routes (e.g. the `GET /auth/session` re-issue) always agree."""
    return cookie_parser(headers.get("cookie", ""))


def _bearer(headers: Headers) -> str | None:
    scheme, _, value = headers.get("authorization", "").partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def _origin_refused(headers: Headers, allowed: frozenset[str]) -> bool:
    """SR-042. `Sec-Fetch-Site` must be absent, `same-origin` or `none` (user-initiated):
    `cross-site` and `same-site` (a sibling host, e.g. another *.ts.net node) are refused.
    A present `Origin` must be in the allow-list; `null` never is. A missing `Origin`
    (non-browser client) is allowed: browsers always send it on unsafe cross-origin
    requests, and the double-submit token still binds the request."""
    if headers.get("sec-fetch-site", "").lower() in ("cross-site", "same-site"):
        return True
    origin = headers.get("origin")
    return origin is not None and origin.rstrip("/") not in allowed


def source_ip(scope: Scope) -> str | None:
    """The address MeshOnly admitted (trusted-proxy aware), else the socket peer."""
    state = scope.get("state") or {}
    admitted = state.get(RESOLVED_SOURCE_KEY)
    if admitted:
        return str(admitted)
    client = scope.get("client")
    return str(client[0]) if client else None


_STANDARD_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "POST", "PUT", "PATCH", "DELETE"})


def bounded_method(method: str) -> str:
    """Closed set for audit/log fields; anything else is `(other)`."""
    m = method.upper()
    return m if m in _STANDARD_METHODS else "(other)"


_Operation = tuple[str, re.Pattern[str], str]


def _compile_operations(operations: frozenset[tuple[str, str]]) -> tuple[_Operation, ...]:
    out: list[_Operation] = []
    for method, template in sorted(operations, key=lambda o: (o[1].count("{"), o)):
        segments = re.split(r"\{[^}]+\}", template)  # literal parts between placeholders
        pattern = "[^/]+".join(re.escape(part) for part in segments)
        out.append((method.upper(), re.compile(pattern), template))
    return tuple(out)


def match_operation(method: str, path: str, operations: tuple[_Operation, ...]) -> str:
    """The contract path template for (method, path) - fewest placeholders first."""
    m = method.upper()
    for op_method, pattern, template in operations:
        if op_method == m and pattern.fullmatch(path):
            return template
    return _UNMATCHED


class RefusalAuditTracker:
    """Bounded set of in-flight refusal audits (C-2.18).

    Each audit runs as a tracked task under `asyncio.shield` so a timeout never
    cancels `AuditWriter.emit` mid-append (cancelling would release the WAL lock
    while the append thread still runs; writer fix #2250). At most `cap` may be in
    flight: over the cap the caller skips the write (counted `audit_throttled`).
    `drain()` waits a bounded time at shutdown, before the audit module stops."""

    def __init__(self, cap: int = MAX_INFLIGHT_AUDITS) -> None:
        self._cap = cap
        self._tasks: set[asyncio.Task[None]] = set()
        self._timed_out: set[asyncio.Task[None]] = set()

    def __len__(self) -> int:
        return len(self._tasks)

    @property
    def full(self) -> bool:
        return len(self._tasks) >= self._cap

    def track(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        """Run *coro* as a tracked task (not a lifecycle `start`; nothing to stop)."""
        task = spawn(coro, name="csrf-refusal-audit")
        self._tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def mark_timed_out(self, task: asyncio.Task[None]) -> None:
        if not task.done():
            self._timed_out.add(task)

    def _done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        late = task in self._timed_out
        self._timed_out.discard(task)
        if late and not task.cancelled() and task.exception() is not None:
            # Only failures nobody awaited any more are reported here.
            exc = task.exception()
            _log().error("auth.csrf_refused.audit_failed_late", error=type(exc).__name__)

    async def drain(self, timeout_s: float = AUDIT_TIMEOUT_S) -> int:
        """Wait up to *timeout_s* for in-flight audits; returns how many remain."""
        pending = set(self._tasks)
        if pending:
            await asyncio.wait(pending, timeout=timeout_s)
        return len(self._tasks)


class CsrfMiddleware:
    """Pure ASGI SR-041/SR-042 guard; see the module docstring."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        codec: CsrfCodec,
        sessions: Callable[[], SessionsLike | None],
        audit: AuditEmitterLike,
        allowed_origins: frozenset[str],
        operations: frozenset[tuple[str, str]] = frozenset(),
        anon_throttle: PerIpLoginThrottle | None = None,
        audit_timeout_s: float = AUDIT_TIMEOUT_S,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        tracker: RefusalAuditTracker | None = None,
        session_throttle: PerIpLoginThrottle | None = None,
    ) -> None:
        self._app = app
        self._codec = codec
        self._sessions = sessions
        self._audit = audit
        self._allowed = allowed_origins
        self._anon = anon_throttle or PerIpLoginThrottle(
            max_attempts=ANON_REFUSALS_PER_WINDOW, window_s=ANON_REFUSAL_WINDOW_S
        )
        self._audit_timeout_s = audit_timeout_s
        self._operations = _compile_operations(operations)
        self._now = clock
        # `is None`, not `or`: an empty tracker has len() == 0 and is falsy.
        self.tracker = tracker if tracker is not None else RefusalAuditTracker()
        self._per_session = session_throttle or PerIpLoginThrottle(
            max_attempts=SESSION_REFUSALS_PER_WINDOW, window_s=ANON_REFUSAL_WINDOW_S
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_unsafe(scope["method"]):
            await self._app(scope, receive, send)
            return
        path: str = scope["path"]
        if _CONTROL.search(path):
            await _bad_path(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if _origin_refused(headers, self._allowed):
            await self._refuse(scope, receive, send, CsrfRefusal.CROSS_ORIGIN, None)
            return
        if is_exempt(scope["method"], path):
            await self._app(scope, receive, send)
            return
        if route_path(path) in _ROUTE_CHECKED_PATHS and scope["method"] == "POST":
            # Refresh and unlock run the whole SR-041 check themselves, against the
            # exact session they act on (after their throttles, before any audit or
            # state change): `verify_refresh_csrf`. The path is matched exactly
            # (control characters were refused above), so no variant reaches the
            # route without that check.
            await self._app(scope, receive, send)
            return
        header = headers.get(CSRF_HEADER)
        cookie = _cookies(headers).get(CSRF_COOKIE)
        if not header or not cookie:
            await self._refuse(scope, receive, send, CsrfRefusal.MISSING, None)
            return
        if not tokens_equal(header, cookie):
            await self._refuse(scope, receive, send, CsrfRefusal.MISMATCH, None)
            return
        if self._codec.verify(header, "-") is CsrfVerdict.BAD_MAC:  # shape only
            await self._refuse(scope, receive, send, CsrfRefusal.BAD_MAC, None)
            return
        record = await self._resolve(headers)
        if self._cookie_identified_logout(scope, headers, record):
            # Contract "Idle lock": no access token inside its lifetime identifies this
            # logout, so its `cv_refresh` cookie does. The route checks SR-042 Origin and
            # binds the token to that cookie's session (`verify_refresh_csrf`) before it
            # audits or revokes anything.
            await self._app(scope, receive, send)
            return
        if record is None:
            await self._refuse(scope, receive, send, CsrfRefusal.WRONG_SESSION, None)
            return
        if self._codec.verify(header, str(record.id)) is not CsrfVerdict.OK:
            await self._refuse(scope, receive, send, CsrfRefusal.WRONG_SESSION, record)
            return
        await self._app(scope, receive, send)

    async def _resolve(self, headers: Headers) -> SessionRecord | None:
        sessions = self._sessions()
        token = _bearer(headers)
        if sessions is None or token is None:
            return None
        return await sessions.peek_access_token(token)

    def _cookie_identified_logout(
        self, scope: Scope, headers: Headers, record: SessionRecord | None
    ) -> bool:
        """`POST /auth/logout` that the route identifies by `cv_refresh`: the cookie is
        present and no access token inside its lifetime identifies a session (none, or
        *record*, its session, is past `ACCESS_TOKEN_TTL`). A bearer this server never
        issued is not: the route refuses it without reading the cookie, so it stays here."""
        if scope["method"] != "POST" or route_path(scope["path"]) != LOGOUT_PATH:
            return False
        if REFRESH_COOKIE not in _cookies(headers):
            return False
        if _bearer(headers) is None:
            return True
        return record is not None and self._now() >= record.issued_at + ACCESS_TOKEN_TTL

    def _route_template(self, scope: Scope) -> str:
        """Bounded audit/log path: the contract operation the request targets
        (closed set), never raw input; `(unmatched)` otherwise."""
        return match_operation(scope["method"], route_path(scope["path"]), self._operations)

    @staticmethod
    def _take(throttle: PerIpLoginThrottle, key: str) -> bool:
        """True while *key* may still write refusal audit records (C-2.9 vs C-12.8)."""
        if throttle.is_blocked(key):
            return False
        throttle.record_failure(key)
        return True

    async def _refuse(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        reason: CsrfRefusal,
        record: SessionRecord | None,
    ) -> None:
        auth_csrf_refused_total.labels(reason=reason.value).inc()
        ip = source_ip(scope)
        path = self._route_template(scope)
        method = bounded_method(scope["method"])
        # Budgets: refusals bound to a live session (same rule as authentication) get a
        # per-session budget; everything else (no session, revoked / expired / locked
        # records, old leaked bearers) shares the per-IP budget. Plus a global cap on
        # audits in flight. Over any of them: same 403, no audit write.
        if record is not None and is_live_session(record, now=self._now()):
            throttle, key = self._per_session, f"sid:{record.id}"
        else:
            throttle, key = self._anon, ip or "(unknown)"
        response = csrf_problem(reason)
        log = _log()
        if self.tracker.full or not self._take(throttle, key):
            auth_csrf_refused_total.labels(reason="audit_throttled").inc()
            retry = throttle.retry_after_s(key) or int(self._audit_timeout_s) or 1
            response.headers["Retry-After"] = str(retry)
            log.warning("auth.csrf_refused.unaudited", reason=reason.value, path=path)
            await response(scope, receive, send)
            return
        log.warning("auth.csrf_refused", reason=reason.value, method=method, path=path)
        await self._emit_audit(
            reason.value,
            actor_label=str(record.user_id) if record is not None else "(unknown)",
            actor_user_id=record.user_id if record is not None else None,
            actor_ip=ip,
            session_id=record.id if record is not None else None,
            outcome=AuditOutcome.DENIED,
            severity=Severity.WARNING,
            reason=reason.value,
            after_state={"method": method, "path": path},
        )
        await response(scope, receive, send)

    async def _emit_audit(self, why: str, **fields: Any) -> None:
        """Write the refusal record without ever cancelling the writer mid-append:
        a tracked task under `asyncio.shield` (see `RefusalAuditTracker`). A slow write
        refuses at the timeout (`audit_slow`) and is left to finish; a failed write is
        `audit_unavailable`. Either way the request stays refused (fail closed)."""
        task = self.tracker.track(self._audit.emit("auth.csrf_refused", **fields))
        try:
            await asyncio.wait_for(asyncio.shield(task), self._audit_timeout_s)
        except TimeoutError:
            self.tracker.mark_timed_out(task)
            auth_csrf_refused_total.labels(reason="audit_slow").inc()
            _log().warning("auth.csrf_refused.audit_slow", reason=why)
        except Exception as exc:
            auth_csrf_refused_total.labels(reason="audit_unavailable").inc()
            _log().error(
                "auth.csrf_refused.audit_unavailable", reason=why, error=type(exc).__name__
            )


async def _bad_path(scope: Scope, receive: Receive, send: Send) -> None:
    await JSONResponse(
        status_code=400,
        content={
            "type": "https://candleviewer.local/errors/validation_failed",
            "title": "Request body or parameters failed schema validation",
            "status": 400,
            "code": "validation_failed",
            "detail": "Request path contains a control character.",
        },
        media_type="application/problem+json",
    )(scope, receive, send)

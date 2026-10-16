"""SR-041 double-submit CSRF and SR-042 Origin enforcement at the HTTP edge (#2090).

Contract: `docs/plan/22-api-openapi.yaml` info "CSRF", `components.parameters.
CsrfToken`, `components.responses.CsrfTokenInvalid`.

`CsrfMiddleware` is a pure ASGI middleware (no blocking calls) mounted inside
`MeshOnlyMiddleware`, so off-mesh traffic never reaches it. Every method except
`GET`/`HEAD`/`OPTIONS` (the contract's safe set) is state-changing. For those requests, in order:

0. a path containing a control character is refused with 400 before anything
   else (Starlette's `$` route regex tolerates a trailing newline; exact
   matching here must never disagree with the router);
1. SR-042: the allow-list decides. A present `Origin` must be in
   `Settings.allowed_origins` and is then admitted whatever `Sec-Fetch-Site`
   says (a listed app origin on another site works, as on the WS upgrade);
   any other present `Origin` is refused. A missing `Origin` is allowed
   (non-browser clients; the double-submit token below is what binds those)
   unless `Sec-Fetch-Site` is `cross-site` or `same-site`. This also covers
   the 5 exempt pre-session operations.

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

`POST /auth/refresh` (exact path) is the one exception to steps 2-5: its session
is the one bound to the presented refresh token, which the route itself loads.
After its throttles and reuse detection (a rotated-out token only revokes, never
mints), the route runs the full check with `verify_refresh_csrf()` before it
audits or rotates. The middleware never reads a request body, so a body it
cannot read can never weaken the check.

A refusal is always `403 csrf_token_invalid` (`detail` never echoes a value),
`auth_csrf_refused_total{reason}`, and an `auth.csrf_refused` audit record
(C-2.9) with a bounded path (the contract route template or `(unmatched)`), up to
a budget: per session for refusals bound to a live session, per source IP for the
rest, plus a global cap on audits in flight (C-2.18). Over a budget
(`audit_throttled`) or with the cap full of stuck writes (`audit_saturated`) the
reply is the same 403 with `Retry-After` and no audit write. The audit write is never
cancelled mid-append (see `RefusalAuditTracker`); one that outlasts the wait
(`audit_slow`) or fails (`audit_unavailable`) still refuses the request. Each counts
beside the refusal's own reason (`auth.metrics.CSRF_AUDIT_REASONS`), and the
`CsrfRefusalAuditUnavailable` / `CsrfRefusalAuditDegraded` alerts read them.
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
from candleviewer.auth.session_service import is_live_session
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.net import RESOLVED_SOURCE_KEY
from candleviewer.observability.context import spawn

CSRF_ERROR_CODE = "csrf_token_invalid"
CSRF_PROBLEM_TYPE = f"https://candleviewer.local/errors/{CSRF_ERROR_CODE}"
_TITLE = "CSRF token missing, not matching the __Host-cv_csrf cookie, or not bound to this session"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})  # contract "Exempt"; TRACE is guarded
_API_PREFIX = "/api/v1"
#: The five pre-session operations (contract info "CSRF", "Exempt"), POST only.
#: One invite-token path segment: no `/`, no `%2F`-decoded separators.
_EXEMPT_PATH = re.compile(
    r"/(?:auth/login|auth/mfa/verify|auth/mfa/recovery|invites/[^/]+|invites/[^/]+/confirm)"
)
REFRESH_PATH = "/auth/refresh"
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
    """SR-042: the allow-list decides, as on the WS upgrade (`23-ws-protocol.md` §2.5).

    A present `Origin` is admitted when it is in the allow-list, whatever `Sec-Fetch-Site`
    says, so a listed app origin on another site (the packaged Electron `app://` origin, a dev
    page on another port) works: a foreign page cannot make a browser send a listed `Origin`.
    Any other present `Origin` is refused, `null` included (it is never listed). A missing
    `Origin` (non-browser client; browsers always send one on unsafe cross-origin requests) is
    allowed, and the double-submit token still binds the request, unless the browser labelled it
    `Sec-Fetch-Site: cross-site` or `same-site` (a sibling host, e.g. another *.ts.net node):
    that request has no listed `Origin` either, so it is refused."""
    origin = headers.get("origin")
    if origin is not None:
        return origin.rstrip("/") not in allowed
    return headers.get("sec-fetch-site", "").lower() in ("cross-site", "same-site")


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


#: Called once for a tracked write that may be lost: it failed after its caller stopped
#: waiting, or it was still running when `drain()` gave up. The owner counts it.
LostWrite = Callable[[], None]


def _count_audit_unavailable() -> None:
    auth_csrf_refused_total.labels(reason="audit_unavailable").inc()


class RefusalAuditTracker:
    """Bounded set of in-flight refusal audits (C-2.18), and the accounting for the ones
    nobody waits for any more. Shared by the CSRF guard and the session-fixation audit, so
    it knows no metric: a consumer passes `on_lost` to `track()` to count its own writes.

    Each audit runs as a tracked task under `asyncio.shield` so a timeout never cancels
    `AuditWriter.emit` mid-append (that would release the WAL lock while the append thread
    still runs; writer fix #2250). At most `cap` may be in flight: over it the caller
    skips the write. A caller that stops waiting (timeout, or its request was cancelled)
    hands the task over with `mark_timed_out()`: when the write fails the tracker logs it
    and calls `on_lost`. `drain()` waits a bounded time at shutdown, before the audit
    module stops, and calls `on_lost` for each write still running (it may be lost)."""

    def __init__(self, cap: int = MAX_INFLIGHT_AUDITS) -> None:
        self._cap = cap
        self._tasks: dict[asyncio.Task[None], LostWrite | None] = {}
        self._timed_out: set[asyncio.Task[None]] = set()

    def __len__(self) -> int:
        return len(self._tasks)

    @property
    def full(self) -> bool:
        return len(self._tasks) >= self._cap

    def track(
        self, coro: Coroutine[Any, Any, None], *, on_lost: LostWrite | None = None
    ) -> asyncio.Task[None]:
        """Run *coro* as a tracked task (not a lifecycle `start`; nothing to stop)."""
        task = spawn(coro, name="csrf-refusal-audit")
        self._tasks[task] = on_lost
        task.add_done_callback(self._done)
        return task

    def mark_timed_out(self, task: asyncio.Task[None]) -> None:
        """The caller stopped waiting for *task* (timeout, or its request was cancelled):
        the tracker reports its failure when it ends."""
        if not task.done():
            self._timed_out.add(task)

    def _done(self, task: asyncio.Task[None]) -> None:
        on_lost = self._tasks.pop(task, None)
        if task not in self._timed_out:
            return  # the awaiting caller handles its outcome
        self._timed_out.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _log().error("auth.csrf_refused.audit_failed_late", error=type(exc).__name__)
            if on_lost is not None:
                on_lost()

    async def drain(self, timeout_s: float = AUDIT_TIMEOUT_S) -> int:
        """Wait up to *timeout_s* for in-flight audits; returns how many remain. Each one
        that remains may be lost when the audit module stops, so its `on_lost` is called
        once (a later failure of the same write is not reported again)."""
        pending = set(self._tasks)
        if pending:
            await asyncio.wait(pending, timeout=timeout_s)
        left = dict(self._tasks)
        for task, on_lost in left.items():
            self._timed_out.discard(task)
            if on_lost is not None:
                on_lost()
        return len(left)


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
        if route_path(path) == REFRESH_PATH and scope["method"] == "POST":
            # The refresh route runs the whole SR-041 check itself, against the exact
            # session it would rotate (after its throttles and reuse detection, before
            # any audit or rotation): `verify_refresh_csrf`. The path is matched exactly
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

    def _skip_reason(self, throttle: PerIpLoginThrottle, key: str) -> str | None:
        """Why this refusal's audit write is skipped, or `None` to write it. The cap on
        writes in flight is checked first, so a saturated tracker spends no budget."""
        if self.tracker.full:
            return "audit_saturated"
        return None if self._take(throttle, key) else "audit_throttled"

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
        skipped = self._skip_reason(throttle, key)
        if skipped is not None:
            auth_csrf_refused_total.labels(reason=skipped).inc()
            retry = throttle.retry_after_s(key) or int(self._audit_timeout_s) or 1
            response.headers["Retry-After"] = str(retry)
            log.warning(
                "auth.csrf_refused.unaudited", reason=reason.value, path=path, cause=skipped
            )
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
        """Write the refusal record without ever cancelling the writer mid-append: a tracked
        task under `asyncio.shield` (see `RefusalAuditTracker`). The request stays refused
        (fail closed) whatever happens to the write. One that outlasts the wait is
        `audit_slow`; one that fails is `audit_unavailable`, also when the writer raises
        `TimeoutError` itself (the task's own outcome decides, not the clock). A failure after
        the caller stopped waiting, or its request was cancelled, is the tracker's to report."""
        task = self.tracker.track(
            self._audit.emit("auth.csrf_refused", **fields), on_lost=_count_audit_unavailable
        )
        try:
            await asyncio.wait_for(asyncio.shield(task), self._audit_timeout_s)
        except TimeoutError:
            failure = task.exception() if task.done() and not task.cancelled() else None
            if failure is not None:
                self._audit_failed(why, failure)
                return
            self.tracker.mark_timed_out(task)
            auth_csrf_refused_total.labels(reason="audit_slow").inc()
            _log().warning("auth.csrf_refused.audit_slow", reason=why)
        except asyncio.CancelledError:
            self.tracker.mark_timed_out(task)
            raise
        except Exception as exc:
            self._audit_failed(why, exc)

    @staticmethod
    def _audit_failed(why: str, exc: BaseException) -> None:
        _count_audit_unavailable()
        _log().error("auth.csrf_refused.audit_unavailable", reason=why, error=type(exc).__name__)


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

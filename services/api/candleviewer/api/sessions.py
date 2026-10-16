"""`POST /auth/refresh`, `GET /auth/session`, `GET /auth/sessions`,
`POST /auth/logout` and `DELETE /me/sessions/{sessionId}` (E09-S03,
US-ONB-004/009; QA defect #1634), and the idle-lock routes `POST /auth/unlock`
and `POST /auth/session/extend` (#2300).

Thin HTTP adapter over `candleviewer.auth.session_service.SessionService`,
same shape as `api/auth.py`: structural Protocols, RFC 7807 problems, audit
emission here (`auth` may not import `audit`). Authentication is the opaque
bearer access token of ADR-0020 (hashed at rest, constant-time compared);
the `cv_refresh` cookie is `HttpOnly; Secure; SameSite=Strict;
Path=/api/v1/auth` and cookie-authenticated refreshes get an Origin check
(SR-042). The SR-041 `__Host-cv_csrf` token is enforced by `api.csrf.CsrfMiddleware`
and rotated here on refresh, re-issued by `GET /auth/session`, expired on logout.

**Identity seam (not invented here):** `SessionInfo`/`AuthenticatedResponse`
need `user`, `permissions` and `account_scope`, which come from the RBAC
decision point (E09-T03, PR #1629) and a user read path that `auth` does not
expose yet. They are supplied by an injected `IdentityProvider`; without one
`/auth/session` and `/auth/refresh` fail closed with `501` (and refresh
checks this *before* rotating anything, so no token is burned). Wiring the
provider — like wiring `principal_resolver` for #1596 — is composition-root
work owned elsewhere; this module does not touch `app.py`.

Revocation propagation (`23-ws-protocol.md` §9.5): every revoke path calls
the injected `publish_revocation(session_id, reason)`; the ws gateway
(`candleviewer.ws.revocation`) closes the matching socket with `4401`.

Session fixation (U6/SR-013, E09-X02 AC2): a bearer or refresh token that was
never issued here is refused with the same 401 as any other, and counted
(`auth_session_fixation_attempts_total`) and audited
(`auth.session_fixation_attempt`) within a per-IP and a global budget, through
the CSRF guard's in-flight-capped, shielded writer path. Expired or revoked
tokens of real sessions are not attempts and stay silent.

Idle lock (#2300, contract info "Idle lock"): activity is explicit, so no route
here re-stamps `last_seen_at` except `POST /auth/session/extend` and a successful
`POST /auth/unlock`, and a refresh carries the idle deadline over.
`GET /auth/session` and `POST /auth/unlock` serve a locked session, identified by
an access token inside its lifetime or else the current `cv_refresh` cookie; every
other operation of a locked session is refused by `api.idle_lock`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Protocol

import structlog
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from candleviewer.api import idle_lock
from candleviewer.api.csrf import (
    AUDIT_TIMEOUT_S,
    RefusalAuditTracker,
    clear_csrf_cookie,
    csrf_problem,
    set_csrf_cookie,
    source_ip,
    verify_refresh_csrf,
)
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec, CsrfVerdict
from candleviewer.auth.errors import (
    RefreshReuseDetected,
    SessionIdleLocked,
    SessionNotFound,
    SessionRevoked,
    UnlockPasswordInvalid,
)
from candleviewer.auth.metrics import auth_csrf_refused_total, auth_session_fixation_attempts_total
from candleviewer.auth.models import (
    MintedSession,
    RefreshOutcome,
    SessionRecord,
    SessionView,
)
from candleviewer.auth.session_chart import SessionChart, SessionChartError, to_us
from candleviewer.auth.session_service import (
    ACCESS_TOKEN_TTL,
    PasswordCheck,
    UnlockOutcome,
    UnlockWriteAhead,
    is_idle_locked_session,
)
from candleviewer.auth.step_up import grace_expires_at
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.observability.redaction import redact_text

REFRESH_COOKIE = "cv_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
ACCESS_TOKEN_EXPIRES_IN_S = 720  # ADR-0020: 12 min
REFRESH_EXPIRES_IN_S = 12 * 3600
MAX_PAGE = 100
#: `POST /auth/unlock` `x-rate-limit`: 10 requests / minute / source IP (throttled like
#: login). Every attempt counts, so a throttled one checks no password.
UNLOCK_MAX_PER_WINDOW = 10
UNLOCK_WINDOW_S = 60.0


class UnlockBody(BaseModel):
    """`UnlockRequest` (22-api-openapi.yaml): the password only, never a TOTP code
    (US-ONB-004). A `SecretStr` keeps it out of reprs; a `ValidationError` echoes its
    input, so the route never logs or returns one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    password: SecretStr = Field(min_length=1, max_length=512)


class SessionServiceLike(Protocol):
    async def peek_refresh(self, raw_refresh_token: str) -> SessionRecord | None: ...

    async def refresh(
        self,
        raw_refresh_token: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
        device_label: str | None = None,
        is_electron: bool = False,
    ) -> RefreshOutcome: ...

    async def authenticate_access_token(
        self, raw_access_token: str, *, allow_locked: bool = False
    ) -> SessionRecord: ...

    async def peek_access_token(self, raw_access_token: str) -> SessionRecord | None: ...

    def now(self) -> datetime: ...

    async def touch(self, session_id: str) -> SessionRecord: ...

    async def unlock(
        self,
        session_id: str,
        *,
        password: str,
        check: PasswordCheck | None = None,
        write_ahead: UnlockWriteAhead | None = None,
    ) -> SessionRecord: ...

    async def revoke(self, session_id: str, *, reason: str) -> SessionRecord | None: ...

    async def revoke_all(
        self, user_id: str, *, reason: str, except_session_id: str | None = None
    ) -> tuple[SessionRecord, ...]: ...

    async def list_sessions(
        self, user_id: str, *, current_session_id: str | None = None
    ) -> tuple[SessionView, ...]: ...


class UnlockAuthority(Protocol):
    """What `POST /auth/unlock` needs besides the session service (#2300): the B16
    chart the lock and the unlock are recorded on (B16.7), and the password check on
    login's Argon2id path and lockout counters (SR-015, SR-016). `StepUpService`."""

    @property
    def chart(self) -> SessionChart: ...

    async def verify_password(self, user_id: str, password: str) -> bool: ...


class AuthServiceLike(Protocol):
    @property
    def sessions_is_active(self) -> bool: ...

    @property
    def sessions(self) -> SessionServiceLike: ...


class IdentityProvider(Protocol):
    """Supplies the OpenAPI `User`/permissions/scope for a user id (E09-T03)."""

    async def user(self, user_id: str) -> dict[str, Any]: ...

    async def session_info(self, user_id: str) -> dict[str, Any]:
        """`permissions`, `account_scope` and optional extras of `SessionInfo`."""
        ...


class AuditEmitter(Protocol):
    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: str | uuid.UUID | None = None,
        actor_ip: str | None = None,
        session_id: str | uuid.UUID | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: Severity = Severity.INFO,
        reason: str | None = None,
        after_state: dict[str, Any] | None = None,
    ) -> None: ...


class AuditServiceLike(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def writer(self) -> AuditEmitter: ...


RevocationPublisher = Callable[[str, str], Awaitable[None]]
Clock = Callable[[], Any]


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _problem(status_code: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"type": "about:blank", "title": title, "status": status_code, "detail": detail},
        media_type="application/problem+json",
    )


def _unauthorized(detail: str = "authentication required") -> JSONResponse:
    # One uniform 401 for unknown/expired/revoked tokens: no session oracle.
    return _problem(401, "Unauthorized", detail)


#: SR-026: a self-service read answers only for the authenticated caller, so it takes only the
#: query parameters its contract operation declares. A target user under any spelling, or any other
#: undeclared key, is refused, never silently ignored (#2573). `userId` is the contract's own name
#: for a target user (`components/parameters/UserId`, the owner-only `/users/{userId}` routes).
_TARGET_USER_PARAMS = frozenset({"user_id", "userId"})
#: Declared query parameters (22-api-openapi.yaml): `authGetSession` has none; `authListSessions`
#: has `Cursor` and `Limit`.
GET_SESSION_QUERY: frozenset[str] = frozenset()
LIST_SESSIONS_QUERY = frozenset({"cursor", "limit"})
#: Echo bounds for client-supplied parameter names, which also pass the shared redaction rules.
_MAX_ECHOED_PARAMS = 8
_MAX_ECHOED_NAME_LEN = 64


def _echoed(name: str) -> str:
    """A client-supplied parameter name as echoed. A name over the bound is never echoed, only its
    length: the shared redaction then only ever scans short names (cheap, and a secret shape is
    seen whole), and no prefix of a long token can leak through a cut (#2573 review)."""
    if len(name) > _MAX_ECHOED_NAME_LEN:
        return f"<{len(name)}-character name>"
    return redact_text(name)


def _undeclared_query_refusal(request: Request, declared: frozenset[str]) -> JSONResponse | None:
    """422 `validation_failed` when a self-service read gets an undeclared query key (SR-026).

    Decided on the parameter names alone, so the answer is identical for any value (no existence
    oracle). It echoes at most `_MAX_ECHOED_PARAMS` redacted, bounded names and never a value.
    """
    undeclared = sorted(set(request.query_params) - declared)
    if not undeclared:
        return None
    named = undeclared[:_MAX_ECHOED_PARAMS]
    more = len(undeclared) - len(named)
    shown = {p: _echoed(p) for p in named}  # redact each name once, reuse in detail and errors
    listed = ", ".join(shown[p] for p in named) + (f" (+{more} more)" if more else "")
    return JSONResponse(
        status_code=422,
        content={
            "type": "https://candleviewer.local/errors/validation_failed",
            "title": "Request body or parameters failed schema validation",
            "status": 422,
            "code": "validation_failed",
            "detail": f"Query parameter not accepted: {listed}. This route answers only for the "
            "authenticated caller and takes no target-user or undeclared parameter.",
            "errors": [
                (
                    {
                        "field": f"query.{p}",
                        "rule": "target_user_not_accepted",
                        "message": "self-service routes do not accept a target-user parameter",
                    }
                    if p in _TARGET_USER_PARAMS
                    else {
                        "field": f"query.{shown[p]}",
                        "rule": "undeclared_parameter",
                        "message": "not a declared parameter of this route",
                    }
                )
                for p in named
            ],
        },
        media_type="application/problem+json",
    )


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def _log() -> Any:
    return structlog.get_logger(__name__)


def _source_ip(request: Request) -> str | None:
    """The address MeshOnly admitted (trusted-proxy aware), else the socket peer."""
    return source_ip(request.scope)


# `/auth/refresh` budget (reuses the E09-S01 sliding-window throttle, one
# instance per key space): at most REFRESH_MAX_PER_WINDOW refresh attempts per
# source IP *and* per presented session within REFRESH_WINDOW_S seconds; the
# next one is 429 + `Retry-After`. A legitimate client refreshes roughly once
# per 12-minute access-token lifetime, so 10/min leaves wide headroom for
# retries and multiple tabs while bounding token-guessing and rotation storms.
REFRESH_MAX_PER_WINDOW = 10
REFRESH_WINDOW_S = 60.0
#: Presentations of a session credential this server never issued (U6/SR-013, E09-X02
#: AC2) that are audited per source IP, and for all sources together, per window, with at
#: most the shared `RefusalAuditTracker` cap in flight. Past any of them the 401 is
#: unchanged and still counted (`audit_throttled`), with no audit row (C-2.9 vs C-2.18, as
#: the CSRF guard). The global budget holds when source addresses rotate or are forwarded.
FIXATION_AUDITS_PER_WINDOW = 20
FIXATION_AUDITS_GLOBAL_PER_WINDOW = 60
FIXATION_AUDIT_WINDOW_S = 60.0
_ALL_SOURCES = "*"


def _route_path(request: Request) -> str:
    """Bounded audit field: the matched route template, never the raw request path."""
    path = getattr(request.scope.get("route"), "path", None)
    return path if isinstance(path, str) else "(unmatched)"


def _origin_ok(request: Request, allowed: frozenset[str]) -> bool:
    """CSRF guard for cookie-authenticated refresh: the Origin header must be
    in the configured allow-list (`Settings.allowed_origins`, injected; empty
    => refuse), never compared to the attacker-controllable Host header.
    SameSite=Strict remains the primary defence."""
    origin = request.headers.get("origin")
    if origin is None:
        return False
    return origin.rstrip("/") in allowed


def _set_refresh_cookie(response: Response, token: str, *, max_age: int) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="strict",
    )


def _view_json(view: SessionView) -> dict[str, Any]:
    return {
        "id": str(view.id),
        "device_name": view.device_name,
        "ip": view.ip,
        "user_agent": view.user_agent,
        "created_at": view.created_at.isoformat(),
        "last_seen_at": view.last_seen_at.isoformat(),
        "expires_at": view.expires_at.isoformat(),
        "current": view.current,
    }


def _tokens(minted: MintedSession, *, include_refresh: bool) -> dict[str, Any]:
    return {
        "access_token": minted.access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_EXPIRES_IN_S,
        "refresh_expires_in": REFRESH_EXPIRES_IN_S,
        "refresh_token": minted.refresh_token if include_refresh else None,
    }


class AuditUnavailableError(RuntimeError):
    """Audit sink not active: state-changing session actions fail closed (C-2.9)."""


def make_session_router(
    auth_service: AuthServiceLike,
    audit_service: AuditServiceLike | None = None,
    *,
    identity: IdentityProvider | None = None,
    publish_revocation: RevocationPublisher | None = None,
    allowed_origins: frozenset[str] = frozenset(),
    ip_throttle: PerIpLoginThrottle | None = None,
    session_throttle: PerIpLoginThrottle | None = None,
    csrf: CsrfCodec,
    fixation_throttle: PerIpLoginThrottle | None = None,
    fixation_global_throttle: PerIpLoginThrottle | None = None,
    audit_tracker: RefusalAuditTracker | None = None,
    audit_timeout_s: float = AUDIT_TIMEOUT_S,
    unlock_authority: Callable[[], UnlockAuthority | None] | None = None,
    unlock_throttle: PerIpLoginThrottle | None = None,
) -> APIRouter:
    """*audit_tracker*: pass the app's CSRF refusal tracker so both guards share one
    in-flight cap and one shutdown drain. *unlock_authority* is a thunk (step-up exists
    only after `AuthService.start()`); without one `POST /auth/unlock` answers 503."""
    router = APIRouter(tags=["auth"])

    def now() -> datetime:
        """Lock state and `server_time` come from the session service's own clock."""
        return auth_service.sessions.now()

    by_unlock_ip = unlock_throttle or PerIpLoginThrottle(
        max_attempts=UNLOCK_MAX_PER_WINDOW, window_s=UNLOCK_WINDOW_S
    )
    by_ip = ip_throttle or PerIpLoginThrottle(
        max_attempts=REFRESH_MAX_PER_WINDOW, window_s=REFRESH_WINDOW_S
    )
    by_session = session_throttle or PerIpLoginThrottle(
        max_attempts=REFRESH_MAX_PER_WINDOW, window_s=REFRESH_WINDOW_S
    )
    by_fixation_ip = fixation_throttle or PerIpLoginThrottle(
        max_attempts=FIXATION_AUDITS_PER_WINDOW, window_s=FIXATION_AUDIT_WINDOW_S
    )
    by_fixation_all = fixation_global_throttle or PerIpLoginThrottle(
        max_attempts=FIXATION_AUDITS_GLOBAL_PER_WINDOW,
        window_s=FIXATION_AUDIT_WINDOW_S,
        max_tracked_ips=1,
    )
    tracker = audit_tracker if audit_tracker is not None else RefusalAuditTracker()

    def _audit_ready() -> bool:
        return audit_service is not None and audit_service.is_active

    async def _audit(
        action: str,
        *,
        record: SessionRecord | None,
        ip: str | None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: Severity = Severity.INFO,
        reason: str | None = None,
        session_id: str | uuid.UUID | None = None,
    ) -> None:
        if audit_service is None or not audit_service.is_active:
            raise AuditUnavailableError
        await audit_service.writer.emit(
            action,
            actor_label=str(record.user_id) if record else "(unknown)",
            actor_user_id=record.user_id if record else None,
            actor_ip=ip,
            session_id=session_id if session_id is not None else (record.id if record else None),
            outcome=outcome,
            severity=severity,
            reason=reason,
        )

    async def _fixation_attempt(request: Request, vector: str) -> None:
        """U6/SR-013 (E09-X02 AC2): a session credential this server never issued was
        presented. The uniform 401 is unchanged (no oracle). The attempt is counted, and
        audited within the per-IP and global budgets and the tracker's in-flight cap; the
        write runs shielded, so a cancelled request never cuts it short (as the CSRF
        guard). The token itself is never recorded; a slow or failed write never changes
        the answer."""
        fixation = auth_session_fixation_attempts_total
        fixation.labels(reason="unknown_token").inc()
        ip = _source_ip(request)
        key = ip or "(unknown)"
        if (
            tracker.full
            or by_fixation_ip.is_blocked(key)
            or by_fixation_all.is_blocked(_ALL_SOURCES)
        ):
            fixation.labels(reason="audit_throttled").inc()
            return
        by_fixation_ip.record_failure(key)
        by_fixation_all.record_failure(_ALL_SOURCES)
        if audit_service is None or not audit_service.is_active:
            fixation.labels(reason="audit_unavailable").inc()
            _log().error("auth.session_fixation_attempt.audit_unavailable", error="inactive")
            return
        task = tracker.track(
            audit_service.writer.emit(
                "auth.session_fixation_attempt",
                actor_label="(unknown)",
                actor_ip=ip,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="unknown_token",
                after_state={"vector": vector, "path": _route_path(request)},
            )
        )
        try:
            await asyncio.wait_for(asyncio.shield(task), audit_timeout_s)
        except TimeoutError:
            tracker.mark_timed_out(task)  # left to finish; never cancelled mid-append
            fixation.labels(reason="audit_slow").inc()
            _log().warning("auth.session_fixation_attempt.audit_slow")
        except Exception as exc:
            fixation.labels(reason="audit_unavailable").inc()
            _log().error(
                "auth.session_fixation_attempt.audit_unavailable", error=type(exc).__name__
            )

    async def _propagate(session_id: str | uuid.UUID, reason: str) -> None:
        if publish_revocation is not None:
            await publish_revocation(str(session_id), reason)

    def _audit_down() -> JSONResponse:
        # Write-ahead audit failed: nothing has been mutated yet (C-2.9).
        return _problem(503, "Service unavailable", "audit sink not active")

    def _throttled(retry_after: int, what: str = "refresh") -> JSONResponse:
        response = _problem(429, "Too many requests", f"{what} rate limit exceeded")
        response.headers["Retry-After"] = str(retry_after)
        return response

    async def _authenticate(
        request: Request, *, allow_locked: bool = False
    ) -> SessionRecord | None:
        token = _bearer(request)
        if token is None:
            return None
        try:
            return await auth_service.sessions.authenticate_access_token(
                token, allow_locked=allow_locked
            )
        except SessionNotFound:
            # Unknown and expired handles share this error. Only a handle this server never
            # issued is an attempt; an expired one is the client's normal refresh trigger.
            if await auth_service.sessions.peek_access_token(token) is None:
                await _fixation_attempt(request, "bearer")
            return None
        except (SessionRevoked, SessionIdleLocked):
            return None

    async def _identify(request: Request) -> tuple[SessionRecord, bool] | None:
        """The session of an operation allowed while idle-locked (contract "Idle lock"):
        an access token inside its lifetime identifies it, else the `cv_refresh` cookie
        does, while it is that session's current refresh token. Revoked, expired and
        locked sessions come back as they are: the operation decides. `None` is the
        uniform 401: no credential, a rotated-away one (reuse detection stays with
        `/auth/refresh`) or one never issued (a fixation attempt). The flag is True when
        the cookie identified the session."""
        sessions = auth_service.sessions
        token = _bearer(request)
        if token is not None:
            found = await sessions.peek_access_token(token)
            if found is None:
                await _fixation_attempt(request, "bearer")
                return None
            if now() < found.issued_at + ACCESS_TOKEN_TTL:
                return None if found.revoked_reason == "rotated" else (found, False)
        cookie = request.cookies.get(REFRESH_COOKIE)
        if cookie is None:
            return None
        found = await sessions.peek_refresh(cookie)
        if found is None:
            await _fixation_attempt(request, "refresh_cookie")
            return None
        return None if found.revoked_reason == "rotated" else (found, True)

    async def _introspected(request: Request) -> SessionRecord | None:
        """`GET /auth/session`'s session, locked or not; a revoked or expired one gets
        the uniform 401, as it would to its access token. Read-only: never activity."""
        caller = await _identify(request)
        if caller is None:
            return None
        record = caller[0]
        if record.is_revoked or record.is_absolute_expired(now=now()):
            return None
        return record

    async def _unauthorized_or_locked(request: Request) -> JSONResponse:
        """The 401 for a bearer `_authenticate` refused: `session_idle_locked` when its
        session would be accepted but for the lock (as `IdleLockMiddleware` answers it),
        else the uniform `unauthenticated`."""
        token = _bearer(request)
        found = None if token is None else await auth_service.sessions.peek_access_token(token)
        if found is not None and is_idle_locked_session(found, now=now()):
            return idle_lock.idle_locked_problem(found.idle_deadline())
        return _unauthorized()

    async def _csrf_refusal(
        request: Request, record: SessionRecord, ip: str | None
    ) -> JSONResponse | None:
        """SR-041 for the POSTs that check it themselves (`api.csrf`): against *record*,
        the session the route acts on, before any audit or state change. A refusal is
        counted and audited; it is refused regardless (a 403, never a 500, #2238 r3)."""
        refusal = verify_refresh_csrf(
            csrf,
            request.headers.get(CSRF_HEADER),
            request.cookies.get(CSRF_COOKIE),
            str(record.id),
        )
        if refusal is None:
            return None
        auth_csrf_refused_total.labels(reason=refusal.value).inc()
        try:
            await _audit(
                "auth.csrf_refused",
                record=record,
                ip=ip,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason=refusal.value,
            )
        except (AuditUnavailableError, AuditError) as exc:
            auth_csrf_refused_total.labels(reason="audit_unavailable").inc()
            _log().error("auth.csrf_refused.audit_unavailable", error=type(exc).__name__)
        return csrf_problem(refusal)

    async def _session_info(
        provider: IdentityProvider, record: SessionRecord, at: datetime
    ) -> dict[str, Any]:
        """`SessionInfo`. No step-up elevation survives the lock (contract "Idle lock"),
        so a locked session reports `step_up_expires_at: null`."""
        locked = record.is_idle_locked(now=at)
        info = await provider.session_info(str(record.user_id))
        return {
            **info,
            "user": await provider.user(str(record.user_id)),
            "server_time": at.isoformat(),
            "step_up_expires_at": (
                None if locked else _iso(grace_expires_at(record.step_up_elevations, at))
            ),
            "session": idle_lock.session_state(record, now=at),
        }

    async def _unlock_password(request: Request) -> str | None:
        """The `UnlockRequest` password, or `None` for any other body (422). The
        `ValidationError` (a `ValueError`) echoes its input, so it is dropped here."""
        try:
            body = UnlockBody.model_validate(await request.json())
        except ValueError:
            return None
        return body.password.get_secret_value()

    async def _record_unlock(
        chart: SessionChart, record: SessionRecord, at: datetime, event: str, **payload: Any
    ) -> JSONResponse | None:
        """Record an unlock event on B16 against the row as read while locked (B16.7). A
        failed record answers 503: the edge never reports a step it could not record."""
        try:
            await chart.record(record, at, event, **payload)
        except SessionChartError as exc:
            _log().error("auth.unlock.chart_failed", b16_event=event, error=type(exc).__name__)
            return _problem(503, "Service unavailable", "session record unavailable")
        return None

    @router.post("/auth/refresh")
    async def refresh(request: Request) -> Response:
        if not _audit_ready():
            return _problem(503, "Service unavailable", "audit sink not active")
        if not auth_service.sessions_is_active:
            return _problem(503, "Service unavailable", "session backend is not wired")
        if identity is None:
            return _problem(
                501, "Not implemented", "identity provider not wired (E09-T03); refresh disabled"
            )
        body: dict[str, Any] = {}
        raw = await request.body()
        if raw:
            try:
                parsed = await request.json()
            except ValueError:
                return _problem(422, "Unprocessable", "invalid JSON body")
            if not isinstance(parsed, dict) or set(parsed) - {"refresh_token"}:
                return _problem(422, "Unprocessable", "unexpected fields in body")
            body = parsed
        cookie_token = request.cookies.get(REFRESH_COOKIE)
        body_token = body.get("refresh_token")
        if cookie_token is not None and not _origin_ok(request, allowed_origins):
            return _problem(403, "Forbidden", "cross-origin refresh refused")
        presented = cookie_token or (body_token if isinstance(body_token, str) else None)
        if not presented:
            return _unauthorized("refresh_token_invalid")
        ip = _source_ip(request)
        ip_key = ip or "(unknown)"
        if by_ip.is_blocked(ip_key):
            return _throttled(by_ip.retry_after_s(ip_key))
        by_ip.record_failure(ip_key)  # counts every attempt, not only failures
        presented_record = await auth_service.sessions.peek_refresh(presented)
        if presented_record is None:
            await _fixation_attempt(request, "refresh_cookie" if cookie_token else "refresh_body")
            return _unauthorized("refresh_token_invalid")
        session_key = str(presented_record.id)
        if by_session.is_blocked(session_key):
            return _throttled(by_session.retry_after_s(session_key))
        by_session.record_failure(session_key)
        reuse = presented_record.revoked_reason == "rotated"
        if not reuse:
            # SR-041: validate against the exact session this refresh would rotate,
            # after the throttles and before any audit write or state change. A
            # rotated-out token skips this and goes straight to reuse detection: that
            # branch only revokes (never mints), and `cv_refresh` is HttpOnly +
            # SameSite=Strict, so it is not CSRF-reachable.
            refusal = await _csrf_refusal(request, presented_record, ip)
            if refusal is not None:
                return refusal
        at = now()
        if presented_record.is_idle_locked(now=at) and not presented_record.is_absolute_expired(
            now=at
        ):
            # Contract "Idle lock": refused like any operation of a locked session, before
            # any audit record or rotation; the same token refreshes after the unlock.
            return idle_lock.idle_locked_problem(presented_record.idle_deadline())
        # C-2.9 write-ahead: the audit record is written before `refresh()`
        # rotates or revokes anything; if the sink is down we refuse (503)
        # with no state change.
        try:
            if reuse:
                await _audit(
                    "auth.refresh_reuse_detected",
                    record=presented_record,
                    ip=ip,
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.CRITICAL,
                    reason="rotation_reuse",
                )
            elif not presented_record.is_revoked:
                await _audit("auth.session_refreshed", record=presented_record, ip=ip)
        except AuditUnavailableError:
            return _audit_down()
        try:
            outcome = await auth_service.sessions.refresh(
                presented, ip=ip, user_agent=request.headers.get("user-agent")
            )
        except RefreshReuseDetected as exc:
            if not reuse:
                # Concurrent-refresh race detected inside the service; the
                # intent record above is followed by the critical outcome.
                await _audit(
                    "auth.refresh_reuse_detected",
                    record=presented_record,
                    ip=ip,
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.CRITICAL,
                    reason="rotation_reuse",
                )
            # Same propagation helper as logout/revoke: every family member's
            # sockets are closed with 4401 (US-ONB-009).
            for sid in exc.revoked_session_ids:
                await _propagate(sid, "session_revoked")
            return _unauthorized("refresh_token_invalid")
        except (SessionNotFound, SessionRevoked, SessionIdleLocked):
            return _unauthorized("refresh_token_invalid")
        minted = outcome.minted
        user = await identity.user(str(presented_record.user_id))
        response = JSONResponse(
            status_code=200,
            content={
                "status": "authenticated",
                "tokens": _tokens(minted, include_refresh=cookie_token is None),
                "user": user,
            },
        )
        _set_refresh_cookie(response, minted.refresh_token, max_age=REFRESH_EXPIRES_IN_S)
        # SR-041: validated above, rotated with the session
        set_csrf_cookie(response, csrf.issue(str(minted.session_id)), max_age=REFRESH_EXPIRES_IN_S)
        return response

    @router.get("/auth/session")
    async def get_session(request: Request) -> Response:
        if not auth_service.sessions_is_active:
            return _problem(503, "Service unavailable", "session backend is not wired")
        record = await _introspected(request)
        if record is None:
            return _unauthorized()
        if (refusal := _undeclared_query_refusal(request, GET_SESSION_QUERY)) is not None:
            return refusal  # SR-026: before any session data is read
        if identity is None:
            return _problem(
                501, "Not implemented", "identity provider not wired (E09-T03); disabled"
            )
        response = JSONResponse(await _session_info(identity, record, now()))
        # SR-041 recovery path: re-issue when absent or not verifying.
        present = request.cookies.get(CSRF_COOKIE)
        if not present or csrf.verify(present, str(record.id)) is not CsrfVerdict.OK:
            set_csrf_cookie(response, csrf.issue(str(record.id)), max_age=REFRESH_EXPIRES_IN_S)
        return response

    @router.post("/auth/session/extend")
    async def extend_session(request: Request) -> Response:
        """CMP-098 "Extend": the explicit activity call (contract `authExtendSession`).
        It never lifts a lock and never moves `expires_at`."""
        if not auth_service.sessions_is_active:
            return _problem(503, "Service unavailable", "session backend is not wired")
        record = await _authenticate(request)
        if record is None:
            return await _unauthorized_or_locked(request)
        try:
            # C-2.9 write-ahead: audit down => 503 and the deadline does not move.
            await _audit("auth.session_extended", record=record, ip=_source_ip(request))
        except (AuditUnavailableError, AuditError):
            return _audit_down()
        try:
            extended = await auth_service.sessions.touch(str(record.id))
        except SessionIdleLocked as exc:  # locked since the check: extend never lifts it
            return idle_lock.idle_locked_problem(exc.idle_locked_at)
        except (SessionNotFound, SessionRevoked):
            return _unauthorized()
        at = now()
        return JSONResponse(
            {"session": idle_lock.session_state(extended, now=at), "server_time": at.isoformat()}
        )

    @router.post("/auth/unlock")
    async def unlock(request: Request) -> Response:
        """SCR-005: lift the idle lock with the password only (contract `authUnlock`)."""
        authority = unlock_authority() if unlock_authority is not None else None
        if not auth_service.sessions_is_active or authority is None:
            return _problem(503, "Service unavailable", "session backend is not wired")
        if identity is None:
            return _problem(
                501, "Not implemented", "identity provider not wired (E09-T03); unlock disabled"
            )
        ip = _source_ip(request)
        ip_key = ip or "(unknown)"
        if by_unlock_ip.is_blocked(ip_key):
            return _throttled(by_unlock_ip.retry_after_s(ip_key), "unlock")
        by_unlock_ip.record_failure(ip_key)  # every attempt: a throttled one checks no password
        caller = await _identify(request)
        if caller is None:
            return _unauthorized()
        record, by_cookie = caller
        if by_cookie and not _origin_ok(request, allowed_origins):
            return _problem(403, "Forbidden", "cross-origin unlock refused")  # SR-042
        if (refusal := await _csrf_refusal(request, record, ip)) is not None:
            return refusal
        at = now()
        if record.is_revoked:
            return idle_lock.session_revoked_problem(record.revoked_reason or "revoked")
        if record.is_absolute_expired(now=at):
            return idle_lock.session_revoked_problem("expired")
        if not record.is_idle_locked(now=at):
            # No password check, no failure counted, no activity, nothing audited.
            return idle_lock.not_locked_problem()
        password = await _unlock_password(request)
        if password is None:
            return _problem(422, "Unprocessable", "body must be exactly {password}")
        if not _audit_ready():
            return _audit_down()  # no password is checked
        chart = authority.chart
        # B16.7: the lock is recorded (`auth.idle_locked`) before `unlock()` runs, so a
        # failed record answers 503 with the row still locked. A `replay` REQUEST only
        # builds the chart and writes no row of its own.
        if (down := await _record_unlock(chart, record, at, "REQUEST", replay=True)) is not None:
            return down
        decided: list[UnlockOutcome] = []

        async def write_ahead(outcome: UnlockOutcome) -> None:
            """C-2.9: each record precedes the change it describes (B16.7: the chart
            writes none of them); a failed write leaves the row as it was."""
            decided.append(outcome)
            if outcome is UnlockOutcome.UNLOCKED:
                await _audit("auth.session_unlocked", record=record, ip=ip)
                return
            await _audit(
                "auth.unlock_failed",
                record=record,
                ip=ip,
                outcome=AuditOutcome.FAILURE,
                severity=Severity.WARNING,
                reason="invalid_password",
            )
            if outcome is UnlockOutcome.REVOKED:
                await _audit(
                    "auth.session_revoked",
                    record=record,
                    ip=ip,
                    severity=Severity.WARNING,
                    reason="unlock_attempts_exceeded",
                )

        verify, user_id = authority.verify_password, str(record.user_id)
        try:
            unlocked = await auth_service.sessions.unlock(
                str(record.id),
                password=password,
                check=lambda candidate: verify(user_id, candidate),
                write_ahead=write_ahead,
            )
        except (AuditUnavailableError, AuditError) as exc:
            _log().error("auth.unlock.audit_unavailable", error=type(exc).__name__)
            return _audit_down()  # the lock stays and nothing was revoked
        except UnlockPasswordInvalid:
            failed = await _record_unlock(chart, record, at, "UNLOCK_FAILED")
            return failed or idle_lock.unlock_invalid_problem()
        except SessionRevoked as exc:
            if UnlockOutcome.REVOKED not in decided:  # revoked by something else meanwhile
                return idle_lock.session_revoked_problem(exc.reason)
            await _propagate(record.id, "session_revoked")  # sockets close with 4401 (#2272)
            # B16.7: `revoked` carries this decision to the chart's guard; `replay` keeps the
            # chart from writing a second `auth.session_revoked`.
            failed = await _record_unlock(
                chart, record, at, "UNLOCK_FAILED", revoked=True, replay=True
            )
            return failed or idle_lock.session_revoked_problem("unlock_attempts_exceeded")
        except SessionNotFound:
            return _unauthorized()
        lifted = await _record_unlock(
            chart, record, at, "UNLOCK_OK", idle_expires_at_us=to_us(unlocked.idle_deadline())
        )
        return lifted or JSONResponse(await _session_info(identity, unlocked, now()))

    @router.get("/auth/sessions")
    async def list_sessions(
        request: Request,
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=MAX_PAGE),
    ) -> Response:
        if not auth_service.sessions_is_active:
            return _problem(503, "Service unavailable", "session backend is not wired")
        record = await _authenticate(request)
        if record is None:
            return _unauthorized()
        if (refusal := _undeclared_query_refusal(request, LIST_SESSIONS_QUERY)) is not None:
            return refusal  # SR-026: before any session data is read
        try:
            offset = int(cursor) if cursor else 0
        except ValueError:
            return _problem(422, "Unprocessable", "invalid cursor")
        if offset < 0:
            return _problem(422, "Unprocessable", "invalid cursor")
        # Scope is always the caller's own user id (x-rbac scope: self): the
        # query is never parameterised by anything the client supplies.
        views = await auth_service.sessions.list_sessions(
            str(record.user_id), current_session_id=str(record.id)
        )
        page = views[offset : offset + limit]
        has_more = offset + limit < len(views)
        return JSONResponse(
            {
                "items": [_view_json(v) for v in page],
                "meta": {
                    "next_cursor": str(offset + limit) if has_more else None,
                    "has_more": has_more,
                    "count": len(page),
                },
            }
        )

    @router.post("/auth/logout")
    async def logout(request: Request) -> Response:
        if not _audit_ready():
            return _problem(503, "Service unavailable", "audit sink not active")
        if not auth_service.sessions_is_active:
            return _problem(503, "Service unavailable", "session backend is not wired")
        record = await _authenticate(request, allow_locked=True)
        if record is None:
            return _unauthorized()
        all_sessions = False
        if await request.body():
            try:
                parsed = await request.json()
            except ValueError:
                return _problem(422, "Unprocessable", "invalid JSON body")
            if not isinstance(parsed, dict) or set(parsed) - {"all_sessions"}:
                return _problem(422, "Unprocessable", "unexpected fields in body")
            flag = parsed.get("all_sessions", False)
            if not isinstance(flag, bool):
                return _problem(422, "Unprocessable", "all_sessions must be boolean")
            all_sessions = flag
        ip = _source_ip(request)
        # C-2.9 write-ahead: record the logout (and every targeted session)
        # before revoking; audit down => 503, nothing revoked.
        reason = "logout_all" if all_sessions else "logout"
        try:
            if all_sessions:
                targets = [
                    v.id for v in await auth_service.sessions.list_sessions(str(record.user_id))
                ]
            else:
                targets = [record.id]
            await _audit("auth.logout", record=record, ip=ip, reason=reason)
            for sid in targets:
                await _audit(
                    "auth.session_revoked", record=record, ip=ip, reason=reason, session_id=sid
                )
        except AuditUnavailableError:
            return _audit_down()
        if all_sessions:
            revoked = await auth_service.sessions.revoke_all(str(record.user_id), reason=reason)
        else:
            one = await auth_service.sessions.revoke(str(record.id), reason=reason)
            revoked = (one,) if one is not None else ()
        for r in revoked:
            await _propagate(r.id, "session_revoked")
        response = Response(status_code=204)
        _clear_refresh_cookie(response)
        clear_csrf_cookie(response)
        return response

    @router.delete("/me/sessions/{sessionId}")
    async def revoke_my_session(
        request: Request, session_id: Annotated[uuid.UUID, Path(alias="sessionId")]
    ) -> Response:
        if not _audit_ready():
            return _problem(503, "Service unavailable", "audit sink not active")
        if not auth_service.sessions_is_active:
            return _problem(503, "Service unavailable", "session backend is not wired")
        record = await _authenticate(request, allow_locked=True)
        if record is None:
            return _unauthorized()
        # IDOR guard: only sessions of the caller's own user are addressable;
        # anything else is indistinguishable from "does not exist" (404).
        own = await auth_service.sessions.list_sessions(
            str(record.user_id), current_session_id=str(record.id)
        )
        if str(session_id) not in {str(v.id) for v in own}:
            return _problem(404, "Not found", "no such session")
        try:
            await _audit(
                "auth.session_revoked",
                record=record,
                ip=_source_ip(request),
                reason="user_revoked",
                session_id=session_id,
            )
        except AuditUnavailableError:
            return _audit_down()
        revoked = await auth_service.sessions.revoke(str(session_id), reason="user_revoked")
        if revoked is not None:
            await _propagate(revoked.id, "session_revoked")
        response = Response(status_code=204)
        if session_id == record.id:  # only the caller's own session ends its cookies
            _clear_refresh_cookie(response)
            clear_csrf_cookie(response)
        return response

    return router

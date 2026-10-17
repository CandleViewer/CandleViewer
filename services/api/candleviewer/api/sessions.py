"""`POST /auth/refresh`, `GET /auth/session`, `GET /auth/sessions`,
`POST /auth/logout` and `DELETE /me/sessions/{sessionId}` (E09-S03,
US-ONB-004/009; QA defect #1634), and the idle-lock route `POST /auth/unlock`
(#2300).

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

Revocation propagation (`23-ws-protocol.md` §9.5) is the session service's:
every revoke path publishes the revoked ids to the sink the composition root
wires to the ws `RevocationHub`, which closes the sockets with `4401` (#2272).
This router publishes nothing itself.

Enrolment-only session (#2295): refresh classifies the presented session as the enrolment
guard classifies a bearer (`AuthService.classify`). One that would outlive its 15-minute
lifetime (Q7) gets the uniform `401 refresh_token_invalid` before any audit write or rotation,
so the client signs in again; one that cannot be classified gets a 503 (fail closed).

Session fixation (U6/SR-013, E09-X02 AC2): a bearer or refresh token that was
never issued here is refused with the same 401 as any other, and counted
(`auth_session_fixation_attempts_total`) and audited
(`auth.session_fixation_attempt`) within a per-IP and a global budget, through
the CSRF guard's in-flight-capped, shielded writer path. Expired or revoked
tokens of real sessions are not attempts and stay silent.

IDOR probe (AC-CSRF-05, #2319): `DELETE /me/sessions/{id}` for an id that is not one
of the caller's live sessions keeps its 404 (a foreign id, an unknown id and the caller's
own ended session answer identically) and is counted (`auth_session_revoke_denied_total`)
and audited (`auth.session_revoke_denied`, reason `not_live_own_session`) within a
per-user and a global budget, through the same in-flight-capped, shielded writer path. Nothing
changes, so that record is not write-ahead: a slow, refused or cancelled write leaves the 404 as
it is, and a budget or cap trip is logged (`auth.session_revoke_denied.unaudited`).

Write-ahead audit (C-2.9, #2251): the record is written before anything is
rotated, revoked, set or cleared. An inactive sink, or a writer that refuses the
record (`AuditError`: WAL full or unwritable, writer stopped), answers 503 with
nothing changed. A record written after the service has acted is an outcome record
(04-security-program.md §8.3 rules 1 and 2) and cannot undo that: a lost one is counted
(`auth_audit_outcome_lost_total`), logged and alerted, and the answer stands
(`_audit_outcomes`). They are, in `/auth/refresh`, the concurrent-refresh race and a disabled
user's refusal (#2911) and, on `/auth/logout`, one `auth.session_revoked` per session revoked,
after the one `auth.logout` intent record that names the targets (#2914). The retry half of rule 2
is the time-boxed exception EX-07 (§16.2).

Idle lock (#2300, contract info "Idle lock"): `GET /auth/session` never re-stamps
`last_seen_at`. `GET /auth/session`, `POST /auth/unlock` and `POST /auth/logout`
serve a locked session, identified by an access token inside its lifetime or else
the current `cv_refresh` cookie (a cookie-identified write gets the SR-042 Origin
and SR-041 checks here); every other operation of a locked session is refused by
`api.idle_lock`, and a locked or cookie-identified logout ends only its own session.
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
    ANON_REFUSAL_WINDOW_S,
    AUDIT_TIMEOUT_S,
    SESSION_REFUSALS_PER_WINDOW,
    RefusalAuditTracker,
    clear_csrf_cookie,
    csrf_problem,
    set_csrf_cookie,
    source_ip,
    verify_refresh_csrf,
)
from candleviewer.api.csrf import REFRESH_COOKIE as REFRESH_COOKIE  # re-exported (contract name)
from candleviewer.api.enrolment_guard import _unavailable as _session_unchecked
from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec, CsrfVerdict
from candleviewer.auth.errors import (
    RefreshReuseDetected,
    SessionIdleLocked,
    SessionNotFound,
    SessionNotLocked,
    SessionRevoked,
    UnlockPasswordInvalid,
    UserDisabled,
)
from candleviewer.auth.metrics import (
    auth_audit_outcome_lost_total,
    auth_csrf_refused_total,
    auth_enrolment_refused_total,
    auth_session_fixation_attempts_total,
    auth_session_revoke_denied_total,
    normalise_outcome_action,
)
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
    SessionClass,
    UnlockOutcome,
    UnlockWriteAhead,
)
from candleviewer.auth.step_up import PasswordVerdict, grace_expires_at
from candleviewer.auth.throttle import PerIpLoginThrottle

REFRESH_COOKIE_PATH = "/api/v1/auth"
ACCESS_TOKEN_EXPIRES_IN_S = 720  # ADR-0020: 12 min
REFRESH_EXPIRES_IN_S = 12 * 3600
MAX_PAGE = 100
#: `auth.logout` names at most this many target sessions in `after_state.session_ids` and counts
#: every target in `session_count`: the record written before the revocation must not grow with the
#: user's session count, and one the writer refuses is a 503 that keeps the user signed in. The
#: rest are the user's `sessions` rows revoked by that call (auth-rbac.md section 10).
LOGOUT_INTENT_SESSION_IDS_MAX = 50
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
        self, raw_access_token: str, *, touch: bool = False, allow_locked: bool = False
    ) -> SessionRecord: ...

    async def peek_access_token(self, raw_access_token: str) -> SessionRecord | None: ...

    async def require_active(
        self, session_id: str, *, allow_locked: bool = False
    ) -> SessionRecord: ...

    def now(self) -> datetime: ...

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

    async def verify_password(self, user_id: str, password: str) -> PasswordVerdict: ...


class AuthServiceLike(Protocol):
    @property
    def sessions_is_active(self) -> bool: ...

    @property
    def sessions(self) -> SessionServiceLike: ...

    @property
    def enrolment_gate_is_active(self) -> bool: ...

    async def classify(self, session: SessionRecord) -> SessionClass: ...


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
        object_kind: str | None = None,
        object_id: str | None = None,
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


#: SR-026: a self-service route answers only for the authenticated caller, so it takes only the
#: query parameters its contract operation declares; anything else is refused by
#: `api.query_allowlist`, never silently ignored (#2573, #2632). Declared query parameters
#: (22-api-openapi.yaml): `authGetSession` has none; `authListSessions` has `Cursor` and `Limit`;
#: `authLogout`, `authUnlock` and `revokeMySession` have none (`CsrfToken` is a header,
#: `sessionId` a path one).
GET_SESSION_QUERY: frozenset[str] = frozenset()
LIST_SESSIONS_QUERY = frozenset({"cursor", "limit"})
LOGOUT_QUERY: frozenset[str] = frozenset()
UNLOCK_QUERY: frozenset[str] = frozenset()
REVOKE_MY_SESSION_QUERY: frozenset[str] = frozenset()


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def _log() -> Any:
    return structlog.get_logger(__name__)


#: Log lines of a write that failed after its route stopped waiting for it (the tracker's too);
#: `_fixation_attempt` names its own after the action it writes (`<action>.audit_failed_late`).
_PROBE_LATE_FAILURE = "auth.session_revoke_denied.audit_failed_late"


def _probe_audit_failed(error: str) -> None:
    """The probe row was not written; the 404 and the count stand, so the log is the trace."""
    _log().error("auth.session_revoke_denied.audit_unavailable", error=error)


def _count_fixation_audit_lost() -> None:
    """A fixation row that may be lost: its write failed late, or ran on past the drain."""
    auth_session_fixation_attempts_total.labels(reason="audit_unavailable").inc()


def _fixation_audit_failed(error: str, action: str) -> None:
    """The fixation (or rotated-cookie probe, #2300) row *action* was not written; the 401
    stands, so the count and the log are the trace."""
    _count_fixation_audit_lost()
    _log().error(f"{action}.audit_unavailable", error=error)


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
#: Revokes of an id that is not one of the caller's live sessions (AC-CSRF-05, #2319) audited per
#: authenticated user (the caller is known, so the key is the user) and for all users together, per
#: window, with at most the shared `RefusalAuditTracker` cap in flight. Past any of them the 404 is
#: unchanged and the attempt is still counted (`auth_session_revoke_denied_total`), with no audit
#: row and one `unaudited` log line (C-2.9 vs C-2.18, as the fixation row).
PROBE_AUDITS_PER_WINDOW = 10
PROBE_AUDITS_GLOBAL_PER_WINDOW = 30
PROBE_AUDIT_WINDOW_S = 60.0
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
    """Audit sink not active, or its writer refused the record: state-changing session
    actions fail closed (C-2.9). The only error `_audit` raises for an audit failure."""


def make_session_router(
    auth_service: AuthServiceLike,
    audit_service: AuditServiceLike | None = None,
    *,
    identity: IdentityProvider | None = None,
    allowed_origins: frozenset[str] = frozenset(),
    ip_throttle: PerIpLoginThrottle | None = None,
    session_throttle: PerIpLoginThrottle | None = None,
    csrf: CsrfCodec,
    fixation_throttle: PerIpLoginThrottle | None = None,
    fixation_global_throttle: PerIpLoginThrottle | None = None,
    probe_throttle: PerIpLoginThrottle | None = None,
    probe_global_throttle: PerIpLoginThrottle | None = None,
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
    by_probe_user = probe_throttle or PerIpLoginThrottle(
        max_attempts=PROBE_AUDITS_PER_WINDOW, window_s=PROBE_AUDIT_WINDOW_S
    )
    by_probe_all = probe_global_throttle or PerIpLoginThrottle(
        max_attempts=PROBE_AUDITS_GLOBAL_PER_WINDOW,
        window_s=PROBE_AUDIT_WINDOW_S,
        max_tracked_ips=1,
    )
    #: Route-checked SR-041 refusals audited per session per window, as `CsrfMiddleware`
    #: budgets its own (contract "CSRF", "Refusal"): a cookie-identified logout has no
    #: request throttle of its own. Past it: the same 403 with `Retry-After`, no record.
    by_csrf_session = PerIpLoginThrottle(
        max_attempts=SESSION_REFUSALS_PER_WINDOW, window_s=ANON_REFUSAL_WINDOW_S
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
        after_state: dict[str, Any] | None = None,
    ) -> None:
        if audit_service is None or not audit_service.is_active:
            raise AuditUnavailableError
        try:
            await audit_service.writer.emit(
                action,
                actor_label=str(record.user_id) if record else "(unknown)",
                actor_user_id=record.user_id if record else None,
                actor_ip=ip,
                session_id=(
                    session_id if session_id is not None else (record.id if record else None)
                ),
                outcome=outcome,
                severity=severity,
                reason=reason,
                after_state=after_state,
            )
        except AuditError as exc:
            # The writer refused the record (WAL full or unwritable, writer stopped, #2251):
            # the same fail-closed answer as an inactive sink. The log carries the action and
            # the class name only, which keeps a registry bug (`UnknownAuditAction`) visible.
            _log().error(
                "auth.session_audit.writer_refused", action=action, error=type(exc).__name__
            )
            raise AuditUnavailableError from exc

    def _outcome_lost(action: str, sid: str | uuid.UUID, error: str) -> None:
        auth_audit_outcome_lost_total.labels(action=normalise_outcome_action(action)).inc()
        _log().error(
            "auth.session_audit.outcome_lost", action=action, session_id=str(sid), error=error
        )

    async def _audit_outcomes(
        action: str,
        *,
        record: SessionRecord,
        ip: str | None,
        session_ids: tuple[str | uuid.UUID, ...],
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: Severity = Severity.INFO,
        reason: str | None = None,
    ) -> None:
        """Write one outcome record per session id (04-security-program.md §8.3 rule 1: after the
        side effect). The service has already acted, so a lost record is counted, logged (action,
        session and error class only) and alerted, and the answer stands. No retry: exception
        EX-07, §16.2. Each write is bounded by `audit_timeout_s`: the writer never cuts an append
        short, so the record in flight may still land, and a sink that does not answer is not asked
        again (one bound, not one per session). The WS fan-out abandons its audit rows after
        `FANOUT_AUDIT_MAX_FAILURES` in a row (`ws/limits.py`, #2824); one timeout is enough here:
        it is one bound per request, the rows not tried are counted, and a refusal returns at once
        and never ends the loop. A request cancelled part-way is the same: the record
        in flight and every one after it are counted and logged, never dropped silently. So is any
        other error of the write (a defect, not the sink's refusal): the rows it leaves unwritten
        are counted and logged by class name, and it propagates as the 500 it always was."""
        for i, sid in enumerate(session_ids):
            try:
                async with asyncio.timeout(audit_timeout_s):
                    await _audit(
                        action,
                        record=record,
                        ip=ip,
                        outcome=outcome,
                        severity=severity,
                        reason=reason,
                        session_id=sid,
                    )
            except AuditUnavailableError as exc:
                cause = exc.__cause__
                _outcome_lost(action, sid, "inactive" if cause is None else type(cause).__name__)
            except TimeoutError:
                for lost in session_ids[i:]:
                    _outcome_lost(action, lost, "timeout")
                return
            except asyncio.CancelledError:
                for lost in session_ids[i:]:
                    _outcome_lost(action, lost, "cancelled")
                raise
            except Exception as exc:
                for lost in session_ids[i:]:
                    _outcome_lost(action, lost, type(exc).__name__)
                raise

    async def _revoke_denied(request: Request, record: SessionRecord, target: uuid.UUID) -> None:
        """AC-CSRF-05 / SR-019 (#2319): the caller named an id that is not one of their live
        sessions: a foreign or an unknown id (an IDOR probe), or their own session that has already
        ended (a stale Sessions row). The route reads the live list only, so it cannot tell the
        three apart, and the 404 is the same for all of them (no oracle). Counted every time;
        audited within the per-user and the global budget and the tracker's in-flight cap (past
        which one `unaudited` line says why), through the shielded writer path as the CSRF guard
        writes its refusal. The id is a validated UUID row key, not a credential. A slow, failed or
        cancelled write never changes the 404."""
        auth_session_revoke_denied_total.inc()
        key = str(record.user_id)
        if tracker.full or by_probe_user.is_blocked(key) or by_probe_all.is_blocked(_ALL_SOURCES):
            cause = "audit_saturated" if tracker.full else "audit_throttled"
            _log().warning("auth.session_revoke_denied.unaudited", cause=cause)
            return
        by_probe_user.record_failure(key)
        by_probe_all.record_failure(_ALL_SOURCES)
        if audit_service is None or not audit_service.is_active:
            _probe_audit_failed("inactive")
            return
        task = tracker.track(
            audit_service.writer.emit(
                "auth.session_revoke_denied",
                actor_label=key,
                actor_user_id=record.user_id,
                actor_ip=_source_ip(request),
                session_id=record.id,
                object_kind="session",
                object_id=str(target),
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="not_live_own_session",
            ),
            late_failure_event=_PROBE_LATE_FAILURE,
        )
        try:
            await asyncio.wait_for(asyncio.shield(task), audit_timeout_s)
        except TimeoutError:
            # The clock, unless the writer raised `TimeoutError` itself: the task's outcome decides.
            failure = task.exception() if task.done() and not task.cancelled() else None
            if failure is not None:
                _probe_audit_failed(type(failure).__name__)
                return
            tracker.mark_timed_out(task)  # left to finish; never cancelled mid-append
            _log().warning("auth.session_revoke_denied.audit_slow")
        except asyncio.CancelledError:
            tracker.mark_timed_out(task)  # the request is gone; the tracker reports a failure
            raise
        except Exception as exc:
            _probe_audit_failed(type(exc).__name__)

    async def _fixation_attempt(
        request: Request, vector: str, *, rotated: SessionRecord | None = None
    ) -> None:
        """U6/SR-013 (E09-X02 AC2): a session credential this server never issued was
        presented, or, with *rotated*, the `cv_refresh` cookie of a session a refresh
        rotated away was presented outside `/auth/refresh` (a reuse probe: it is not
        revoked here, contract "Idle lock"). The uniform 401 is unchanged (no oracle).
        The attempt is counted, and audited within the per-IP and global budgets and the
        tracker's in-flight cap; the write runs shielded, so a cancelled request never
        cuts it short (as the CSRF guard). The token itself is never recorded; a slow or
        failed write never changes the answer."""
        fixation = auth_session_fixation_attempts_total
        fixation.labels(reason="unknown_token" if rotated is None else "rotated").inc()
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
        action = "auth.refresh_reuse_detected" if rotated else "auth.session_fixation_attempt"
        late = f"{action}.audit_failed_late"
        if audit_service is None or not audit_service.is_active:
            _fixation_audit_failed("inactive", action)
            return
        where = {"vector": vector, "path": _route_path(request)}
        if rotated is None:
            emitted = audit_service.writer.emit(
                action,
                actor_label="(unknown)",
                actor_ip=ip,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="unknown_token",
                after_state=where,
            )
        else:
            emitted = audit_service.writer.emit(
                action,
                actor_label=str(rotated.user_id),
                actor_user_id=rotated.user_id,
                actor_ip=ip,
                session_id=rotated.id,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="rotation_reuse",
                after_state={**where, "family_revoked": False},
            )
        task = tracker.track(emitted, on_lost=_count_fixation_audit_lost, late_failure_event=late)
        try:
            await asyncio.wait_for(asyncio.shield(task), audit_timeout_s)
        except TimeoutError:
            # The clock, unless the writer raised `TimeoutError` itself: the task's outcome decides.
            failure = task.exception() if task.done() and not task.cancelled() else None
            if failure is not None:
                _fixation_audit_failed(type(failure).__name__, action)
                return
            tracker.mark_timed_out(task)  # left to finish; never cancelled mid-append
            fixation.labels(reason="audit_slow").inc()
            _log().warning(f"{action}.audit_slow")
        except asyncio.CancelledError:
            tracker.mark_timed_out(task)  # the request is gone; the tracker reports a failure
            raise
        except Exception as exc:
            _fixation_audit_failed(type(exc).__name__, action)

    async def _refresh_refusal(record: SessionRecord) -> JSONResponse | None:
        """#2295 (Q7): an enrolment-only session that would outlive its 15 minutes was not
        minted as one, and one past them is dead; the enrolment guard answers their every
        request 401. Refresh ends them the same way, before any audit write or rotation, so
        "sign in again" is reached without a bearer too. A session that cannot be classified
        is refused (fail closed); a disabled or deleted user's goes on to #2911's refusal."""
        if not auth_service.enrolment_gate_is_active:
            return None  # no session store: nothing authenticates, so no such session exists
        try:
            verdict = await auth_service.classify(record)
        except Exception as exc:
            auth_enrolment_refused_total.labels(transport="http", reason="unclassified").inc()
            _log().error(
                "auth.enrolment_only.unclassified",
                path="/auth/refresh",
                error=type(exc).__name__,
                session_id=str(record.id),
                user_id=str(record.user_id),
            )
            return _session_unchecked()  # the guard's `503 store_unavailable` and Retry-After
        if verdict is not SessionClass.ENROLMENT_ONLY_EXPIRED:
            return None
        auth_enrolment_refused_total.labels(transport="http", reason="expired").inc()
        _log().warning(
            "auth.enrolment_only.expired",
            path="/auth/refresh",
            session_id=str(record.id),
            user_id=str(record.user_id),
        )
        return _unauthorized("refresh_token_invalid")

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
                token, touch=not allow_locked, allow_locked=allow_locked
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
        `/auth/refresh`) or one never issued (a fixation attempt). A rotated-away cookie
        is counted and audited as a reuse probe; a rotated-away access token is not (a tab
        still holding it after another tab refreshed is normal). The flag is True when
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
        if found.revoked_reason == "rotated":
            await _fixation_attempt(request, "refresh_cookie", rotated=found)
            return None
        return found, True

    async def _introspected(request: Request) -> SessionRecord | None:
        """`GET /auth/session`'s session, locked or not; a revoked or expired one gets
        the uniform 401, as it would to its access token. Never activity. The session
        service's on-use backstop still applies (#2911): a disabled user's session is
        revoked as `user_disabled` and refused."""
        caller = await _identify(request)
        if caller is None:
            return None
        record = caller[0]
        if record.is_revoked or record.is_absolute_expired(now=now()):
            return None
        try:
            return await auth_service.sessions.require_active(str(record.id), allow_locked=True)
        except (SessionNotFound, SessionRevoked):
            return None

    async def _csrf_refusal(
        request: Request, record: SessionRecord, ip: str | None
    ) -> JSONResponse | None:
        """SR-041 for the POSTs that check it themselves (`api.csrf`): against *record*,
        the session the route acts on, before any audit or state change. A refusal is
        counted and audited up to a per-session budget (past it: the same 403 with
        `Retry-After` and no record); it is refused regardless (a 403, never a 500,
        #2238 r3)."""
        refusal = verify_refresh_csrf(
            csrf,
            request.headers.get(CSRF_HEADER),
            request.cookies.get(CSRF_COOKIE),
            str(record.id),
        )
        if refusal is None:
            return None
        auth_csrf_refused_total.labels(reason=refusal.value).inc()
        budget = str(record.id)
        if by_csrf_session.is_blocked(budget):
            auth_csrf_refused_total.labels(reason="audit_throttled").inc()
            throttled = csrf_problem(refusal)
            throttled.headers["Retry-After"] = str(by_csrf_session.retry_after_s(budget) or 1)
            return throttled
        by_csrf_session.record_failure(budget)
        try:
            await _audit(
                "auth.csrf_refused",
                record=record,
                ip=ip,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason=refusal.value,
            )
        except AuditUnavailableError as exc:
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

    async def _chart_step(event: str, step: Awaitable[None]) -> JSONResponse | None:
        """Await an unlock step on B16 (*event* names it), against the row as read while
        locked (B16.7). A failed record answers 503: the edge never reports a step it
        could not record."""
        try:
            await step
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
        if not reuse and not presented_record.is_revoked:
            refused = await _refresh_refusal(presented_record)
            if refused is not None:
                return refused
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
        except RefreshReuseDetected:
            if not reuse:
                # Concurrent-refresh race detected inside the service: the intent record above is
                # followed by the critical outcome. Not write-ahead: the service has already
                # decided, and for a rotated token revoked the family and published every
                # revocation (#2272), so a 503 "nothing changed" would be false. The 401 stands; a
                # lost record is counted, never a 500 (#2251).
                await _audit_outcomes(
                    "auth.refresh_reuse_detected",
                    record=presented_record,
                    ip=ip,
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.CRITICAL,
                    reason="rotation_reuse",
                    session_ids=(presented_record.id,),
                )
            # The service already closed every family member's sockets (#2272).
            return _unauthorized("refresh_token_invalid")
        except UserDisabled:
            # #2911: the user is disabled (or deleted); nothing was minted. The intent record
            # above is followed by the refusal, an outcome record like the reuse one: a lost
            # record is counted and logged and the 401 stands.
            await _audit_outcomes(
                "auth.session_refreshed",
                record=presented_record,
                ip=ip,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="user_disabled",
                session_ids=(presented_record.id,),
            )
            return _unauthorized("refresh_token_invalid")
        except (SessionNotFound, SessionRevoked, SessionIdleLocked):
            return _unauthorized("refresh_token_invalid")
        except asyncio.CancelledError:
            # The service commits a family's revocation before it publishes it to the sockets, so
            # a request cancelled in there (a shutdown) may have ended the family of a token the
            # lookup saw live, and its critical outcome record can no longer be written. The
            # route cannot tell that from a cancellation elsewhere in `refresh()`: counted as
            # lost either way, a false loss being the safe direction. A spent token wrote its
            # record ahead (above), so it loses none.
            if not reuse:
                _outcome_lost("auth.refresh_reuse_detected", presented_record.id, "cancelled")
            raise
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
        if (refusal := undeclared_query_refusal(request, GET_SESSION_QUERY)) is not None:
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
        try:  # #2911's on-use backstop, as on `GET /auth/session`: before any password check
            record = await auth_service.sessions.require_active(str(record.id), allow_locked=True)
        except SessionRevoked as exc:  # e.g. a disabled user's session, now `user_disabled`
            return idle_lock.session_revoked_problem(exc.reason)
        except SessionNotFound:
            return _unauthorized()
        if (refusal := undeclared_query_refusal(request, UNLOCK_QUERY)) is not None:
            return refusal  # SR-026: before the lock state is told or a password checked
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
        # failed record answers 503 with the row still locked. `observe` sends no event
        # but the lock the row shows: the route never sends `REQUEST`.
        if (down := await _chart_step("IDLE_DEADLINE", chart.observe(record, at))) is not None:
            return down
        decided: list[UnlockOutcome] = []
        locked_account: list[datetime] = []
        verify, user_id = authority.verify_password, str(record.user_id)

        async def check(candidate: str) -> bool:
            """The password on login's path (SR-015, SR-016); notes a lockout it applied."""
            verdict = await verify(user_id, candidate)
            if verdict.locked_until is not None:
                locked_account.append(verdict.locked_until)
            return verdict.ok

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
            if locked_account:
                # SR-016: this wrong password locked the account (the check's own write,
                # as on login); recorded before the answer, like login's lockout.
                await _audit(
                    "auth.account_locked",
                    record=record,
                    ip=ip,
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason="unlock_failed",
                )
            if outcome is UnlockOutcome.REVOKED:
                await _audit(
                    "auth.session_revoked",
                    record=record,
                    ip=ip,
                    severity=Severity.WARNING,
                    reason="unlock_attempts_exceeded",
                )

        try:
            unlocked = await auth_service.sessions.unlock(
                str(record.id), password=password, check=check, write_ahead=write_ahead
            )
        except AuditUnavailableError as exc:
            _log().error("auth.unlock.audit_unavailable", error=type(exc).__name__)
            return _audit_down()  # the lock stays and nothing was revoked
        except UnlockPasswordInvalid:
            failed = await _chart_step("UNLOCK_FAILED", chart.record(record, at, "UNLOCK_FAILED"))
            return failed or idle_lock.unlock_invalid_problem()
        except SessionNotLocked:  # lifted by another request since the check above
            return idle_lock.not_locked_problem()
        except SessionRevoked as exc:
            if UnlockOutcome.REVOKED not in decided:  # revoked by something else meanwhile
                return idle_lock.session_revoked_problem(exc.reason)
            # The service already published the revocation: sockets close with 4401 (#2272).
            # B16.7: `revoked` carries this decision to the chart's guard; `replay` keeps the
            # chart from writing a second `auth.session_revoked`.
            failed = await _chart_step(
                "UNLOCK_FAILED",
                chart.record(record, at, "UNLOCK_FAILED", revoked=True, replay=True),
            )
            return failed or idle_lock.session_revoked_problem("unlock_attempts_exceeded")
        except SessionNotFound:
            return _unauthorized()
        lifted = await _chart_step(
            "UNLOCK_OK",
            chart.record(
                record, at, "UNLOCK_OK", idle_expires_at_us=to_us(unlocked.idle_deadline())
            ),
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
        if (refusal := undeclared_query_refusal(request, LIST_SESSIONS_QUERY)) is not None:
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
        """Ends the calling session, or with `all_sessions` every session of the user
        (contract `authLogout`). The session is identified as in "Idle lock": an access
        token inside its lifetime (`CsrfMiddleware` binds the SR-041 token to it), else
        the current `cv_refresh` cookie, checked here (SR-042 Origin, SR-041 against the
        cookie's session). A locked session, and a cookie-identified one, may end only
        itself (#2290 ruling, rule 3b): `all_sessions` is then refused before any record."""
        if not _audit_ready():
            return _problem(503, "Service unavailable", "audit sink not active")
        if not auth_service.sessions_is_active:
            return _problem(503, "Service unavailable", "session backend is not wired")
        caller = await _identify(request)
        if caller is None:
            return _unauthorized()
        record, by_cookie = caller
        at = now()
        if record.is_revoked or record.is_absolute_expired(now=at):
            return _unauthorized()  # uniform, as to its access token: no session oracle
        ip = _source_ip(request)
        if by_cookie:
            if not _origin_ok(request, allowed_origins):
                return _problem(403, "Forbidden", "cross-origin logout refused")  # SR-042
            if (refusal := await _csrf_refusal(request, record, ip)) is not None:
                return refusal
        if (refusal := undeclared_query_refusal(request, LOGOUT_QUERY)) is not None:
            return refusal  # SR-026: before the body is read or the logout audited or revoked
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
        if all_sessions and record.is_idle_locked(now=at):
            # Contract "Idle lock": whoever is at a locked terminal has not proved who they
            # are. Nothing is revoked, audited or cleared, the calling session included.
            return idle_lock.idle_locked_problem(record.idle_deadline())
        if all_sessions and by_cookie:
            return _unauthorized()  # ending every session needs an access token
        # C-2.9 / 04-security-program.md §8.3 rule 1: one intent record, naming the targets, before
        # anything is revoked (audit down => 503, nothing revoked and nothing left to repeat on a
        # retry), then one outcome record per session the service did revoke (#2914).
        reason = "logout_all" if all_sessions else "logout"
        try:
            if all_sessions:
                targets = [
                    str(v.id)
                    for v in await auth_service.sessions.list_sessions(str(record.user_id))
                ]
            else:
                targets = [str(record.id)]
            await _audit(
                "auth.logout",
                record=record,
                ip=ip,
                reason=reason,
                after_state={
                    "session_ids": targets[:LOGOUT_INTENT_SESSION_IDS_MAX],
                    "session_count": len(targets),
                },
            )
        except AuditUnavailableError:
            return _audit_down()
        try:
            if all_sessions:
                revoked = await auth_service.sessions.revoke_all(str(record.user_id), reason=reason)
            else:
                ended = await auth_service.sessions.revoke(str(record.id), reason=reason)
                revoked = () if ended is None else (ended,)
        except asyncio.CancelledError:
            # The service commits the revocation before it publishes it to the sockets, so a
            # request cancelled in there (a shutdown) may have ended sessions without ever seeing
            # which: their outcome rows can no longer be written. Every target is counted and
            # logged as lost, as `_audit_outcomes` does for a cancellation; a session the
            # cancellation reached first is counted too, and a false loss is the safe direction
            # (04-security-program.md §8.3 rule 2).
            for sid in targets:
                _outcome_lost("auth.session_revoked", sid, "cancelled")
            raise
        # What the service revoked, not what was read before: a session may have signed in since.
        await _audit_outcomes(
            "auth.session_revoked",
            record=record,
            ip=ip,
            reason=reason,
            session_ids=tuple(s.id for s in revoked),
        )
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
        if (refusal := undeclared_query_refusal(request, REVOKE_MY_SESSION_QUERY)) is not None:
            return refusal  # SR-026: before the session list is read or anything is revoked
        # IDOR guard: only sessions of the caller's own user are addressable;
        # anything else is indistinguishable from "does not exist" (404).
        own = await auth_service.sessions.list_sessions(
            str(record.user_id), current_session_id=str(record.id)
        )
        if str(session_id) not in {str(v.id) for v in own}:
            await _revoke_denied(request, record, session_id)
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
        await auth_service.sessions.revoke(str(session_id), reason="user_revoked")
        response = Response(status_code=204)
        if session_id == record.id:  # only the caller's own session ends its cookies
            _clear_refresh_cookie(response)
            clear_csrf_cookie(response)
        return response

    return router

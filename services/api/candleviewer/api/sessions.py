"""`POST /auth/refresh`, `GET /auth/session`, `GET /auth/sessions`,
`POST /auth/logout` and `DELETE /me/sessions/{sessionId}` (E09-S03,
US-ONB-004/009; QA defect #1634).

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
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.csrf import clear_csrf_cookie, set_csrf_cookie
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CSRF_COOKIE, CsrfCodec, CsrfVerdict
from candleviewer.auth.errors import (
    RefreshReuseDetected,
    SessionIdleLocked,
    SessionNotFound,
    SessionRevoked,
)
from candleviewer.auth.models import (
    MintedSession,
    RefreshOutcome,
    SessionRecord,
    SessionView,
)
from candleviewer.auth.step_up import grace_expires_at
from candleviewer.auth.throttle import PerIpLoginThrottle

REFRESH_COOKIE = "cv_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
ACCESS_TOKEN_EXPIRES_IN_S = 720  # ADR-0020: 12 min
REFRESH_EXPIRES_IN_S = 12 * 3600
MAX_PAGE = 100


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

    async def revoke(self, session_id: str, *, reason: str) -> SessionRecord | None: ...

    async def revoke_all(
        self, user_id: str, *, reason: str, except_session_id: str | None = None
    ) -> tuple[SessionRecord, ...]: ...

    async def list_sessions(
        self, user_id: str, *, current_session_id: str | None = None
    ) -> tuple[SessionView, ...]: ...


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


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def _source_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


# `/auth/refresh` budget (reuses the E09-S01 sliding-window throttle, one
# instance per key space): at most REFRESH_MAX_PER_WINDOW refresh attempts per
# source IP *and* per presented session within REFRESH_WINDOW_S seconds; the
# next one is 429 + `Retry-After`. A legitimate client refreshes roughly once
# per 12-minute access-token lifetime, so 10/min leaves wide headroom for
# retries and multiple tabs while bounding token-guessing and rotation storms.
REFRESH_MAX_PER_WINDOW = 10
REFRESH_WINDOW_S = 60.0


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
    csrf: CsrfCodec | None = None,
) -> APIRouter:
    router = APIRouter(tags=["auth"])
    by_ip = ip_throttle or PerIpLoginThrottle(
        max_attempts=REFRESH_MAX_PER_WINDOW, window_s=REFRESH_WINDOW_S
    )
    by_session = session_throttle or PerIpLoginThrottle(
        max_attempts=REFRESH_MAX_PER_WINDOW, window_s=REFRESH_WINDOW_S
    )

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

    async def _propagate(session_id: str | uuid.UUID, reason: str) -> None:
        if publish_revocation is not None:
            await publish_revocation(str(session_id), reason)

    def _audit_down() -> JSONResponse:
        # Write-ahead audit failed: nothing has been mutated yet (C-2.9).
        return _problem(503, "Service unavailable", "audit sink not active")

    def _throttled(retry_after: int) -> JSONResponse:
        response = _problem(429, "Too many requests", "refresh rate limit exceeded")
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
        except (SessionNotFound, SessionRevoked):
            return None
        except SessionIdleLocked:
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
            return _unauthorized("refresh_token_invalid")
        session_key = str(presented_record.id)
        if by_session.is_blocked(session_key):
            return _throttled(by_session.retry_after_s(session_key))
        by_session.record_failure(session_key)
        # C-2.9 write-ahead: the audit record is written before `refresh()`
        # rotates or revokes anything; if the sink is down we refuse (503)
        # with no state change.
        reuse = presented_record.revoked_reason == "rotated"
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
        if csrf is not None:  # SR-041: validated by CsrfMiddleware, rotated with the session
            set_csrf_cookie(
                response, csrf.issue(str(minted.session_id)), max_age=REFRESH_EXPIRES_IN_S
            )
        return response

    @router.get("/auth/session")
    async def get_session(request: Request) -> Response:
        if not auth_service.sessions_is_active:
            return _problem(503, "Service unavailable", "session backend is not wired")
        record = await _authenticate(request)
        if record is None:
            return _unauthorized()
        if identity is None:
            return _problem(
                501, "Not implemented", "identity provider not wired (E09-T03); disabled"
            )
        info = await identity.session_info(str(record.user_id))

        response = JSONResponse(
            {
                **info,
                "user": await identity.user(str(record.user_id)),
                "server_time": datetime.now(UTC).isoformat(),
                "step_up_expires_at": _iso(
                    grace_expires_at(record.step_up_elevations, datetime.now(UTC))
                ),
                "session": {
                    "id": str(record.id),
                    "issued_at": record.issued_at.isoformat(),
                    "expires_at": record.expires_at.isoformat(),
                    "idle_deadline": record.idle_deadline().isoformat(),
                },
            }
        )
        if csrf is not None:
            # SR-041 recovery path: re-issue when absent or not verifying.
            present = request.cookies.get(CSRF_COOKIE)
            if not present or csrf.verify(present, str(record.id)) is not CsrfVerdict.OK:
                set_csrf_cookie(response, csrf.issue(str(record.id)), max_age=REFRESH_EXPIRES_IN_S)
        return response

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
        if session_id == record.id:
            _clear_refresh_cookie(response)
        clear_csrf_cookie(response)
        return response

    return router

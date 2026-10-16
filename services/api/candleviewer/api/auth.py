"""`POST /auth/login` (E09-S01, US-ONB-001) and the E09-S02 (US-ONB-002/003)
MFA endpoints: `/auth/mfa/verify`, `/auth/mfa/enroll`,
`/auth/mfa/enroll/confirm`, `/auth/mfa/recovery`.

Thin HTTP adapter over `candleviewer.auth.login_service.LoginService` /
`candleviewer.auth.mfa_service.MfaService`: translates typed domain errors
to the RFC 7807-shaped problem responses the tickets' acceptance criteria
specify, and — when a live `AuditWriter` is injected — emits the
`auth.mfa_*` actions already registered in
`candleviewer.audit.actions.AUDIT_ACTIONS`. `api` (M23) is on the allow-list
to import `candleviewer.audit`; `auth` itself is not (see
`auth/login_service.py`'s module docstring) — that boundary is exactly why
the audit calls live in this router. On the fake/CI default backend
(`audit_writer=None`) the routes still work; they just skip the audit call.

**Enrolment (#2295; formerly Deviation 1, PR #1618 review finding 1):**
`/auth/mfa/enroll` and `/auth/mfa/enroll/confirm` act only for the user of
the caller's bearer session (`x-rbac scope: self`, SR-026): no header and
no query parameter can name another user. A user who already has a
confirmed method gets `409` (voluntary re-enrolment is not specified yet).
Confirm checks the code first, writes its audit records ahead of any change
(C-2.9), then completes the enrolment in one repository transaction,
revokes every session of the user and mints a full one (SR-013). When that
rotation fails after the commit, the method stays active and the answer is a
`503` telling the client to sign in again with it (error log
`auth.enrolment.completed_unrotated`; runbook `auth-rbac.md` section 2).
`/auth/login` answers a user with `mfa_required` and no confirmed method
with an enrolment-only session (`22-api-openapi.yaml` "Enrolment-only
session"); `api/enrolment_guard.py` confines it to five operations. A
session credential carried into that sign-in is audited as at the MFA step.

**Recovery (#2344; formerly Deviation 2, PR #1618 review finding 2):**
`/auth/mfa/verify` mints a full session (QA #1658). `/auth/mfa/recovery`
completes the same challenge with a recovery code and mints the
enrolment-only session instead, never a full one. It checks the code without
spending it, reads the user (fail closed without `mfa_required`, C-12.2),
writes its audit records (C-2.9), then one transaction spends the code,
satisfies the challenge and revokes every MFA method of the user; every
session of the user is revoked next and the new one minted. It used to answer
200 with no session while it spent the code, which locked the user out.

Audit `actor_ip`, the SR-015 per-address sign-in throttle key and the minted
session's `ip` are `api.csrf.source_ip`: the address `MeshOnlyMiddleware`
admitted (trusted-proxy aware), else the socket peer, the same value the
session router and the CSRF guard record. `X-Forwarded-For` is never read here.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from candleviewer.api.csrf import set_csrf_cookie
from candleviewer.api.csrf import source_ip as admitted_source_ip
from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.api.sessions import (
    REFRESH_COOKIE,
    REFRESH_EXPIRES_IN_S,
    IdentityProvider,
    _bearer,
    _set_refresh_cookie,
    _tokens,
    refresh_lifetime_s,
)
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.errors import (
    AccountDisabled,
    AccountLocked,
    AuthError,
    InvalidCredentials,
    MfaChallengeInvalid,
    MfaChallengeLocked,
    MfaCodeInvalid,
    MfaCodeReused,
    MfaEnrollmentNotFound,
    RecoveryCodeInvalid,
    RecoveryCodesExhausted,
)
from candleviewer.auth.login_service import EnrolmentOnlyLogin
from candleviewer.auth.metrics import (
    auth_enrolment_only_sessions_total,
    auth_enrolments_total,
    auth_session_fixation_attempts_total,
    normalise_role,
)
from candleviewer.auth.models import (
    LoginRequest,
    MfaChallengeResult,
    MfaEnrollConfirmRequest,
    MfaEnrollRequest,
    MfaEnrollResult,
    MfaMethodKind,
    MfaMethodRecord,
    MfaMethodView,
    MfaRecoveryCheck,
    MfaRecoveryRequest,
    MfaVerifiedResult,
    MfaVerifyRequest,
    MintedSession,
    SessionRecord,
    SessionView,
    UserRecord,
)
from candleviewer.auth.recovery_codes import RECOVERY_CODE_COUNT

#: `sessions.revoked_reason` and audit `reason` of the sessions a confirmed enrolment ends:
#: every session of the user, the caller's own included (rotation, SR-013) (#2295).
ENROLLED_REASON = "mfa_enrolled"
#: The same for the sessions a recovery sign-in ends: every session of the user (#2344).
RECOVERED_REASON = "mfa_recovery"
#: Titles of the catalogue codes (`x-error-codes`) the enrolment routes answer with.
_UNAUTHENTICATED = "Missing, malformed or expired access token"
_CONFLICT = "Concurrent modification or state conflict"
_INVALID = "Request body or parameters failed schema validation"
_FAILED = AuditOutcome.FAILURE
#: The `detail` of a confirm whose enrolment committed but whose session rotation failed (#2295).
_UNROTATED = "the new TOTP method is active but the session was not rotated; sign in again"
#: The `MfaMethodRecord` fields the `MfaMethod` response shows (never the secret).
_METHOD_FIELDS = {"id", "kind", "label", "created_at", "last_used_at"}


class LoginServiceLike(Protocol):
    """Structural type for `candleviewer.auth.login_service.LoginService`
    (no import edge needed beyond the one `auth.models`/`auth.errors`
    already require for the request/response/error shapes)."""

    async def login(
        self, request: LoginRequest, *, source_ip: str
    ) -> MfaChallengeResult | EnrolmentOnlyLogin: ...


class MfaServiceLike(Protocol):
    """Structural type for `candleviewer.auth.mfa_service.MfaService`."""

    async def verify(self, request: MfaVerifyRequest) -> MfaVerifiedResult: ...

    async def enroll(
        self, user_id: str, request: MfaEnrollRequest, *, account_name: str
    ) -> MfaEnrollResult: ...

    async def check_enrollment(self, user_id: str, *, method_id: str, code: str) -> int: ...

    async def complete_enrollment(
        self, user_id: str, *, method_id: str, time_step: int
    ) -> tuple[MfaMethodRecord, tuple[str, ...]]: ...

    async def check_recovery(self, mfa_token: str, recovery_code: str) -> MfaRecoveryCheck: ...

    async def complete_recovery(self, check: MfaRecoveryCheck) -> None: ...


class SessionMinterLike(Protocol):
    async def mint(
        self,
        user_id: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
        session_id: uuid.UUID | None = None,
    ) -> MintedSession: ...

    async def mint_enrolment_only(
        self,
        user_id: str,
        *,
        session_id: uuid.UUID,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> MintedSession: ...

    async def peek_refresh(self, raw_refresh_token: str) -> SessionRecord | None: ...

    async def peek_access_token(self, raw_access_token: str) -> SessionRecord | None: ...

    async def authenticate_access_token(
        self, raw_access_token: str, *, touch: bool = False
    ) -> SessionRecord: ...

    async def list_sessions(self, user_id: str) -> tuple[SessionView, ...]: ...

    async def revoke_all(self, user_id: str, *, reason: str) -> tuple[SessionRecord, ...]: ...


class AuthServiceLike(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def sessions_is_active(self) -> bool: ...

    @property
    def sessions(self) -> SessionMinterLike: ...

    @property
    def login(self) -> LoginServiceLike: ...

    @property
    def mfa_is_active(self) -> bool: ...

    @property
    def mfa(self) -> MfaServiceLike: ...

    async def find_user(self, user_id: str) -> UserRecord | None: ...


class AuditWriterLike(Protocol):
    """Structural type for `candleviewer.audit.writer.AuditWriter` (only the
    subset of its `emit()` keyword arguments this router actually passes)."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_ip: str | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: Severity = Severity.INFO,
        actor_user_id: str | uuid.UUID | None = None,
        session_id: str | uuid.UUID | None = None,
        reason: str | None = None,
        after_state: dict[str, Any] | None = None,
    ) -> None: ...


class AuditServiceLike(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def writer(self) -> AuditWriterLike: ...


async def _audit(
    audit_service: AuditServiceLike | None,
    action: str,
    *,
    actor_label: str,
    actor_ip: str | None,
    outcome: AuditOutcome,
    severity: Severity = Severity.INFO,
) -> None:
    if audit_service is None or not audit_service.is_active:
        return
    await audit_service.writer.emit(
        action, actor_label=actor_label, actor_ip=actor_ip, outcome=outcome, severity=severity
    )


def _problem(status_code: int, title: str, detail: str, *, code: str | None = None) -> JSONResponse:
    content: dict[str, Any] = {"type": "about:blank", "title": title, "status": status_code}
    if code is not None:  # the catalogue code (`x-error-codes`) and its type URI
        content.update(type=f"https://candleviewer.local/errors/{code}", code=code)
    return JSONResponse(
        status_code=status_code,
        content={**content, "detail": detail},
        media_type="application/problem+json",
    )


def _client_ip(request: Request) -> str | None:
    """Peer address for `audit_log.actor_ip` (an `inet` column): `None`, never
    a placeholder string, when unknown (QA #1658: "unknown" broke the real sink).
    The address MeshOnly admitted, else the socket peer (as the session router).
    Behind the configured trusted proxy it is the client's hop, never the proxy (#2275)."""
    return admitted_source_ip(request.scope)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _redact_identifier(identifier: str) -> str:
    """Best-effort redaction for the audit `actor_label` on a *failed*
    login (C-12.6: "never log ... into an audit record" anything that
    might be a credential). A failed attempt's identifier field may
    actually hold a password the user pasted into the wrong box, so unlike
    the success path (which audits the real, validated username) failure
    audit records only ever get a short, truncated, non-reversible label —
    enough to correlate repeated attempts, never enough to leak a secret."""
    if not identifier:
        return "(empty)"
    return f"{identifier[:3]}***(len={len(identifier)})"


def make_auth_router(
    auth_service: AuthServiceLike,
    audit_service: AuditServiceLike | None = None,
    *,
    identity: IdentityProvider | None = None,
    csrf: CsrfCodec,
) -> APIRouter:
    """Bind `/auth/login` to a concrete `AuthService` instance. *csrf* issues the
    SR-041 `__Host-cv_csrf` cookie wherever a session is minted (#2090)."""
    router = APIRouter(tags=["auth"])

    async def _audit_carried_sessions(request: Request, user_id: uuid.UUID, *, stage: str) -> bool:
        """U6/SR-013 (E09-X02 AC2): a session credential carried into the step that mints a
        session (*stage*: the MFA step, or the password sign-in of an enrolment-only session,
        #2295) is never adopted (`mint` always issues a new id). One that is not this user's
        own session, i.e. never issued here or another user's, is counted and audited as an
        attempt.

        Fail closed (C-2.9 write-ahead): `False` when that record cannot be written, so
        the caller refuses and mints nothing."""
        sessions = auth_service.sessions
        carried = (
            ("refresh_cookie", request.cookies.get(REFRESH_COOKIE)),
            ("bearer", _bearer(request)),
        )
        for vector, raw in carried:
            if not raw:
                continue
            if vector == "refresh_cookie":
                record = await sessions.peek_refresh(raw)
            else:
                record = await sessions.peek_access_token(raw)
            if record is not None and record.user_id == user_id:
                continue  # a stale or parallel session of the same user: a re-login
            reason = "unknown_token" if record is None else "foreign_session"
            auth_session_fixation_attempts_total.labels(reason=reason).inc()
            if audit_service is None or not audit_service.is_active:
                continue
            after: dict[str, Any] = {"vector": vector, "stage": stage}
            if record is not None:
                after["presented_session_id"] = str(record.id)
            try:
                await audit_service.writer.emit(
                    "auth.session_fixation_attempt",
                    actor_label=str(user_id),
                    actor_user_id=user_id,
                    actor_ip=_client_ip(request),
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason=reason,
                    after_state=after,
                )
            except AuditError as exc:
                auth_session_fixation_attempts_total.labels(reason="audit_failed").inc()
                _log().error("auth.session_fixation_attempt.audit_failed", error=type(exc).__name__)
                return False
        return True

    def _enrolment_ready(*, mfa: bool) -> tuple[AuditWriterLike, IdentityProvider] | JSONResponse:
        """The audit writer and the identity provider when every backend an enrolment-only
        sign-in (*mfa* False) or an enrolment step (*mfa* True) needs is wired, else a 503:
        nothing here is minted or changed without its write-ahead audit record (C-2.9)."""
        wired = auth_service.is_active and auth_service.sessions_is_active
        if identity is None or not wired or (mfa and not auth_service.mfa_is_active):
            return _problem(503, "Service unavailable", "enrolment backend is not wired")
        if audit_service is None or not audit_service.is_active:
            return _problem(503, "Service unavailable", "audit sink not active")
        return audit_service.writer, identity

    def _signed_in(
        minted: MintedSession, user: dict[str, Any], *, lifetime_s: int, **extra: Any
    ) -> JSONResponse:
        """`AuthenticatedResponse` (plus *extra*) with the `cv_refresh` and SR-041 cookies of
        the session just minted, each living *lifetime_s* seconds."""
        tokens = _tokens(minted, include_refresh=False, refresh_expires_in=lifetime_s)
        response = JSONResponse(
            status_code=200,
            content={"status": "authenticated", "tokens": tokens, "user": user, **extra},
        )
        _set_refresh_cookie(response, minted.refresh_token, max_age=lifetime_s)
        set_csrf_cookie(response, csrf.issue(str(minted.session_id)), max_age=lifetime_s)
        return response

    async def _enrolment_only_sign_in(
        request: Request, identifier: str, user_id: uuid.UUID
    ) -> JSONResponse:
        """#2295 (Q6, Q7): the session of a user who must enrol TOTP is enrolment-only: minted
        on the password alone for 15 minutes. A session credential carried into this sign-in
        is audited as at the MFA step (U6/SR-013). Write-ahead (C-2.9): that record,
        `auth.login` and `auth.session_created` (`enrolment_only: true`) precede the session,
        and a failed write mints none (503). The user is read before anything is written."""
        ready = _enrolment_ready(mfa=False)
        if isinstance(ready, JSONResponse):
            return ready
        writer, ident = ready
        unaudited = _problem(503, "Service unavailable", "audit sink not active")
        if not await _audit_carried_sessions(request, user_id, stage="login"):
            return unaudited
        user = await ident.user(str(user_id))
        ip, session_id, only = _client_ip(request), uuid.uuid4(), {"enrolment_only": True}
        try:
            await writer.emit(
                "auth.login", actor_label=identifier, actor_user_id=user_id, actor_ip=ip
            )
            await writer.emit(
                "auth.session_created",
                actor_label=str(user_id),
                actor_user_id=user_id,
                actor_ip=ip,
                session_id=session_id,
                after_state={**only, "mfa_satisfied": False},
            )
        except AuditError:
            return unaudited
        minted = await auth_service.sessions.mint_enrolment_only(
            str(user_id), session_id=session_id, ip=ip, user_agent=request.headers.get("user-agent")
        )
        # U33 (RR-15): an Owner's password-only session is the series an alert pages on.
        role = normalise_role(user.get("roles") or ())
        auth_enrolment_only_sessions_total.labels(role=role).inc()
        return _signed_in(minted, user, lifetime_s=refresh_lifetime_s(minted, password_only=True))

    async def _enrolling_caller(
        request: Request,
    ) -> tuple[AuditWriterLike, IdentityProvider, SessionRecord, UserRecord] | JSONResponse:
        """The caller of enrol or confirm (#2295): the live session of the bearer and its
        user, read now. Only the bearer names the user (SR-026: no header and no query
        parameter can). A user who already has a confirmed method gets 409 (Q10: voluntary
        re-enrolment is not specified yet), and nothing changes."""
        ready = _enrolment_ready(mfa=True)
        if isinstance(ready, JSONResponse):
            return ready
        unauthenticated = _problem(
            401, _UNAUTHENTICATED, "authentication required", code="unauthenticated"
        )
        token = _bearer(request)
        if token is None:
            return unauthenticated
        try:
            record = await auth_service.sessions.authenticate_access_token(token, touch=True)
        except AuthError:
            return unauthenticated  # unknown, expired, revoked or idle-locked: one answer
        if (refusal := undeclared_query_refusal(request, frozenset())) is not None:
            return refusal  # SR-026: before the user is read or anything changes
        user = await auth_service.find_user(str(record.user_id))
        if user is None:
            return unauthenticated
        if user.mfa_methods:
            detail = "a confirmed MFA method exists; re-enrolment is not available yet"
            return _problem(409, _CONFLICT, detail, code="conflict")
        return (*ready, record, user)

    @router.post("/auth/login")
    async def login(request: Request, body: LoginRequest) -> JSONResponse:
        if not auth_service.is_active:
            return _problem(503, "Service unavailable", "auth backend is not wired")

        audit_ip = _client_ip(request)
        try:
            # SR-015: keyed on the audited address, so each client behind the configured
            # trusted proxy has its own bucket instead of sharing the proxy's (#2275).
            result = await auth_service.login.login(body, source_ip=audit_ip or "unknown")
        except InvalidCredentials as exc:
            await _audit(
                audit_service,
                "auth.login_failed",
                actor_label=_redact_identifier(body.identifier),
                actor_ip=audit_ip,
                outcome=AuditOutcome.FAILURE,
            )
            return _problem(401, "Invalid credentials", str(exc))
        except AccountDisabled as exc:
            await _audit(
                audit_service,
                "auth.login_failed",
                actor_label=_redact_identifier(body.identifier),
                actor_ip=audit_ip,
                outcome=AuditOutcome.DENIED,
            )
            return _problem(403, "Account disabled", str(exc))
        except AccountLocked as exc:
            await _audit(
                audit_service,
                "auth.account_locked",
                actor_label=_redact_identifier(body.identifier),
                actor_ip=audit_ip,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
            )
            response = _problem(423, "Account locked", str(exc))
            response.headers["Retry-After"] = str(exc.retry_after_s)
            return response
        except NotImplementedError:
            # CodeQL py/stack-trace-exposure: never forward an exception's
            # message (which may embed internal detail such as source
            # locations) into an HTTP response body; this branch only ever
            # fires for the deliberate, out-of-scope stub in
            # `LoginService.login` (see its docstring), so a fixed,
            # generic detail is all a caller needs.
            return _problem(501, "Not implemented", "this login path is not yet available")

        if isinstance(result, EnrolmentOnlyLogin):
            return await _enrolment_only_sign_in(request, body.identifier, result.user_id)
        await _audit(
            audit_service,
            "auth.login",
            actor_label=body.identifier,
            actor_ip=audit_ip,
            outcome=AuditOutcome.SUCCESS,
        )
        return JSONResponse(
            status_code=200,
            content={
                "status": "mfa_required",
                "mfa_token": result.mfa_token,
                "methods": list(result.methods),
                "expires_in": result.expires_in,
            },
        )

    @router.post("/auth/mfa/verify")
    async def mfa_verify(request: Request, body: MfaVerifyRequest) -> JSONResponse:
        if not auth_service.mfa_is_active:
            return _problem(503, "Service unavailable", "mfa backend is not wired")
        try:
            result = await auth_service.mfa.verify(body)
        except (MfaChallengeInvalid, MfaChallengeLocked, MfaCodeInvalid, MfaCodeReused):
            await _audit(
                audit_service,
                "auth.mfa_failed",
                actor_label="(mfa_token)",
                actor_ip=_client_ip(request),
                outcome=AuditOutcome.FAILURE,
            )
            # PR #1618 review finding 4 (low): `str(exc)` used to leak which
            # of "locked" / "expired" / "reused" / "wrong code" applied,
            # which is a free oracle for an unauthenticated caller (e.g.
            # distinguishing "this code was already used" from "this code
            # is simply wrong" narrows a brute-force search). A single
            # generic detail is returned regardless of which of the four
            # errors was raised; the distinct HTTP status/audit action
            # still lets a legitimate, already-authenticated client tell
            # locked apart from merely-wrong via the challenge-expiry UX
            # (SCR-002's "locked after 5 tries" state), not via this text.
            return _problem(401, "MFA verification failed", "invalid or expired code")

        await _audit(
            audit_service,
            "auth.mfa_verified",
            actor_label=str(result.user_id),
            actor_ip=_client_ip(request),
            outcome=AuditOutcome.SUCCESS,
        )
        if identity is None or not auth_service.sessions_is_active:
            # No session backend wired (fake/CI default): E09-S02 behaviour.
            return JSONResponse(status_code=200, content={"status": "authenticated"})
        # QA #1658: second factor satisfied -> mint the session (ADR-0020),
        # set the `cv_refresh` cookie and return `AuthenticatedResponse`.
        if not await _audit_carried_sessions(request, result.user_id, stage="mfa_verify"):
            # Fail closed (C-2.9 write-ahead): the attempt could not be recorded, so nothing is
            # minted. 401 is this operation's documented refusal (no 503 in its contract).
            return _problem(401, "MFA verification failed", "audit sink not active")
        minted = await auth_service.sessions.mint(
            str(result.user_id),
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        if audit_service is not None and audit_service.is_active:
            await audit_service.writer.emit(
                "auth.session_created",
                actor_label=str(result.user_id),
                actor_user_id=result.user_id,
                actor_ip=_client_ip(request),
                session_id=minted.session_id,
                outcome=AuditOutcome.SUCCESS,
                after_state={"mfa_method": "totp", "mfa_satisfied": True},
            )
        response = JSONResponse(
            status_code=200,
            content={
                "status": "authenticated",
                "tokens": _tokens(minted, include_refresh=False),
                "user": await identity.user(str(result.user_id)),
            },
        )
        _set_refresh_cookie(response, minted.refresh_token, max_age=REFRESH_EXPIRES_IN_S)
        # SR-041: the new session gets its own CSRF token
        set_csrf_cookie(response, csrf.issue(str(minted.session_id)), max_age=REFRESH_EXPIRES_IN_S)
        return response

    @router.post("/auth/mfa/recovery")
    async def mfa_recovery(request: Request, body: MfaRecoveryRequest) -> JSONResponse:
        """#2344 (contract `authMfaRecovery`): the code is checked first, unspent, and the user
        read; a user without `mfa_required` is refused (C-12.2). The audit records come next
        (C-2.9): the code's use, one `auth.session_revoked` per live session of the user and
        the new session. Then one transaction spends the code, satisfies the challenge and
        revokes every MFA method; every session of the user is revoked (their sockets close)
        and an enrolment-only session minted (15 minutes, never a full one). Every refusal
        spends nothing. A store failure after the commit mints nothing (500); the user, who
        has no method left, then signs in with the password alone to enrol."""
        ready = _enrolment_ready(mfa=True)
        if isinstance(ready, JSONResponse):
            return ready  # nothing is checked or spent that could not be audited and minted
        writer, ident = ready
        mfa, sessions, ip = auth_service.mfa, auth_service.sessions, _client_ip(request)
        # PR #1618 review finding 4 (low): one detail whether the challenge was invalid,
        # expired or locked, or the code wrong or spent, so an unauthenticated caller cannot
        # use the answer to narrow a brute-force search. `RecoveryCodesExhausted` stays
        # distinct: the ticket's Gherkin ("Recovery codes exhausted") requires a
        # contact-the-owner message the UI must render differently.
        refused = _problem(401, "Recovery failed", "invalid or expired code")
        # Fail closed (C-2.9 write-ahead): 401 is this operation's documented refusal (no 503
        # in its contract), as on `/auth/mfa/verify`.
        unaudited = _problem(401, "Recovery failed", "audit sink not active")
        try:
            check = await mfa.check_recovery(body.mfa_token, body.recovery_code)
        except RecoveryCodesExhausted as exc:
            await _audit(
                audit_service,
                "auth.recovery_codes_exhausted",
                actor_label="(mfa_token)",
                actor_ip=ip,
                outcome=AuditOutcome.DENIED,
                severity=Severity.ERROR,
            )
            return _problem(401, "Recovery codes exhausted", str(exc))
        except (MfaChallengeInvalid, MfaChallengeLocked, RecoveryCodeInvalid):
            await _audit(
                audit_service,
                "auth.mfa_failed",
                actor_label="(mfa_token)",
                actor_ip=ip,
                outcome=_FAILED,
            )
            return refused
        uid = check.user_id
        user = await auth_service.find_user(str(uid))
        if user is None or not user.mfa_required:
            # The contract fails a user without `mfa_required` closed: nothing is spent or
            # minted, and the answer is the one a wrong code gets.
            await _audit(
                audit_service,
                "auth.mfa_failed",
                actor_label=str(uid),
                actor_ip=ip,
                outcome=AuditOutcome.DENIED,
            )
            return refused
        if not await _audit_carried_sessions(request, uid, stage="mfa_recovery"):
            return unaudited
        profile = await ident.user(str(uid))  # before any change: one failure point fewer
        new_id = uuid.uuid4()  # named by the write-ahead records
        only = {"enrolment_only": True, "mfa_method": "recovery_code", "mfa_satisfied": False}
        planned: list[tuple[str, uuid.UUID, str | None, dict[str, Any] | None, Severity]] = [
            (
                "auth.recovery_code_used",
                new_id,
                None,
                {"forced_totp_reenroll": True},
                Severity.WARNING,
            ),
            *(
                ("auth.session_revoked", view.id, RECOVERED_REASON, None, Severity.INFO)
                for view in await sessions.list_sessions(str(uid))
            ),
            ("auth.session_created", new_id, None, only, Severity.INFO),
        ]
        try:
            for action, sid, reason, after, severity in planned:
                await writer.emit(
                    action,
                    actor_label=str(uid),
                    actor_user_id=uid,
                    actor_ip=ip,
                    severity=severity,
                    session_id=sid,
                    reason=reason,
                    after_state=after,
                )
            await mfa.complete_recovery(check)
        except AuditError:
            return unaudited
        except RecoveryCodeInvalid:  # a concurrent request spent the code or the challenge
            await _audit(
                audit_service, "auth.mfa_failed", actor_label=str(uid), actor_ip=ip, outcome=_FAILED
            )
            return refused
        await sessions.revoke_all(str(uid), reason=RECOVERED_REASON)
        minted = await sessions.mint_enrolment_only(
            str(uid), session_id=new_id, ip=ip, user_agent=request.headers.get("user-agent")
        )
        # Read before the commit, which revoked every method: the client opens enrolment.
        shown = {**profile, "mfa_required": user.mfa_required, "mfa_enabled": False}
        return _signed_in(minted, shown, lifetime_s=refresh_lifetime_s(minted, password_only=True))

    @router.post("/auth/mfa/enroll", status_code=201)
    async def mfa_enroll(request: Request, body: MfaEnrollRequest) -> JSONResponse:
        """#2295: start a TOTP enrolment for the caller's own user. Earlier pending methods
        are superseded; the response carries the provisioning URI once and never recovery
        codes. `auth.mfa_enroll` is written ahead of any change (C-2.9)."""
        caller = await _enrolling_caller(request)
        if isinstance(caller, JSONResponse):
            return caller
        writer, _ident, record, user = caller
        if body.method is not MfaMethodKind.TOTP:
            return _problem(
                422, _INVALID, "only method=totp can be enrolled", code="validation_failed"
            )
        try:
            await writer.emit(
                "auth.mfa_enroll",
                actor_label=str(user.id),
                actor_user_id=user.id,
                actor_ip=_client_ip(request),
                session_id=record.id,
                after_state={"method": MfaMethodKind.TOTP.value},
            )
        except AuditError:
            return _problem(503, "Service unavailable", "audit sink not active")
        result = await auth_service.mfa.enroll(str(user.id), body, account_name=user.username)
        content = {
            "method_id": str(result.method_id),
            "method": result.method.value,
            "otpauth_uri": result.otpauth_uri,
            "webauthn_creation_options": None,
        }
        return JSONResponse(status_code=201, content=content)

    @router.post("/auth/mfa/enroll/confirm")
    async def mfa_enroll_confirm(request: Request, body: MfaEnrollConfirmRequest) -> JSONResponse:
        """#2295 (Q8): the code is checked first and the user read (no change), the audit
        records are written next (C-2.9), then one transaction confirms the method, revokes the
        user's other TOTP methods and replaces the recovery codes; every session of the user is
        revoked and a full one minted (SR-013). The 10 new codes appear in this response only.
        If that rotation fails after the commit, the method stays active: the answer is a 503
        telling the client to sign in again with it, and an error log names the sessions."""
        caller = await _enrolling_caller(request)
        if isinstance(caller, JSONResponse):
            return caller
        writer, ident, record, user = caller
        uid, method_id, ip = str(user.id), str(body.method_id), _client_ip(request)
        mfa, sessions = auth_service.mfa, auth_service.sessions
        try:
            step = await mfa.check_enrollment(uid, method_id=method_id, code=body.code)
            profile = await ident.user(uid)  # before any change: one failure point fewer
            new_id = uuid.uuid4()  # named by the write-ahead record
            planned: list[tuple[str, uuid.UUID, dict[str, Any] | None, str | None]] = [
                ("auth.mfa_enrolled", record.id, {"method_id": method_id}, None),
                (
                    "auth.recovery_codes_regenerated",
                    record.id,
                    {"count": RECOVERY_CODE_COUNT},
                    None,
                ),
                *(
                    ("auth.session_revoked", view.id, None, ENROLLED_REASON)
                    for view in await sessions.list_sessions(uid)  # the caller's too: rotation
                ),
                ("auth.session_created", new_id, {"rotated_from": str(record.id)}, None),
            ]
            for action, sid, after, reason in planned:
                await writer.emit(
                    action,
                    actor_label=uid,
                    actor_user_id=user.id,
                    actor_ip=ip,
                    session_id=sid,
                    reason=reason,
                    after_state=after,
                )
            method, codes = await mfa.complete_enrollment(uid, method_id=method_id, time_step=step)
        except AuditError:
            return _problem(503, "Service unavailable", "audit sink not active")
        except (MfaEnrollmentNotFound, MfaCodeInvalid):  # wrong code, other method, lost race
            auth_enrolments_total.labels(outcome="refused").inc()
            await _audit(
                audit_service, "auth.mfa_failed", actor_label=uid, actor_ip=ip, outcome=_FAILED
            )
            detail = "invalid or expired enrolment code"
            return _problem(422, _INVALID, detail, code="validation_failed")
        auth_enrolments_total.labels(outcome="completed").inc()
        try:
            await sessions.revoke_all(uid, reason=ENROLLED_REASON)
            minted = await sessions.mint(
                uid, ip=ip, user_agent=request.headers.get("user-agent"), session_id=new_id
            )
        except Exception as exc:  # any store failure: the committed enrolment stands
            revoked = [str(sid) for act, sid, _, _ in planned if act == "auth.session_revoked"]
            _log().error(
                "auth.enrolment.completed_unrotated",
                user_id=uid,
                session_id=str(record.id),
                revoked_session_ids=revoked,
                new_session_id=str(new_id),
                error=type(exc).__name__,
            )
            return _problem(503, "Service unavailable", _UNROTATED)
        activated = MfaMethodView(active=True, **method.model_dump(include=_METHOD_FIELDS))
        return _signed_in(
            minted,
            {**profile, "mfa_enabled": True},  # read before the commit, which enabled MFA
            lifetime_s=REFRESH_EXPIRES_IN_S,
            mfa_method=activated.model_dump(mode="json"),
            recovery_codes=list(codes),
        )

    return router

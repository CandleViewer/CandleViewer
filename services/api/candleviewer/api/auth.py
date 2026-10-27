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
the audit calls live in this router.

**Audit lane (ADR-0037 Q2, #2914):** a row written after its decision (a refused
or locked sign-in, the password step that passed, a failed second factor, a refused
mint, the recovery's and the confirm's refusal rows, the recovery's `unplanned`
revocations) goes to `AuditService.lane`, the writer its fallback (`_audit_outcome`); one
both refuse, or whose write times out or is cancelled, or that has no sink, is
counted lost (`auth_audit_outcome_lost_total`) and the answer stands. Every
write-ahead record stays on the writer, a mint's in particular, so a mint fails
closed while the sink refuses, whatever the lane would take (U42).

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

**Enrolment-only sign-in (#2295):** `/auth/login` answers a user with
`mfa_required` and no confirmed method with an enrolment-only session
(`22-api-openapi.yaml` "Enrolment-only session"); `api/enrolment_guard.py`
confines it to five operations. A session credential carried into that
sign-in is audited as at the MFA step.

**Recovery (#2344; formerly Deviation 2, PR #1618 review finding 2):**
`/auth/mfa/verify` mints a full session (QA #1658). `/auth/mfa/recovery`
completes the same challenge with a recovery code and mints the
enrolment-only session instead, never a full one. It checks the code without
spending it, reads the user (fail closed without `mfa_required`, C-12.2, or
once disabled, #2911, read again under the user-row lock as the code is
spent), writes its audit records (C-2.9), then one transaction spends the
code, satisfies the challenge and revokes every MFA method of the user; every
session of the user is revoked next and the new one minted. It used to answer
200 with no session while it spent the code, which locked the user out.
Every refusal is the contract's 401, a backend that is not wired and an audit
record that cannot be written included (its 503 is #2152's `AuthUnavailable`).
When the session step fails after that transaction, the 401 tells the client to
sign in again with the password, which is enrolment-only with no method left
(error log `auth.recovery.completed_unminted`; runbook `auth-rbac.md` section 1).

Audit `actor_ip`, the SR-015 per-address sign-in throttle key and the minted
session's `ip` are `api.csrf.source_ip`: the address `MeshOnlyMiddleware`
admitted (trusted-proxy aware), else the socket peer, the same value the
session router and the CSRF guard record. `X-Forwarded-For` is never read here.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Protocol

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from candleviewer.api.csrf import AUDIT_TIMEOUT_S, set_csrf_cookie
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
from candleviewer.audit.service import LaneNotWired
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
    SignInBusy,
    UserDisabled,
)
from candleviewer.auth.hashing import last_verify_ms
from candleviewer.auth.login_service import EnrolmentOnlyLogin
from candleviewer.auth.metrics import (
    auth_audit_outcome_lost_total,
    auth_enrolment_only_sessions_total,
    auth_enrolments_total,
    auth_login_failures_total,
    auth_recovery_codes_used_total,
    auth_session_fixation_attempts_total,
    normalise_outcome_action,
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
    UserStatus,
)
from candleviewer.auth.recovery_codes import RECOVERY_CODE_COUNT
from candleviewer.observability.context import current_request_uuid

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
#: The `title` of every refusal of `/auth/mfa/recovery`: its contract declares 401, never 503.
_RECOVERY_FAILED = "Recovery failed"
#: The row of a refused recovery whose user is disabled or gone, as `_audit_refusal` writes (#2911).
_DISABLED: dict[str, Any] = {"severity": Severity.WARNING, "reason": "user_disabled"}
#: The `detail` of a recovery whose commit spent the code but whose session step failed (#2344):
#: no method is left, so the password alone signs in, enrolment-only.
_UNMINTED = "the recovery code was used but no session was minted; sign in again with your password"
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
        request_id: str | uuid.UUID | None = None,
    ) -> None: ...


class AuditServiceLike(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def writer(self) -> AuditWriterLike: ...

    @property
    def lane(self) -> AuditWriterLike:
        """The journal-first façade (ADR-0037) of a started service, for the outcome and refusal
        rows only; `LaneNotWired` while there is none, as `AuditService.lane` raises."""
        ...


def _problem(
    status_code: int,
    title: str,
    detail: str,
    *,
    code: str | None = None,
    retry_after_s: int | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {"type": "about:blank", "title": title, "status": status_code}
    if code is not None:  # the catalogue code (`x-error-codes`) and its type URI
        content.update(type=f"https://candleviewer.local/errors/{code}", code=code)
    if retry_after_s is not None:  # the `Problem` field and the `Retry-After` header agree
        content["retry_after_seconds"] = retry_after_s
    response = JSONResponse(
        status_code=status_code,
        content={**content, "detail": detail},
        media_type="application/problem+json",
    )
    if retry_after_s is not None:
        response.headers["Retry-After"] = str(retry_after_s)
    return response


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


def _set_argon2_server_timing(challenge: JSONResponse) -> None:
    """#2097 Q2: this login's measured Argon2id verification time (`Hasher.verify` keeps it
    for the request), set only on the 200 challenge: its caller has already proved the
    password, so the header tells an unauthenticated caller nothing (SR-014)."""
    elapsed_ms = last_verify_ms()
    if elapsed_ms is not None:
        challenge.headers["Server-Timing"] = f"argon2;dur={elapsed_ms:.1f}"


def make_auth_router(
    auth_service: AuthServiceLike,
    audit_service: AuditServiceLike | None = None,
    *,
    identity: IdentityProvider | None = None,
    csrf: CsrfCodec,
    server_timing: bool = False,
) -> APIRouter:
    """Bind `/auth/login` to a concrete `AuthService` instance. *csrf* issues the
    SR-041 `__Host-cv_csrf` cookie wherever a session is minted (#2090).
    *server_timing* (#2097, `CV_AUTH_PERF_ENABLED`, keyless testnet only) adds
    `Server-Timing: argon2;dur=<ms>` to the `mfa_required` challenge and to no
    other response, so it never helps tell a wrong password from an unknown user
    (SR-014)."""
    router = APIRouter(tags=["auth"])
    lane_unwired_logged = False

    def _lane_unwired(action: str) -> None:
        """A row goes to the writer alone, as before the lane, because the service has no façade
        (`LaneNotWired`). One warning per router, with the action alone."""
        nonlocal lane_unwired_logged
        if not lane_unwired_logged:
            lane_unwired_logged = True
            _log().warning("auth.login_audit.lane_unavailable", action=action)

    def _outcome_lost(action: str, error: str) -> None:
        auth_audit_outcome_lost_total.labels(action=normalise_outcome_action(action)).inc()
        _log().error("auth.login_audit.outcome_lost", action=action, error=error)

    async def _audit_outcome(action: str, **row: Any) -> None:
        """An outcome or refusal row (04-security-program.md §8.3 rule 1: written after its
        decision), through the lane's façade (ADR-0037 Q2): the lane first, the writer its
        fallback, the two together bounded by the audit timeout. The answer is decided already, so
        a row both refuse, or whose write times out or is cancelled, is counted lost and logged
        (action and error class only, C-12.6) and the answer stands; any other error is a defect,
        counted too, and propagates. A mint's write-ahead records never come here: they stay on
        the writer, so a mint fails closed while the sink refuses (U42)."""
        if audit_service is None or not audit_service.is_active:
            _outcome_lost(action, "inactive")
            return
        try:
            async with asyncio.timeout(AUDIT_TIMEOUT_S):
                try:
                    sink = audit_service.lane
                except LaneNotWired:  # stopping, or never started: the writer alone
                    _lane_unwired(action)
                    sink = audit_service.writer
                await sink.emit(action, request_id=current_request_uuid(), **row)
        except AuditError as exc:
            _outcome_lost(action, type(exc).__name__)
        except TimeoutError:
            _outcome_lost(action, "timeout")
        except asyncio.CancelledError:
            _outcome_lost(action, "cancelled")
            raise
        except Exception as exc:
            _outcome_lost(action, type(exc).__name__)
            raise

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
                    request_id=current_request_uuid(),
                )
            except AuditError as exc:
                auth_session_fixation_attempts_total.labels(reason="audit_failed").inc()
                _log().error("auth.session_fixation_attempt.audit_failed", error=type(exc).__name__)
                return False
        return True

    async def _audit_refusal(
        request: Request,
        user_id: uuid.UUID,
        *,
        session_id: uuid.UUID | None = None,
        after_state: dict[str, Any] | None = None,
    ) -> None:
        """#2911: record a disabled user's refused mint. Not write-ahead (the refusal is
        already decided and nothing was minted): an outcome row through the lane (`_audit_outcome`),
        and the caller's refusal (403 at sign-in, 401 at the MFA step or the confirm) stands.
        *session_id* and *after_state* void a session a write-ahead record announced (#2295)."""
        await _audit_outcome(
            "auth.login_failed",
            actor_label=str(user_id),
            actor_user_id=user_id,
            actor_ip=_client_ip(request),
            outcome=AuditOutcome.DENIED,
            severity=Severity.WARNING,
            reason="user_disabled",
            session_id=session_id,
            after_state=after_state,
        )

    def _enrolment_ready(
        *, mfa: bool, status: int = 503, title: str = "Service unavailable"
    ) -> tuple[AuditWriterLike, IdentityProvider] | JSONResponse:
        """The audit writer and the identity provider when every backend an enrolment-only
        sign-in (*mfa* False) or an enrolment step or recovery (*mfa* True) needs is wired, else
        a *status* refusal (503; 401 on recovery, whose 503 is #2152's `AuthUnavailable`):
        nothing here is minted or changed without its write-ahead audit record (C-2.9)."""
        wired = auth_service.is_active and auth_service.sessions_is_active
        if identity is None or not wired or (mfa and not auth_service.mfa_is_active):
            return _problem(status, title, "enrolment backend is not wired")
        if audit_service is None or not audit_service.is_active:
            return _problem(status, title, "audit sink not active")
        return audit_service.writer, identity

    def _signed_in(
        request: Request,
        minted: MintedSession,
        user: dict[str, Any],
        *,
        lifetime_s: int,
        **extra: Any,
    ) -> JSONResponse:
        """`AuthenticatedResponse` (plus *extra*) with the `cv_refresh` and SR-041 cookies of
        the session just minted, each living *lifetime_s* seconds, and the token header that
        *request* may get (ADR-0038 3b)."""
        tokens = _tokens(minted, include_refresh=False, refresh_expires_in=lifetime_s)
        response = JSONResponse({"status": "authenticated", "tokens": tokens, "user": user} | extra)
        _set_refresh_cookie(response, minted.refresh_token, max_age=lifetime_s)
        set_csrf_cookie(request, response, csrf.issue(str(minted.session_id)), max_age=lifetime_s)
        return response

    async def _enrolment_only_sign_in(
        request: Request, identifier: str, user_id: uuid.UUID
    ) -> JSONResponse:
        """#2295 (Q6, Q7): the session of a user who must enrol TOTP is enrolment-only: minted
        on the password alone for 15 minutes. A session credential carried into this sign-in
        is audited as at the MFA step (U6/SR-013). Write-ahead (C-2.9): that record,
        `auth.login` and `auth.session_created` (`enrolment_only: true`) precede the session,
        and a failed write mints none (503). The user is read before anything is written."""
        if isinstance(ready := _enrolment_ready(mfa=False), JSONResponse):
            return ready
        writer, ident = ready
        unaudited = _problem(503, "Service unavailable", "audit sink not active")
        if not await _audit_carried_sessions(request, user_id, stage="login"):
            return unaudited
        user = await ident.user(str(user_id))
        ip, session_id, only = _client_ip(request), uuid.uuid4(), {"enrolment_only": True}
        try:
            await writer.emit(
                "auth.login",
                actor_label=identifier,
                actor_user_id=user_id,
                actor_ip=ip,
                request_id=current_request_uuid(),
            )
            await writer.emit(
                "auth.session_created",
                actor_label=str(user_id),
                actor_user_id=user_id,
                actor_ip=ip,
                session_id=session_id,
                after_state={**only, "mfa_satisfied": False},
                request_id=current_request_uuid(),
            )
        except AuditError:
            return unaudited
        try:
            minted = await auth_service.sessions.mint_enrolment_only(
                str(user_id),
                session_id=session_id,
                ip=ip,
                user_agent=request.headers.get("user-agent"),
            )
        except UserDisabled:
            # #2911: disabled (or deleted) since the password check; nothing was minted. The
            # records written ahead are followed by the refusal, counted and audited like login's
            # refusal of a disabled account (SR-125), then login's 403 for it: never a 500. Its
            # row voids the session that `auth.session_created` announced (C-2.9).
            auth_login_failures_total.labels(method="password").inc()
            voided = {"voids_session_created": str(session_id)}
            await _audit_refusal(request, user_id, session_id=session_id, after_state=voided)
            return _problem(403, "Account disabled", "Account disabled - contact the owner")
        # U34 (RR-15): an Owner's password-only session is to page; no rule yet (#2746).
        role = normalise_role(user.get("roles") or ())
        auth_enrolment_only_sessions_total.labels(role=role).inc()
        return _signed_in(
            request, minted, user, lifetime_s=refresh_lifetime_s(minted, password_only=True)
        )

    async def _enrolling_caller(
        request: Request,
    ) -> tuple[AuditWriterLike, IdentityProvider, SessionRecord, UserRecord] | JSONResponse:
        """The caller of enrol or confirm (#2295): the live session of the bearer and its
        user, read now. Only the bearer names the user (SR-026: no header and no query
        parameter can). A user who already has a confirmed method gets 409 (Q10: voluntary
        re-enrolment is not specified yet), and nothing changes."""
        if isinstance(ready := _enrolment_ready(mfa=True), JSONResponse):
            return ready
        unauthenticated = _problem(
            401, _UNAUTHENTICATED, "authentication required", code="unauthenticated"
        )
        if (token := _bearer(request)) is None:
            return unauthenticated
        try:
            record = await auth_service.sessions.authenticate_access_token(token, touch=True)
        except AuthError:
            return unauthenticated  # unknown, expired, revoked or idle-locked: one answer
        if (refusal := undeclared_query_refusal(request, frozenset())) is not None:
            return refusal  # SR-026: before the user is read or anything changes
        user = await auth_service.find_user(str(record.user_id))
        if user is None or user.status is UserStatus.DISABLED:  # gone or disabled since (#2911)
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
            auth_login_failures_total.labels(method="password").inc()  # SR-125
            await _audit_outcome(
                "auth.login_failed",
                actor_label=_redact_identifier(body.identifier),
                actor_ip=audit_ip,
                outcome=AuditOutcome.FAILURE,
            )
            return _problem(401, "Invalid credentials", str(exc))
        except AccountDisabled as exc:
            auth_login_failures_total.labels(method="password").inc()
            await _audit_outcome(
                "auth.login_failed",
                actor_label=_redact_identifier(body.identifier),
                actor_ip=audit_ip,
                outcome=AuditOutcome.DENIED,
            )
            return _problem(403, "Account disabled", str(exc))
        except AccountLocked as exc:
            await _audit_outcome(
                "auth.account_locked",
                actor_label=_redact_identifier(body.identifier),
                actor_ip=audit_ip,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
            )
            response = _problem(423, "Account locked", str(exc))
            response.headers["Retry-After"] = str(exc.retry_after_s)
            return response
        except SignInBusy as exc:
            # #4663: refused before the identifier was looked up or the password checked, so
            # only the attempt itself is recorded; counted by `LoginService`.
            await _audit_outcome(
                "auth.login_failed",
                actor_label=_redact_identifier(body.identifier),
                actor_ip=audit_ip,
                outcome=AuditOutcome.DENIED,
                reason="verify_busy",
            )
            return _problem(
                429,
                "Too many requests",
                str(exc),
                code="rate_limited",
                retry_after_s=exc.retry_after_s,
            )
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
        # The password step's outcome: no session exists yet (the mint's records are MFA's).
        await _audit_outcome(
            "auth.login",
            actor_label=body.identifier,
            actor_ip=audit_ip,
            outcome=AuditOutcome.SUCCESS,
        )
        challenge = JSONResponse(
            status_code=200,
            content={
                "status": "mfa_required",
                "mfa_token": result.mfa_token,
                "methods": list(result.methods),
                "expires_in": result.expires_in,
            },
        )
        if server_timing:
            _set_argon2_server_timing(challenge)
        return challenge

    @router.post("/auth/mfa/verify")
    async def mfa_verify(request: Request, body: MfaVerifyRequest) -> JSONResponse:
        if not auth_service.mfa_is_active:
            return _problem(503, "Service unavailable", "mfa backend is not wired")
        try:
            result = await auth_service.mfa.verify(body)
        except (MfaChallengeInvalid, MfaChallengeLocked, MfaCodeInvalid, MfaCodeReused):
            auth_login_failures_total.labels(method=body.method.value).inc()
            await _audit_outcome(
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

        # Fail closed (C-2.9 write-ahead): a record that cannot be written mints nothing. 401 is
        # this operation's documented refusal (its 503 is #2152's `AuthUnavailable`).
        unaudited = _problem(401, "MFA verification failed", "audit sink not active")
        if audit_service is not None and audit_service.is_active:
            # The mint's first write-ahead record (ADR-0037 decision 3): the writer's, never the
            # lane's (U42), so while the sink refuses nothing is minted (the step stays spent).
            try:
                await audit_service.writer.emit(
                    "auth.mfa_verified",
                    actor_label=str(result.user_id),
                    actor_ip=_client_ip(request),
                    outcome=AuditOutcome.SUCCESS,
                    request_id=current_request_uuid(),
                )
            except AuditError:
                return unaudited
        if identity is None or not auth_service.sessions_is_active:
            # No session backend wired (fake/CI default): E09-S02 behaviour.
            return JSONResponse(status_code=200, content={"status": "authenticated"})
        # QA #1658: second factor satisfied -> mint the session (ADR-0020),
        # set the `cv_refresh` cookie and return `AuthenticatedResponse`.
        if not await _audit_carried_sessions(request, result.user_id, stage="mfa_verify"):
            return unaudited
        session_id = uuid.uuid4()  # named by its write-ahead record, as at sign-in (#2914)
        if audit_service is not None and audit_service.is_active:
            try:
                await audit_service.writer.emit(
                    "auth.session_created",
                    actor_label=str(result.user_id),
                    actor_user_id=result.user_id,
                    actor_ip=_client_ip(request),
                    session_id=session_id,
                    outcome=AuditOutcome.SUCCESS,
                    after_state={"mfa_method": "totp", "mfa_satisfied": True},
                    request_id=current_request_uuid(),
                )
            except AuditError:
                return unaudited
        try:
            minted = await auth_service.sessions.mint(
                str(result.user_id),
                ip=_client_ip(request),
                user_agent=request.headers.get("user-agent"),
                session_id=session_id,
            )
        except UserDisabled:
            # #2911: disabled (or deleted) since the password step; nothing was minted.
            # Counted and audited like login's refusal of a disabled account, then this
            # operation's 401 whether or not the record could be written. The count is one per
            # `auth.login_failed` row, on the factor the request named: the code was right, so
            # neither `totp` nor `webauthn` is the wrong one (#3054). Its row voids the session
            # `auth.session_created` announced (C-2.9).
            auth_login_failures_total.labels(method=body.method.value).inc()
            voided = {"voids_session_created": str(session_id)}
            await _audit_refusal(request, result.user_id, session_id=session_id, after_state=voided)
            return _problem(401, "MFA verification failed", "account is disabled")
        except Exception as exc:  # a store failure: nothing was minted, and the 500 stands
            # Its `auth.mfa_failed` row voids the session `auth.session_created` announced (C-2.9)
            # and counts as this route's other `auth.mfa_failed` rows do (SR-125). The error log
            # names both ids and the error class only (C-12.6), in case that row is lost too.
            auth_login_failures_total.labels(method=body.method.value).inc()
            _log().error(
                "auth.mfa_verify.unminted",
                user_id=str(result.user_id),
                new_session_id=str(session_id),
                error=type(exc).__name__,
            )
            await _audit_outcome(
                "auth.mfa_failed",
                actor_label=str(result.user_id),
                actor_user_id=result.user_id,
                actor_ip=_client_ip(request),
                outcome=_FAILED,
                session_id=session_id,
                reason="unminted",
                after_state={"voids_session_created": str(session_id)},
            )
            raise
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
        set_csrf_cookie(
            request, response, csrf.issue(str(minted.session_id)), max_age=REFRESH_EXPIRES_IN_S
        )
        return response

    @router.post("/auth/mfa/recovery")
    async def mfa_recovery(request: Request, body: MfaRecoveryRequest) -> JSONResponse:
        """#2344 (contract `authMfaRecovery`): the code is checked first, unspent, and the user
        read; a user without `mfa_required` (C-12.2) or disabled since the password step
        (#2911) is refused. The audit records come next (C-2.9): the code's use, one
        `auth.session_revoked` per live session of the user and the new session. Then one
        transaction spends the code, satisfies the challenge and revokes every MFA method, or
        rolls back for a user disabled meanwhile; every session of the user is revoked (their
        sockets close; one the records could not name gets its own, `unplanned`) and an
        enrolment-only session minted (15 minutes, never a full one). Every refusal spends
        nothing, is the documented 401 and counts its row (SR-125). A failure after the commit
        mints nothing: its 401 tells the client to sign in again with the password, which is
        enrolment-only once no method is left, the error log `auth.recovery.completed_unminted`
        names the user and the sessions, and a refusal row voids the session announced."""
        # 401 is this operation's documented refusal (its 503 is #2152's `AuthUnavailable`), as on
        # `/auth/mfa/verify`: nothing is checked or spent that could not be audited and minted.
        ready = _enrolment_ready(mfa=True, status=401, title=_RECOVERY_FAILED)
        if isinstance(ready, JSONResponse):
            return ready
        writer, ident = ready
        mfa, sessions, ip = auth_service.mfa, auth_service.sessions, _client_ip(request)
        # PR #1618 review finding 4 (low): one detail whether the challenge was invalid,
        # expired or locked, the code wrong or spent, or a record could not be written (the
        # cause is logged), so an unauthenticated caller cannot use the answer to narrow a
        # brute-force search. `RecoveryCodesExhausted` stays distinct: the ticket's Gherkin
        # ("Recovery codes exhausted") requires a contact-the-owner message the UI must render
        # differently.
        refused = _problem(401, _RECOVERY_FAILED, "invalid or expired code")

        async def failed(action: str, outcome: AuditOutcome, **row: Any) -> JSONResponse:
            """A refusal's row, counted once (SR-125). It follows the refusal, never ahead of it:
            an outcome row through the lane (`_audit_outcome`), and the answer stands either way."""
            auth_login_failures_total.labels(method=MfaMethodKind.RECOVERY_CODE.value).inc()
            await _audit_outcome(action, actor_ip=ip, outcome=outcome, **row)
            return refused

        try:
            check = await mfa.check_recovery(body.mfa_token, body.recovery_code)
        except RecoveryCodesExhausted as exc:
            exhausted = {"actor_label": "(mfa_token)", "severity": Severity.ERROR}
            await failed("auth.recovery_codes_exhausted", AuditOutcome.DENIED, **exhausted)
            return _problem(401, "Recovery codes exhausted", str(exc))
        except (MfaChallengeInvalid, MfaChallengeLocked, RecoveryCodeInvalid):
            return await failed("auth.mfa_failed", _FAILED, actor_label="(mfa_token)")
        uid = check.user_id
        mine: dict[str, Any] = {"actor_label": str(uid), "actor_user_id": uid}
        user = await auth_service.find_user(str(uid))
        if user is None or not user.mfa_required:
            # The contract fails a user without `mfa_required` closed: nothing is spent or
            # minted, and the answer is the one a wrong code gets.
            return await failed("auth.mfa_failed", AuditOutcome.DENIED, **mine)
        if user.status is UserStatus.DISABLED:
            # #2911: disabled since the password step, refused as a mint is (not `locked` or
            # `invited`), before anything is written or spent; the answer stays uniform.
            return await failed("auth.login_failed", AuditOutcome.DENIED, **_DISABLED, **mine)
        if not await _audit_carried_sessions(request, uid, stage="mfa_recovery"):
            return refused  # C-2.9 write-ahead; the cause is logged there
        profile = await ident.user(str(uid))  # before any change: one failure point fewer
        new_id = uuid.uuid4()  # named by the write-ahead records
        ending = [view.id for view in await sessions.list_sessions(str(uid))]
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
                ("auth.session_revoked", sid, RECOVERED_REASON, None, Severity.INFO)
                for sid in ending
            ),
            ("auth.session_created", new_id, None, only, Severity.INFO),
        ]

        async def write(
            action: str,
            sid: uuid.UUID,
            reason: str | None,
            after: dict[str, Any] | None,
            severity: Severity = Severity.INFO,
            outcome: AuditOutcome = AuditOutcome.SUCCESS,
        ) -> None:
            await writer.emit(
                action,
                actor_label=str(uid),
                actor_user_id=uid,
                actor_ip=ip,
                outcome=outcome,
                severity=severity,
                session_id=sid,
                reason=reason,
                after_state=after,
                request_id=current_request_uuid(),
            )

        try:
            for action, sid, reason, after, severity in planned:
                await write(action, sid, reason, after, severity)
        except AuditError as exc:  # C-2.9 write-ahead: nothing is spent without its records
            _log().error("auth.recovery.audit_unavailable", action=action, error=type(exc).__name__)
            return refused
        # Should the transaction not commit, nothing changed, and the refusal's row voids the
        # session and the revocations announced above.
        voided = {
            "voids_session_created": str(new_id),
            "voids_session_revoked": [str(sid) for sid in ending],
        }
        void = {"session_id": new_id, "after_state": voided, **mine}
        try:
            await mfa.complete_recovery(check)
        except UserDisabled:  # #2911: disabled since the read, under the user-row lock
            return await failed("auth.login_failed", AuditOutcome.DENIED, **_DISABLED, **void)
        except RecoveryCodeInvalid:  # a concurrent request spent the code or the challenge
            return await failed("auth.mfa_failed", _FAILED, reason="lost_race", **void)
        except Exception as exc:  # a store failure (a timeout, a deadlock) rolls it back
            _log().error(
                "auth.recovery.commit_failed",
                user_id=str(uid),
                new_session_id=str(new_id),
                error=type(exc).__name__,
            )
            return await failed("auth.mfa_failed", _FAILED, reason="store_error", **void)
        # SR-022 (#2496): each spent code pages the Owner (`AuthRecoveryCodeUsed`). Counted as soon
        # as the commit spent it, so no later failure can hide a use; a failing audit sink cannot
        # either, because nothing is spent without its record (written ahead above).
        auth_recovery_codes_used_total.inc()
        created = {"session_id": new_id, "after_state": {"voids_session_created": str(new_id)}}
        unplanned: list[uuid.UUID] = []  # minted since the plan, so its records do not name them
        try:
            revoked = await sessions.revoke_all(str(uid), reason=RECOVERED_REASON)
            unplanned = [row.id for row in revoked if row.id not in ending]
            for sid in unplanned:  # outcome rows: each revocation has happened
                await _audit_outcome(
                    "auth.session_revoked",
                    actor_ip=ip,
                    session_id=sid,
                    reason=RECOVERED_REASON,
                    after_state={"unplanned": True},
                    **mine,
                )
            minted = await sessions.mint_enrolment_only(
                str(uid), session_id=new_id, ip=ip, user_agent=request.headers.get("user-agent")
            )
        except UserDisabled:  # #2911: disabled since the commit; the code is spent, nothing minted
            await failed("auth.login_failed", AuditOutcome.DENIED, **_DISABLED, **mine, **created)
            return _problem(401, _RECOVERY_FAILED, "account is disabled")
        except Exception as exc:  # any failure: the committed recovery stands, nothing is minted
            _log().error(
                "auth.recovery.completed_unminted",
                user_id=str(uid),
                new_session_id=str(new_id),
                revoked_session_ids=[str(sid) for sid in (*ending, *unplanned)],
                error=type(exc).__name__,
            )
            await failed("auth.mfa_failed", _FAILED, reason="unminted", **mine, **created)  # C-2.9
            return _problem(401, _RECOVERY_FAILED, _UNMINTED)
        # U34 (RR-15): an Owner's enrolment-only session is to page; no rule yet (#2746).
        auth_enrolment_only_sessions_total.labels(
            role=normalise_role(profile.get("roles") or ())
        ).inc()
        # Read before the commit, which revoked every method: the client opens enrolment.
        shown = {**profile, "mfa_required": user.mfa_required, "mfa_enabled": False}
        return _signed_in(
            request, minted, shown, lifetime_s=refresh_lifetime_s(minted, password_only=True)
        )

    @router.post("/auth/mfa/enroll", status_code=201)
    async def mfa_enroll(request: Request, body: MfaEnrollRequest) -> JSONResponse:
        """#2295: start a TOTP enrolment for the caller's own user. Earlier pending methods
        are superseded; the response carries the provisioning URI once and never recovery
        codes. `auth.mfa_enroll` is written ahead of any change (C-2.9)."""
        if isinstance(caller := await _enrolling_caller(request), JSONResponse):
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
                request_id=current_request_uuid(),
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
        telling the client to sign in again with it, and an error log names the sessions. A
        transaction that does not commit changes nothing: the error log
        `auth.enrolment.commit_failed` names the user and the new session, and the refusal's row
        voids that session (#2344, as on the recovery). A lost race answers 422 as a wrong code
        does, a store failure 500, and a user disabled since the read (#2911, read again under
        the user-row lock) `_enrolling_caller`'s 401."""
        if isinstance(caller := await _enrolling_caller(request), JSONResponse):
            return caller
        writer, ident, record, user = caller
        uid, method_id, ip = str(user.id), str(body.method_id), _client_ip(request)
        mfa, sessions = auth_service.mfa, auth_service.sessions
        invalid = _problem(
            422, _INVALID, "invalid or expired enrolment code", code="validation_failed"
        )
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
                    request_id=current_request_uuid(),
                )
        except AuditError:
            return _problem(503, "Service unavailable", "audit sink not active")
        except (MfaEnrollmentNotFound, MfaCodeInvalid):  # wrong code, no such pending method
            auth_enrolments_total.labels(result="refused").inc()
            await _audit_outcome("auth.mfa_failed", actor_label=uid, actor_ip=ip, outcome=_FAILED)
            return invalid

        void: dict[str, Any] = {"voids_session_created": str(new_id)}

        async def uncommitted(exc: Exception, reason: str) -> None:
            """Nothing changed: the error log names the ids and the error class (C-12.6), and the
            refusal's row voids the session the records above announced (C-2.9)."""
            _log().error(
                "auth.enrolment.commit_failed",
                user_id=uid,
                new_session_id=str(new_id),
                error=type(exc).__name__,
            )
            if reason == "user_disabled":  # the row of a disabled user's refused mint
                await _audit_refusal(request, user.id, session_id=new_id, after_state=void)
                return
            await _audit_outcome(
                "auth.mfa_failed",
                actor_label=uid,
                actor_user_id=user.id,
                actor_ip=ip,
                outcome=_FAILED,
                session_id=new_id,
                reason=reason,
                after_state=void,
            )

        try:
            method, codes = await mfa.complete_enrollment(uid, method_id=method_id, time_step=step)
        except UserDisabled as exc:  # #2911: disabled since the read, under the user-row lock
            await uncommitted(exc, "user_disabled")
            return _problem(
                401, _UNAUTHENTICATED, "authentication required", code="unauthenticated"
            )
        except MfaEnrollmentNotFound as exc:  # a concurrent confirm or enrolment won
            auth_enrolments_total.labels(result="refused").inc()
            await uncommitted(exc, "lost_race")
            return invalid
        except Exception as exc:  # a store failure (a timeout, a deadlock): still the 500
            await uncommitted(exc, "store_error")
            raise
        auth_enrolments_total.labels(result="completed").inc()
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
            request,
            minted,
            {**profile, "mfa_enabled": True},  # read before the commit, which enabled MFA
            lifetime_s=REFRESH_EXPIRES_IN_S,
            mfa_method=activated.model_dump(mode="json"),
            recovery_codes=list(codes),
        )

    return router

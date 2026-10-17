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

**Deviation 1 (PR #1618 review finding 1 — security, blocking until
resolved as below):** `/auth/mfa/enroll`, `/auth/mfa/enroll/confirm` and
`/auth/mfa/recovery`'s regeneration sibling are `x-rbac scope: self` per
`22-api-openapi.yaml`, which normally means "the authenticated caller,
resolved from their session". Real session authentication (the
`cv_refresh` cookie / bearer access token / RBAC middleware) is E09-S03
scope, not yet merged, so there is today no way to verify that an
`X-User-Id`/`X-Username` header actually belongs to the caller — trusting
it would let anyone enrol (and read the one-time recovery codes for) any
account, an MFA takeover. Per this repo's multi-agent protocol §5 this is
not a "minor gap" (it touches security/money-adjacent identity), so rather
than guessing at an undocumented trust boundary, `/auth/mfa/enroll` and
`/auth/mfa/enroll/confirm` are **disabled** (`501 Not Implemented`) until
E09-S03 wires real session/principal resolution — mirroring exactly how
`api/audit.py`'s `principal_resolver=None` path already fails closed with
`501` for the same reason (see that module's docstring). `/auth/login`,
`/auth/mfa/verify` and `/auth/mfa/recovery`'s login path need no such
header: they resolve the user from the `mfa_token` challenge alone,
exactly like `/auth/login` needs no prior session — so those three stay
enabled.

**Deviation 2 (PR #1618 review finding 2 — acceptance criterion):** the
ticket's "Valid code creates a session" scenario is not fully met by this
PR: `/auth/mfa/verify` and the recovery-code login path in
`/auth/mfa/recovery` both return `{"status": "authenticated"}` but mint no
session (no `cv_refresh` cookie, no access token) — session/token minting
is E09-S03 scope (`auth/login_service.py`'s own docstring: "non-MFA
session issuance is E09-S03 scope"; the same boundary applies to the MFA
leg). This PR closes E09-S02 exactly as scoped ("second factor,
enrolment and recovery codes"); the end-to-end scenario is completed by
E09-S03, which is already `blocked_by` this story and picks this up next.

Audit `actor_ip`, the SR-015 per-address sign-in throttle key and the minted
session's `ip` are `api.csrf.source_ip`: the address `MeshOnlyMiddleware`
admitted (trusted-proxy aware), else the socket peer, the same value the
session router and the CSRF guard record. `X-Forwarded-For` is never read here.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from candleviewer.api.csrf import set_csrf_cookie
from candleviewer.api.csrf import source_ip as admitted_source_ip
from candleviewer.api.sessions import (
    REFRESH_COOKIE,
    REFRESH_EXPIRES_IN_S,
    IdentityProvider,
    _bearer,
    _set_refresh_cookie,
    _tokens,
)
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.errors import (
    AccountDisabled,
    AccountLocked,
    InvalidCredentials,
    MfaChallengeInvalid,
    MfaChallengeLocked,
    MfaCodeInvalid,
    MfaCodeReused,
    RecoveryCodeInvalid,
    RecoveryCodesExhausted,
    UserDisabled,
)
from candleviewer.auth.hashing import last_verify_ms
from candleviewer.auth.metrics import (
    auth_login_failures_total,
    auth_recovery_codes_used_total,
    auth_session_fixation_attempts_total,
)
from candleviewer.auth.models import (
    LoginRequest,
    MfaChallengeResult,
    MfaEnrollConfirmRequest,
    MfaEnrollRequest,
    MfaEnrollResult,
    MfaMethodKind,
    MfaRecoveryRequest,
    MfaVerifiedResult,
    MfaVerifyRequest,
    MintedSession,
    SessionRecord,
)


class LoginServiceLike(Protocol):
    """Structural type for `candleviewer.auth.login_service.LoginService`
    (no import edge needed beyond the one `auth.models`/`auth.errors`
    already require for the request/response/error shapes)."""

    async def login(self, request: LoginRequest, *, source_ip: str) -> MfaChallengeResult: ...


class MfaServiceLike(Protocol):
    """Structural type for `candleviewer.auth.mfa_service.MfaService`."""

    async def verify(self, request: MfaVerifyRequest) -> MfaVerifiedResult: ...

    async def enroll(
        self, user_id: str, request: MfaEnrollRequest, *, account_name: str
    ) -> MfaEnrollResult: ...

    async def confirm_enrollment(
        self, user_id: str, *, method_id: str, code: str
    ) -> tuple[MfaMethodKind, tuple[str, ...]]: ...

    async def recover(self, mfa_token: str, recovery_code: str) -> MfaVerifiedResult: ...


class SessionMinterLike(Protocol):
    async def mint(
        self, user_id: str, *, ip: str | None = None, user_agent: str | None = None
    ) -> MintedSession: ...

    async def peek_refresh(self, raw_refresh_token: str) -> SessionRecord | None: ...

    async def peek_access_token(self, raw_access_token: str) -> SessionRecord | None: ...


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


def _problem(status_code: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"type": "about:blank", "title": title, "status": status_code, "detail": detail},
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

    async def _audit_carried_sessions(request: Request, user_id: uuid.UUID) -> bool:
        """U6/SR-013 (E09-X02 AC2): a session credential carried into the MFA step is never
        adopted (`mint` always issues a new id). One that is not this user's own session,
        i.e. never issued here or another user's, is counted and audited as an attempt.

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
            after: dict[str, Any] = {"vector": vector, "stage": "mfa_verify"}
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

    async def _audit_refusal(request: Request, user_id: uuid.UUID) -> None:
        """#2911: record a disabled user's refused mint. Not write-ahead (the refusal is
        already decided and nothing was minted): a record that cannot be written is logged,
        and the caller's 401 stands."""
        if audit_service is None or not audit_service.is_active:
            _log().error("auth.login_failed.audit_unavailable", error="inactive")
            return
        try:
            await audit_service.writer.emit(
                "auth.login_failed",
                actor_label=str(user_id),
                actor_user_id=user_id,
                actor_ip=_client_ip(request),
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="user_disabled",
            )
        except AuditError as exc:
            _log().error("auth.login_failed.audit_unavailable", error=type(exc).__name__)

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
            await _audit(
                audit_service,
                "auth.login_failed",
                actor_label=_redact_identifier(body.identifier),
                actor_ip=audit_ip,
                outcome=AuditOutcome.FAILURE,
            )
            return _problem(401, "Invalid credentials", str(exc))
        except AccountDisabled as exc:
            auth_login_failures_total.labels(method="password").inc()
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

        await _audit(
            audit_service,
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
        if not await _audit_carried_sessions(request, result.user_id):
            # Fail closed (C-2.9 write-ahead): the attempt could not be recorded, so nothing is
            # minted. 401 is this operation's documented refusal (no 503 in its contract).
            return _problem(401, "MFA verification failed", "audit sink not active")
        try:
            minted = await auth_service.sessions.mint(
                str(result.user_id),
                ip=_client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
        except UserDisabled:
            # #2911: disabled (or deleted) since the password step; nothing was minted.
            # Audited like login's refusal of a disabled account, then this operation's 401
            # whether or not the record could be written.
            await _audit_refusal(request, result.user_id)
            return _problem(401, "MFA verification failed", "account is disabled")
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
        if not auth_service.mfa_is_active:
            return _problem(503, "Service unavailable", "mfa backend is not wired")
        try:
            result = await auth_service.mfa.recover(body.mfa_token, body.recovery_code)
        except RecoveryCodesExhausted as exc:
            auth_login_failures_total.labels(method=MfaMethodKind.RECOVERY_CODE.value).inc()
            await _audit(
                audit_service,
                "auth.recovery_codes_exhausted",
                actor_label="(mfa_token)",
                actor_ip=_client_ip(request),
                outcome=AuditOutcome.DENIED,
                severity=Severity.ERROR,
            )
            return _problem(401, "Recovery codes exhausted", str(exc))
        except (MfaChallengeInvalid, MfaChallengeLocked, RecoveryCodeInvalid):
            auth_login_failures_total.labels(method=MfaMethodKind.RECOVERY_CODE.value).inc()
            await _audit(
                audit_service,
                "auth.mfa_failed",
                actor_label="(mfa_token)",
                actor_ip=_client_ip(request),
                outcome=AuditOutcome.FAILURE,
            )
            # PR #1618 review finding 4 (low): same rationale as
            # `mfa_verify` above — a uniform detail regardless of whether
            # the challenge was invalid/expired/locked or the code was
            # simply wrong, so an unauthenticated caller cannot use this
            # response to narrow a brute-force search. `RecoveryCodesExhausted`
            # stays a distinct branch above because the ticket's own
            # Gherkin ("Recovery codes exhausted") requires a
            # contact-the-owner message the UI must render differently.
            return _problem(401, "Recovery failed", "invalid or expired code")

        # SR-022 (#2496): each use pages the Owner (`AuthRecoveryCodeUsed`). Counted before the
        # audit write, so a failing audit sink cannot hide a use (the count can then exceed rows).
        auth_recovery_codes_used_total.inc()
        await _audit(
            audit_service,
            "auth.recovery_code_used",
            actor_label=str(result.user_id),
            actor_ip=_client_ip(request),
            outcome=AuditOutcome.SUCCESS,
            severity=Severity.WARNING,
        )
        return JSONResponse(
            status_code=200,
            content={
                "status": "authenticated",
                "forced_totp_reenroll": result.forced_totp_reenroll,
            },
        )

    @router.post("/auth/mfa/enroll", status_code=201)  # nosem: audit-write-required reason=fail-closed-501-stub-no-mutation-removed-by-E09-S03-#230 owner=@CandleViewer/security review=2026-12-31  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def mfa_enroll(
        body: MfaEnrollRequest,
        x_user_id: str | None = Header(default=None),
        x_username: str | None = Header(default=None),
    ) -> JSONResponse:
        # PR #1618 review finding 1 (security, blocking): no session/RBAC
        # middleware exists yet to verify `X-User-Id`/`X-Username` actually
        # belong to the caller (E09-S03 scope). Trusting them would let any
        # caller enrol MFA (and read the one-time recovery codes) for any
        # account — an MFA takeover. This route fails closed with `501`
        # (mirroring `api/audit.py`'s `principal_resolver=None` path) until
        # E09-S03 lands a real principal resolver here. See the module
        # docstring's "Deviation 1".
        del x_user_id, x_username
        return _problem(
            501,
            "Not implemented",
            "enrolment requires session authentication (E09-S03); disabled until then",
        )

    @router.post("/auth/mfa/enroll/confirm")  # nosem: audit-write-required reason=fail-closed-501-stub-no-mutation-removed-by-E09-S03-#230 owner=@CandleViewer/security review=2026-12-31  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def mfa_enroll_confirm(
        body: MfaEnrollConfirmRequest,
        x_user_id: str | None = Header(default=None),
    ) -> JSONResponse:
        # Same rationale as `/auth/mfa/enroll` above (Deviation 1): trusting
        # an unauthenticated `X-User-Id` here would let anyone confirm
        # (and thereby activate) a TOTP method — and mint that account's
        # recovery codes — for any user id. Disabled until E09-S03.
        del x_user_id
        return _problem(
            501,
            "Not implemented",
            "enrolment confirmation requires session authentication (E09-S03); disabled until then",
        )

    return router

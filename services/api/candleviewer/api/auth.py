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

Source IP resolution intentionally does not trust `X-Forwarded-For` unless
the deployment topology has a trusted reverse proxy configured elsewhere
(out of this ticket's scope, C-2.11); it reads `request.client.host`, which
is correct for CandleViewer's binding model (`127.0.0.1`/Tailscale — see
`50-security.md`).
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from candleviewer.api.csrf import set_csrf_cookie
from candleviewer.api.sessions import (
    REFRESH_EXPIRES_IN_S,
    IdentityProvider,
    _set_refresh_cookie,
    _tokens,
)
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
    a placeholder string, when unknown (QA #1658: "unknown" broke the real sink)."""
    return request.client.host if request.client is not None else None


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

    @router.post("/auth/login")
    async def login(request: Request, body: LoginRequest) -> JSONResponse:
        if not auth_service.is_active:
            return _problem(503, "Service unavailable", "auth backend is not wired")

        source_ip = request.client.host if request.client is not None else "unknown"
        audit_ip = _client_ip(request)
        try:
            result = await auth_service.login.login(body, source_ip=source_ip)
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
        source_ip = request.client.host if request.client is not None else None
        minted = await auth_service.sessions.mint(
            str(result.user_id), ip=source_ip, user_agent=request.headers.get("user-agent")
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
        if not auth_service.mfa_is_active:
            return _problem(503, "Service unavailable", "mfa backend is not wired")
        try:
            result = await auth_service.mfa.recover(body.mfa_token, body.recovery_code)
        except RecoveryCodesExhausted as exc:
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

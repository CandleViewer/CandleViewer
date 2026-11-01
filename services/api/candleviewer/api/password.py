"""`PUT /auth/password` (#2110, contract #2330: `22` `authChangePassword`; SR-013, SR-028;
`04-security-program.md` Sec.6.3.1).

The caller changes its own user's password (`scope: self`, SR-026: only the bearer names the
user). Not step-up gated (orchestrator ruling on #2330, BQ-220): the re-verified current password is
the proof. The CSRF guard, the enrolment guard, the view-as policy, the read-only guard and the
idle-lock gate refuse before this handler runs (contract steps 2 and 3); this handler decides
the rest, in the contract's order, each step answered before the next runs:

1. The bearer (`401 unauthenticated`, or `session_idle_locked`), then an undeclared query key.
2. The body (`422 validation_failed`, `errors[{field, rule}]`): no password is checked.
3. The audit sink: none active is `503 audit_unavailable`, before any password is checked.
4. `PasswordChangeService.prepare`: the verification bound (`429`), the current password (`403
   current_password_invalid`, held to the minimum failure time once its rows are written), the
   policy (`422 password_breached` / `password_policy`) and the history (`422 password_reused`).
   Each refusal is one `auth.password_change` outcome row (lane first, the writer its fallback);
   a lockout this failure applied adds `auth.account_locked`.
5. Write-ahead (C-2.9, on the writer, never the lane): `auth.password_change` (`stage: intent`),
   one `auth.session_revoked` per live session of the user, the caller's included (reason
   `password_change`), and the replacement's `auth.session_created` (`rotated_from`). A record
   that cannot be written within `AUDIT_TIMEOUT_S` is `503 audit_unavailable`, nothing changed.
6. The compare-and-swap commit; a concurrent change that won first is `409 conflict` (its row
   voids the records written ahead) and nothing changes.
7. Every session of the user is revoked (their sockets close, #2272) and the caller's
   replacement minted with the old absolute expiry and idle timeout and no step-up state
   (BQ-221; a session that never proved a second factor stays unproved). A session minted
   since step 5 is revoked too, with an `unplanned` outcome row. A failure here leaves the new
   password standing: `503`, "sign in again", with a `FAILURE` `unrotated` outcome row.
8. The outcome row (`stage: outcome`), then `200` with the replacement's `TokenBundle` and its
   rotated `cv_refresh` and `__Host-cv_csrf` cookies (SR-041).

No row, log line or answer carries a password, a hash or a length (C-12.6).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable
from typing import Any, Protocol

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from candleviewer.api.auth import AuditServiceLike
from candleviewer.api.csrf import AUDIT_TIMEOUT_S, set_csrf_cookie, source_ip
from candleviewer.api.idle_lock import idle_locked_problem
from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.api.sessions import (
    _bearer,
    _set_refresh_cookie,
    _tokens,
    remaining_lifetime_s,
)
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.service import LaneNotWired
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.errors import (
    AuthError,
    CurrentPasswordInvalid,
    PasswordRefused,
    SessionIdleLocked,
    SignInBusy,
)
from candleviewer.auth.metrics import auth_audit_outcome_lost_total, normalise_outcome_action
from candleviewer.auth.models import MintedSession, SessionRecord
from candleviewer.auth.password_service import PasswordChangeService
from candleviewer.observability.context import current_request_uuid

#: `sessions.revoked_reason` and the audit `reason` of every session a change ends (21 Sec.3.1.4).
REVOKE_REASON = "password_change"
ACTION = "auth.password_change"
#: SR-026: `authChangePassword` declares no query parameter.
CHANGE_PASSWORD_QUERY: frozenset[str] = frozenset()
_PROBLEM = "application/problem+json"
_INVALID_TITLE = "Request body or parameters failed schema validation"
_CURRENT_INVALID_TITLE = (
    "The current password given to change the password is wrong (counts toward the account lockout)"
)
_CURRENT_INVALID_DETAIL = "Your current password is incorrect."
_TITLES = {
    "password_breached": (
        "The new password is on the local breached-password list or follows a simple pattern"
    ),
    "password_reused": (
        "The new password equals the current one or one of the user's last 4 retired passwords"
    ),
    "password_policy": (
        "The new password breaks a password-policy rule other than the breached list "
        "(errors name the rule)"
    ),
}
_AUDIT_DOWN = (
    "Write-ahead audit record could not be written (or no audit backend is wired); refused, "
    "fail closed (C-2.9)"
)
#: The `detail` of a change whose commit stood but whose rotation failed (BQ-232).
UNROTATED = "password changed; sign in again"
#: pydantic's error types, as the contract's `errors[].rule` names them.
_RULES = {
    "missing": "required",
    "string_too_short": "min_length",
    "string_too_long": "max_length",
    "too_short": "min_length",  # `SecretStr`'s length errors
    "too_long": "max_length",
    "extra_forbidden": "additional_properties",
}


class ChangePasswordBody(BaseModel):
    """`ChangePasswordRequest`: no member names a user (SR-026). `SecretStr` keeps both out of
    reprs; a `ValidationError` is never logged or returned as is (it echoes its input)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_password: SecretStr = Field(min_length=1, max_length=512)
    new_password: SecretStr = Field(min_length=1, max_length=512)


class AuthLike(Protocol):
    @property
    def sessions_is_active(self) -> bool: ...

    @property
    def sessions(self) -> Any: ...

    @property
    def passwords_is_active(self) -> bool: ...

    @property
    def passwords(self) -> PasswordChangeService: ...


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _problem(status: int, code: str, title: str, detail: str, **extra: Any) -> JSONResponse:
    content = {
        "type": f"https://candleviewer.local/errors/{code}",
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        **extra,
    }
    headers = {}
    if "retry_after_seconds" in extra:
        headers["Retry-After"] = str(extra["retry_after_seconds"])
    return JSONResponse(status_code=status, content=content, media_type=_PROBLEM, headers=headers)


def _unauthenticated() -> JSONResponse:
    title = "Missing, malformed or expired access token"
    return _problem(401, "unauthenticated", title, "authentication required")


def _audit_unavailable() -> JSONResponse:
    return _problem(503, "audit_unavailable", _AUDIT_DOWN, "audit unavailable")


def _store_unavailable(detail: str) -> JSONResponse:
    return _problem(
        503, "store_unavailable", "QuestDB / Postgres / Parquet tier unavailable", detail
    )


def _invalid(exc: ValidationError) -> JSONResponse:
    """`422 validation_failed` naming each field and rule, never a value: a member the schema
    does not declare is reported as `body`, never by name."""
    errors = []
    for err in exc.errors(include_url=False, include_context=False, include_input=False):
        loc = err["loc"][0] if err["loc"] else "body"
        field = str(loc) if loc in ChangePasswordBody.model_fields else "body"
        rule = _RULES.get(err["type"], "type")
        errors.append({"field": field, "rule": rule, "message": f"{field}: {rule}"})
    detail = "The request body does not match its schema."
    return _problem(422, "validation_failed", _INVALID_TITLE, detail, errors=errors)


def make_password_router(
    auth: AuthLike, audit: AuditServiceLike | None, *, csrf: CsrfCodec
) -> APIRouter:
    router = APIRouter(tags=["auth"])

    async def _ahead(record: Awaitable[None]) -> None:
        """A record written ahead (C-2.9): on the writer, bounded by `AUDIT_TIMEOUT_S`."""
        async with asyncio.timeout(AUDIT_TIMEOUT_S):
            await record

    async def _outcome(action: str = ACTION, /, **row: Any) -> None:
        """An outcome or refusal row (`04` Sec.8.3 rule 1): the lane first, the writer its
        fallback, bounded; the answer is decided already, so a row both refuse, or whose write
        times out, is counted lost and logged (action and error class only) and the answer
        stands."""
        if audit is None or not audit.is_active:
            _lost(action, "inactive")
            return
        try:
            async with asyncio.timeout(AUDIT_TIMEOUT_S):
                try:
                    sink = audit.lane
                except LaneNotWired:
                    sink = audit.writer
                await sink.emit(action, request_id=current_request_uuid(), **row)
        except AuditError as exc:
            _lost(action, type(exc).__name__)
        except TimeoutError:
            _lost(action, "timeout")

    def _lost(action: str, error: str) -> None:
        auth_audit_outcome_lost_total.labels(action=normalise_outcome_action(action)).inc()
        _log().error("auth.password_change.outcome_lost", action=action, error=error)

    @router.put("/auth/password")
    async def change_password(request: Request) -> JSONResponse:
        if not auth.sessions_is_active:
            return _store_unavailable("session backend is not wired")
        bearer = _bearer(request)
        if bearer is None:
            return _unauthenticated()
        sessions = auth.sessions
        try:
            record: SessionRecord = await sessions.authenticate_access_token(bearer)
        except SessionIdleLocked as exc:
            return idle_locked_problem(exc.idle_locked_at)
        except AuthError:
            return _unauthenticated()
        if (refusal := undeclared_query_refusal(request, CHANGE_PASSWORD_QUERY)) is not None:
            return refusal
        try:
            raw = await request.json()
        except ValueError:
            raw = None
        try:  # a body that is not an object has none of the members
            body = ChangePasswordBody.model_validate(raw if isinstance(raw, dict) else {})
        except ValidationError as exc:
            return _invalid(exc)  # step 2: a user-naming or admin member never gets further
        if not auth.passwords_is_active:  # after the bearer and the body (steps 1-2)
            return _store_unavailable("password backend is not wired")
        if audit is None or not audit.is_active:
            return _audit_unavailable()  # no password is checked that could not be audited
        uid, ip = str(record.user_id), source_ip(request.scope)
        mine: dict[str, Any] = {
            "actor_label": uid,
            "actor_user_id": record.user_id,
            "actor_ip": ip,
            "session_id": record.id,
        }
        service = auth.passwords
        hold = service.failure_hold
        started = hold.start()
        try:
            change = await service.prepare(
                uid,
                current=body.current_password.get_secret_value(),
                new=body.new_password.get_secret_value(),
            )
        except SignInBusy as exc:
            await _outcome(outcome=AuditOutcome.DENIED, reason="verify_busy", **mine)
            detail = "Too many sign-in attempts are being checked; retry shortly."
            return _problem(
                429,
                "rate_limited",
                "Per-user API rate limit exceeded",
                detail,
                retry_after_seconds=exc.retry_after_s,
            )
        except CurrentPasswordInvalid as exc:
            await _outcome(
                outcome=AuditOutcome.FAILURE,
                severity=Severity.WARNING,
                reason="current_password_invalid",
                **mine,
            )
            if exc.locked_until is not None:  # SR-016: this failure locked the account
                await _outcome_locked(mine)
            await hold.hold(started)  # #4664: after its rows, as `POST /auth/unlock` does
            return _problem(
                403, "current_password_invalid", _CURRENT_INVALID_TITLE, _CURRENT_INVALID_DETAIL
            )
        except PasswordRefused as exc:
            await _outcome(outcome=AuditOutcome.DENIED, reason=exc.code, **mine)
            extra: dict[str, Any] = {}
            if exc.rule is not None:
                rule = {"field": "new_password", "rule": exc.rule, "message": exc.detail}
                extra["errors"] = [rule]
            return _problem(422, exc.code, _TITLES[exc.code], exc.detail, **extra)

        new_id = uuid.uuid4()  # named by the records written ahead
        ending = [view.id for view in await sessions.list_sessions(uid)]
        writer = audit.writer
        try:
            await _ahead(
                writer.emit(
                    ACTION,
                    after_state={"stage": "intent", "rotated_to": str(new_id)},
                    request_id=current_request_uuid(),
                    **mine,
                )
            )
            for sid in ending:
                await _ahead(
                    writer.emit(
                        "auth.session_revoked",
                        reason=REVOKE_REASON,
                        request_id=current_request_uuid(),
                        **{**mine, "session_id": sid},
                    )
                )
            await _ahead(
                writer.emit(
                    "auth.session_created",
                    after_state={"rotated_from": str(record.id)},
                    request_id=current_request_uuid(),
                    **{**mine, "session_id": new_id},
                )
            )
        except (AuditError, TimeoutError) as exc:
            _log().error("auth.password_change.audit_unavailable", error=type(exc).__name__)
            return _audit_unavailable()
        voided = {
            "voids_session_created": str(new_id),
            "voids_session_revoked": [str(sid) for sid in ending],
        }
        try:
            committed = await service.commit(change)
        except Exception as exc:  # a store failure rolls it back: nothing changed, the 500 stands
            _log().error("auth.password_change.commit_failed", error=type(exc).__name__)
            await _outcome(
                outcome=AuditOutcome.FAILURE, reason="store_error", after_state=voided, **mine
            )
            raise
        if not committed:
            await _outcome(
                outcome=AuditOutcome.FAILURE, reason="conflict", after_state=voided, **mine
            )
            detail = "the password was changed by another request; re-read and retry"
            return _problem(409, "conflict", "Concurrent modification or state conflict", detail)
        unrotated = {"committed": True, "voids_session_created": str(new_id)}
        try:
            revoked = await sessions.revoke_all(uid, reason=REVOKE_REASON)
        except Exception as exc:  # the committed change stands; the sessions were not revoked
            _log().error(
                "auth.password_change.sessions_not_revoked",
                user_id=uid,
                session_id=str(record.id),
                new_session_id=str(new_id),
                error=type(exc).__name__,
            )
            voids = {**unrotated, "voids_session_revoked": [str(sid) for sid in ending]}
            await _outcome(
                outcome=AuditOutcome.FAILURE, reason="unrotated", after_state=voids, **mine
            )
            return _store_unavailable(UNROTATED)
        unplanned = [row.id for row in revoked if row.id not in ending]
        for sid in unplanned:  # minted since the plan: outcome rows, each revocation happened
            await _outcome(
                "auth.session_revoked",
                reason=REVOKE_REASON,
                after_state={"unplanned": True},
                **{**mine, "session_id": sid},
            )
        try:
            minted: MintedSession = await sessions.mint(
                uid,
                ip=ip,
                user_agent=request.headers.get("user-agent"),
                device_label=record.device_label,
                is_electron=record.is_electron,
                idle_timeout_s=record.idle_timeout_s,
                # BQ-221: a rotation never upgrades a session that never proved a second factor
                mfa_satisfied=record.mfa_satisfied_at is not None,
                expires_at=record.expires_at,  # the change never extends the session (SR-024)
                session_id=new_id,
            )
        except Exception as exc:  # the committed change stands: the user signs in with it
            _log().error(
                "auth.password_change.completed_unrotated",
                user_id=uid,
                session_id=str(record.id),
                new_session_id=str(new_id),
                error=type(exc).__name__,
            )
            await _outcome(
                outcome=AuditOutcome.FAILURE, reason="unrotated", after_state=unrotated, **mine
            )
            return _store_unavailable(UNROTATED)
        await _outcome(after_state={"stage": "outcome"}, **{**mine, "session_id": new_id})
        lifetime = remaining_lifetime_s(record, now=sessions.now())
        tokens = _tokens(minted, include_refresh=False, refresh_expires_in=lifetime)
        response = JSONResponse({"status": "password_changed", "tokens": tokens})
        _set_refresh_cookie(response, minted.refresh_token, max_age=lifetime)
        set_csrf_cookie(request, response, csrf.issue(str(minted.session_id)), max_age=lifetime)
        return response

    async def _outcome_locked(mine: dict[str, Any]) -> None:
        if audit is None or not audit.is_active:
            return
        try:
            async with asyncio.timeout(AUDIT_TIMEOUT_S):
                await audit.writer.emit(
                    "auth.account_locked",
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason="password_change_failed",
                    request_id=current_request_uuid(),
                    **mine,
                )
        except (AuditError, TimeoutError) as exc:
            _log().error("auth.password_change.lockout_audit_lost", error=type(exc).__name__)

    return router

"""Invite-based user creation and redemption (E09-S05, US-ONB-006).

Owner side (`users:write`, step-up `users` enforced by the dangerous-route
middleware in `api/step_up.py`): `POST /users`, `GET /users/invites`,
`POST|DELETE /users/{userId}/invite` (re-issue / revoke).

Invitee side (unauthenticated, per-IP throttled): `GET /invites/{token}`
validates without consuming; `POST /invites/{token}` sets the password, consumes
the token and starts TOTP enrolment; `POST /invites/{token}/confirm` verifies
the first TOTP code, activates the account and returns the one-time recovery
codes. No session is minted - the invitee signs in normally afterwards.

Every unknown / expired / redeemed / revoked token yields the same 404 body so
links cannot be probed. A request that tries to carry a `role`/`roles` field on
the invitee side is refused with 403 and audited (role immutability). The raw
token is never logged, audited or echoed after creation.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import (
    InviteConflict,
    InviteNotFound,
    InviteRejected,
    PasswordPolicyViolation,
)
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.invite_service import InviteService
from candleviewer.auth.models import CreatedInvite, InviteCreateRequest, InviteRecord
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce

_TOKEN = Path(alias="inviteToken", min_length=16, max_length=128)
_UNIFORM_DETAIL = "This invitation link is not valid."


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class InviteAuthLike(Protocol):
    @property
    def invites_is_active(self) -> bool: ...

    @property
    def invites(self) -> InviteService: ...


def _problem(status: int, title: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            **extra,
        },
        media_type="application/problem+json",
    )


def _uniform_not_found() -> JSONResponse:
    return _problem(404, "Not found", _UNIFORM_DETAIL)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _invite_json(invite: CreatedInvite) -> dict[str, Any]:
    return {
        "id": str(invite.user_id),
        "username": invite.username,
        "email": invite.email,
        "display_name": invite.display_name,
        "roles": [invite.role],
        "status": "invited",
        "invite_url": f"/invite/{invite.token}",
        "invite_expires_at": invite.expires_at.isoformat(),
        "created_at": invite.created_at.isoformat(),
    }


def _pending_json(record: InviteRecord) -> dict[str, Any]:
    return {
        "user_id": str(record.user_id),
        "username": record.username,
        "email": record.email,
        "display_name": record.display_name,
        "role": record.role,
        "expires_at": record.expires_at.isoformat(),
        "expired": False,
    }


def make_invites_router(
    auth: InviteAuthLike,
    emitter: _Emitter,
    principal_resolver: SnapshotResolver | None,
    *,
    audit_ready: Callable[[], bool],
    now: Any = None,
) -> APIRouter:
    """`emitter` is mandatory: an invite action without an audit record
    (C-2.9) is refused at wiring time, and while `audit_ready()` is false
    every invite action answers 503 before changing anything (#2492).
    `principal_resolver=None` fails the owner routes closed with 501 (as
    `/users/{id}/roles`)."""
    if emitter is None:
        raise TypeError("make_invites_router: audit emitter is required")
    router = APIRouter(tags=["users"])

    def _audit_down() -> JSONResponse | None:
        if audit_ready():
            return None
        return _problem(503, "Service unavailable", "audit unavailable; nothing was changed")

    async def _owner(request: Request) -> PrincipalSnapshot | JSONResponse:
        if principal_resolver is None:
            return _problem(501, "Not implemented", "no principal resolver wired")
        if not auth.invites_is_active:
            return _problem(503, "Service unavailable", "invites not wired")
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _problem(401, "Unauthorized", "no verified session for this request")
        try:
            await enforce(principal, Permission.USERS_WRITE, scope=Scope.NONE, emitter=emitter)
        except ForbiddenError as exc:
            return _problem(
                403, "Forbidden", "forbidden", code="forbidden", reason=exc.deny.reason.value
            )
        return principal

    async def _audit_owner(
        action: str, principal: PrincipalSnapshot, target: uuid.UUID, role: str, request: Request
    ) -> None:
        await emitter.emit(
            action,
            actor_label=str(principal.user_id),
            actor_user_id=principal.user_id,
            actor_ip=request.client.host if request.client else None,
            object_kind="user",
            object_id=str(target),
            after_state={"role": role},
        )

    async def _reject_audit(reason: str, request: Request) -> None:
        await emitter.emit(
            "users.invite_rejected",
            actor_label="anonymous",
            actor_ip=request.client.host if request.client else None,
            outcome=AuditOutcome.DENIED,
            severity=Severity.WARNING if reason in {"redeemed", "role_tamper"} else Severity.INFO,
            reason=reason,
        )

    async def _json_body(request: Request) -> dict[str, Any] | None:
        try:
            body = await request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    # -- owner side --------------------------------------------------------

    @router.post("/users")
    async def create_user(request: Request) -> JSONResponse:
        got = await _owner(request)
        if isinstance(got, JSONResponse):
            return got
        if (down := _audit_down()) is not None:
            return down
        body = await _json_body(request)
        if body is None:
            return _problem(400, "Bad request", "body must be a JSON object")
        try:
            parsed = InviteCreateRequest.model_validate(body)
        except ValidationError:
            # Covers non-viewer roles, account_access grants and malformed fields.
            await emitter.emit(
                "users.invite_refused",
                actor_label=str(got.user_id),
                actor_user_id=got.user_id,
                actor_ip=request.client.host if request.client else None,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="invalid_invite_request",
            )
            return _problem(422, "Unprocessable entity", "invalid invite request")
        try:
            invite = await auth.invites.create(parsed, invited_by=got.user_id)
        except InviteConflict:
            return _problem(409, "Conflict", "email or username already in use")
        await _audit_owner("users.invited", got, invite.user_id, invite.role, request)
        return JSONResponse(status_code=201, content=_invite_json(invite))

    @router.get("/users/invites")
    async def list_invites(request: Request) -> JSONResponse:
        got = await _owner(request)
        if isinstance(got, JSONResponse):
            return got
        pending = await auth.invites.list_pending()
        items = []
        for rec in pending:
            item = _pending_json(rec)
            item["expired"] = rec.expires_at <= auth.invites.now()
            items.append(item)
        return JSONResponse(status_code=200, content={"items": items})

    @router.post("/users/{userId}/invite")
    async def reissue_invite(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        got = await _owner(request)
        if isinstance(got, JSONResponse):
            return got
        if (down := _audit_down()) is not None:
            return down
        try:
            invite = await auth.invites.reissue(user_id, invited_by=got.user_id)
        except InviteNotFound:
            return _problem(404, "Not found", "no invited user with this id")
        await _audit_owner("users.invite_reissued", got, invite.user_id, invite.role, request)
        return JSONResponse(status_code=201, content=_invite_json(invite))

    @router.delete("/users/{userId}/invite")
    async def revoke_invite(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        got = await _owner(request)
        if isinstance(got, JSONResponse):
            return got
        if (down := _audit_down()) is not None:
            return down
        try:
            await auth.invites.revoke(user_id)
        except InviteNotFound:
            return _problem(404, "Not found", "no pending invite for this user")
        await _audit_owner("users.invite_revoked", got, user_id, "", request)
        return JSONResponse(status_code=200, content={"user_id": str(user_id), "revoked": True})

    # -- invitee side ------------------------------------------------------

    async def _gate(request: Request) -> JSONResponse | None:
        if not auth.invites_is_active:
            return _problem(503, "Service unavailable", "invites not wired")
        if (down := _audit_down()) is not None:
            return down
        if auth.invites.is_blocked(_client_ip(request)):
            return _problem(429, "Too many requests", "too many invalid attempts; try later")
        return None

    @router.get("/invites/{inviteToken}")
    async def inspect_invite(
        request: Request, invite_token: Annotated[str, _TOKEN]
    ) -> JSONResponse:
        if (denied := await _gate(request)) is not None:
            return denied
        try:
            view = await auth.invites.inspect(invite_token, source_ip=_client_ip(request))
        except InviteRejected as exc:
            await _reject_audit(exc.reason, request)
            return _uniform_not_found()
        return JSONResponse(
            status_code=200,
            content={
                "display_name": view.display_name,
                "role": "viewer",
                "expires_at": view.expires_at.isoformat(),
            },
        )

    async def _tamper_check(body: dict[str, Any] | None, request: Request) -> JSONResponse | None:
        if body is None:
            return _problem(400, "Bad request", "body must be a JSON object")
        if "role" in body or "roles" in body:
            await _reject_audit("role_tamper", request)
            return _problem(
                403, "Forbidden", "the invited role cannot be changed", code="forbidden"
            )
        return None

    @router.post("/invites/{inviteToken}")
    async def redeem_invite(request: Request, invite_token: Annotated[str, _TOKEN]) -> JSONResponse:
        if (denied := await _gate(request)) is not None:
            return denied
        body = await _json_body(request)
        if (bad := await _tamper_check(body, request)) is not None:
            return bad
        body = body or {}
        password = body.get("password")
        if not isinstance(password, str) or set(body) - {"password"}:
            return _problem(400, "Bad request", "password is required")
        try:
            start = await auth.invites.begin_redemption(
                invite_token, password=password, source_ip=_client_ip(request)
            )
        except InviteRejected as exc:
            await _reject_audit(exc.reason, request)
            return _uniform_not_found()
        except PasswordPolicyViolation as exc:
            return _problem(422, "Unprocessable entity", exc.reason, code="password_policy")
        return JSONResponse(
            status_code=200,
            content={
                "method_id": str(start.method_id),
                "otpauth_uri": start.otpauth_uri,
                "secret_base32": start.secret_base32,
            },
        )

    @router.post("/invites/{inviteToken}/confirm")
    async def confirm_invite(
        request: Request, invite_token: Annotated[str, _TOKEN]
    ) -> JSONResponse:
        if (denied := await _gate(request)) is not None:
            return denied
        body = await _json_body(request)
        if (bad := await _tamper_check(body, request)) is not None:
            return bad
        body = body or {}
        method_id, code = body.get("method_id"), body.get("code")
        if (
            not isinstance(method_id, str)
            or not isinstance(code, str)
            or set(body)
            - {
                "method_id",
                "code",
            }
        ):
            return _problem(400, "Bad request", "method_id and code are required")

        async def _audit_downgrade(rec: InviteRecord, stored_role: str) -> None:
            await emitter.emit(
                "users.invite_role_downgraded",
                actor_label=rec.username,
                actor_user_id=rec.user_id,
                actor_ip=request.client.host if request.client else None,
                object_kind="user",
                object_id=str(rec.user_id),
                severity=Severity.WARNING,
                before_state={"role": stored_role},
                after_state={"role": "viewer"},
            )

        try:
            record, recovery = await auth.invites.complete_redemption(
                invite_token,
                method_id=method_id,
                code=code,
                source_ip=_client_ip(request),
                audit_downgrade=_audit_downgrade,
            )
        except InviteRejected as exc:
            await _reject_audit(exc.reason, request)
            if exc.reason == "enrollment_invalid":
                return _problem(422, "Unprocessable entity", "invalid code", code="invalid_code")
            return _uniform_not_found()
        await emitter.emit(
            "users.invite_redeemed",
            actor_label=record.username,
            actor_user_id=record.user_id,
            actor_ip=request.client.host if request.client else None,
            object_kind="user",
            object_id=str(record.user_id),
            after_state={"role": record.role},
        )
        return JSONResponse(
            status_code=200,
            content={"status": "active", "role": record.role, "recovery_codes": list(recovery)},
        )

    return router

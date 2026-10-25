"""Session-backed `PrincipalResolver` for `/admin/audit*` (QA #1596).

Bearer token -> `SessionService.authenticate_access_token` -> the SQL identity
read path for username + permission codes. Every failure (no/unknown/expired/
revoked/idle-locked token, unknown or non-active user) resolves to `None`,
which the router maps to 401. Permissions are read server-side per request
(C-12.4); nothing is trusted from the client. The principal's `ip` (the audit
`actor_ip` of every route that resolves one) is the address MeshOnly admitted,
as the auth audit records it: behind the configured trusted proxy, the client's
hop, never the proxy (#2275). `last_step_up_at` is read from the same session row, so the
resolver makes no query of its own for it (#2754). Its `request_id` is the id
`CorrelationMiddleware` bound for the request, the one the response echoes as `X-Correlation-Id`
(#3990): never a request header read here, so no record written with it carries NULL.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from fastapi import Request

from candleviewer.api.csrf import source_ip
from candleviewer.api.view_as_subject import view_as_stamp, view_as_subject
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.errors import SessionIdleLocked, SessionNotFound, SessionRevoked
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.step_up import last_step_up_at
from candleviewer.observability.context import current_request_uuid


def _is_owner(user_id: uuid.UUID, roles: Any) -> bool:
    """Owner-ness via the sanctioned `PrincipalSnapshot.is_owner` (SR-017).
    Unknown role names fail closed (not owner) instead of raising."""
    try:
        snapshot = PrincipalSnapshot(
            user_id=user_id, roles=frozenset(str(r) for r in roles), permissions=frozenset()
        )
    except ValueError:
        return False
    return snapshot.is_owner


def _last_step_up_at(record: Any) -> datetime | None:
    """The latest step-up instant the loaded session row records. A record that carries no
    step-up state has none."""
    elevations = getattr(record, "step_up_elevations", None)
    return last_step_up_at(elevations) if elevations else None


class _Sessions(Protocol):
    async def authenticate_access_token(
        self, raw_access_token: str, *, touch: bool = ...
    ) -> Any: ...


class _Identity(Protocol):
    async def user(self, user_id: str) -> dict[str, Any]: ...

    async def session_info(self, user_id: str) -> dict[str, Any]: ...


async def identity_snapshot(identity: _Identity, user_id: uuid.UUID) -> PrincipalSnapshot | None:
    """`user_id`'s roles and permissions as the identity store holds them, with no grants, or
    `None` for a user who cannot act: not `active`, or holding a role outside the system set (fail
    closed). A user the store does not hold raises `LookupError`; any other failure propagates."""
    user = await identity.user(str(user_id))
    info = await identity.session_info(str(user_id))
    if user.get("status") != "active":
        return None
    codes = {str(code) for code in info.get("permissions", ())}
    try:
        return PrincipalSnapshot(
            user_id=user_id,
            roles=frozenset(str(role) for role in user.get("roles") or ()),
            permissions=frozenset(p for p in Permission if p.value in codes),
        )
    except ValueError:
        return None


class SessionAuditPrincipalResolver:
    def __init__(self, sessions: Callable[[], _Sessions], identity: _Identity) -> None:
        # Lazy: `AuthService.sessions` only exists after `start()` (lifespan).
        self._sessions = sessions
        self._identity = identity

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            record = await self._sessions().authenticate_access_token(token, touch=True)
            subject = view_as_subject(request, record)  # the target on a live view (#3085)
            user = await self._identity.user(str(subject))
            info = await self._identity.session_info(str(subject))
        except (RuntimeError, SessionNotFound, SessionRevoked, SessionIdleLocked, LookupError):
            return None
        if user.get("status") != "active":  # a locked target's view has no scope (Q11)
            return None
        stamp = view_as_stamp(request) if subject != record.user_id else None
        return AuditPrincipal(
            user_id=subject,
            username=str(user["username"]),
            permissions=frozenset(str(p) for p in info.get("permissions", ())),
            is_owner=_is_owner(subject, user.get("roles") or ()),
            last_step_up_at=_last_step_up_at(record),
            session_id=record.id,
            ip=source_ip(request.scope),
            request_id=current_request_uuid(),
            actor_user_id=None if stamp is None else stamp.viewer_user_id,
            actor_username=None if stamp is None else stamp.viewer_label,
        )

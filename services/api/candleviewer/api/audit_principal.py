"""Session-backed `PrincipalResolver` for `/admin/audit*` (QA #1596).

Bearer token -> `SessionService.authenticate_access_token` -> the SQL identity
read path for username + permission codes. Every failure (no/unknown/expired/
revoked/idle-locked token, unknown or non-active user) resolves to `None`,
which the router maps to 401. Permissions are read server-side per request
(C-12.4); nothing is trusted from the client. The principal's `ip` (the audit
`actor_ip` of every route that resolves one) is the address MeshOnly admitted,
as the auth audit records it: behind the configured trusted proxy, the client's
hop, never the proxy (#2275). `last_step_up_at` is read from the same session row, so the
resolver makes no query of its own for it (#2754).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from fastapi import Request

from candleviewer.api.csrf import source_ip
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.errors import SessionIdleLocked, SessionNotFound, SessionRevoked
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.step_up import last_step_up_at


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
    async def authenticate_access_token(self, raw_access_token: str) -> Any: ...


class _Identity(Protocol):
    async def user(self, user_id: str) -> dict[str, Any]: ...

    async def session_info(self, user_id: str) -> dict[str, Any]: ...


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
            record = await self._sessions().authenticate_access_token(token)  # never activity
            user = await self._identity.user(str(record.user_id))
            info = await self._identity.session_info(str(record.user_id))
        except (RuntimeError, SessionNotFound, SessionRevoked, SessionIdleLocked, LookupError):
            return None
        if user.get("status") != "active":
            return None
        rid = request.headers.get("x-request-id")
        try:
            request_id = uuid.UUID(rid) if rid else None
        except ValueError:
            request_id = None
        return AuditPrincipal(
            user_id=record.user_id,
            username=str(user["username"]),
            permissions=frozenset(str(p) for p in info.get("permissions", ())),
            is_owner=_is_owner(record.user_id, user.get("roles") or ()),
            last_step_up_at=_last_step_up_at(record),
            session_id=record.id,
            ip=source_ip(request.scope),
            request_id=request_id,
        )

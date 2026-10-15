"""Session-backed `SnapshotResolver` for the owner user-management routes (#2492).

Bearer token -> `SessionService.authenticate_access_token` -> the SQL identity read
path -> `PrincipalSnapshot` (roles, permission codes), re-read server-side on every
request (C-12.4). As `SessionAuditPrincipalResolver`: an unknown/expired/revoked/
idle-locked token, an unknown or non-active user or an unknown role name resolve to
`None` (401); unknown permission codes are dropped. Account grants are not loaded
(these routes decide on `Scope.NONE`), so a `GRANTED_ACCOUNTS` check denies non-owners.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Request

from candleviewer.auth.errors import AuthError
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot


class SessionSnapshotResolver:
    def __init__(self, sessions: Callable[[], Any], identity: Any) -> None:
        # Lazy: `AuthService.sessions` only exists after `start()` (lifespan).
        self._sessions = sessions
        self._identity = identity

    async def resolve(self, request: Request) -> PrincipalSnapshot | None:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            record = await self._sessions().authenticate_access_token(token, touch=True)
            user = await self._identity.user(str(record.user_id))
            info = await self._identity.session_info(str(record.user_id))
        except (AuthError, RuntimeError, LookupError):
            return None
        if user.get("status") != "active":
            return None
        codes = {str(code) for code in info.get("permissions", ())}
        try:
            return PrincipalSnapshot(
                user_id=uuid.UUID(str(record.user_id)),
                roles=frozenset(str(r) for r in (user.get("roles") or ())),
                permissions=frozenset(p for p in Permission if p.value in codes),
            )
        except ValueError:  # a role outside the system set: no principal (fail closed)
            return None

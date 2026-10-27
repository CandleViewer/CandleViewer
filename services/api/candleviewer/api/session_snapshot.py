"""Session-backed `SnapshotResolver` for the owner user-management routes (#2492).

Bearer token -> `SessionService.authenticate_access_token` -> the SQL identity read
path -> `PrincipalSnapshot` (roles, permission codes), re-read server-side on every
request (C-12.4). As `SessionAuditPrincipalResolver`: an unknown/expired/revoked/
idle-locked token, an unknown or non-active user or an unknown role name resolve to
`None` (401); unknown permission codes are dropped. Account grants are loaded only when asked
(`grants=True`, the profile reads of #906); without them a `GRANTED_ACCOUNTS` check denies
non-owners.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Request

from candleviewer.api.audit_principal import _Identity, _Sessions
from candleviewer.api.view_as_subject import view_as_subject
from candleviewer.auth.errors import AuthError
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot


class SessionSnapshotResolver:
    """`SnapshotResolver` that re-reads the caller's roles and permissions per request."""

    def __init__(
        self, sessions: Callable[[], _Sessions], identity: _Identity, *, grants: bool = False
    ) -> None:
        """`sessions` is a thunk: `AuthService.sessions` only exists after `start()`
        (lifespan); `identity` is the SQL identity read path. With `grants`, the principal holds
        the caller's view grants that are not frozen, as `session_info` lists them (`can_trade` is
        not loaded)."""
        self._sessions = sessions
        self._identity = identity
        self._grants = grants

    async def resolve(self, request: Request) -> PrincipalSnapshot | None:
        """The bearer token's principal, or `None` (401) on any failure (module docstring)."""
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            record = await self._sessions().authenticate_access_token(token)
            subject = view_as_subject(request, record)  # the target on a live view (#3085)
            user = await self._identity.user(str(subject))
            info = await self._identity.session_info(str(subject))
        except (AuthError, RuntimeError, LookupError):
            return None
        if user.get("status") != "active":
            return None
        codes = {str(code) for code in info.get("permissions", ())}
        try:
            grants = tuple(
                AccountGrant(uuid.UUID(str(a)), True, False, False)
                for a in (info.get("account_scope", ()) if self._grants else ())
            )
            return PrincipalSnapshot(
                user_id=uuid.UUID(str(subject)),
                roles=frozenset(str(r) for r in (user.get("roles") or ())),
                permissions=frozenset(p for p in Permission if p.value in codes),
                account_grants=grants,
            )
        except ValueError:  # an unknown role or a malformed grant id: no principal (fail closed)
            return None

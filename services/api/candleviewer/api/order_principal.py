"""The session-backed trading principal of `POST /orders` (E29-T04 #913 slice 3; 24 Sec.8.4 step 1).

Bearer token -> session -> the SQL identity read -> the user's grants with `can_trade`
(`SqlAlchemyScopeSource.load_trade_grants`), re-read per request (C-12.4), so the route's
`enforce(orders:write, GRANTED_ACCOUNTS, account, requires_trade=True)` admits a Manager with a
trade grant and refuses a view-only or frozen one (04 Sec.7.2.2 row 10); an Owner's grants are not
read, as they are every account. The principal is the user `view_as_subject` names (#3085): the
session's own with no live context, and the viewer for a write the view-as guard passed. The guard
refuses `placeOrder` from a session viewing as another user (#4177), and this does not rely on it:
a context its request carries no stamp for is `StoreUnavailable`, never the session's own scope.

It fails closed: no session (no bearer, a refused token, a user unknown or not `active`, a role
outside the system set) is `None`, the route's 401; a store that does not answer within
`PRINCIPAL_READ_TIMEOUT_S`, the auth service not started included, or a view-as context with no
stamp, raises `StoreUnavailable`, its 503, never a 401 that would end the client's session. Only
the session and identity reads can say "no such session or user": a `LookupError` from the grants
read is the store's. Unknown permission codes are dropped.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Final, Protocol

import structlog
from fastapi import Request

from candleviewer.api.audit_principal import _Identity, _Sessions
from candleviewer.api.view_as_subject import view_as_subject
from candleviewer.auth.errors import AuthError, AuthServiceUnavailable
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.oms.errors import StoreUnavailable

#: Bounds the session, identity and grant reads together, so a stalled store holds no request.
PRINCIPAL_READ_TIMEOUT_S: Final = 2.0


class _TradeGrants(Protocol):
    async def load_trade_grants(
        self, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, bool, bool, bool]]: ...


@dataclass(frozen=True, slots=True)
class TradingPrincipal:
    """The order route's caller: its session, and its roles, permissions and trade grants."""

    session_id: uuid.UUID
    snapshot: PrincipalSnapshot


class SessionTradingPrincipalResolver:
    def __init__(
        self,
        sessions: Callable[[], _Sessions],
        identity: _Identity,
        grants: _TradeGrants,
        *,
        timeout_s: float = PRINCIPAL_READ_TIMEOUT_S,
    ) -> None:
        """`sessions` is a thunk: `AuthService.sessions` only exists after `start()`."""
        self._sessions, self._identity, self._grants = sessions, identity, grants
        self._timeout_s = timeout_s

    async def resolve(self, request: Request) -> TradingPrincipal | None:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            async with asyncio.timeout(self._timeout_s):
                return await self._read(request, token)
        except Exception as exc:  # TimeoutError, ViewAsUnstamped, a store failure: no principal
            failure = type(exc).__name__
        structlog.get_logger(__name__).warning("order_principal_unread", error=failure)
        raise StoreUnavailable

    async def _read(self, request: Request, token: str) -> TradingPrincipal | None:
        try:
            record = await self._sessions().authenticate_access_token(token, touch=True)
            # A context with no stamp raises `ViewAsUnstamped`: neither an `AuthError` nor a
            # `LookupError`, so it reaches `resolve`'s catch and is `StoreUnavailable` (#3085).
            user_id = view_as_subject(request, record)
            user = await self._identity.user(str(user_id))
            info = await self._identity.session_info(str(user_id))
        except AuthServiceUnavailable:
            raise  # auth not started: an `AuthError` that is the store's, not a session's
        except (AuthError, LookupError):  # no such session, or no such user
            return None
        if user.get("status") != "active":
            return None
        codes = {str(code) for code in info.get("permissions", ())}
        try:
            snapshot = PrincipalSnapshot(
                user_id=user_id,
                roles=frozenset(str(role) for role in user.get("roles") or ()),
                permissions=frozenset(p for p in Permission if p.value in codes),
            )
        except ValueError:  # a role outside the system set: no principal (fail closed)
            return None
        if not snapshot.is_owner:
            rows = await self._grants.load_trade_grants(user_id)
            snapshot = replace(snapshot, account_grants=tuple(AccountGrant(*row) for row in rows))
        return TradingPrincipal(session_id=record.id, snapshot=snapshot)

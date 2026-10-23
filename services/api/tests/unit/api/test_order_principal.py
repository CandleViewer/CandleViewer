"""The order route's trading principal (E29-T04 #913, slice 3C; `api.order_principal`).

The route's `enforce(orders:write, GRANTED_ACCOUNTS, account, requires_trade=True)` is run over the
principal's snapshot: it admits a Manager with a live trade grant and refuses a view-only or a
frozen one, and an Owner's grants are not read. No session is no principal (the route's 401); a
store that does not answer, whatever failed, is `StoreUnavailable` (its 503), and so is a view-as
context its request carries no stamp for: the principal asks `view_as_subject` and does not rely on
the view-as guard having refused the write (SEC-S3C1A-01). The Postgres read of the grants is
`tests/integration/storage/test_trade_grants_pg.py`'s.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.requests import Request
from structlog.testing import capture_logs

from candleviewer.api.order_principal import (
    SessionTradingPrincipalResolver,
    TradingPrincipal,
    _TradeGrants,
)
from candleviewer.api.view_as_policy import OWN_OPERATIONS, PROTECTIVE_WRITES
from candleviewer.api.view_as_subject import STATE_KEY
from candleviewer.auth.errors import AuthServiceUnavailable, SessionIdleLocked, SessionRevoked
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import Allow, Deny, DenyReason, decide
from candleviewer.auth.view_as import ViewAsPhase, ViewAsRequestContext, ViewAsState
from candleviewer.oms.errors import StoreUnavailable
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource

USER, SESSION, TRADE, VIEW, FROZEN = (uuid.UUID(int=n) for n in range(1, 6))
TARGET, CONTEXT = uuid.UUID(int=6), uuid.UUID(int=7)
NOW = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)


class _Sessions:
    """A session holding the view-as context `view_as` names: none, unless a test gives one."""

    def __init__(
        self, error: BaseException | None = None, *, hang: bool = False, view_as: Any = None
    ) -> None:
        self.error, self.hang, self.view_as = error, hang, view_as

    async def authenticate_access_token(self, token: str, *, touch: bool = False) -> Any:
        if self.hang:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error
        return SimpleNamespace(id=SESSION, user_id=USER, view_as=self.view_as)


class _Identity:
    def __init__(
        self, roles: Any = ("manager",), status: str = "active", error: Any = None
    ) -> None:
        self.roles, self.status, self.error = roles, status, error

    async def user(self, user_id: str) -> dict[str, Any]:
        assert user_id == str(USER)  # the session's own user
        if self.error is not None or self.status == "missing":
            raise self.error or LookupError(user_id)
        return {"roles": list(self.roles), "status": self.status}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["orders:write", "not:a_code"]}


class _Grants:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error, self.asked = error, list[uuid.UUID]()

    async def load_trade_grants(
        self, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, bool, bool, bool]]:
        self.asked.append(user_id)
        if self.error is not None:
            raise self.error
        return [(TRADE, True, True, False), (VIEW, True, False, False), (FROZEN, True, True, True)]


def _resolver(
    sessions: _Sessions | None = None, identity: Any = None, grants: Any = None, **kw: Any
) -> SessionTradingPrincipalResolver:
    held = sessions or _Sessions()
    return SessionTradingPrincipalResolver(
        lambda: held, identity or _Identity(), grants or _Grants(), **kw
    )


def _live() -> ViewAsState:
    """The session's context: viewing `TARGET`, live."""
    return ViewAsState.start(CONTEXT, TARGET, now=NOW)


def _cleared() -> ViewAsState:
    return _live().model_copy(
        update={"ended_at": NOW, "end_reason": "ended", "end_recorded_at": NOW, "cleared_at": NOW}
    )


def _stamp(*, context: uuid.UUID = CONTEXT, session: uuid.UUID = SESSION) -> ViewAsRequestContext:
    """What the view-as guard stamps on a write it passes as the viewer (`api/view_as_guard.py`)."""
    return ViewAsRequestContext(
        viewer_user_id=USER, viewer_session_id=session, viewer_label="owner-anna",
        target_user_id=TARGET, context_id=context, subject_user_id=USER, phase=ViewAsPhase.LIVE,
    )  # fmt: skip


def _request(
    authorization: str | None = "Bearer tok", stamp: ViewAsRequestContext | None = None
) -> Request:
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]
    state = {} if stamp is None else {STATE_KEY: stamp}
    return Request({"type": "http", "headers": headers, "state": state})


def _decide(principal: TradingPrincipal | None, account: uuid.UUID) -> object:
    """The order route's RBAC step (24 Sec.8.4 step 2) for `account`."""
    assert principal is not None
    return decide(
        principal.snapshot, Permission.ORDERS_WRITE, scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=account, requires_trade=True,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("account", "reason"),
    [(TRADE, None), (VIEW, DenyReason.TRADING_NOT_GRANTED), (FROZEN, DenyReason.ACCOUNT_FROZEN)],
    ids=["trade_grant", "view_only", "frozen"],
)
async def test_the_order_routes_check_admits_a_manager_only_with_a_live_trade_grant(
    account: uuid.UUID, reason: DenyReason | None
) -> None:
    grants = _Grants()
    principal = await _resolver(grants=grants).resolve(_request())
    assert principal is not None and (principal.session_id, principal.snapshot.user_id) == (
        SESSION, USER
    )  # fmt: skip
    assert principal.snapshot.permissions == {Permission.ORDERS_WRITE} and grants.asked == [USER]
    denied = Deny(reason, Permission.ORDERS_WRITE, Scope.GRANTED_ACCOUNTS) if reason else None
    assert _decide(principal, account) == (denied or Allow())


async def test_an_owners_grants_are_not_read_and_every_account_is_its() -> None:
    grants = _Grants()
    principal = await _resolver(identity=_Identity(("owner",)), grants=grants).resolve(_request())
    assert principal is not None and grants.asked == [] and principal.snapshot.account_grants == ()
    assert _decide(principal, uuid.uuid4()) == Allow()


@pytest.mark.parametrize(
    ("authorization", "sessions", "identity"),
    [
        pytest.param(None, _Sessions(), _Identity(), id="no-header"),
        pytest.param("Basic tok", _Sessions(), _Identity(), id="not-bearer"),
        pytest.param("Bearer  ", _Sessions(), _Identity(), id="empty-token"),
        pytest.param("Bearer t", _Sessions(SessionRevoked("x")), _Identity(), id="revoked"),
        pytest.param("Bearer t", _Sessions(SessionIdleLocked("x")), _Identity(), id="idle"),
        pytest.param("Bearer t", _Sessions(LookupError("x")), _Identity(), id="unknown-session"),
        pytest.param("Bearer t", _Sessions(), _Identity(status="missing"), id="unknown-user"),
        pytest.param("Bearer t", _Sessions(), _Identity(status="disabled"), id="disabled"),
        pytest.param("Bearer t", _Sessions(), _Identity(("owner", "root")), id="unknown-role"),
    ],
)
async def test_no_session_is_no_principal(
    authorization: str | None, sessions: _Sessions, identity: _Identity
) -> None:
    assert await _resolver(sessions, identity).resolve(_request(authorization)) is None


@pytest.mark.parametrize(
    "resolver",
    [
        pytest.param(lambda: _resolver(_Sessions(ConnectionResetError())), id="session-store"),
        pytest.param(lambda: _resolver(_Sessions(RuntimeError("x"))), id="auth-not-started"),
        pytest.param(lambda: _resolver(_Sessions(AuthServiceUnavailable())), id="auth-unwired"),
        pytest.param(lambda: _resolver(identity=_Identity(error=OSError())), id="identity"),
        pytest.param(lambda: _resolver(grants=_Grants(StorageTierUnavailable("x"))), id="grants"),
        pytest.param(lambda: _resolver(grants=_Grants(LookupError("x"))), id="grants-lookup"),
        pytest.param(lambda: _resolver(_Sessions(hang=True), timeout_s=0), id="no-answer"),
    ],
)
async def test_a_store_that_does_not_answer_is_the_stores_unavailability(resolver: Any) -> None:
    with pytest.raises(StoreUnavailable) as raised:
        await resolver().resolve(_request())
    assert raised.value.__context__ is None  # nothing of the store's failure rides along


def test_the_sql_scope_source_fills_the_resolvers_grants_port() -> None:
    """`mypy --strict` checks this assignment, so a drift of `load_trade_grants` fails here."""
    grants: _TradeGrants = SqlAlchemyScopeSource(cast(Any, object()))  # no database is touched
    assert inspect.iscoroutinefunction(grants.load_trade_grants)  # the resolver awaits it


async def test_a_cleared_context_is_the_sessions_own_scope_and_needs_no_stamp() -> None:
    principal = await _resolver(_Sessions(view_as=_cleared())).resolve(_request())
    assert principal is not None and (principal.session_id, principal.snapshot.user_id) == (
        SESSION, USER
    )  # fmt: skip


async def test_a_context_stamped_for_the_viewer_is_the_viewers_principal() -> None:
    """A write the guard passes as the viewer, a registered protective one, carries a stamp whose
    subject is the viewer: the principal is the session's own, as with no context."""
    resolver = _resolver(_Sessions(view_as=_live()))
    principal = await resolver.resolve(_request(stamp=_stamp()))
    assert principal is not None and (principal.session_id, principal.snapshot.user_id) == (
        SESSION, USER
    )  # fmt: skip


@pytest.mark.parametrize(
    "stamp",
    [None, _stamp(context=uuid.UUID(int=8)), _stamp(session=uuid.UUID(int=9))],
    ids=["no-stamp", "another-context", "another-session"],
)
async def test_a_live_context_with_no_stamp_for_it_is_the_stores_unavailability(
    stamp: ViewAsRequestContext | None,
) -> None:
    """The guard stamps each request it passes for a session holding a context, and the route does
    not rely on it: a request it did not stamp (a bypass, a re-ordered stack, a mount outside it)
    is a 503, never the session's own scope, which is an Owner's (SEC-S3C1A-01)."""
    grants = _Grants()
    resolver = _resolver(_Sessions(view_as=_live()), grants=grants)
    with capture_logs() as logs, pytest.raises(StoreUnavailable) as raised:
        await resolver.resolve(_request(stamp=stamp))
    assert raised.value.__context__ is None and grants.asked == []
    assert [(entry["event"], entry["error"]) for entry in logs] == [
        ("order_principal_unread", "ViewAsUnstamped")
    ]


def test_place_order_is_neither_an_own_operation_nor_a_protective_write() -> None:
    """The guard refuses `POST /orders` from a session holding a context while the policy lists it
    as neither (`api/view_as_policy.py`): a change that made it own or protective fails here
    first, with the resolver's `view_as_subject` the second line (SEC-S3C1A-01)."""
    place_order = ("POST", "/orders")
    protective = {operation for operation, _ticket in PROTECTIVE_WRITES.values()}
    assert place_order not in OWN_OPERATIONS and place_order not in protective

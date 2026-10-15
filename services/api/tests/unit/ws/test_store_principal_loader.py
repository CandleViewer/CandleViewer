"""#2505: `StorePrincipalLoader`, the WS principal on the real backend (`ws_wiring.py`).

The store edges are fakes (no Postgres, no network, no sleeps). Every failure must yield the
deny-all snapshot without raising, including on re-evaluation, where raising would leave the live
sockets on their previous principal."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import Allow, Deny, DenyReason, PrincipalSnapshot, decide
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SubscriptionServices,
    auth_ok_payload,
    handle_sub,
)
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import PRINCIPAL_LOAD_TIMEOUT_S, StorePrincipalLoader

USER = uuid.UUID(int=0x2505)
GRANTED = uuid.UUID(int=0xA)
FROZEN = uuid.UUID(int=0xF)
VIEWLESS = uuid.UUID(int=0xE)
FOREIGN = uuid.UUID(int=0xB)
EXC_TEXT_MARKER = "exception-text-7f3c"
FAILED = "ws principal load failed; denying all"


class _Identity:
    """`SqlAlchemyIdentityProvider` shape: `user` and `session_info`."""

    def __init__(self, roles: tuple[str, ...] = ("manager",), status: str = "active") -> None:
        self.roles, self.status = list(roles), status
        self.permissions = ["orders:read", "positions:read", "not:a-permission"]
        self.fail: Exception | None = None

    async def user(self, user_id: str) -> dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        return {"id": user_id, "username": "u", "roles": self.roles, "status": self.status}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": list(self.permissions), "account_scope": []}


class _Grants:
    """`SqlAlchemyScopeSource.load_grants` shape: `(account, can_view, frozen)` rows."""

    def __init__(self) -> None:
        self.rows = [(GRANTED, True, False), (FROZEN, True, True), (VIEWLESS, False, False)]
        self.fail: Exception | None = None
        self.hang = False
        self.entered = asyncio.Event()

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        self.entered.set()
        if self.hang:
            await asyncio.Event().wait()  # never set: a hung store
        if self.fail is not None:
            raise self.fail
        return list(self.rows)


def _deny_all() -> PrincipalSnapshot:
    return PrincipalSnapshot(USER, frozenset(), frozenset())


def _may_view(principal: PrincipalSnapshot, account: uuid.UUID) -> Allow | Deny:
    return decide(
        principal, Permission.ORDERS_READ, scope=Scope.GRANTED_ACCOUNTS, exchange_account_id=account
    )


async def test_manager_principal_has_its_roles_known_permissions_and_grants() -> None:
    principal = await StorePrincipalLoader(_Identity(), _Grants())(USER)
    assert principal.user_id == USER and principal.roles == {"manager"}
    assert principal.permissions == {Permission.ORDERS_READ, Permission.POSITIONS_READ}
    assert [(g.exchange_account_id, g.can_view, g.frozen) for g in principal.account_grants] == [
        (GRANTED, True, False),
        (FROZEN, True, True),
        (VIEWLESS, False, False),
    ]
    assert not any(g.can_trade for g in principal.account_grants)  # never loaded: fail closed
    assert auth_ok_payload(principal)["account_scope"] == sorted([str(GRANTED), str(FROZEN)])


async def test_only_a_viewable_unfrozen_grant_lets_a_manager_see_an_account() -> None:
    principal = await StorePrincipalLoader(_Identity(), _Grants())(USER)
    assert isinstance(_may_view(principal, GRANTED), Allow)
    denied = {acc: _may_view(principal, acc) for acc in (FROZEN, VIEWLESS, FOREIGN)}
    assert {acc: d.reason for acc, d in denied.items() if isinstance(d, Deny)} == {
        FROZEN: DenyReason.ACCOUNT_FROZEN,
        VIEWLESS: DenyReason.ACCOUNT_NOT_GRANTED,
        FOREIGN: DenyReason.ACCOUNT_NOT_GRANTED,
    }


async def test_owner_gets_no_grant_rows_so_every_account_is_in_scope() -> None:
    """`auth/scopes.py`: an owner's empty grants mean every account, so rows are not copied."""
    principal = await StorePrincipalLoader(_Identity(roles=("owner",)), _Grants())(USER)
    assert principal.is_owner and principal.account_grants == ()
    assert auth_ok_payload(principal)["account_scope"] == []
    assert all(isinstance(_may_view(principal, a), Allow) for a in (GRANTED, FROZEN, FOREIGN))


@pytest.mark.parametrize("status", ["invited", "disabled", "locked", ""])
async def test_non_active_user_gets_the_deny_all_snapshot(status: str) -> None:
    assert await StorePrincipalLoader(_Identity(status=status), _Grants())(USER) == _deny_all()


async def test_role_outside_the_system_set_denies_all_and_is_logged() -> None:
    with capture_logs() as logs:
        principal = await StorePrincipalLoader(_Identity(roles=("superuser",)), _Grants())(USER)
    assert principal == _deny_all()
    assert [(e["event"], e["error"]) for e in logs] == [(FAILED, "ValueError")]


@pytest.mark.parametrize(
    ("where", "exc"),
    [
        ("identity", LookupError(f"unknown user {EXC_TEXT_MARKER}")),
        ("identity", OSError(f"connection refused {EXC_TEXT_MARKER}")),
        ("grants", RuntimeError(f"pool closed {EXC_TEXT_MARKER}")),
    ],
)
async def test_store_failure_denies_all_without_raising(where: str, exc: Exception) -> None:
    identity, grants = _Identity(), _Grants()
    (identity if where == "identity" else grants).fail = exc
    with capture_logs() as logs:
        principal = await StorePrincipalLoader(identity, grants)(USER)
    assert principal == _deny_all()
    assert logs == [
        {
            "event": FAILED,
            "user_id": str(USER),
            "error": type(exc).__name__,
            "log_level": "warning",
        }
    ]
    assert EXC_TEXT_MARKER not in repr(logs)  # the exception text never reaches the log


async def test_hung_store_is_cut_off_by_the_timeout() -> None:
    grants = _Grants()
    grants.hang = True
    with capture_logs() as logs:
        async with asyncio.timeout(10):  # fails fast, not hangs, if the loader's bound is removed
            principal = await StorePrincipalLoader(_Identity(), grants, timeout_s=0)(USER)
    assert principal == _deny_all()
    assert [e["error"] for e in logs] == ["TimeoutError"]
    assert 0 < PRINCIPAL_LOAD_TIMEOUT_S <= 10  # the default bound stays short


async def test_cancellation_is_never_swallowed() -> None:
    grants = _Grants()
    grants.hang = True
    task = asyncio.create_task(StorePrincipalLoader(_Identity(), grants)(USER))
    await grants.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_every_load_reads_the_store_again() -> None:
    """C-12.4: nothing is cached; each `auth` and re-evaluation sees the current rows."""
    identity, grants = _Identity(), _Grants()
    loader = StorePrincipalLoader(identity, grants)
    assert isinstance(_may_view(await loader(USER), GRANTED), Allow)
    grants.rows = []
    identity.permissions = ["marketdata:read"]
    principal = await loader(USER)
    assert principal.permissions == {Permission.MARKETDATA_READ}
    assert principal.account_grants == ()


class _NoUpstream:
    async def open(self, key: Any) -> None:
        return None

    async def drop(self, key: Any) -> None:
        return None


@pytest.mark.parametrize("change", ["grant_withdrawn", "store_down"])
async def test_reevaluation_through_the_loader_revokes_and_never_raises(change: str) -> None:
    """`grants_changed` re-reads the store. A withdrawn grant, and equally a store failure
    (fail closed), revokes the live subscription instead of keeping the old principal."""
    identity, grants = _Identity(), _Grants()
    registry = ConnectionRegistry(
        StorePrincipalLoader(identity, grants),
        lambda: 42,
        SubscriptionServices(upstream=UpstreamRefs(_NoUpstream())),
    )
    sent: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    conn = ConnectionAuthz(await registry.resolve(USER), registry.services)
    registry.register(conn, send)
    sub = {"ch": "orders", "opts": {"exchange_account_ids": [str(GRANTED)]}}
    await handle_sub(conn, {"t": "sub", "id": "s", "p": {"topics": [sub]}}, send)
    assert sent[0]["p"]["results"][0]["ok"] is True
    if change == "grant_withdrawn":
        grants.rows = []
    else:
        identity.fail = OSError("store down")
    await registry.grants_changed(USER)
    assert [f["t"] for f in sent] == ["sub_ok", "permission_change", "revoked"]
    assert conn.topics == set()

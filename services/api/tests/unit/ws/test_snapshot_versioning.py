"""SR-189 (#2172): an older WS permission snapshot never replaces a newer one (SR-E17-07).

Races run in the order of the QA reproduction on #378, deterministically: a read captures the
grants, the grant change fans out while that read is parked, then the stale read returns."""

from __future__ import annotations

import asyncio
import functools
import uuid
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.permissions import (
    ConnectionAuthz,
    ConnectionRegistry,
    SubscriptionServices,
    VersionedSnapshot,
    cv_ws_permission_snapshots_refused_total,
)
from candleviewer.ws.revocation import RevocationHub

MGR = uuid.UUID(int=0x189)
A = uuid.UUID(int=0xA)
B = uuid.UUID(int=0xB)
PERMS = frozenset({Permission.MARKETDATA_READ, Permission.ORDERS_READ, Permission.POSITIONS_READ})
JSON = ["cv.v1.json"]
ORIGIN = "http://testserver"  # §2.5: allow-listed and sent on every upgrade
ORIGINS = frozenset({ORIGIN})


def _mgr(*accounts: uuid.UUID) -> PrincipalSnapshot:
    grants = tuple(AccountGrant(a, True, False, False) for a in accounts)
    return PrincipalSnapshot(MGR, frozenset({"manager"}), PERMS, grants)


def _acc(*accounts: uuid.UUID) -> dict[str, Any]:
    return {"exchange_account_ids": [str(a) for a in accounts]}


def _refused(event: str) -> float:
    return float(cv_ws_permission_snapshots_refused_total.labels(event=event)._value.get())


class _Audit:
    def __init__(self, *, broken: bool = False) -> None:
        self.records: list[dict[str, Any]] = []
        self.broken = broken

    async def emit(self, action: str, **kw: Any) -> None:
        if self.broken:
            raise RuntimeError("audit sink down")
        self.records.append({"action": action, **kw})


class _Store:
    """Identity store: a read captures the grants, then `races[n]` runs while read n is parked."""

    def __init__(self) -> None:
        self.accounts: tuple[uuid.UUID, ...] = (A, B)
        self.reads = 0
        self.races: dict[int, Callable[[], Awaitable[object]]] = {}

    async def resolve(self, _uid: uuid.UUID) -> PrincipalSnapshot:
        self.reads += 1
        snapshot = _mgr(*self.accounts)
        race = self.races.pop(self.reads, None)
        if race is not None:
            await race()
        return snapshot


def _registry(store: _Store, audit: _Audit | None = None) -> ConnectionRegistry:
    return ConnectionRegistry(store.resolve, lambda: 42, SubscriptionServices(audit=audit))


def _withdraw_b(store: _Store, reg: ConnectionRegistry) -> Callable[[], Awaitable[None]]:
    async def race() -> None:  # the owner withdraws B; E09 then notifies the registry
        store.accounts = (A,)
        await reg.grants_changed(MGR)

    return race


async def _connect(reg: ConnectionRegistry, sent: list[dict[str, Any]]) -> ConnectionAuthz:
    async def send(frame: dict[str, Any]) -> None:
        sent.append(frame)

    snap = await reg.resolve(MGR)
    conn = ConnectionAuthz(snap.principal, reg.services, version=snap.version)
    reg.register(conn, send)
    return conn


def test_apply_snapshot_older_version_is_refused_and_changes_nothing() -> None:
    conn = ConnectionAuthz(_mgr(A, B), version=1)
    conn.admit({"ch": "positions", "opts": _acc(A, B)})
    newer = VersionedSnapshot(_mgr(A), 3)
    assert conn.apply_snapshot(newer, 9) is not None
    assert conn.apply_snapshot(VersionedSnapshot(_mgr(A, B), 2), 9) is None
    assert (conn.version, conn.principal) == (3, newer.principal)
    assert conn.subs == {("positions", A)}


@settings(max_examples=60, deadline=None, derandomize=True)
@given(order=st.permutations(range(1, 9)))
def test_newest_snapshot_wins_in_any_arrival_order(order: list[int]) -> None:
    snaps = {v: VersionedSnapshot(_mgr(A) if v % 2 else _mgr(A, B), v) for v in order}
    conn = ConnectionAuthz(_mgr(A, B))
    for v in order:
        conn.apply_snapshot(snaps[v], v)
    assert (conn.version, conn.principal) == (8, snaps[8].principal)


def test_kill_switch_transition_during_a_handshake_read_forces_a_recheck() -> None:
    store = _Store()
    reg = _registry(store)
    store.races[1] = reg.kill_switch_changed  # no user is connected yet

    async def scenario() -> None:
        await reg.recheck(await _connect(reg, []))

    asyncio.run(scenario())
    assert store.reads == 2


def test_grant_change_snapshot_overtaken_by_a_later_read_is_refused_and_sends_nothing() -> None:
    store, audit = _Store(), _Audit(broken=True)
    reg = _registry(store, audit)
    sent: list[dict[str, Any]] = []
    conns: list[ConnectionAuthz] = []

    async def later_reauth_lands_first() -> None:  # read 3 began after the change: it is newer
        fresh = await reg.resolve(MGR)
        await reg.apply(conns[0], fresh, 1, event="reauth")

    store.races[2] = later_reauth_lands_first  # read 2 is the grant change's own read
    before = _refused("grant_change")

    async def scenario() -> None:
        conns.append(await _connect(reg, sent))
        await reg.grants_changed(MGR)  # the audit sink is down: still refused, nothing raised

    asyncio.run(scenario())
    assert conns[0].version == 3 and sent == []
    assert _refused("grant_change") == before + 1


def _gateway(audit: _Audit | None = None) -> tuple[_Store, ConnectionRegistry, TestClient]:
    store = _Store()
    reg = _registry(store, audit)

    async def auth(_token: str) -> tuple[str, uuid.UUID, datetime]:
        return "sess-189", MGR, datetime(2100, 1, 1, tzinfo=UTC)

    router = make_ws_router(
        authenticate=auth, registry=reg, revocation_hub=RevocationHub(), allowed_origins=ORIGINS
    )
    app = FastAPI()
    app.include_router(router)
    return store, reg, TestClient(app, headers={"origin": ORIGIN})


def _frame(ws: Any) -> dict[str, Any]:
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return dict(pool.submit(ws.receive_json).result(timeout=5.0))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _send(ws: Any, t: str, p: dict[str, Any] | None = None) -> None:
    ws.send_json({"t": t, "id": t[:1], "p": p or {}})


def _open(ws: Any) -> dict[str, Any]:
    _send(ws, "hello")
    assert _frame(ws)["t"] == "welcome"
    _send(ws, "auth", {"access_token": "first"})
    return _frame(ws)


def _sub_b_on_orders(ws: Any) -> str:
    _send(ws, "sub", {"topics": [{"ch": "orders", "opts": _acc(B)}]})
    return str(_frame(ws)["p"]["results"][0]["error"]["code"])


def test_socket_reauth_parked_across_a_withdrawal_keeps_the_withdrawal() -> None:
    audit = _Audit()
    store, reg, client = _gateway(audit)
    before = _refused("reauth")
    with client, client.websocket_connect("/ws", subprotocols=JSON) as ws:
        assert _open(ws)["p"]["account_scope"] == [str(A), str(B)]
        _send(ws, "sub", {"topics": [{"ch": "positions", "opts": _acc(A, B)}]})
        assert _frame(ws)["p"]["results"][0]["ok"] is True
        store.races[2] = _withdraw_b(store, reg)  # read 2 is the re-auth's principal read
        _send(ws, "auth", {"access_token": "second"})
        change, revoked = _frame(ws), _frame(ws)  # the withdrawal's fan-out lands first
        assert (change["t"], revoked["p"]["removed_accounts"]) == ("permission_change", [str(B)])
        ok = _frame(ws)
        assert (ok["t"], ok["p"]["account_scope"]) == ("auth_ok", [str(A)])
        assert _sub_b_on_orders(ws) == "account_scope_denied"
    assert store.reads == 3 and _refused("reauth") == before + 1  # 1st auth: no extra read
    (record,) = [r for r in audit.records if r["action"] == "ws.permission_snapshot.refused"]
    assert (record["reason"], record["object_kind"]) == ("stale", "ws_connection")
    assert record["after_state"] == {"event": "reauth", "applied_version": 3, "refused_version": 2}


def test_socket_handshake_raced_by_two_grant_changes_gets_auth_ok_first_with_newer_scope() -> None:
    store, reg, client = _gateway()  # no audit sink: the refusal is still counted
    store.races[1] = _withdraw_b(store, reg)  # the socket is not registered yet
    store.races[2] = functools.partial(reg.grants_changed, MGR)  # the re-check after register
    before = _refused("handshake")
    with client, client.websocket_connect("/ws", subprotocols=JSON) as ws:
        ok = _open(ws)  # the 2nd change reached the registered socket before its auth_ok
        assert (ok["t"], ok["p"]["account_scope"]) == ("auth_ok", [str(A)])
        assert _sub_b_on_orders(ws) == "account_scope_denied"
    assert store.reads == 3 and _refused("handshake") == before + 1


def test_socket_closed_during_the_handshake_recheck_gets_no_auth_ok() -> None:
    store, reg, client = _gateway()
    store.races[1] = _withdraw_b(store, reg)  # forces the re-check (read 2)
    store.races[2] = functools.partial(reg.user_disabled, MGR)  # the socket is registered
    with client, client.websocket_connect("/ws", subprotocols=JSON) as ws:
        bye = _open(ws)
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "user_disabled")

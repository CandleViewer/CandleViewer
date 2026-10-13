"""SR-189 (#2172): an older WS permission snapshot never replaces a newer one (QA #378 order)."""

from __future__ import annotations

import asyncio
import functools
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.metrics import cv_ws_auth_failures_total
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


def _counts() -> tuple[float, ...]:
    """Refusals at (re-auth, handshake, grant change), then auth failures counted `rejected`."""
    refused = cv_ws_permission_snapshots_refused_total.labels
    rejected = cv_ws_auth_failures_total.labels(reason="rejected")
    events = ("reauth", "handshake", "grant_change")
    return (*(float(refused(event=e)._value.get()) for e in events), rejected._value.get())


class _Audit(list[dict[str, Any]]):
    down = False

    async def emit(self, action: str, **kw: Any) -> None:
        if self.down:
            raise OSError("audit sink down")
        self.append({"action": action, **kw})


async def _store_down() -> None:
    raise OSError("identity store unavailable")


class _Store:
    """Identity store: a read captures the grants, then `races[n]` runs while read n is parked."""

    def __init__(self) -> None:
        self.accounts: tuple[uuid.UUID, ...] = (A, B)
        self.reads = 0
        self.races: dict[int, Any] = {}

    async def resolve(self, _uid: uuid.UUID) -> PrincipalSnapshot:
        self.reads += 1
        snapshot = _mgr(*self.accounts)
        if (race := self.races.pop(self.reads, None)) is not None:
            await race()
        return snapshot


def _withdraw_b(store: _Store, reg: ConnectionRegistry) -> Any:
    async def race() -> None:  # the owner withdraws B; E09 then notifies the registry
        store.accounts = (A,)
        await reg.grants_changed(MGR)

    return race


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
def test_newest_snapshot_wins_in_sampled_arrival_orders(order: list[int]) -> None:
    snaps = {v: VersionedSnapshot(_mgr(A) if v % 2 else _mgr(A, B), v) for v in order}
    conn = ConnectionAuthz(_mgr(A, B))
    for v in order:
        conn.apply_snapshot(snaps[v], v)
    assert (conn.version, conn.principal) == (8, snaps[8].principal)


def test_grant_change_read_older_than_the_applied_snapshot_is_refused_and_sends_nothing() -> None:
    store, audit, sent = _Store(), _Audit(), _Audit()
    audit.down = True  # the audit sink is down: the refusal is still counted, nothing raises
    reg = ConnectionRegistry(store.resolve, lambda: 42, SubscriptionServices(audit=audit))
    conn = ConnectionAuthz(_mgr(A, B), reg.services)

    async def later_read_lands_first() -> None:  # read 2 began after the change: it is newer
        await reg.apply(conn, await reg.resolve(MGR), 1, event="reauth")

    reg.register(conn, sent.emit)  # records any frame the change would send
    store.races[1] = later_read_lands_first  # read 1 is the grant change's own read
    before = _counts()
    asyncio.run(reg.grants_changed(MGR))
    assert (conn.version, sent, _counts()[2]) == (2, [], before[2] + 1)


def _gateway(audit: _Audit | None = None) -> tuple[_Store, ConnectionRegistry, TestClient]:
    store = _Store()
    reg = ConnectionRegistry(store.resolve, lambda: 42, SubscriptionServices(audit=audit))

    async def auth(_token: str) -> tuple[str, uuid.UUID, datetime]:
        return "sess-189", MGR, datetime(2100, 1, 1, tzinfo=UTC)

    router = make_ws_router(
        authenticate=auth, registry=reg, revocation_hub=RevocationHub(), allowed_origins=ORIGINS
    )
    app = FastAPI()
    app.include_router(router)
    return store, reg, TestClient(app, headers={"origin": ORIGIN})


def _send(ws: Any, t: str, p: dict[str, Any] | None = None) -> None:
    ws.send_json({"t": t, "id": t[:1], "p": p or {}})


def _open(ws: Any) -> dict[str, Any]:
    _send(ws, "hello")
    assert ws.receive_json()["t"] == "welcome"
    _send(ws, "auth", {"access_token": "first"})
    return dict(ws.receive_json())


def test_socket_reauth_parked_across_a_withdrawal_keeps_the_withdrawal() -> None:
    audit = _Audit()
    store, reg, client = _gateway(audit)
    before = _counts()
    with client, client.websocket_connect("/ws", subprotocols=JSON) as ws:
        assert _open(ws)["p"]["account_scope"] == [str(A), str(B)]
        _send(ws, "sub", {"topics": [{"ch": "positions", "opts": _acc(A, B)}]})
        assert ws.receive_json()["p"]["results"][0]["ok"] is True
        store.races[2] = _withdraw_b(store, reg)  # read 2 is the re-auth's principal read
        _send(ws, "auth", {"access_token": "second"})
        change, revoked, ok = ws.receive_json(), ws.receive_json(), ws.receive_json()
        assert (change["t"], revoked["p"]["removed_accounts"]) == ("permission_change", [str(B)])
        assert (ok["t"], ok["p"]["account_scope"]) == ("auth_ok", [str(A)])
        _send(ws, "sub", {"topics": [{"ch": "orders", "opts": _acc(B)}]})
        assert ws.receive_json()["p"]["results"][0]["error"]["code"] == "account_scope_denied"
    assert store.reads == 3 and _counts()[0] == before[0] + 1  # 1st auth: no extra read
    (record,) = [r for r in audit if r["action"] == "ws.permission_snapshot.refused"]
    assert (record["reason"], record["object_kind"]) == ("stale", "ws_connection")
    assert record["after_state"] == {"event": "reauth", "applied_version": 3, "refused_version": 2}


def test_socket_handshake_recheck_failure_is_counted_and_undone_then_newer_scope_wins() -> None:
    store, reg, client = _gateway()
    store.races[1] = _withdraw_b(store, reg)  # the socket is not registered yet: re-check
    store.races[2] = _store_down  # ...and that re-check read fails: a counted auth failure
    store.races[3] = _withdraw_b(store, reg)  # the retry starts clean and is raced the same way
    store.races[4] = functools.partial(reg.grants_changed, MGR)  # lands before its auth_ok
    before = _counts()
    with client, client.websocket_connect("/ws", subprotocols=JSON) as ws:
        assert _open(ws)["p"]["code"] == "auth_failed"
        _send(ws, "auth", {"access_token": "retry"})
        ok = ws.receive_json()  # nothing was pushed ahead of auth_ok
        assert (ok["t"], ok["p"]["account_scope"]) == ("auth_ok", [str(A)])
        _send(ws, "sub", {"topics": [{"ch": "orders", "opts": _acc(B)}]})
        assert ws.receive_json()["p"]["results"][0]["error"]["code"] == "account_scope_denied"
    assert [b - a for a, b in zip(before, _counts(), strict=True)] == [0, 1, 0, 1]


def test_socket_closed_during_the_handshake_recheck_gets_no_auth_ok() -> None:
    store, reg, client = _gateway()
    store.races[1] = reg.kill_switch_changed  # a kill-switch transition also forces a re-check
    store.races[2] = functools.partial(reg.user_disabled, MGR)  # the socket is registered
    with client, client.websocket_connect("/ws", subprotocols=JSON) as ws:
        bye = _open(ws)
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "user_disabled")

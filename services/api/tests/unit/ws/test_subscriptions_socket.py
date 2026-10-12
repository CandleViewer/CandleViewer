"""E17-S02 acceptance scenarios over a real `/ws` socket (`23-ws-protocol.md` §5, §6, §9.5).

Every receive is bounded by `_recv` (worker thread + 5 s deadline). The scope change is driven
through `ConnectionRegistry.grants_changed` on the app's portal, exactly as the E09 grant-change
path does; "within 1 s" is asserted on the elapsed wall time of that call plus the receive.
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.upstream import UpstreamRefs

MGR = uuid.UUID(int=0x51)
ACC_A = uuid.UUID(int=0xA1)
ACC_B = uuid.UUID(int=0xB2)
PERMS = frozenset({Permission.MARKETDATA_READ, Permission.POSITIONS_READ, Permission.ORDERS_READ})
JSON = ["cv.v1.json"]
ORIGIN = "http://testserver"  # §2.5: allow-listed and sent on every upgrade
_TIMEOUT_S = 5.0
#: Far-future token expiry: this module does not test expiry (test_token_expiry.py does).
_EXPIRES = datetime(2100, 1, 1, tzinfo=UTC)


def _recv(ws: Any) -> dict[str, Any]:
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        frame: dict[str, Any] = pool.submit(ws.receive_json).result(timeout=_TIMEOUT_S)
    except FutureTimeout:
        pytest.fail(f"no WS frame within {_TIMEOUT_S}s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return frame


class _World:
    def __init__(self) -> None:
        self.grants: tuple[AccountGrant, ...] = (
            AccountGrant(ACC_A, True, False, False),
            AccountGrant(ACC_B, True, False, False),
        )

        async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
            return PrincipalSnapshot(uid, frozenset({"manager"}), PERMS, self.grants)

        async def authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
            if token != "good":  # noqa: S105 - fake test token, not a credential
                raise PermissionError("bad token")
            return "sess-1", MGR, _EXPIRES

        self.registry = ConnectionRegistry(
            resolve, lambda: 1, SubscriptionServices(upstream=UpstreamRefs())
        )
        app = FastAPI()
        app.include_router(
            make_ws_router(
                authenticate=authenticate,
                registry=self.registry,
                revocation_hub=RevocationHub(),
                allowed_origins=frozenset({ORIGIN}),
                tick_s=0.005,
            )
        )
        self.client = TestClient(app, headers={"origin": ORIGIN})


@pytest.fixture
def world() -> _World:
    return _World()


def _open(ws: Any, *, auth: bool = True) -> None:
    ws.send_json({"t": "hello", "id": "h"})
    assert _recv(ws)["t"] == "welcome"
    if auth:
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "good"}})
        assert _recv(ws)["t"] == "auth_ok"


def _sub(ws: Any, *topics: Any) -> list[dict[str, Any]]:
    ws.send_json({"t": "sub", "id": "s", "p": {"topics": list(topics)}})
    frame = _recv(ws)
    assert frame["t"] == "sub_ok", frame
    results: list[dict[str, Any]] = frame["p"]["results"]
    return results


def _acc(*a: uuid.UUID) -> dict[str, Any]:
    return {"exchange_account_ids": [str(x) for x in a]}


def test_socket_partial_success_and_cross_account_raw_frame(world: _World) -> None:
    world.grants = (AccountGrant(ACC_A, True, False, False),)
    with world.client, world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        res = _sub(
            ws, {"ch": "book.BTCUSDT.50"}, {"ch": "trades.BTCUSDT"},
            {"ch": "orders", "opts": _acc(ACC_B)},
        )  # fmt: skip
        assert [(r["ch"], r["ok"]) for r in res] == [
            ("book.BTCUSDT.50", True), ("trades.BTCUSDT", True), ("orders", False),
        ]  # fmt: skip
        assert res[2]["error"]["code"] == "account_scope_denied"
        (pos,) = _sub(ws, {"ch": "positions", "opts": _acc(ACC_B)})
        assert pos["error"]["code"] == "account_scope_denied"


def test_socket_unauthenticated_sub_is_refused(world: _World) -> None:
    with world.client, world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws, auth=False)
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": [{"ch": "positions"}]}})
        err = _recv(ws)
        assert (err["t"], err["p"]["code"]) == ("err", "not_authenticated")


def test_socket_grant_withdrawn_mid_stream_is_announced_within_1s(world: _World) -> None:
    with world.client, world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        res = _sub(ws, {"ch": "positions", "opts": _acc(ACC_A, ACC_B)}, "trades.BTCUSDT")
        assert all(r["ok"] for r in res)
        world.grants = (AccountGrant(ACC_A, True, False, False),)
        started = time.monotonic()
        assert world.client.portal is not None
        world.client.portal.call(world.registry.grants_changed, MGR)
        assert _recv(ws)["t"] == "permission_change"
        revoked = _recv(ws)
        assert time.monotonic() - started < 1.0
        assert (revoked["t"], revoked["ch"]) == ("revoked", "positions")
        assert revoked["p"]["reason"] == "account_scope_changed"
        assert revoked["p"]["removed_accounts"] == [str(ACC_B)]
        # Account A and every other topic continue: retuning both still works.
        ws.send_json({"t": "ctl", "id": "k", "ch": "positions", "p": {"throttle_ms": 200}})
        assert _recv(ws)["t"] == "ctl_ok"
        ws.send_json({"t": "ctl", "id": "k2", "ch": "trades.BTCUSDT", "p": {"throttle_ms": 200}})
        assert _recv(ws)["t"] == "ctl_ok"


def test_socket_unsub_idempotent_and_system_refused(world: _World) -> None:
    with world.client, world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        _sub(ws, "book.BTCUSDT.50")
        for expected in ({"ch": "book.BTCUSDT.50", "ok": True},
                         {"ch": "book.BTCUSDT.50", "ok": True, "noop": True}):  # fmt: skip
            ws.send_json({"t": "unsub", "id": "u", "p": {"topics": ["book.BTCUSDT.50"]}})
            frame = _recv(ws)
            assert (frame["t"], frame["p"]["results"]) == ("unsub_ok", [expected])
        ws.send_json({"t": "unsub", "id": "u", "p": {"topics": ["system"]}})
        assert _recv(ws)["p"]["results"] == [{"ch": "system", "ok": False}]


def test_socket_ctl_on_unsubscribed_topic_is_not_subscribed(world: _World) -> None:
    with world.client, world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        ws.send_json({"t": "ctl", "id": "k", "ch": "heatmap.BTCUSDT", "p": {"throttle_ms": 9}})
        err = _recv(ws)
        assert (err["t"], err["id"], err["p"]["code"]) == ("err", "k", "not_subscribed")
        _sub(ws, "heatmap.BTCUSDT")
        ws.send_json(
            {"t": "ctl", "id": "k", "ch": "heatmap.BTCUSDT", "p": {"time_bucket_ms": 1000}}
        )
        assert _recv(ws)["p"]["resnapshot"] is True


def test_socket_disabled_user_gets_bye_4403(world: _World) -> None:
    with world.client, world.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        _sub(ws, "trades.BTCUSDT")
        assert world.client.portal is not None
        assert world.client.portal.call(world.registry.user_disabled, MGR) == 1
        bye = _recv(ws)
        assert (bye["t"], bye["p"]["reason"], bye["p"]["code"]) == ("bye", "user_disabled", 4403)
        with pytest.raises(WebSocketDisconnect) as exc:
            _recv(ws)
    assert exc.value.code == 4403

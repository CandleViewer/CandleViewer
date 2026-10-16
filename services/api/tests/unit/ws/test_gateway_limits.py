"""Gateway deny branches and C-2.18 bounds (PR #1654 security review)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws import limits
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.permissions import ConnectionAuthz, ConnectionRegistry, handle_sub
from candleviewer.ws.revocation import RevocationHub

USER = uuid.uuid4()
#: Far-future token expiry: this module does not test expiry (test_token_expiry.py does).
_EXPIRES = datetime(2100, 1, 1, tzinfo=UTC)
ORIGIN = "http://testserver"  # §2.5: allow-listed and sent on every upgrade
ALLOWED = frozenset({ORIGIN})


async def _resolve(uid: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(uid, frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ}))


async def _authenticate(presented: str) -> tuple[str, uuid.UUID, datetime]:
    if presented != "ok":
        raise PermissionError("bad token")
    return "sess", USER, _EXPIRES


def _client(**kw: Any) -> TestClient:
    app = FastAPI()
    reg = ConnectionRegistry(_resolve, lambda: 1)
    app.include_router(
        make_ws_router(
            authenticate=_authenticate,
            registry=reg,
            revocation_hub=RevocationHub(),
            allowed_origins=ALLOWED,
            **kw,
        )
    )
    return TestClient(app, headers={"origin": ORIGIN})


def _hello(ws: Any) -> None:
    ws.send_json({"t": "hello", "id": "h"})
    assert ws.receive_json()["t"] == "welcome"


@pytest.mark.parametrize("payload", [{}, {"access_token": 7}, None, "x"])
def test_gateway_auth_without_string_token_fails_and_third_closes_4401(payload: Any) -> None:
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        for _ in range(2):
            ws.send_json({"t": "auth", "id": "a", "p": payload})
            assert ws.receive_json()["p"]["code"] == "auth_failed"
        ws.send_json({"t": "auth", "id": "a", "p": payload})
        bye = ws.receive_json()
        assert (bye["t"], bye["p"]["reason"]) == ("bye", "auth_failed")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4401


def test_gateway_non_object_and_non_json_frames_are_err_then_ping_still_served() -> None:
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        ws.send_json([1, 2])
        assert ws.receive_json()["p"]["code"] == "frame_malformed"
        ws.send_json({"t": "ping", "id": "p"})
        pong = ws.receive_json()
        assert (pong["t"], pong["id"]) == ("pong", "p")


def test_gateway_authenticated_socket_unsub_ok() -> None:
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "ok"}})
        assert ws.receive_json()["t"] == "auth_ok"
        ws.send_json({"t": "unsub", "id": "u", "p": {"topics": ["book.X"]}})
        assert ws.receive_json()["t"] == "unsub_ok"


@pytest.mark.parametrize("binary", [False, True])
def test_gateway_oversized_frame_closes_1009_before_parse(binary: bool) -> None:
    with _client(max_frame_bytes=64).websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        blob = '{"t":"ping","id":"' + "x" * 100 + '"}'
        if binary:
            ws.send_bytes(blob.encode())
        else:
            ws.send_text(blob)
        bye = ws.receive_json()  # S11: bye precedes every server-initiated close
        assert (bye["t"], bye["p"]["reason"], bye["p"]["code"]) == ("bye", "frame_too_big", 1009)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == limits.CLOSE_TOO_BIG


def _viewer() -> ConnectionAuthz:
    return ConnectionAuthz(
        PrincipalSnapshot(USER, frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ}))
    )


async def _collect_sub(authz: ConnectionAuthz, topics: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        out.append(frame)

    await handle_sub(authz, {"t": "sub", "id": "s", "p": {"topics": topics}}, send)
    results: list[dict[str, Any]] = out[0]["p"]["results"]
    return results


def _many(start: int, n: int) -> list[str]:
    """`n` distinct public topics on ONE symbol (the 40-symbol cap is a separate limit)."""
    # footprint, not bars: bars.* has its own 16-per-connection cap (SR-E12-07, §6.1)
    return [f"footprint.BTCUSDT.tick.{i}" for i in range(start + 1, start + n + 1)]


def test_sub_over_subscription_cap_is_rejected_and_set_does_not_grow() -> None:
    authz = _viewer()
    for start in range(0, limits.MAX_SUBSCRIPTIONS, limits.MAX_TOPICS_PER_SUB):
        topics = _many(start, limits.MAX_TOPICS_PER_SUB)
        assert all(r["ok"] for r in asyncio.run(_collect_sub(authz, topics)))
    assert len(authz.by_id) == limits.MAX_SUBSCRIPTIONS
    before = dict(authz.by_id)
    res = asyncio.run(_collect_sub(authz, ["book.BTCUSDT.50", "footprint.BTCUSDT.tick.1"]))
    assert res[0]["error"]["code"] == "subscription_limit"
    assert res[1]["error"]["code"] == "duplicate_subscription"  # existing subs untouched
    assert authz.by_id == before


def test_sub_frame_with_too_many_topics_rejects_the_excess() -> None:
    authz = _viewer()
    topics = _many(0, limits.MAX_TOPICS_PER_SUB + 3)
    res = asyncio.run(_collect_sub(authz, topics))
    assert [r["error"]["code"] for r in res if not r["ok"]] == ["too_many_topics"] * 3
    assert len(authz.by_id) == limits.MAX_TOPICS_PER_SUB


def test_roles_changed_stalled_socket_is_evicted_and_does_not_block_others() -> None:
    async def scenario() -> tuple[list[str], list[dict[str, Any]], int]:
        reg = ConnectionRegistry(_resolve, lambda: 1)
        reg.send_timeout_s = 0.05
        never = asyncio.Event()
        closed: list[str] = []
        good: list[dict[str, Any]] = []

        async def stalled(frame: dict[str, Any]) -> None:
            await never.wait()

        async def close_stalled() -> None:
            closed.append("stalled")

        async def ok(frame: dict[str, Any]) -> None:
            good.append(frame)

        async def broken(frame: dict[str, Any]) -> None:
            raise RuntimeError("socket gone")

        reg.register(_viewer(), stalled, close_stalled)
        reg.register(_viewer(), broken)  # no close hook: still evicted
        reg.register(_viewer(), ok)
        await reg.roles_changed(USER)
        await reg.roles_changed(USER)  # evicted sockets receive nothing more
        return closed, good, len(reg._conns[USER])

    closed, good, remaining = asyncio.run(scenario())
    assert closed == ["stalled"]
    assert [f["t"] for f in good] == ["permission_change", "permission_change"]
    assert remaining == 1


def test_gateway_client_disconnect_before_auth_cleans_up() -> None:
    with _client().websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        ws.send_json({"t": "hello", "id": "h"})
        assert ws.receive_json()["t"] == "welcome"
    # context exit = client close frame -> server leaves the loop without error


def test_gateway_evict_hook_sends_slow_consumer_and_closes_4429() -> None:
    app = FastAPI()
    reg = ConnectionRegistry(_resolve, lambda: 1)
    app.include_router(
        make_ws_router(
            authenticate=_authenticate,
            registry=reg,
            revocation_hub=RevocationHub(),
            allowed_origins=ALLOWED,
        )
    )
    client = TestClient(app, headers={"origin": ORIGIN})
    with client, client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        _hello(ws)
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "ok"}})
        assert ws.receive_json()["t"] == "auth_ok"
        _, _, evict = reg._conns[USER][0]
        assert client.portal is not None
        client.portal.call(evict)
        assert ws.receive_json()["p"]["reason"] == "slow_consumer"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == limits.CLOSE_SLOW_CONSUMER

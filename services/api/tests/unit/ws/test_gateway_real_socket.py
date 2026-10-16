"""#2484 gap 4 (E17-S01 test plan "full handshake over a real socket"): the gateway behind a real
uvicorn server, built with the production `uvicorn_kwargs()` limits, on an ephemeral loopback port.
The rest of the WS suite uses Starlette's in-process TestClient, which differs from a real server
in the upgrade (an unknown subprotocol is HTTP 403 here, `1002` there) and has no transport
size cap. No network beyond 127.0.0.1; every wait is bounded by `asyncio.timeout`.

#2483 adds `cv.v1.msgpack`: the extension handshake, which only a real server performs (§3.5)."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import msgpack
import pytest
import uvicorn
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.typing import Origin, Subprotocol

from candleviewer.server import uvicorn_kwargs
from candleviewer.ws.limits import MAX_INBOUND_FRAME_BYTES, SERVER_WS_MAX_SIZE
from tests.unit.ws.test_lifecycle_socket import JSON, ORIGIN, _World

_DEADLINE_S = 10.0
_ORIGIN = Origin(ORIGIN)
_JSON = [Subprotocol(p) for p in JSON]


@asynccontextmanager
async def _serve() -> AsyncIterator[str]:
    """The `/ws` URL of a real uvicorn server running the lifecycle test world's gateway."""
    kw = uvicorn_kwargs()
    del kw["host"], kw["port"]  # the pre-bound loopback socket below
    config = uvicorn.Config(_World().client.app, lifespan="off", log_level="warning", **kw)
    config.load()
    server = uvicorn.Server(config)
    server.lifespan = config.lifespan_class(config)  # as `Server.serve` does before `startup`
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    await server.startup(sockets=[sock])
    try:
        yield f"ws://127.0.0.1:{sock.getsockname()[1]}/ws"
    finally:
        await server.shutdown(sockets=[sock])
        sock.close()


async def _send(ws: ClientConnection, frame: dict[str, Any]) -> dict[str, Any]:
    await ws.send(json.dumps(frame))
    reply: dict[str, Any] = json.loads(await ws.recv())
    return reply


async def _authenticated(ws: ClientConnection) -> None:
    assert (await _send(ws, {"t": "hello", "id": "h"}))["t"] == "welcome"
    auth = {"t": "auth", "id": "a", "p": {"access_token": "good-1"}}
    assert (await _send(ws, auth))["t"] == "auth_ok"


async def test_real_socket_handshake_hello_auth_auth_ok() -> None:
    async with asyncio.timeout(_DEADLINE_S), _serve() as url:
        async with connect(url, subprotocols=_JSON, origin=_ORIGIN) as ws:
            assert ws.subprotocol == "cv.v1.json"
            await _authenticated(ws)
            assert (await _send(ws, {"t": "ping", "id": "p"}))["t"] == "pong"


async def test_real_socket_unknown_subprotocol_is_refused_with_http_403() -> None:
    async with asyncio.timeout(_DEADLINE_S), _serve() as url:
        with pytest.raises(InvalidStatus) as exc:
            async with connect(url, subprotocols=[Subprotocol("cv.v2.json")], origin=_ORIGIN):
                pass
        assert exc.value.response.status_code == 403  # in process (TestClient) this is 1002


@pytest.mark.parametrize(
    ("offer", "chosen", "extensions"),
    [
        (_JSON, "cv.v1.json", ["permessage-deflate"]),
        ([Subprotocol("cv.v1.msgpack"), *_JSON], "cv.v1.msgpack", []),
        ([*_JSON, Subprotocol("cv.v1.msgpack")], "cv.v1.msgpack", []),  # the server's order wins
        ([Subprotocol("cv.v1.msgpack")], "cv.v1.msgpack", []),
    ],
    ids=["json", "msgpack", "json-first", "msgpack-only"],
)
async def test_real_socket_permessage_deflate_is_on_for_json_and_off_for_msgpack(
    offer: list[Subprotocol], chosen: str, extensions: list[str]
) -> None:
    """§3.5: the client offers permessage-deflate either way (the `websockets` default), and the
    server agrees to it for `cv.v1.json` only. Frames then flow in the agreed encoding."""
    async with asyncio.timeout(_DEADLINE_S), _serve() as url:
        async with connect(url, subprotocols=offer, origin=_ORIGIN) as ws:
            assert ws.subprotocol == chosen
            assert [e.name for e in ws.protocol.extensions] == extensions
            binary = chosen == "cv.v1.msgpack"
            hello = {"t": "hello", "id": "h"}
            await ws.send(msgpack.packb(hello) if binary else json.dumps(hello))
            raw = await ws.recv()
            assert isinstance(raw, bytes) is binary  # a binary frame on msgpack, text on JSON
            welcome = msgpack.unpackb(raw) if binary else json.loads(raw)
            assert welcome["p"]["encoding"] == chosen.removeprefix("cv.v1.")


async def test_real_socket_frame_over_the_gateway_cap_gets_bye_then_1009() -> None:
    frame = json.dumps({"t": "ping", "id": "big", "p": {"pad": "x" * MAX_INBOUND_FRAME_BYTES}})
    assert MAX_INBOUND_FRAME_BYTES < len(frame) <= SERVER_WS_MAX_SIZE  # past the gateway cap only
    async with asyncio.timeout(_DEADLINE_S), _serve() as url:
        async with connect(url, subprotocols=_JSON, origin=_ORIGIN, compression=None) as ws:
            await _authenticated(ws)
            await ws.send(frame)
            bye = json.loads(await ws.recv())
            assert (bye["t"], bye["p"]["reason"]) == ("bye", "frame_too_big")
            with pytest.raises(ConnectionClosed) as exc:
                await ws.recv()
    assert exc.value.rcvd is not None and exc.value.rcvd.code == 1009


async def test_real_socket_frame_over_the_transport_cap_closes_1009_without_bye() -> None:
    """The server layer, not the gateway, refuses it: no `bye` (the S11 exception #2486 records)."""
    async with asyncio.timeout(_DEADLINE_S), _serve() as url:
        async with connect(url, subprotocols=_JSON, origin=_ORIGIN, compression=None) as ws:
            await _authenticated(ws)
            await ws.send("x" * (SERVER_WS_MAX_SIZE + 1))
            with pytest.raises(ConnectionClosed) as exc:
                await ws.recv()
    assert exc.value.rcvd is not None and exc.value.rcvd.code == 1009

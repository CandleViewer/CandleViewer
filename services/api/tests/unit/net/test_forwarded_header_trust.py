"""#2275: `X-Forwarded-For` has one interpreter, MeshOnly, and only from the configured proxy.

uvicorn's `ProxyHeadersMiddleware` rewrote `scope["client"]` from `X-Forwarded-For` for any
loopback peer (`proxy_headers=True`, `forwarded_allow_ips` `127.0.0.1,::1`), so a loopback peer
chose the address MeshOnly judged and recorded (`cv_mesh_source`: the WS refusal log's
`source_ip`, the auth audit's `actor_ip`). These tests run the real `create_app()` under a real
uvicorn server built from `uvicorn_kwargs()`, on an ephemeral loopback port, so uvicorn's own
wrapping is in play. A probe route behind the whole middleware stack reports what a handler
sees. No network beyond 127.0.0.1; every wait is bounded by `asyncio.timeout`.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import pytest
import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse
from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.net import RESOLVED_SOURCE_KEY
from candleviewer.server import uvicorn_kwargs
from candleviewer.settings import Settings

_DEADLINE_S = 10.0
_LOOPBACK = "127.0.0.1"
_PROBE = "/__mesh_probe"
_EVIL = "https://evil.example"
_REFUSED_LINE = "ws upgrade refused"

#: (configured trusted proxy address, `X-Forwarded-For` a loopback peer sends, the address MeshOnly
#: must judge and record). Without a configured proxy the header is ignored, whether its value is
#: on the mesh (once logged as the source) or off it (once refused by MeshOnly). Through the
#: configured proxy MeshOnly reads the right-most hop, exactly once.
CASES = [
    pytest.param(None, "100.64.66.66", _LOOPBACK, id="no-proxy-on-mesh-header"),
    pytest.param(None, "203.0.113.7", _LOOPBACK, id="no-proxy-off-mesh-header"),
    pytest.param(_LOOPBACK, "203.0.113.9, 100.64.1.2", "100.64.1.2", id="trusted-proxy-right-most"),
]


async def _probe(request: Request) -> JSONResponse:
    """What a handler sees: the peer uvicorn reported, and the address MeshOnly admitted."""
    client = request.client
    state: Mapping[str, Any] = request.scope.get("state") or {}
    return JSONResponse(
        {"client": client.host if client else None, "mesh_source": state.get(RESOLVED_SOURCE_KEY)}
    )


def _settings(proxy: str | None) -> Settings:
    return Settings(
        allowed_origins="http://app.example",
        mesh_cidrs_csv="100.64.0.0/10",
        mesh_trusted_proxy_header="x-forwarded-for" if proxy is not None else None,
        mesh_trusted_proxy_address=proxy,
    )


@asynccontextmanager
async def _serve(settings: Settings) -> AsyncIterator[int]:
    """`create_app(settings)` under a uvicorn server configured by `uvicorn_kwargs(settings)`
    (host included), on an ephemeral port; yields the port."""
    app = create_app(settings)
    app.add_route(_PROBE, _probe, methods=["GET"], include_in_schema=False)
    kwargs = {**uvicorn_kwargs(settings), "port": 0, "lifespan": "off", "log_level": "warning"}
    config = uvicorn.Config(app, **kwargs)
    config.load()
    server = uvicorn.Server(config)
    server.lifespan = config.lifespan_class(config)  # as `Server.serve` does before `startup`
    await server.startup()
    try:
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        await server.shutdown()


async def _status_and_body(port: int, path: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
    """One raw HTTP/1.1 GET from a loopback socket, read until the server closes it."""
    lines = [f"GET {path} HTTP/1.1", f"Host: {_LOOPBACK}"]
    lines += [f"{name}: {value}" for name, value in headers.items()]
    reader, writer = await asyncio.open_connection(_LOOPBACK, port)
    try:
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        await writer.drain()
        raw = await reader.read()
    finally:
        writer.close()
        await writer.wait_closed()
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), body


def _request_headers(forwarded_for: str) -> dict[str, str]:
    return {"Connection": "close", "X-Forwarded-For": forwarded_for}


def _upgrade_headers(forwarded_for: str) -> dict[str, str]:
    return {
        "Connection": "Upgrade",
        "Upgrade": "websocket",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": base64.b64encode(bytes(16)).decode(),  # a 16-byte nonce, RFC 6455
        "Origin": _EVIL,
        "X-Forwarded-For": forwarded_for,
    }


@pytest.mark.parametrize(("proxy", "forwarded_for", "recorded"), CASES)
async def test_request_mesh_source_is_the_peer_or_the_trusted_proxy_hop(
    proxy: str | None, forwarded_for: str, recorded: str
) -> None:
    async with asyncio.timeout(_DEADLINE_S), _serve(_settings(proxy)) as port:
        status, body = await _status_and_body(port, _PROBE, _request_headers(forwarded_for))
    assert status == 200  # MeshOnly judged `recorded`, which is on the mesh or loopback
    # uvicorn never rewrites `scope["client"]`; MeshOnly alone read the header, if trusted.
    assert json.loads(body) == {"client": _LOOPBACK, "mesh_source": recorded}


@pytest.mark.parametrize(("proxy", "forwarded_for", "recorded"), CASES)
async def test_ws_upgrade_refusal_logs_the_peer_or_the_trusted_proxy_hop(
    proxy: str | None, forwarded_for: str, recorded: str
) -> None:
    async with asyncio.timeout(_DEADLINE_S), _serve(_settings(proxy)) as port:
        with capture_logs() as logs:
            status, _ = await _status_and_body(port, "/ws", _upgrade_headers(forwarded_for))
    assert status == 403  # refused by the Origin check, after MeshOnly admitted `recorded`
    assert [e["source_ip"] for e in logs if e["event"] == _REFUSED_LINE] == [recorded]


async def test_forwarded_allow_ips_cannot_add_a_second_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uvicorn reads `FORWARDED_ALLOW_IPS` only when its proxy-header handling is on."""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    async with asyncio.timeout(_DEADLINE_S), _serve(_settings(None)) as port:
        status, body = await _status_and_body(port, _PROBE, _request_headers("100.64.66.66"))
    assert (status, json.loads(body)) == (200, {"client": _LOOPBACK, "mesh_source": _LOOPBACK})

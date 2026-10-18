"""E27-T03 (#836 slice 2b5): production's private-WS connector on a real socket.

The probe's other tests use a fake stream. These run it on `connect_private_ws` itself against
`websockets` servers on ephemeral 127.0.0.1 ports, so the library's own redirect handling and
frame bound are what is tested. No network beyond 127.0.0.1, and every wait is bounded.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from http import HTTPStatus

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from candleviewer.exchange.bybit import key_ws_probe
from candleviewer.exchange.bybit.key_ws_probe import KeyWsProbe, PrivateSocket, WsProbeResult
from tests._signing import CREDENTIAL_ID, fake_capability
from tests.unit.exchange.bybit.test_key_ws_probe import MARK, NOW_MS, OK, URLS, Clock

_DEADLINE_S = 10.0
FAILED = WsProbeResult(ok=False, error="transport_error", latency_ms=None)


class Peer:
    """A private stream on 127.0.0.1. It counts handshakes and keeps each frame; it answers a
    handshake with a 302 to `redirect`, or else each frame with `reply`."""

    def __init__(self, reply: str = OK, redirect: str | None = None) -> None:
        self.reply, self.redirect = reply, redirect
        self.handshakes = 0
        self.frames: list[str] = []

    def process_request(self, conn: ServerConnection, _request: Request) -> Response | None:
        self.handshakes += 1
        if self.redirect is None:
            return None
        response = conn.respond(HTTPStatus.FOUND, "")
        response.headers["Location"] = self.redirect
        return response

    async def handler(self, conn: ServerConnection) -> None:
        with contextlib.suppress(ConnectionClosed):
            async for frame in conn:
                self.frames.append(str(frame))
                await conn.send(self.reply)

    @contextlib.asynccontextmanager
    async def serving(self) -> AsyncIterator[str]:
        """This stream's URL while it listens."""
        async with serve(self.handler, "127.0.0.1", 0, process_request=self.process_request) as s:
            yield f"ws://127.0.0.1:{s.sockets[0].getsockname()[1]}/v5/private"


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A proxy named in the environment would carry the dial off 127.0.0.1."""
    monkeypatch.setenv("no_proxy", "*")


async def probe(url: str) -> WsProbeResult:
    """A demo probe on production's connector, the demo stream being `url`."""

    async def dial(dialled: str) -> PrivateSocket:
        assert dialled == URLS["demo"]
        return await key_ws_probe.connect_private_ws(url)

    ws_probe = KeyWsProbe(dial, monotonic=Clock(), wall_ms=lambda: NOW_MS)
    return await ws_probe.probe(fake_capability(MARK), "demo", CREDENTIAL_ID)


async def test_a_granted_auth_on_a_real_socket_passes_after_one_auth_frame() -> None:
    peer = Peer()
    async with asyncio.timeout(_DEADLINE_S), peer.serving() as url:
        assert await probe(url) == WsProbeResult(ok=True, error=None, latency_ms=0)
    assert [json.loads(frame)["op"] for frame in peer.frames] == ["auth"]


async def test_a_redirect_is_refused_so_the_signed_auth_reaches_no_other_host() -> None:
    """SR-040a, C-2.11: `websockets` follows a 3xx to any host by default; production's connector
    follows none, so the probe fails on its own host after one handshake, and nothing else is
    dialled."""
    other = Peer()
    async with asyncio.timeout(_DEADLINE_S), other.serving() as elsewhere:
        own = Peer(redirect=elsewhere)
        async with own.serving() as url:
            assert await probe(url) == FAILED
    assert (own.handshakes, other.handshakes, other.frames) == (1, 0, [])


async def test_a_redirect_the_library_follows_anyway_is_aborted_before_any_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defence in depth, as `rest.py`'s `_assert_same_host`: should the library follow the 3xx
    regardless, the handshake did not go to the requested stream, so the socket is aborted with
    nothing sent on it."""
    library = connect.process_redirect
    monkeypatch.setattr(key_ws_probe._NoRedirectConnect, "process_redirect", library)
    other = Peer()
    async with asyncio.timeout(_DEADLINE_S), other.serving() as elsewhere:
        own = Peer(redirect=elsewhere)
        async with own.serving() as url:
            assert await probe(url) == FAILED
    assert (own.handshakes, other.handshakes, other.frames) == (1, 1, [])


async def test_a_reply_above_4096_bytes_is_refused_by_the_library_as_a_transport_error() -> None:
    peer = Peer(reply=json.dumps({"op": "auth", "success": True, "pad": "x" * 4096}))
    async with asyncio.timeout(_DEADLINE_S), peer.serving() as url:
        assert await probe(url) == FAILED
    assert len(peer.frames) == 1

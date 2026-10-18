"""E27-T03 (#836 slice 2b5): production's private-WS connector on a real socket.

The probe's other tests use a fake stream. These run it on `connect_private_ws` itself against
`websockets` servers on ephemeral 127.0.0.1 ports, so the library's own redirect, frame bound,
TLS and proxy handling are what is tested. No network beyond 127.0.0.1, and every wait is bounded.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import ssl
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from http import HTTPStatus
from ipaddress import IPv4Address
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close
from websockets.http11 import Request, Response
from websockets.proxy import get_proxy
from websockets.uri import parse_uri

from candleviewer.exchange.bybit import key_ws_probe
from candleviewer.exchange.bybit.key_ws_probe import KeyWsProbe, PrivateSocket, WsProbeResult
from tests._signing import CREDENTIAL_ID, fake_capability
from tests.unit.exchange.bybit.test_key_ws_probe import MARK, NOW_MS, OK, URLS, Clock

_DEADLINE_S = 10.0
FAILED = WsProbeResult(ok=False, error="transport_error", latency_ms=None)
GRANTED = WsProbeResult(ok=True, error=None, latency_ms=0)


class Peer:
    """A private stream on 127.0.0.1. It counts handshakes and keeps each one's path, each frame,
    and the close frame each connection got from the client (None when the client dropped the
    socket without one, as an abort does); it answers a handshake for `/v5/private` with a 302 to
    `redirect`, or else each frame with `reply`."""

    def __init__(self, reply: str = OK, redirect: str | None = None) -> None:
        self.reply, self.redirect = reply, redirect
        self.handshakes = 0
        self.paths: list[str] = []
        self.frames: list[str] = []
        self.closes: list[Close | None] = []

    def process_request(self, conn: ServerConnection, request: Request) -> Response | None:
        self.handshakes += 1
        self.paths.append(request.path)
        if self.redirect is None or request.path != "/v5/private":
            return None
        response = conn.respond(HTTPStatus.FOUND, "")
        response.headers["Location"] = self.redirect
        return response

    async def handler(self, conn: ServerConnection) -> None:
        with contextlib.suppress(ConnectionClosed):
            async for frame in conn:
                self.frames.append(str(frame))
                await conn.send(self.reply)
        self.closes.append(conn.protocol.close_rcvd)

    @contextlib.asynccontextmanager
    async def serving(self, tls: ssl.SSLContext | None = None) -> AsyncIterator[str]:
        """This stream's URL while it listens, on `wss://` when it serves `tls`."""
        scheme = "ws" if tls is None else "wss"
        async with serve(
            self.handler, "127.0.0.1", 0, process_request=self.process_request, ssl=tls
        ) as s:
            yield f"{scheme}://127.0.0.1:{s.sockets[0].getsockname()[1]}/v5/private"


class Proxy:
    """A proxy's port on 127.0.0.1: it counts the connections it gets and drops each."""

    def __init__(self) -> None:
        self.asked = 0

    async def drop(self, _: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.asked += 1
        writer.close()
        await writer.wait_closed()

    @contextlib.asynccontextmanager
    async def listening(self) -> AsyncIterator[str]:
        """This proxy's URL while it listens."""
        async with await asyncio.start_server(self.drop, "127.0.0.1", 0) as server:
            yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"


#: A root's key usage: it signs certificates and revocation lists, nothing else.
_ROOT_USAGE = x509.KeyUsage(
    digital_signature=False,
    content_commitment=False,
    key_encipherment=False,
    data_encipherment=False,
    key_agreement=False,
    key_cert_sign=True,
    crl_sign=True,
    encipher_only=False,
    decipher_only=False,
)


def _issue(tmp_path: Path) -> tuple[Path, ssl.SSLContext]:
    """A throwaway root's PEM file, and a TLS server context holding a 127.0.0.1 certificate the
    root signed. Both carry the extensions OpenSSL's strict chain checks ask for (Python 3.13 turns
    them on), so trust alone decides a dial's handshake."""
    root_key, key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    root_name = _name("cv-test-root")
    root = (
        _builder(root_name, root_name, root_key)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(_ROOT_USAGE, critical=True)
        .sign(root_key, hashes.SHA256())
    )
    issued_by_root = x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key())
    at_loopback = x509.SubjectAlternativeName([x509.IPAddress(IPv4Address("127.0.0.1"))])
    server = (
        _builder(_name("127.0.0.1"), root_name, key)
        .add_extension(issued_by_root, critical=False)
        .add_extension(at_loopback, critical=False)
        .sign(root_key, hashes.SHA256())
    )
    pem, pkcs8 = serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8
    (root_file := tmp_path / "root.pem").write_bytes(root.public_bytes(pem))
    (server_file := tmp_path / "server.pem").write_bytes(
        server.public_bytes(pem) + key.private_bytes(pem, pkcs8, serialization.NoEncryption())
    )
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(server_file)
    return root_file, tls


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _builder(
    subject: x509.Name, issuer: x509.Name, key: ec.EllipticCurvePrivateKey
) -> x509.CertificateBuilder:
    return (
        x509.CertificateBuilder(issuer_name=issuer, subject_name=subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime(2020, 1, 1, tzinfo=UTC))
        .not_valid_after(datetime(2120, 1, 1, tzinfo=UTC))
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    )


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A proxy named in the environment would carry the library's own dials off 127.0.0.1;
    production's connector takes none (the proxy test below)."""
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
    nothing sent on it: the other stream sees it dropped with no close frame."""
    library = connect.process_redirect
    monkeypatch.setattr(key_ws_probe._NoRedirectConnect, "process_redirect", library)
    other = Peer()
    async with asyncio.timeout(_DEADLINE_S), other.serving() as elsewhere:
        own = Peer(redirect=elsewhere)
        async with own.serving() as url:
            assert await probe(url) == FAILED
    assert (own.handshakes, other.handshakes, other.frames, other.closes) == (1, 1, [], [None])


async def test_a_redirect_to_another_path_of_its_own_host_is_aborted_before_any_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The path half of the handshake check: a 3xx from `/v5/private` to `/v5/trade` on the same
    host and port is a same-origin redirect, which the library follows whatever its cross-origin
    rules; the socket on the other path is aborted with nothing sent on it, dropped with no close
    frame."""
    library = connect.process_redirect
    monkeypatch.setattr(key_ws_probe._NoRedirectConnect, "process_redirect", library)
    own = Peer(redirect="/v5/trade")
    async with asyncio.timeout(_DEADLINE_S), own.serving() as url:
        assert await probe(url) == FAILED
    assert (own.paths, own.frames, own.closes) == (["/v5/private", "/v5/trade"], [], [None])


async def test_a_reply_above_4096_bytes_is_refused_by_the_library_as_a_transport_error() -> None:
    peer = Peer(reply=json.dumps({"op": "auth", "success": True, "pad": "x" * 4096}))
    async with asyncio.timeout(_DEADLINE_S), peer.serving() as url:
        assert await probe(url) == FAILED
    assert len(peer.frames) == 1


async def test_a_root_only_the_os_store_trusts_never_sees_the_signed_auth(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C-2.7 and C-12.2, defence in depth: a TLS-inspecting gateway's root in the OS store (here
    through `SSL_CERT_FILE`, which OpenSSL's default store reads) lets the library's default dial
    finish its handshake; production's connector trusts certifi's roots only, so its handshake
    fails before any frame."""
    root, served = _issue(tmp_path)
    monkeypatch.setenv("SSL_CERT_FILE", str(root))
    peer = Peer()
    async with asyncio.timeout(_DEADLINE_S), peer.serving(served) as url:
        async with connect(url):  # the OS store trusts the stream
            pass
        assert await probe(url) == FAILED
    assert (peer.handshakes, peer.frames) == (1, [])


async def test_a_proxy_the_environment_names_never_carries_the_dial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.7 and C-12.2, defence in depth: with `HTTPS_PROXY` set, the library's default dial
    goes through that proxy (`ws://` takes it as well); production's connector dials the stream
    itself, so no proxy sees the signed `auth`."""
    for name in [name for name in os.environ if name.lower().endswith("_proxy")]:
        monkeypatch.delenv(name)
    proxy, peer = Proxy(), Peer()
    async with asyncio.timeout(_DEADLINE_S), proxy.listening() as via, peer.serving() as url:
        monkeypatch.setenv("HTTPS_PROXY", via)
        assert get_proxy(parse_uri(url)) == via  # the proxy the library's default dial takes
        assert await probe(url) == GRANTED
    assert (proxy.asked, peer.handshakes, len(peer.frames)) == (0, 1, 1)

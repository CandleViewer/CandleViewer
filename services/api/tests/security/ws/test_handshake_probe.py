"""E17-X02 slice j (#415, threat model `E17-ws-gateway.md` §7, AC-22 to AC-25): the local equivalent
of a DAST pass over the handshake. Raw sockets send real upgrade requests and frames to the E17-Q02
chaos rig's gateway on a real uvicorn server (production WS settings, 127.0.0.1 only). Behind every
refusal before `accept`, the gateway's `accept`, the authenticator and the connection registry never
ran; a socket admitted and then closed made no authenticator call and wrote no audit row. No sleeps,
every wait bounded. #2176 (WS-D14) is merged, as #3890: its request-header deadline closes AC-25's
two partial requests after 10 s with nothing sent, and a header line over 8 KiB gets 431 at once.
No test here waits for the 10 s (the tests of #3890 do). The staging ZAP pass and the TLS check are
not run here (slice i records them).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import email
import json
import tracemalloc
import zlib
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from email.message import Message
from typing import Any

import msgpack
import pytest
from fastapi import APIRouter
from starlette.websockets import WebSocket
from websockets.frames import Frame, Opcode

from candleviewer.api.csrf import RefusalAuditTracker
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.origin_audit import OriginRefusalAudit
from tests.chaos.ingestion._clock import VirtualClock
from tests.chaos.ws import _server
from tests.chaos.ws._client import TIMEOUT_S
from tests.chaos.ws._proxy import HOST
from tests.chaos.ws._server import Stack
from tests.contract.ws._support import ORIGIN
from tests.security.auth._stack import RegistryAudit
from tests.security.ws._raw import delta
from tests.unit.ws._seq_support import ACC_A, ACC_B

Change = Mapping[str, str | None]  # header edits: a value replaces, None drops
Streams = tuple[asyncio.StreamReader, asyncio.StreamWriter]
J, M = "cv.v1.json", "cv.v1.msgpack"
FOREIGN = "https://evil.example"
GOOD = {  # a valid upgrade to `cv.v1.json` from the listed origin
    "Host": HOST,
    "Upgrade": "websocket",
    "Connection": "Upgrade",
    "Origin": ORIGIN,
    "Sec-WebSocket-Key": base64.b64encode(b"x02-probe-key-16").decode(),
    "Sec-WebSocket-Version": "13",
    "Sec-WebSocket-Protocol": J,
}
DEFLATE = "Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits"
HELLO = json.dumps({"t": "hello", "id": "h"}).encode()
CAP = (256 + 4) * 1024  # §3.6, §4.4: the inbound cap plus 4 KiB, applied to the inflated message
CAP_BEFORE_AUTH = 8 * 1024  # §3.6: the inbound cap until `auth_ok`


def request(change: Change | None = None, *extra: str) -> bytes:
    """`GOOD` with `change` applied, then the `extra` header lines as given (a repeated header)."""
    lines = [f"{k}: {v}" for k, v in {**GOOD, **(change or {})}.items() if v is not None]
    return ("GET /ws HTTP/1.1\r\n" + "\r\n".join([*lines, *extra]) + "\r\n\r\n").encode("latin-1")


async def answer(reader: asyncio.StreamReader) -> tuple[int, Message]:
    """The status and headers of the server's answer to an upgrade."""
    async with asyncio.timeout(TIMEOUT_S):
        head = await reader.readuntil(b"\r\n\r\n")
    status, _, fields = head.decode("latin-1").partition("\r\n")
    return int(status.split()[1]), email.message_from_string(fields)


def frame(opcode: Opcode, data: bytes, *, fin: bool = True, rsv1: bool = False) -> bytes:
    """One masked client frame; `rsv1` marks a compressed message (RFC 7692), set on the bytes
    because the library refuses to serialise a reserved bit without an extension."""
    raw = Frame(opcode, data, fin=fin).serialize(mask=True)
    return bytes([raw[0] | rsv1 << 6]) + raw[1:]


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """The server's next frame: its opcode and payload."""
    async with asyncio.timeout(TIMEOUT_S):
        b0, b1 = await reader.readexactly(2)
        size = b1 & 0x7F
        if size > 125:
            size = int.from_bytes(await reader.readexactly(2 if size == 126 else 8), "big")
        return b0 & 0x0F, await reader.readexactly(size)


async def until_close(reader: asyncio.StreamReader) -> tuple[list[int], int]:
    """The opcodes of the frames the server sent before its close frame, and the close code."""
    opcodes: list[int] = []
    while (got := await read_frame(reader))[0] != Opcode.CLOSE:
        opcodes.append(got[0])
    return opcodes, int.from_bytes(got[1][:2], "big")


def deflated(*parts: bytes) -> bytes:
    """The parts, joined, as one permessage-deflate message (RFC 7692 §7.2.1); fed part by part, in
    the window the server agrees (`client_max_window_bits=12`)."""
    co = zlib.compressobj(9, zlib.DEFLATED, -12)
    packed = b"".join(co.compress(part) for part in parts) + co.flush(zlib.Z_SYNC_FLUSH)
    return packed.removesuffix(b"\x00\x00\xff\xff")


class Gateway:
    """The chaos rig's gateway on real uvicorn, and what a probe reads: every `accept` (with the
    subprotocol it chose), every token the authenticator was asked about, the audit rows, and the
    origin and subprotocol refusals counted since the start."""

    def __init__(self, stack: Stack, audit: RegistryAudit) -> None:
        self.stack, self.audit = stack, audit
        self.accepts: list[str | None] = []
        self.auth_calls: list[str] = []
        self.origin = delta("cv_ws_closes_total", reason="origin_forbidden")
        self.protocol = delta("cv_ws_closes_total", reason="unsupported_protocol")

    def untouched(self, origin: int = 0, protocol: int = 0) -> None:
        """Nothing past the transport ran: no `accept`, authenticator call or registered connection,
        and no audit row but an origin refusal's. The two refusals counted are as given."""
        assert (self.accepts, self.auth_calls, len(self.stack.gateway)) == ([], [], 0)
        assert {r["action"] for r in self.audit.records} <= {"auth.ws_origin_refused"}
        assert (self.origin(), self.protocol()) == (origin, protocol)

    @asynccontextmanager
    async def dial(self, payload: bytes) -> AsyncIterator[Streams]:
        reader, writer = await asyncio.open_connection(HOST, self.stack.port)
        try:
            writer.write(payload)
            yield reader, writer
        finally:
            writer.close()
            with contextlib.suppress(OSError, TimeoutError):
                async with asyncio.timeout(TIMEOUT_S):
                    await writer.wait_closed()

    async def refused(self, status: int, change: Change | None, *extra: str) -> None:
        """An upgrade the server answers with `status` and no `Sec-WebSocket-Accept`, then EOF."""
        async with self.dial(request(change, *extra)) as (reader, _):
            got, headers = await answer(reader)
            assert got == status and "sec-websocket-accept" not in headers  # a 101 fails here
            async with asyncio.timeout(TIMEOUT_S):
                await reader.read()

    @asynccontextmanager
    async def admitted(
        self, change: Change | None = None, *extra: str
    ) -> AsyncIterator[tuple[asyncio.StreamReader, asyncio.StreamWriter, Message]]:
        """An upgrade the server admits (101); on close, no authenticator call and no audit row."""
        async with self.dial(request(change, *extra)) as (reader, writer):
            status, headers = await answer(reader)
            assert status == 101
            yield reader, writer, headers
        await self.stack.until_no_connections()  # the server saw the close
        assert (self.auth_calls, self.audit.records) == ([], [])


@pytest.fixture
async def gateway(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Gateway]:
    audit = RegistryAudit()
    origin_audit = OriginRefusalAudit(audit, tracker=RefusalAuditTracker())
    listed = frozenset({ORIGIN, "null"})  # `null` is listed: §2.5 refuses it even so

    def router(**kw: Any) -> APIRouter:  # the rig's wiring, plus an audit sink and this allow-list
        kw |= {"audit": audit, "origin_audit": origin_audit, "allowed_origins": listed}
        return make_ws_router(**kw)

    monkeypatch.setattr(_server, "make_ws_router", router)
    async with Stack(VirtualClock(), ACC_A, ACC_B) as stack:
        gw = Gateway(stack, audit)
        authenticate, accept = stack.sessions.authenticate_access_token, WebSocket.accept

        async def spy_authenticate(token: str) -> Any:
            gw.auth_calls.append(token)
            return await authenticate(token)

        async def spy_accept(
            self: WebSocket, subprotocol: str | None = None, headers: Iterable[Any] | None = None
        ) -> None:
            gw.accepts.append(subprotocol)
            await accept(self, subprotocol, headers)

        monkeypatch.setattr(stack.sessions, "authenticate_access_token", spy_authenticate)
        monkeypatch.setattr(WebSocket, "accept", spy_accept)
        yield gw


def site(*values: str) -> tuple[str, ...]:
    return tuple(f"Sec-Fetch-Site: {v}" for v in values)


F: dict[str, str | None] = {"Origin": FOREIGN}
# The gateway's own refusal: HTTP 403, and one `auth.ws_origin_refused` row with this reason.
ORIGINS: dict[str, tuple[Change, tuple[str, ...], str]] = {
    "missing": ({"Origin": None}, (), "origin_missing"),
    "missing-same-origin": ({"Origin": None}, site("same-origin"), "origin_missing"),
    "null-though-listed": ({"Origin": "null"}, (), "origin_null"),
    "null-in-any-case": ({"Origin": "NuLL"}, (), "origin_null"),
    "foreign": (F, (), "origin_not_allowed"),
    "foreign-cross-site": (F, site("cross-site"), "cross_site"),
    "foreign-same-site": (F, site("same-site"), "cross_site"),
    "foreign-same-origin": (F, site("same-origin"), "origin_not_allowed"),
    "foreign-two-sites": (F, site("none", "cross-site"), "cross_site"),
    "foreign-no-subprotocol": (F | {"Sec-WebSocket-Protocol": None}, (), "origin_not_allowed"),
    "listed-in-upper-case": ({"Origin": ORIGIN.upper()}, (), "origin_not_allowed"),
    "listed-then-foreign-in-one": ({"Origin": f"{ORIGIN}, {FOREIGN}"}, (), "origin_not_allowed"),
    "name-in-odd-case": ({"Origin": None, "oRiGiN": FOREIGN}, (), "origin_not_allowed"),
}
# The allow-list decides: a listed origin is admitted whatever `Sec-Fetch-Site` says.
ADMITTED: dict[str, tuple[Change, tuple[str, ...]]] = {
    "cross-site": ({}, site("cross-site")),
    "same-origin": ({}, site("same-origin")),
    "trailing-slash": ({"Origin": ORIGIN + "/"}, ()),
    "name-in-odd-case": ({"Origin": None, "ORIGIN": ORIGIN}, ()),
}
# Refused before `accept`: (header edits, repeated lines, HTTP status, subprotocol refusals).
# The transport answers 400 before the gateway runs: a repeated `Origin` (§2.5 says 403), an empty
# or malformed subprotocol offer (§2.2 says 403). The gateway answers 403 for an unsupported offer.
REFUSED: dict[str, tuple[Change, tuple[str, ...], int, int]] = {
    "origin-repeated": ({}, (f"Origin: {ORIGIN}",), 400, 0),
    "origin-listed-then-foreign": ({}, (f"Origin: {FOREIGN}",), 400, 0),
    "origin-foreign-then-listed": (F, (f"Origin: {ORIGIN}",), 400, 0),
    "version-12": ({"Sec-WebSocket-Version": "12"}, (), 400, 0),
    "version-missing": ({"Sec-WebSocket-Version": None}, (), 400, 0),
    "key-missing": ({"Sec-WebSocket-Key": None}, (), 400, 0),
    "key-too-short": ({"Sec-WebSocket-Key": base64.b64encode(b"short").decode()}, (), 400, 0),
    "key-not-base64": ({"Sec-WebSocket-Key": "!!!not base64!!!"}, (), 400, 0),
    "subprotocol-empty": ({"Sec-WebSocket-Protocol": ""}, (), 400, 0),
    "subprotocol-space-inside": ({"Sec-WebSocket-Protocol": "cv.v1 .json"}, (), 400, 0),
    "subprotocol-none-offered": ({"Sec-WebSocket-Protocol": None}, (), 403, 1),
    "subprotocol-unknown": ({"Sec-WebSocket-Protocol": "cv.v2.json"}, (), 403, 1),
    "subprotocol-upper-case": ({"Sec-WebSocket-Protocol": "CV.V1.JSON"}, (), 403, 1),
    "subprotocol-msgpack-mixed-case": ({"Sec-WebSocket-Protocol": "Cv.V1.Msgpack"}, (), 403, 1),
    "subprotocol-prefix": ({"Sec-WebSocket-Protocol": "cv.v1"}, (), 403, 1),
}
# Offer's lines -> the one subprotocol echoed: the server's order decides, not the client's.
CHOSEN: dict[str, tuple[tuple[str, ...], str]] = {
    "json-twice": ((f"{J}, {J}",), J),
    "unknown-first": ((f"cv.v2.json, {J}",), J),
    "stray-commas": ((f",{J},",), J),
    "two-headers": (("cv.v2.json", J), J),
    "msgpack-only": ((M,), M),
    "json-then-msgpack": ((f"{J}, {M}",), M),
    "msgpack-then-json": ((f"{M}, {J}",), M),
    "two-headers-json-then-msgpack": ((J, M), M),
}
DEFLATES = {  # permessage-deflate offered with msgpack, in the forms a client may use (§3.5)
    "plain": (M, ("permessage-deflate",)),
    "behind-another-extension": (M, ("x-unknown", "permessage-deflate")),
}
PARTIAL = {  # AC-25: two requests cut short, and a complete one with a header line over 8 KiB
    "request-line-only": b"GET /ws HTTP/1.1\r\n",
    "cut-mid-header": request()[:60],
    "complete-request-one-header-line-over-8-KiB": request({"X-Pad": "a" * 9000}),
}


@pytest.mark.parametrize(("change", "extra", "reason"), ORIGINS.values(), ids=ORIGINS)
async def test_x02_ac_23_a_bad_origin_is_refused_before_accept_and_auth_never_runs(
    gateway: Gateway, change: Change, extra: tuple[str, ...], reason: str
) -> None:
    await gateway.refused(403, change, *extra)
    gateway.untouched(origin=1)
    rows = [(r["action"], r["reason"]) for r in gateway.audit.records]
    assert rows == [("auth.ws_origin_refused", reason)]


@pytest.mark.parametrize(("change", "extra"), ADMITTED.values(), ids=ADMITTED)
async def test_x02_ac_23_a_listed_origin_is_admitted_whatever_the_fetch_site(
    gateway: Gateway, change: Change, extra: tuple[str, ...]
) -> None:
    async with gateway.admitted(change, *extra):
        assert gateway.accepts == [J]
    assert (gateway.auth_calls, gateway.audit.records, gateway.origin()) == ([], [], 0)


@pytest.mark.parametrize(("change", "extra", "status", "protocol"), REFUSED.values(), ids=REFUSED)
async def test_x02_handshake_a_bad_request_or_subprotocol_is_refused_before_accept(
    gateway: Gateway, change: Change, extra: tuple[str, ...], status: int, protocol: int
) -> None:
    await gateway.refused(status, change, *extra)
    gateway.untouched(protocol=protocol)


@pytest.mark.parametrize(("offer", "chosen"), CHOSEN.values(), ids=CHOSEN)
async def test_x02_ac_22_one_subprotocol_is_echoed_by_the_servers_order_and_deflate_follows_it(
    gateway: Gateway, offer: tuple[str, ...], chosen: str
) -> None:
    first, *more = offer
    lines = [f"Sec-WebSocket-Protocol: {o}" for o in more]
    async with gateway.admitted({"Sec-WebSocket-Protocol": first}, *lines, DEFLATE) as (_, _, h):
        assert h.get_all("sec-websocket-protocol") == [chosen]  # exactly one
        assert ("sec-websocket-extensions" in h) is (chosen == J)  # §3.5: JSON only
    assert (gateway.accepts, gateway.auth_calls) == ([chosen], [])


@pytest.mark.parametrize(("protocols", "offers"), DEFLATES.values(), ids=DEFLATES)
async def test_x02_ac_22_deflate_is_never_agreed_with_msgpack_and_a_compressed_frame_is_refused(
    gateway: Gateway, protocols: str, offers: tuple[str, ...]
) -> None:
    lines = [f"Sec-WebSocket-Extensions: {o}" for o in offers]
    async with gateway.admitted({"Sec-WebSocket-Protocol": protocols}, *lines) as (r, w, h):
        assert h.get_all("sec-websocket-protocol") == [M] and "sec-websocket-extensions" not in h
        # A really compressed `hello`: an agreed extension would inflate it and answer.
        w.write(frame(Opcode.BINARY, deflated(msgpack.packb({"t": "hello"})), rsv1=True))
        assert await until_close(r) == ([], 1002)  # no extension, so the reserved bit is an error


@pytest.mark.parametrize(
    ("wire", "opcode", "payload"),
    [(M, Opcode.TEXT, HELLO), (J, Opcode.BINARY, msgpack.packb({"t": "hello"}))],
    ids=["first-frame-text-on-msgpack", "first-frame-binary-on-json"],
)
async def test_x02_ac_22_a_first_frame_of_the_other_wire_is_a_protocol_violation(
    gateway: Gateway, wire: str, opcode: Opcode, payload: bytes
) -> None:
    """Before `hello` (§4.2). After it, a frame of the other kind is a `frame_malformed` strike
    (§3.6): `tests/unit/ws/test_json_decode_bounds.py` and `test_msgpack_socket.py` pin that."""
    async with gateway.admitted({"Sec-WebSocket-Protocol": wire}) as (reader, writer, _):
        writer.write(frame(opcode, payload))
        bye = Opcode.BINARY if wire == M else Opcode.TEXT  # in the wire's own kind
        assert await until_close(reader) == ([bye], 1002)


@pytest.mark.parametrize(
    ("inflated", "before_close"),
    [(64 << 20, []), (CAP, [Opcode.TEXT]), (CAP + 1, [])],
    ids=["64-MiB", "at-the-cap", "one-byte-over"],
)
async def test_x02_ac_24_the_transport_cap_counts_the_inflated_message_and_stops_the_inflation(
    gateway: Gateway, inflated: int, before_close: list[int]
) -> None:
    head, tail = b'{"t":"hello","id":"', b'"}'
    pad = inflated - len(head + tail)
    chunks = [bytes([104]) * (1 << 20)] * (pad >> 20) + [bytes([104]) * (pad & ((1 << 20) - 1))]
    message = frame(Opcode.TEXT, deflated(head, *chunks, tail), rsv1=True)  # never held inflated
    async with gateway.admitted({}, DEFLATE) as (reader, writer, h):
        assert "sec-websocket-extensions" in h
        with contextlib.ExitStack() as tracing:
            if not tracemalloc.is_tracing():  # an outer tracer keeps running, and is read from
                tracemalloc.start()
                tracing.callback(tracemalloc.stop)
            tracemalloc.reset_peak()
            base = tracemalloc.get_traced_memory()[0]
            writer.write(message)
            result = await until_close(reader)
            peak = tracemalloc.get_traced_memory()[1]
    # §4.4: the transport admits exactly 260 KiB and the gateway answers with its limit before
    # `auth_ok` (a `bye`, then 1009); one byte over, the transport closes first, with no `bye`.
    assert result == (before_close, 1009)
    assert peak - base < 2 << 20  # the inflation stopped at the cap: a full one is 64 MiB


async def test_x02_ac_24_a_message_in_many_small_fragments_is_reassembled_and_served(
    gateway: Gateway,
) -> None:
    async with gateway.admitted() as (reader, writer, _):
        for i in range(len(HELLO)):  # one byte per frame
            opcode = Opcode.TEXT if i == 0 else Opcode.CONT
            writer.write(frame(opcode, HELLO[i : i + 1], fin=i == len(HELLO) - 1))
        assert json.loads((await read_frame(reader))[1])["t"] == "welcome"


async def test_x02_ac_24_fragments_past_the_cap_are_refused_without_waiting_for_the_last(
    gateway: Gateway,
) -> None:
    async with gateway.admitted() as (reader, writer, _):
        for i in range(CAP // 1024 + 1):  # 1 KiB over the cap; no last fragment
            writer.write(frame(Opcode.TEXT if i == 0 else Opcode.CONT, bytes(1024), fin=False))
        assert await until_close(reader) == ([], 1009)


async def test_x02_ac_24_the_gateway_limit_counts_the_reassembled_message(gateway: Gateway) -> None:
    half = CAP_BEFORE_AUTH // 2  # 8 KiB + 1 byte before `auth`, in three fragments
    async with gateway.admitted() as (reader, writer, _):
        writer.write(frame(Opcode.TEXT, bytes(half), fin=False))
        writer.write(frame(Opcode.CONT, bytes(half), fin=False) + frame(Opcode.CONT, b"x"))
        opcode, data = await read_frame(reader)
        assert (opcode, json.loads(data)["p"]["reason"]) == (Opcode.TEXT, "frame_too_big")
        assert await until_close(reader) == ([], 1009)


@pytest.mark.parametrize("partial", PARTIAL.values(), ids=PARTIAL)
async def test_x02_ac_25_partial_upgrades_hold_no_gateway_state_and_leave_a_real_client_served(
    gateway: Gateway, partial: bytes
) -> None:
    async with contextlib.AsyncExitStack() as held:
        for _ in range(8):
            await held.enter_async_context(gateway.dial(partial))
        async with gateway.admitted() as (reader, writer, _):
            writer.write(frame(Opcode.TEXT, HELLO))
            assert json.loads((await read_frame(reader))[1])["t"] == "welcome"
            assert len(gateway.stack.gateway) == 1  # only the real client is registered
    assert (gateway.accepts, gateway.auth_calls, gateway.audit.records) == ([J], [], [])

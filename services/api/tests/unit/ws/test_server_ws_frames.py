"""#2176 (WS-D13, WS-D14): `CvWebSocketsProtocol` in memory, built as uvicorn's HTTP protocol builds
it on an upgrade (the production `uvicorn_kwargs()` config, keyword arguments), on a transport
that keeps what the server writes. Frames are the client's, masked. One test per bound on a
fragmented message, the inbound queue's bound, the server's close, and a request websockets refuses
or that never completes. Every wait is bounded by `asyncio.timeout`; no sleeps."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import uvicorn
from prometheus_client import REGISTRY
from uvicorn.server import ServerState
from websockets.frames import Close, CloseCode, Frame, Opcode

from candleviewer.server import CvWebSocketsProtocol, uvicorn_kwargs
from candleviewer.ws.lifecycle import RATE_PER_SECOND, PongBudget
from candleviewer.ws.limits import (
    MAX_INBOUND_FRAME_BYTES,
    SERVER_READ_HEADER_TIMEOUT_S,
    SERVER_WS_MAX_SIZE,
    WS_FRAGMENT_OVERHEAD_BYTES,
    WS_INBOUND_FRAME_BURST,
    WS_MAX_FRAGMENTS_PER_MESSAGE,
    WS_MAX_QUEUED_MESSAGES,
)
from tests.unit.ws.test_request_header_deadline_real_socket import PAST_LIMITS, too_big, upgrade

N = WS_MAX_FRAGMENTS_PER_MESSAGE
#: A `ws_max_size` that the per-fragment charge reaches well before `N` fragments.
SMALL = 2_000
REFUSED = {"type": "websocket.disconnect", "code": 1009}
_BOUND_S = 10.0


class _Transport(asyncio.Transport):
    """Keeps what the server writes; `is_closing()` once it closes; `reading` unless paused. Its
    close never drains unless `drains`: then the protocol (`owner`) is told it is lost, once, as a
    real transport tells it."""

    def __init__(self, drains: bool = False) -> None:
        super().__init__()
        self.written = bytearray()
        self.closed = asyncio.Event()
        self.aborted = asyncio.Event()
        self.reading = True
        self.drains, self.drained = drains, asyncio.Event()
        self.owner: asyncio.BaseProtocol | None = None

    def write(self, data: bytes | bytearray | memoryview) -> None:
        self.written += data

    def close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        if self.drains and self.owner is not None:
            asyncio.get_running_loop().call_soon(self._drain, self.owner)

    def _drain(self, owner: asyncio.BaseProtocol) -> None:
        owner.connection_lost(None)
        self.drained.set()

    def abort(self) -> None:
        self.aborted.set()
        self.closed.set()

    def is_closing(self) -> bool:
        return self.closed.is_set()

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return ("127.0.0.1", 50000) if name in ("peername", "sockname") else default

    def pause_reading(self) -> None:
        self.reading = False

    def resume_reading(self) -> None:
        self.reading = True

    def set_protocol(self, protocol: asyncio.BaseProtocol) -> None:
        self.protocol = protocol


class _App:
    """Accepts, then hands on what it receives, where the gateway would read it."""

    def __init__(self) -> None:
        self.accepted = asyncio.Event()
        self.received: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await receive()  # `websocket.connect`
        await send({"type": "websocket.accept"})
        self.accepted.set()
        while True:
            message = await receive()
            self.received.put_nowait(message)
            if message["type"] == "websocket.disconnect":
                return


def _protocol(
    app: _App, max_size: int, header_timeout_s: float = SERVER_READ_HEADER_TIMEOUT_S
) -> tuple[CvWebSocketsProtocol, _Transport]:
    config = uvicorn.Config(app, **{**uvicorn_kwargs(), "ws_max_size": max_size, "lifespan": "off"})
    config.load()
    proto = CvWebSocketsProtocol(
        config=config, server_state=ServerState(), app_state={}, header_timeout_s=header_timeout_s
    )
    transport = _Transport()
    proto.connection_made(transport)
    return proto, transport


@asynccontextmanager
async def _opened(
    app: _App, max_size: int
) -> AsyncIterator[tuple[CvWebSocketsProtocol, _Transport]]:
    """Upgraded and accepted; dropped at the end, which ends the app."""
    proto, transport = _protocol(app, max_size)
    proto.data_received(upgrade())
    await app.accepted.wait()
    try:
        yield proto, transport
    finally:
        proto.connection_lost(None)
        await asyncio.gather(*proto.tasks)


def _message(
    count: int,
    payload: bytes,
    opcode: Opcode = Opcode.TEXT,
    fin: bool = True,
    last: bytes | None = None,
) -> bytes:
    """A message in `count` fragments of `payload` (`last` in the last one, if given): a first
    frame, then continuation frames, the last one final unless `fin` is False."""
    frames = (
        Frame(
            Opcode.CONT if i else opcode,
            last if last is not None and i == count - 1 else payload,
            fin=fin and i == count - 1,
        )
        for i in range(count)
    )
    return b"".join(frame.serialize(mask=True) for frame in frames)


async def _outcome(
    count: int, payload: bytes, max_size: int, last: bytes | None = None
) -> tuple[dict[str, Any], int | None, int]:
    """What the app receives for a message of `count` fragments, the close code the server sent
    (None: the socket is still open), and how many of the message's fragments it keeps."""
    app = _App()
    async with asyncio.timeout(_BOUND_S), _opened(app, max_size) as (proto, transport):
        proto.data_received(_message(count, payload, last=last))
        received = await app.received.get()
        sent = proto.conn.close_sent if transport.is_closing() else None
        kept = len(proto.frames)
    return received, None if sent is None else sent.code, kept


@pytest.mark.parametrize("payload", [b"x", b""], ids=["one-byte", "zero-length"])
async def test_a_message_of_64_fragments_is_read_and_one_of_65_is_refused(payload: bytes) -> None:
    """The refused message's 64 buffered fragments are let go of with the close."""
    read = {"type": "websocket.receive", "text": (payload * N).decode()}
    assert await _outcome(N, payload, SERVER_WS_MAX_SIZE) == (read, None, 0)
    counted = too_big()
    assert await _outcome(N + 1, payload, SERVER_WS_MAX_SIZE) == (REFUSED, 1009, 0)
    assert too_big() == counted + 1


@pytest.mark.parametrize("payload", [b"x", b""], ids=["one-byte", "zero-length"])
async def test_each_fragment_is_charged_against_the_size_cap(payload: bytes) -> None:
    """websockets alone counts `count + 1` such fragments as a few bytes at most."""
    count = SMALL // (len(payload) + WS_FRAGMENT_OVERHEAD_BYTES)  # the most that fit
    assert count < N
    assert (await _outcome(count, payload, SMALL))[1] is None
    counted = too_big()
    assert await _outcome(count + 1, payload, SMALL) == (REFUSED, 1009, 0)
    assert too_big() == counted + 1


async def test_a_message_at_the_gateway_cap_in_64_fragments_fills_the_size_cap_exactly() -> None:
    """64 fragments of 4 KiB, the gateway's cap, plus 64 B charged for each, are `ws_max_size`
    to the byte and are read; one byte more in the last fragment is refused."""
    payload = b"x" * (MAX_INBOUND_FRAME_BYTES // N)
    assert N * (len(payload) + WS_FRAGMENT_OVERHEAD_BYTES) == SERVER_WS_MAX_SIZE
    read = {"type": "websocket.receive", "text": (payload * N).decode()}
    assert await _outcome(N, payload, SERVER_WS_MAX_SIZE) == (read, None, 0)
    longer = await _outcome(N, payload, SERVER_WS_MAX_SIZE, last=payload + b"x")
    assert longer == (REFUSED, 1009, 0)


@pytest.mark.parametrize("opcode", [Opcode.TEXT, Opcode.BINARY], ids=["text", "binary"])
async def test_data_frames_after_the_servers_close_are_not_buffered(opcode: Opcode) -> None:
    """Read at once, queue or not: the client's close then ends the closing handshake."""
    async with asyncio.timeout(_BOUND_S), _opened(_App(), SERVER_WS_MAX_SIZE) as (proto, transport):
        await proto.send({"type": "websocket.close", "code": 1000})
        proto.data_received(_message(N, b"x", opcode, fin=False))
        assert proto.frames == []
        assert not transport.is_closing()
        reply = Close(CloseCode.NORMAL_CLOSURE, "").serialize()
        proto.data_received(Frame(Opcode.CLOSE, reply).serialize(mask=True))
        assert transport.is_closing()


@pytest.mark.parametrize(
    ("request_bytes", "status"), PAST_LIMITS, ids=["header-line", "header-count", "request-line"]
)
async def test_a_request_past_the_websocket_request_limits_is_refused_at_once(
    request_bytes: bytes, status: int
) -> None:
    """uvicorn's own class sends nothing and keeps the socket open: no deadline is involved. Each
    request of `PAST_LIMITS` is answered with websockets' status and the transport is closed after
    it; on a real socket the answer can be lost to a reset, so only here is each status asserted
    (`test_request_header_deadline_real_socket.py`). Its server shutdown then only closes
    (uvicorn's would answer 500 after the 431 and raise)."""
    proto, transport = _protocol(_App(), SERVER_WS_MAX_SIZE)
    proto.data_received(request_bytes)
    assert transport.is_closing()
    assert transport.written.startswith(f"HTTP/1.1 {status} ".encode())
    proto.shutdown()
    proto.connection_lost(None)


async def test_a_request_still_incomplete_at_the_deadline_is_closed_unanswered() -> None:
    proto, transport = _protocol(_App(), SERVER_WS_MAX_SIZE, header_timeout_s=0.05)
    proto.data_received(upgrade()[:-2])  # no blank line after the headers
    async with asyncio.timeout(_BOUND_S):
        await transport.closed.wait()
    assert transport.written == b""


async def test_a_read_past_the_queue_bound_queues_the_bound_and_loses_no_message() -> None:
    """The inbound message queue is bounded: of one read of three times `WS_MAX_QUEUED_MESSAGES`
    messages it queues that many and holds the rest unparsed, reading paused. As the app reads the
    queue to empty, the rest follow, in parts of the bound, and none is lost."""
    app, count = _App(), 3 * WS_MAX_QUEUED_MESSAGES
    async with asyncio.timeout(_BOUND_S), _opened(app, SERVER_WS_MAX_SIZE) as (proto, transport):
        proto.frame_budget = PongBudget(per_second=1, burst=count)  # the queue's bound alone
        proto.data_received(_message(1, b"") * count)  # 6 bytes each: the smallest client frame
        assert proto.queue.qsize() == WS_MAX_QUEUED_MESSAGES
        assert proto.unread and not transport.reading
        received = [await app.received.get() for _ in range(count)]
        assert received == [{"type": "websocket.receive", "text": ""}] * count
        assert not proto.unread and transport.reading


async def test_frames_that_come_before_the_app_reads_the_upgrade_wait_with_reading_paused() -> None:
    """The queue holds the upgrade's `websocket.connect` until the app reads it: a frame that
    comes first is held unparsed, reading paused, and read once the app has read the upgrade."""
    app = _App()
    proto, transport = _protocol(app, SERVER_WS_MAX_SIZE)
    proto.data_received(upgrade())
    proto.data_received(_message(1, b"x"))  # before the app has run
    assert proto.queue.qsize() == 1 and proto.unread and not transport.reading
    async with asyncio.timeout(_BOUND_S):
        assert await app.received.get() == {"type": "websocket.receive", "text": "x"}
        assert not proto.unread and transport.reading
        proto.connection_lost(None)
        await asyncio.gather(*proto.tasks)


def _frame(opcode: Opcode) -> bytes:
    return Frame(opcode, b"").serialize(mask=True)


def too_fast() -> float:
    """`cv_ws_closes_total{reason="client_rate_limited"}`."""
    return REGISTRY.get_sample_value("cv_ws_closes_total", {"reason": "client_rate_limited"}) or 0.0


@pytest.mark.parametrize(
    "opcode",
    [Opcode.PING, Opcode.PONG, Opcode.TEXT, Opcode.BINARY],
    ids=["ping", "pong", "text", "binary"],
)
async def test_frames_past_the_frame_budget_close_the_connection_4429(opcode: Opcode) -> None:
    """Every frame takes a token, whatever its opcode or payload; past the burst the connection is
    closed as the gateway's `client_rate_limited` is, counted, with no `bye`."""
    counted = too_fast()
    async with asyncio.timeout(_BOUND_S), _opened(_App(), SERVER_WS_MAX_SIZE) as (proto, transport):
        proto.data_received(_frame(opcode) * (2 * WS_INBOUND_FRAME_BURST))
        assert transport.is_closing()
        assert proto.conn.close_sent is not None and proto.conn.close_sent.code == 4429
    assert too_fast() == counted + 1


async def test_each_continuation_frame_takes_a_token() -> None:
    """With a budget of 5, a message's first frame and 4 continuation frames are read, and the
    next continuation frame closes the connection `4429`, long before the fragment cap."""
    async with asyncio.timeout(_BOUND_S), _opened(_App(), SERVER_WS_MAX_SIZE) as (proto, transport):
        proto.frame_budget = PongBudget(per_second=1, burst=5)
        proto.data_received(_message(11, b"x", fin=False))
        assert transport.is_closing()
        assert proto.conn.close_sent is not None and proto.conn.close_sent.code == 4429


async def test_a_client_within_the_inbound_rate_is_never_refused() -> None:
    """30 messages a second for a minute (more than the gateway's limiter lets through: 30/s and
    300/min), each second at once, with a ping, and the pong to the server's ping every 15 s. The
    clock is the test's, in place of the loop's that the protocol reads."""
    app, now = _App(), [0.0]
    async with asyncio.timeout(_BOUND_S), _opened(app, SERVER_WS_MAX_SIZE) as (proto, transport):
        assert proto.frame_clock == proto.loop.time
        proto.frame_clock = lambda: now[0]
        for second in range(60):
            now[0] = float(second)
            pong = _frame(Opcode.PONG) if second % 15 == 0 else b""
            proto.data_received(_message(1, b"x") * RATE_PER_SECOND + _frame(Opcode.PING) + pong)
            for _ in range(RATE_PER_SECOND):
                assert (await app.received.get())["type"] == "websocket.receive"
        assert not transport.is_closing()


async def test_pings_under_write_pressure_get_one_pong_for_the_latest_once_it_drains() -> None:
    """While the transport's write buffer is over its high-water mark, the client's pings get one
    pong, for the latest (RFC 6455 §5.5.3), once it drains. Reading goes on, so a client whose
    reads stall still gets its own heartbeats read (§9.1)."""
    app = _App()
    async with asyncio.timeout(_BOUND_S), _opened(app, SERVER_WS_MAX_SIZE) as (proto, transport):
        proto.pause_writing()
        sent = len(transport.written)
        pings = b"".join(Frame(Opcode.PING, n).serialize(mask=True) for n in (b"1", b"2", b"3"))
        proto.data_received(pings + _message(1, b"x"))
        assert len(transport.written) == sent
        assert await app.received.get() == {"type": "websocket.receive", "text": "x"}
        assert transport.reading
        proto.resume_writing()
        pong = Frame(Opcode.PONG, b"3").serialize(mask=False)
        assert transport.written[sent:] == pong
        proto.pause_writing()
        proto.resume_writing()  # a second drain: nothing is held, so nothing more is sent
        assert transport.written[sent:] == pong

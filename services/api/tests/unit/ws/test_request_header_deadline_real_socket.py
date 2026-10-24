"""#2176 (WS-D14, WS-D13): the request line and headers deadline, and the fragment cap, on a real
uvicorn server built from the production `uvicorn_kwargs()` (`limit_concurrency` unchanged) and
serving `create_app`, as `test_planned_shutdown_real_socket.py` does. Both protocol classes get a
0.2 s deadline through their `header_timeout_s` parameter (two tests keep the production 10 s),
and where a test says so a 0.2 s drain bound through `drain_timeout_s`. A test waits for a
deadline by waiting for the server to close a socket, and for the drain bound by waiting for the
server's protocol to lose its connection: no sleeps, and every wait is bounded by
`asyncio.timeout`. No network beyond 127.0.0.1."""

from __future__ import annotations

import asyncio
import base64
import functools
import json
import logging
import socket
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

import pytest
import uvicorn
from prometheus_client import REGISTRY
from uvicorn.server import ServerState
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.http11 import MAX_LINE_LENGTH, MAX_NUM_HEADERS
from websockets.typing import Origin, Subprotocol

from candleviewer.app import create_app
from candleviewer.server import CvHttpToolsProtocol, uvicorn_kwargs
from candleviewer.ws.limits import (
    SERVER_CLOSE_DRAIN_TIMEOUT_S,
    SERVER_LIMIT_CONCURRENCY,
    SERVER_READ_HEADER_TIMEOUT_S,
    WS_MAX_FRAGMENTS_PER_MESSAGE,
)
from tests.unit.ws.test_app_wiring import JSON, ORIGIN, _authenticate, _Kill, _settings

DEADLINE_S = 0.2
DRAIN_S = 0.2
SOCKETS = 300
#: An answer far larger than the kernel's buffers hold for a peer that reads none of it.
LARGE = 16 * 1024 * 1024
_BOUND_S = 30.0
#: How long a test waits for a close it expects soon. The upgrades test's window is its claim
#: (refused at once), so it must stay below `SERVER_READ_HEADER_TIMEOUT_S`.
_CLOSE_WAIT_S = 5.0
OK = b"HTTP/1.1 200 OK"
UNAUTHORIZED = b"HTTP/1.1 401 Unauthorized"
#: A request body far larger than the kernel's buffers hold, sent after the server has answered.
UPLOAD = 5_000_000
GET = b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
INCOMPLETE = b"GET /healthz HTTP/1.1\r\nHost: 127.0.0.1\r\n"  # no blank line after the headers
HELLO = {"t": "hello", "id": "h", "p": {"clock_ms": 1}}
_ORIGIN = Origin(ORIGIN)
_JSON = [Subprotocol(p) for p in JSON]


#: RFC 6455 §1.3's sample `Sec-WebSocket-Key` (the base64 of "the sample nonce"), built at import
#: so no key-shaped literal sits in the source.
_SAMPLE_KEY = base64.b64encode(b"the sample nonce").decode()


def upgrade(target: str = "/ws", extra: str = "") -> bytes:
    """A complete WebSocket upgrade request (it ends with the blank line)."""
    return (
        f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {_SAMPLE_KEY}\r\nSec-WebSocket-Version: 13\r\n{extra}\r\n"
    ).encode()


def too_big() -> float:
    """`cv_ws_closes_total{reason="frame_too_big"}`, the gateway's own refusal of a frame."""
    return REGISTRY.get_sample_value("cv_ws_closes_total", {"reason": "frame_too_big"}) or 0.0


#: Upgrades past websockets' request limits, which httptools reads and uvicorn hands on, and the
#: status websockets refuses each with: a header line, the header count, the request line.
PAST_LIMITS = (
    (upgrade(extra=f"X-Pad: {'a' * MAX_LINE_LENGTH}\r\n"), 431),
    (upgrade(extra="".join(f"X-{i}: v\r\n" for i in range(MAX_NUM_HEADERS))), 431),
    (upgrade(target=f"/ws?{'a' * MAX_LINE_LENGTH}"), 414),
)


@asynccontextmanager
async def _serve(
    app: Any = None,
    drain_timeout_s: float = SERVER_CLOSE_DRAIN_TIMEOUT_S,
    header_timeout_s: float = DEADLINE_S,
) -> AsyncIterator[tuple[int, ServerState]]:
    """The port and the state of a real uvicorn server running `app`, `create_app` by default."""
    if app is None:
        app = create_app(_settings(), snapshot_loader=_Kill().load, ws_authenticate=_authenticate)
    kw = uvicorn_kwargs()
    del kw["host"], kw["port"]  # the pre-bound loopback socket below
    for protocol in ("http", "ws"):
        kw[protocol] = functools.partial(
            kw[protocol], header_timeout_s=header_timeout_s, drain_timeout_s=drain_timeout_s
        )
    config = uvicorn.Config(app, lifespan="off", log_level="warning", **kw)
    config.load()
    server = uvicorn.Server(config)
    server.lifespan = config.lifespan_class(config)  # as `Server.serve` does before `startup`
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    await server.startup(sockets=[sock])
    try:
        yield sock.getsockname()[1], server.server_state
    finally:
        await server.shutdown(sockets=[sock])
        sock.close()


@asynccontextmanager
async def _sent(
    port: int, requests: list[bytes], resets: bool = False
) -> AsyncIterator[asyncio.Future[list[Any]]]:
    """A socket per request, the request sent as it connects (the server normally reads it long
    before the deadline, so its close is a FIN; see `resets`) and the socket left open: what each
    one reads until the server closes it. With `resets`, a socket's result is the exception that
    ended its read, a reset included, in place of what it read."""
    conns = []
    for request in requests:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(request)
        conns.append((reader, writer))
    reads = asyncio.gather(*(reader.read() for reader, _ in conns), return_exceptions=resets)
    try:
        yield reads
    finally:
        reads.cancel()
        for _, writer in conns:
            writer.close()


async def _answer(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, data: bytes = GET
) -> bytes:
    """Sends `data` on a kept-alive connection and reads one answer: its status line."""
    writer.write(data)
    head = await reader.readuntil(b"\r\n\r\n")
    await reader.readexactly(int(head.lower().split(b"content-length: ")[1].split(b"\r\n")[0]))
    return head.split(b"\r\n")[0]


async def _rest(port: int) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        return await _answer(reader, writer)
    finally:
        writer.close()


async def _echo(scope: dict[str, Any], receive: Any, send: Any) -> None:
    """Answers each request with its body, once all of it has arrived."""
    body, more = b"", True
    while more:
        message = await receive()
        body, more = body + message.get("body", b""), message.get("more_body", False)
    headers = [(b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _call(ws: ClientConnection, frame: dict[str, Any]) -> str:
    await ws.send(json.dumps(frame))
    reply: str = json.loads(await ws.recv())["t"]
    return reply


@pytest.mark.parametrize("request_bytes", [INCOMPLETE, b""], ids=["part-of-a-request", "nothing"])
async def test_300_incomplete_requests_are_closed_at_the_deadline_and_rest_answers(
    request_bytes: bytes,
) -> None:
    """More sockets than `limit_concurrency` admits, none of them done with its headers: they send
    part of a request, or nothing at all (the deadline then runs from the connection's opening).
    The deadline closes each, unanswered, and a REST call then succeeds. The test waits for every
    close before it calls REST, so a slow runner's late closes never meet REST (#4429); with no
    deadline nothing closes them, and the bound fails the test. A socket whose bytes the server
    has not read yet when its deadline closes it is reset, not ended: that is still a close, and an
    answer the client reads still fails the test. Sending nothing leaves nothing unread, so there
    only a FIN will do."""
    assert SOCKETS > SERVER_LIMIT_CONCURRENCY
    reset = ConnectionResetError if request_bytes else ()  # unread bytes are a reset's only cause
    async with (
        asyncio.timeout(_BOUND_S),
        _serve() as (port, _),
        _sent(port, [request_bytes] * SOCKETS, resets=True) as reads,
    ):
        closed = await reads  # each close ran the server's `connection_lost`: no slot is held
        assert await _rest(port) == OK
        assert [c for c in closed if c != b"" and not isinstance(c, reset)] == []


async def test_300_upgrades_past_the_websocket_request_limits_are_refused_at_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """uvicorn's own WebSocket class neither answers nor closes these; REST then answers 503. On
    the production deadline, only the refusal at once closes them in time. A reset can discard an
    answer before the client reads it, so a socket is refused when it read websockets' status or
    was reset, and asyncio logs no transport error; the status of each request is asserted in
    memory (`test_server_ws_frames.py`)."""
    caplog.set_level(logging.ERROR, logger="asyncio")
    cases = [PAST_LIMITS[i % len(PAST_LIMITS)] for i in range(SOCKETS)]
    async with (
        asyncio.timeout(_BOUND_S),
        _serve(header_timeout_s=SERVER_READ_HEADER_TIMEOUT_S) as (port, _),
        _sent(port, [request for request, _ in cases], resets=True) as reads,
    ):
        await asyncio.wait({reads}, timeout=_CLOSE_WAIT_S)
        assert await _rest(port) == OK
        ended = reads.result()
    for (_, status), answer in zip(cases, ended, strict=True):
        assert isinstance(answer, ConnectionResetError) or answer.startswith(
            f"HTTP/1.1 {status} ".encode()
        ), answer
    assert [r.getMessage() for r in caplog.records if r.name == "asyncio"] == []


async def test_a_kept_alive_connection_outlives_the_deadline_until_its_next_bytes() -> None:
    """Complete headers stop the deadline: the connection is still served once the deadline of a
    socket opened later has run out. The first bytes after a response start it again, even a
    bare CRLF, which llhttp skips."""
    async with asyncio.timeout(_BOUND_S), _serve() as (port, _):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            assert await _answer(reader, writer) == OK
            async with _sent(port, [INCOMPLETE]) as later:
                assert await later == [b""]
            assert await _answer(reader, writer) == OK
            writer.write(b"\r\n")
            assert await reader.read() == b""
        finally:
            writer.close()


async def test_a_request_whose_body_comes_after_the_deadline_is_answered_and_kept_alive() -> None:
    """Complete headers stop the deadline for the whole request: its body may come later, and the
    bytes of a request being answered start none."""
    async with asyncio.timeout(_BOUND_S), _serve(_echo) as (port, _):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(b"PUT / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 2\r\n\r\n")
            async with _sent(port, [INCOMPLETE]) as later:
                assert await later == [b""]
            assert await _answer(reader, writer, b"ok") == OK
            async with _sent(port, [INCOMPLETE]) as later:
                assert await later == [b""]
            assert await _answer(reader, writer) == OK
        finally:
            writer.close()


async def test_a_websocket_outlives_the_deadline_of_both_protocols() -> None:
    async with asyncio.timeout(_BOUND_S), _serve() as (port, _):
        url = f"ws://127.0.0.1:{port}/ws"
        async with connect(url, subprotocols=_JSON, origin=_ORIGIN) as ws:
            assert await _call(ws, HELLO) == "welcome"
            async with _sent(port, [INCOMPLETE]) as later:
                assert await later == [b""]
            auth = {"t": "auth", "id": "a", "p": {"access_token": "tok"}}
            assert await _call(ws, auth) == "auth_ok"


async def test_a_message_of_64_fragments_is_read_and_one_of_65_closes_1009() -> None:
    """The client sends each item as a frame, then an empty final continuation frame. The refusal
    is counted as the gateway counts its own `frame_too_big`, once."""
    hello, counted = json.dumps(HELLO), too_big()
    async with asyncio.timeout(_BOUND_S), _serve() as (port, _):
        url = f"ws://127.0.0.1:{port}/ws"
        async with connect(url, subprotocols=_JSON, origin=_ORIGIN, compression=None) as ws:
            await ws.send([hello, *[""] * (WS_MAX_FRAGMENTS_PER_MESSAGE - 2)])
            assert json.loads(await ws.recv())["t"] == "welcome"
            await ws.send([hello, *[""] * (WS_MAX_FRAGMENTS_PER_MESSAGE - 1)])
            with pytest.raises(ConnectionClosed) as exc:
                await ws.recv()
    assert exc.value.rcvd is not None and exc.value.rcvd.code == 1009
    assert too_big() == counted + 1


def _large(close: bool, answered: asyncio.Event) -> Any:
    """Answers with `LARGE` bytes in one piece, and `connection: close` if `close`."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        headers = [(b"content-length", b"%d" % LARGE)]
        if close:
            headers.append((b"connection", b"close"))
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b"x" * LARGE})
        answered.set()

    return app


async def _aborted_at_the_bound(ends: str) -> None:
    """A peer that reads nothing is sent `LARGE` bytes, and the connection is closed as `ends`
    says: its transport is aborted once `DRAIN_S` has passed, not before."""
    loop, answered = asyncio.get_running_loop(), asyncio.Event()
    app = _large(ends == "connection-close", answered)
    async with asyncio.timeout(_BOUND_S), _serve(app, DRAIN_S) as (port, state):
        with socket.socket() as peer:
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            peer.setblocking(False)
            await loop.sock_connect(peer, ("127.0.0.1", port))
            since = loop.time()  # before the request, so before the server's timer starts
            await loop.sock_sendall(peer, GET)
            await answered.wait()
            (conn,) = state.connections
            assert isinstance(conn, CvHttpToolsProtocol) and conn.flow.write_paused
            if ends == "peer-fin":
                peer.shutdown(socket.SHUT_WR)
            async with asyncio.timeout(_CLOSE_WAIT_S):
                await conn.flow.drain()  # writable again only at connection_lost: none is read
            assert loop.time() - since >= DRAIN_S / 2
            assert not state.connections


def _run_on(loop_kind: str, main: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Runs `main()` on asyncio's loop or on uvloop, which uvicorn's `loop="auto"` runs where it
    is installed."""
    if loop_kind == "asyncio":
        factory: Callable[[], asyncio.AbstractEventLoop] = asyncio.new_event_loop
    else:
        factory = pytest.importorskip("uvloop").new_event_loop
    with asyncio.Runner(loop_factory=factory) as runner:
        runner.run(main())


@pytest.mark.parametrize("ends", ["connection-close", "peer-fin"])
@pytest.mark.parametrize("loop_kind", ["asyncio", "uvloop"])
def test_a_connection_whose_peer_reads_nothing_is_aborted_at_the_drain_bound(
    loop_kind: str, ends: str
) -> None:
    """Closed by the server after a `connection: close` answer, or at the peer's FIN after an
    answer that keeps it alive, on asyncio's loop and on uvloop."""
    _run_on(loop_kind, functools.partial(_aborted_at_the_bound, ends))


async def _unauthorized(scope: dict[str, Any], receive: Any, send: Any) -> None:
    """Answers 401 at once, reading no body."""
    headers = [(b"content-length", b"0")]
    await send({"type": "http.response.start", "status": 401, "headers": headers})
    await send({"type": "http.response.body", "body": b""})


async def _answered_first(body: str) -> None:
    """A request answered 401 before its body has all come. The client sends all `UPLOAD` bytes of
    it, with the production deadline, and only then reads; or it reads the answer, then sends part
    of the body and no more."""
    loop = asyncio.get_running_loop()
    deadline_s = SERVER_READ_HEADER_TIMEOUT_S if body == "all-of-it" else DEADLINE_S
    head = b"POST / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: %d\r\n\r\n" % UPLOAD
    serving = _serve(_unauthorized, header_timeout_s=deadline_s)
    async with asyncio.timeout(_BOUND_S), serving as (port, _):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            if body == "all-of-it":
                writer.write(head)
                writer.write(b"x" * UPLOAD)
                await writer.drain()
                assert await _answer(reader, writer, b"") == UNAUTHORIZED
                assert await _answer(reader, writer) == UNAUTHORIZED  # the next request
            else:
                since = loop.time()  # before the answer, which starts the server's timer
                assert await _answer(reader, writer, head) == UNAUTHORIZED
                writer.write(b"x" * 1024)  # part of the body, and no more
                async with asyncio.timeout(_CLOSE_WAIT_S):
                    assert await reader.read() == b""
                assert loop.time() - since >= DEADLINE_S / 2
        finally:
            writer.close()


@pytest.mark.parametrize("body", ["all-of-it", "part-of-it"])
@pytest.mark.parametrize("loop_kind", ["asyncio", "uvloop"])
def test_a_client_that_sends_its_body_after_an_early_answer_reads_the_answer(
    loop_kind: str, body: str
) -> None:
    """The answer is delivered, on asyncio's loop and on uvloop. A client that sends all of a 5 MB
    body and only then reads gets the 401, not a reset, and its next request is answered. One that
    sends part of the body after the answer, and no more, is closed at the deadline, no sooner
    than half of it, with a clean end of input."""
    _run_on(loop_kind, functools.partial(_answered_first, body))

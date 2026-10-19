"""Server-layer limits equal the protocol constants (single source: ws/limits.py), and #2176's
bounds in the two protocol classes, built in memory as uvicorn builds them from the production
`uvicorn_kwargs()` config. Every wait is bounded by `asyncio.timeout`; no sleeps."""

from __future__ import annotations

import asyncio
import gc
import logging
import weakref
from collections.abc import Callable
from importlib.metadata import version
from typing import Any, cast

import pytest
import uvicorn
from pydantic import ValidationError
from uvicorn.server import ServerState

from candleviewer.server import APP, CvHttpToolsProtocol, CvWebSocketsProtocol, uvicorn_kwargs
from candleviewer.settings import Settings
from candleviewer.ws import limits
from candleviewer.ws.lifecycle import HEARTBEAT_INTERVAL_S, HEARTBEAT_TIMEOUT_S, RATE_PER_SECOND
from tests.unit.ws.test_request_header_deadline_real_socket import GET, upgrade
from tests.unit.ws.test_server_ws_frames import _App, _Transport

HEAD = limits.SERVER_MAX_REQUEST_HEAD_BYTES
LIMIT = limits.SERVER_LIMIT_CONCURRENCY
_BOUND_S = 10.0
_NO_BODY = (b"content-length", b"0")
_PUT = b"PUT / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: %d\r\n\r\n"
_CHUNKED = b"PUT / HTTP/1.1\r\nHost: 127.0.0.1\r\nTransfer-Encoding: chunked\r\n\r\n"


def test_server_config_matches_limits() -> None:
    cfg = uvicorn.Config(APP, **uvicorn_kwargs())
    assert cfg.ws_max_size == limits.MAX_INBOUND_FRAME_BYTES + limits.SERVER_WS_HEADROOM_BYTES
    assert limits.MAX_INBOUND_FRAME_BYTES < cfg.ws_max_size < 2 * limits.MAX_INBOUND_FRAME_BYTES
    assert cfg.ws_per_message_deflate is limits.SERVER_WS_PER_MESSAGE_DEFLATE
    assert cfg.ws is CvWebSocketsProtocol  # §3.5: deflate off for cv.v1.msgpack (server.py)
    assert cfg.http is CvHttpToolsProtocol  # #2176: the request line and headers deadline
    assert cfg.limit_concurrency == limits.SERVER_LIMIT_CONCURRENCY
    # SR-191: set where the other bounds are, though it is uvicorn's default.
    assert uvicorn_kwargs()["timeout_keep_alive"] == limits.SERVER_KEEP_ALIVE_TIMEOUT_S
    assert cfg.timeout_keep_alive == limits.SERVER_KEEP_ALIVE_TIMEOUT_S
    assert cfg.ws_ping_interval == HEARTBEAT_INTERVAL_S
    assert cfg.ws_ping_timeout == HEARTBEAT_TIMEOUT_S
    # #2275: uvicorn never reads `X-Forwarded-For`; MeshOnly's trusted proxy is the only reader.
    assert cfg.proxy_headers is False


def test_server_limits_are_not_library_defaults() -> None:
    cfg = uvicorn.Config(APP, **uvicorn_kwargs())
    assert cfg.ws_max_size != 16 * 1024 * 1024
    assert cfg.limit_concurrency is not None
    assert cfg.timeout_graceful_shutdown is not None  # uvicorn's own default is no bound (#2565)


def test_server_sets_no_setting_its_websocket_protocol_does_not_read() -> None:
    """#2176: `ws_max_queue` is read by uvicorn's legacy `ws="websockets"` protocol only."""
    assert "ws_max_queue" not in uvicorn_kwargs()


def test_fragment_charge_fits_the_headroom_at_the_gateway_cap() -> None:
    """A message the gateway accepts, in the most fragments allowed, is never refused for size."""
    charge = limits.WS_MAX_FRAGMENTS_PER_MESSAGE * limits.WS_FRAGMENT_OVERHEAD_BYTES
    assert limits.MAX_INBOUND_FRAME_BYTES + charge <= limits.SERVER_WS_MAX_SIZE


def test_the_2176_bounds_have_the_values_the_runbook_states() -> None:
    assert limits.SERVER_READ_HEADER_TIMEOUT_S == 10.0
    assert limits.SERVER_KEEP_ALIVE_TIMEOUT_S == 5
    assert limits.SERVER_MAX_REQUEST_HEAD_BYTES == 32 * 1024
    assert limits.WS_MAX_FRAGMENTS_PER_MESSAGE == 64
    assert limits.WS_FRAGMENT_OVERHEAD_BYTES == 64
    assert limits.WS_MAX_QUEUED_MESSAGES == 1024
    assert limits.WS_INBOUND_FRAMES_PER_S == 64
    assert limits.WS_INBOUND_FRAME_BURST == 256
    assert limits.SERVER_CLOSE_DRAIN_TIMEOUT_S == 5.0


def test_the_frame_budget_is_well_above_the_gateways_inbound_rate() -> None:
    """Twice its one-second burst, and room for that burst and a message in 64 fragments."""
    assert limits.WS_INBOUND_FRAMES_PER_S >= 2 * RATE_PER_SECOND
    assert limits.WS_INBOUND_FRAME_BURST > RATE_PER_SECOND + limits.WS_MAX_FRAGMENTS_PER_MESSAGE


async def _answer(send: Any, status: int) -> None:
    await send({"type": "http.response.start", "status": status, "headers": [_NO_BODY]})
    await send({"type": "http.response.body", "body": b""})


async def _ok(scope: Any, receive: Any, send: Any) -> None:
    """Accepts a WebSocket and reads it to its end; answers a request 200 once it is read."""
    if scope["type"] == "websocket":
        await _App()(scope, receive, send)
        return
    while (await receive()).get("more_body", False):
        pass
    await _answer(send, 200)


async def _early(scope: Any, receive: Any, send: Any) -> None:
    """Answers a request 401 before reading its body; accepts a WebSocket as `_ok` does."""
    if scope["type"] == "websocket":
        await _ok(scope, receive, send)
        return
    await _answer(send, 401)


class _Clock:
    """The HTTP deadline's clock in place of the loop's: `call_later` as the loop's, and the test
    moves it; `advance` runs each timer it reaches, in order, unless it is cancelled."""

    def __init__(self) -> None:
        self.now = 0.0
        self.timers: list[tuple[asyncio.TimerHandle, Callable[[], object]]] = []

    def call_later(self, delay: float, callback: Callable[[], object]) -> asyncio.TimerHandle:
        timer = asyncio.TimerHandle(self.now + delay, callback, (), asyncio.get_running_loop())
        self.timers.append((timer, callback))
        return timer

    def advance(self, seconds: float) -> None:
        self.now += seconds
        due = [t for t in self.timers if t[0].when() <= self.now]
        self.timers = [t for t in self.timers if t[0].when() > self.now]
        for timer, callback in sorted(due, key=lambda t: t[0].when()):
            if not timer.cancelled():
                callback()


def _built(
    kind: str,
    app: Any = _ok,
    state: ServerState | None = None,
    drain_timeout_s: float | None = None,
) -> CvHttpToolsProtocol | CvWebSocketsProtocol:
    """A protocol of the class the production config names, built as uvicorn builds it, on a
    server state of its own unless `state` is given, with the class's own drain bound unless
    `drain_timeout_s` is given."""
    config = uvicorn.Config(app, **{**uvicorn_kwargs(), "lifespan": "off"})
    config.load()
    cls = config.http_protocol_class if kind == "http" else config.ws_protocol_class
    assert cls is not None and issubclass(cls, (CvHttpToolsProtocol, CvWebSocketsProtocol))
    state = ServerState() if state is None else state
    if drain_timeout_s is None:
        return cls(config=config, server_state=state, app_state={})
    return cls(config=config, server_state=state, app_state={}, drain_timeout_s=drain_timeout_s)


def _http(app: Any = _ok, clock: _Clock | None = None) -> tuple[CvHttpToolsProtocol, _Transport]:
    """The HTTP class, its connection open, its deadline on `clock` if given."""
    proto, transport = _built("http", app), _Transport()
    assert isinstance(proto, CvHttpToolsProtocol)
    if clock is not None:
        proto.header_deadline.loop = cast(asyncio.AbstractEventLoop, clock)
    proto.connection_made(transport)
    return proto, transport


def _head(size: int, end: bytes = b"\r\n\r\n") -> bytes:
    """A request line and a padding header, `size` bytes with `end`, the end of the headers."""
    start = b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Pad: "
    return start + b"a" * (size - len(start) - len(end)) + end


async def _settled(proto: CvHttpToolsProtocol | CvWebSocketsProtocol) -> None:
    """Every request or WebSocket the app was handed has ended."""
    async with asyncio.timeout(_BOUND_S):
        await asyncio.gather(*list(proto.tasks))


@pytest.mark.parametrize("kind", ["http", "ws"])
async def test_each_protocol_arms_the_production_deadline_when_a_connection_opens(
    kind: str,
) -> None:
    proto = _built(kind)
    loop = asyncio.get_running_loop()
    before = loop.time()
    proto.connection_made(_Transport())
    after = loop.time()
    deadline, timeout_s = proto.header_deadline, limits.SERVER_READ_HEADER_TIMEOUT_S
    assert deadline.timeout_s == timeout_s
    assert deadline.timer is not None
    assert before + timeout_s <= deadline.timer.when() <= after + timeout_s
    assert proto.bounded.drain_timeout_s == limits.SERVER_CLOSE_DRAIN_TIMEOUT_S  # none injected
    proto.connection_lost(None)
    assert deadline.timer is None


@pytest.mark.parametrize(("kind", "head"), [("http", GET), ("ws", upgrade())], ids=["http", "ws"])
async def test_complete_headers_stop_the_deadline_in_each_protocol(kind: str, head: bytes) -> None:
    """`on_headers_complete` in the HTTP class, `handle_connect` in the WebSocket class."""
    proto = _built(kind)
    proto.connection_made(_Transport())
    proto.data_received(head)
    assert proto.header_deadline.timer is None
    proto.connection_lost(None)
    await _settled(proto)


@pytest.mark.parametrize("kind", ["http", "ws"])
async def test_a_lost_connections_protocol_is_freed_without_the_cyclic_gc(kind: str) -> None:
    """The deadline lets go of the protocol at `connection_lost`, as uvicorn's own classes are let
    go of then (uvicorn drops its parser there)."""
    proto = _built(kind)
    proto.connection_made(_Transport())
    proto.connection_lost(None)
    freed = weakref.ref(proto)
    gc.disable()
    try:
        del proto
        assert freed() is None
    finally:
        gc.enable()


@pytest.mark.parametrize(
    ("head", "rest"),
    [(_PUT % 100, b"x" * 9), (_PUT % 4, b"abcd" + GET[:5]), (_CHUNKED, b"1\r\nx\r\n")],
    ids=["body", "then-next-head", "chunked"],
)
async def test_an_early_answer_starts_the_deadline_for_the_rest_of_its_body(
    head: bytes, rest: bytes
) -> None:
    """A request answered before its body has all come, its length announced or chunked, gets its
    answer, and the rest of the body is read and let go of, as uvicorn's own classes do. The answer
    starts the deadline and no byte after it starts it again: with a byte a second of a body that
    never ends, or of the body and then the next request line, the connection is closed 10 s after
    the answer, through the drain bound."""
    clock = _Clock()
    proto, transport = _http(_early, clock)
    proto.data_received(head)
    await _settled(proto)
    assert transport.written.startswith(b"HTTP/1.1 401 ")
    for byte in rest:
        clock.advance(1.0)
        proto.data_received(bytes([byte]))
    clock.advance(9.5 - len(rest))
    assert not transport.is_closing()
    clock.advance(0.5)  # 10 s after the answer
    assert transport.is_closing() and proto.bounded.abort_timer is not None
    assert transport.written.count(b"HTTP/1.1 ") == 1
    assert not proto.cycle.body  # the body after the answer is let go of
    proto.connection_lost(None)


@pytest.mark.parametrize("head", [GET, upgrade()], ids=["request", "upgrade"])
async def test_an_early_answer_whose_body_and_next_head_come_in_time_keeps_the_connection(
    head: bytes,
) -> None:
    """The rest of the body comes 4 s after the answer, and the next request line and headers,
    complete, 5 s later: they stop the deadline, as any request's do. The request is answered, or
    the upgrade's WebSocket opened, and the deadline does not close the connection afterwards: the
    answer to a request whose body had all come starts none. (uvicorn's keep-alive timer, on the
    loop's clock, is not run here; on a server it closes an idle connection 5 s after the
    answer.)"""
    clock = _Clock()
    proto, transport = _http(_early, clock)
    proto.data_received(_PUT % 4)
    await _settled(proto)
    clock.advance(4.0)
    proto.data_received(b"abcd")
    clock.advance(5.0)
    proto.data_received(head)
    if head == GET:
        await _settled(proto)
        assert transport.written.count(b"HTTP/1.1 401 ") == 2
    else:
        assert isinstance(transport.protocol, CvWebSocketsProtocol)
    clock.advance(60.0)
    assert not transport.is_closing()
    assert proto.header_deadline.timer is None
    (proto if head == GET else transport.protocol).connection_lost(None)
    await _settled(proto)


async def test_a_request_pipelined_behind_an_answer_with_its_body_to_come_is_answered() -> None:
    """The deadline is for the request answered, not for one queued behind it: that one's body may
    come after the deadline would have run out, and it is answered, the connection kept alive."""
    first = asyncio.Event()

    async def app(scope: Any, receive: Any, send: Any) -> None:
        if scope["method"] == "GET":
            await first.wait()
        await _ok(scope, receive, send)

    clock = _Clock()
    proto, transport = _http(app, clock)
    proto.data_received(GET + _PUT % 2)
    first.set()
    await _settled(proto)  # the GET's answer, which starts the PUT's request
    clock.advance(60.0)
    proto.data_received(b"ok")
    await _settled(proto)
    assert transport.written.count(b"HTTP/1.1 200 ") == 2
    assert not transport.is_closing()
    proto.connection_lost(None)


@pytest.mark.parametrize("reads", [1, 2], ids=["one-read", "two-reads"])
async def test_each_request_of_a_kept_alive_connection_has_its_own_32_kib(reads: int) -> None:
    """12 requests of 3 000 bytes, 36 000 in all, each in `reads` reads, on one connection: each
    is answered, and the connection is kept alive."""
    proto, transport = _http()
    head, size = _head(3000), 3000 // reads
    for answered in range(1, 13):
        for at in range(0, len(head), size):
            proto.data_received(head[at : at + size])
        await _settled(proto)
        assert transport.written.count(b"HTTP/1.1 200 ") == answered
        assert not transport.is_closing()
    proto.connection_lost(None)


async def test_bytes_while_a_response_is_in_flight_start_no_deadline() -> None:
    """So the deadline never runs out while uvicorn's `shutdown` would wait for a response: a
    request begun while the one before it is answered starts it once that answer is complete."""
    answer = asyncio.Event()

    async def slow(scope: Any, receive: Any, send: Any) -> None:
        await answer.wait()
        await _answer(send, 200)

    proto, _ = _http(slow)
    for data in (GET + b"GE", b"T"):  # the next request, begun during the answer
        proto.data_received(data)
        assert proto.header_deadline.timer is None
    answer.set()
    await _settled(proto)
    proto.data_received(b" ")
    assert proto.header_deadline.timer is not None
    proto.connection_lost(None)


@pytest.mark.parametrize("piece", [HEAD + 1, 1000], ids=["one-read", "reads-of-1000-bytes"])
@pytest.mark.parametrize(("size", "status"), [(HEAD, 200), (HEAD + 1, 400)], ids=["32-kib", "over"])
async def test_request_line_and_headers_over_32_kib_get_400_and_the_close(
    piece: int, size: int, status: int
) -> None:
    proto, transport = _http()
    data = _head(size)
    for at in range(0, len(data), piece):
        proto.data_received(data[at : at + piece])
    await _settled(proto)
    assert transport.written.startswith(b"HTTP/1.1 %d " % status)
    assert transport.is_closing() is (status == 400)
    proto.connection_lost(None)


async def test_a_header_line_still_open_past_32_kib_gets_400_and_the_close(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """httptools passes on a header only once its line ends: the bound counts bytes as read."""
    proto, transport = _http()
    line = _head(HEAD, end=b"")  # one header line, still open
    for at in range(0, HEAD, 1000):
        proto.data_received(line[at : at + 1000])
    assert not transport.is_closing()
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        proto.data_received(b"a")
    assert transport.written.startswith(b"HTTP/1.1 400 ")
    assert transport.is_closing()
    assert caplog.messages == ["Request line and headers too large."]
    proto.connection_lost(None)


async def test_a_request_the_parser_refuses_in_a_long_read_is_answered_once() -> None:
    proto, transport = _http()
    proto.data_received(b"\x00" * (HEAD + 1))
    assert transport.written.count(b"HTTP/1.1 400 ") == 1
    assert transport.is_closing()


async def test_the_rest_of_a_read_that_ends_in_an_upgrade_is_not_read_as_http() -> None:
    """As uvicorn, which reads nothing more of such a read, also when the bound splits it."""
    proto, transport = _http()
    proto.data_received(upgrade() + b"x" * HEAD)
    ws = transport.protocol
    assert isinstance(ws, CvWebSocketsProtocol)
    assert ws.bounded is proto.bounded  # the HTTP protocol's wrapper, handed on, not wrapped again
    assert not transport.is_closing()
    assert transport.written == b""
    ws.connection_lost(None)
    await _settled(ws)


async def test_a_body_read_with_its_headers_is_not_counted_as_headers() -> None:
    proto, transport = _http()
    body = b"b" * (2 * HEAD)
    head = b"PUT / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: %d\r\n\r\n" % len(body)
    proto.data_received(head + body)
    await _settled(proto)
    assert transport.written.startswith(b"HTTP/1.1 200 ")
    proto.connection_lost(None)


def test_server_bounds_uvicorns_drain_by_the_settings_timeout() -> None:
    """#2565: an unbounded drain (`_wait_tasks_to_complete`) keeps `lifespan.shutdown()`, and with
    it the module teardown, from ever running while one connection or task stays open."""
    kwargs = uvicorn_kwargs()
    assert kwargs["timeout_graceful_shutdown"] == Settings().uvicorn_drain_timeout_s == 5
    assert uvicorn.Config(APP, **kwargs).timeout_graceful_shutdown == 5
    custom = Settings(uvicorn_drain_timeout_s=9, api_stop_budget_s=60)
    assert uvicorn_kwargs(custom)["timeout_graceful_shutdown"] == 9


def test_server_host_and_port_come_from_settings() -> None:
    kwargs = uvicorn_kwargs(Settings(bind_host="172.28.0.10", bind_port=8123))
    assert kwargs["host"] == "172.28.0.10"
    assert kwargs["port"] == 8123


def test_server_default_host_is_loopback() -> None:
    assert uvicorn_kwargs(Settings())["host"] == "127.0.0.1"


def test_wildcard_bind_host_is_refused_by_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(bind_host="0.0.0.0")  # nosec B104  # noqa: S104 - asserting the refusal


async def _accepts(scope: Any, receive: Any, send: Any) -> None:
    """Accepts a WebSocket, then its run ends."""
    await receive()
    await send({"type": "websocket.accept"})


async def _aborted(
    proto: CvHttpToolsProtocol | CvWebSocketsProtocol, transport: _Transport
) -> None:
    async with asyncio.timeout(_BOUND_S):
        await transport.aborted.wait()
    proto.connection_lost(None)
    await _settled(proto)


async def test_an_http_answer_that_does_not_drain_is_aborted() -> None:
    """Answered and closed by the server, with a transport that never sends what it holds: it is
    aborted at the bound, which a second close does not move."""
    proto, transport = _built("http", drain_timeout_s=0.05), _Transport()
    proto.connection_made(transport)
    proto.data_received(_head(HEAD + 1))
    timer = proto.bounded.abort_timer
    proto.transport.close()
    assert timer is not None and proto.bounded.abort_timer is timer
    await _aborted(proto, transport)


@pytest.mark.parametrize("kind", ["http", "ws"])
async def test_the_end_of_the_peers_input_closes_with_the_drain_bound(kind: str) -> None:
    """At a peer's FIN the protocol closes through the wrapper, before the loop closes the
    transport itself, so a peer that has also stopped reading is aborted at the bound."""
    proto, transport = _built(kind, drain_timeout_s=0.05), _Transport()
    proto.connection_made(transport)
    proto.eof_received()
    assert transport.is_closing()
    await _aborted(proto, transport)


@pytest.mark.parametrize("ends", ["close-timer", "app-returns"])
async def test_a_websocket_close_that_does_not_drain_is_aborted(ends: str) -> None:
    """Closed by uvicorn's close timer (the client never answers the server's close) or at the
    end of the app's run, alike."""
    app = _App()
    proto = _built("ws", app if ends == "close-timer" else _accepts, drain_timeout_s=0.05)
    assert isinstance(proto, CvWebSocketsProtocol)
    transport = _Transport()
    proto.connection_made(transport)
    proto.data_received(upgrade())
    if ends == "close-timer":
        await app.accepted.wait()
        proto.close_timeout = 0.01  # uvicorn's wait for the client's close
        await proto.send({"type": "websocket.close", "code": 1000})
    await _aborted(proto, transport)


@pytest.mark.parametrize("kind", ["http", "ws"])
async def test_a_closed_connection_that_drains_is_not_aborted(kind: str) -> None:
    transport = _Transport(drains=True)
    proto = _built(kind, drain_timeout_s=0.05)
    transport.owner = proto
    proto.connection_made(transport)
    proto.transport.close()
    async with asyncio.timeout(_BOUND_S):
        await transport.drained.wait()
    assert proto.bounded.abort_timer is None
    assert not transport.aborted.is_set()


@pytest.mark.parametrize(
    ("live", "http", "status"),
    [(LIMIT, 1, 200), (16, LIMIT - 1, 200), (16, LIMIT, 503)],
    ids=["every-slot-websockets", "under-the-limit", "at-the-limit"],
)
async def test_live_websockets_raise_the_limit_a_request_meets_by_their_number(
    live: int, http: int, status: int
) -> None:
    """Beside live WebSockets, their handlers running, a request is answered until it comes on
    the `limit_concurrency`th HTTP connection, which gets uvicorn's 503."""
    state = ServerState()
    held = [_built("ws", state=state) for _ in range(live)]
    held += [_built("http", state=state) for _ in range(http - 1)]
    for proto in held:
        proto.connection_made(_Transport())
        if isinstance(proto, CvWebSocketsProtocol):
            proto.data_received(upgrade())  # its handler starts
    request, transport = _built("http", state=state), _Transport()
    request.connection_made(transport)
    handlers = set(state.tasks)
    request.data_received(GET)
    async with asyncio.timeout(_BOUND_S):
        await asyncio.gather(*(state.tasks - handlers))
    assert transport.written.startswith(b"HTTP/1.1 %d " % status)
    for proto in [*held, request]:
        proto.connection_lost(None)
    await _settled(request)


def test_the_protocol_classes_match_the_uvicorn_and_websockets_they_were_read_against() -> None:
    """They extend parts of both that are not their documented API. When this fails, re-read
    uvicorn's `httptools_impl.py` and `websockets_sansio_impl.py`, and websockets' `protocol.py`
    and `http11.py`, against `candleviewer/server.py`, measure the per-fragment cost again
    (`WS_FRAGMENT_OVERHEAD_BYTES`), then move these two pins."""
    moved = "uvicorn changed: re-read server.py against httptools_impl.py, see the docstring"
    assert version("uvicorn").split(".")[:2] == ["0", "54"], moved
    moved = "websockets changed: re-read server.py against protocol.py, see the docstring"
    assert version("websockets").split(".")[:2] == ["17", "1"], moved

"""Process entrypoint: `python -m candleviewer.server [--reload]`.

Builds the uvicorn configuration from `candleviewer.ws.limits` and
`candleviewer.ws.lifecycle` so server-level WebSocket limits cannot drift from
the protocol (`23-ws-protocol.md` §16.2). uvicorn's proxy-header handling is off
(#2275): `MeshOnlyMiddleware` is the only reader of forwarded headers. The server runs the
§9.4 planned WebSocket shutdown before uvicorn's own (`PlannedShutdownServer`), and agrees to
permessage-deflate for `cv.v1.json` only (§3.5, `CvWebSocketsProtocol`). uvicorn installs no
logging config of its own: its loggers use the root handler `configure_logging()` sets up.
Both protocol classes close a connection whose request line and headers are late, and bound what
a connection's reads can make them keep (#2176).
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import sys
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, cast

import structlog
import uvicorn
from uvicorn.config import STARTUP_FAILURE
from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol
from uvicorn.protocols.websockets.websockets_sansio_impl import WebSocketsSansIOProtocol
from uvicorn.server import ServerState
from websockets.frames import Frame
from websockets.http11 import Request

from candleviewer.observability.context import spawn
from candleviewer.settings import Settings, get_settings
from candleviewer.ws import limits
from candleviewer.ws.lifecycle import (
    CLOSE_REASONS,
    HEARTBEAT_INTERVAL_S,
    HEARTBEAT_TIMEOUT_S,
    SUBPROTOCOL_MSGPACK,
    PongBudget,
    negotiate_subprotocol,
)
from candleviewer.ws.metrics import cv_ws_closes_total

if TYPE_CHECKING:
    from uvicorn._types import ASGIReceiveEvent

APP = "candleviewer.main:app"
#: RFC 6455: a client frame is masked, so it takes at least 6 bytes (a 2-byte header and the
#: 4-byte mask key), and 6 x n bytes complete at most n frames.
_MIN_CLIENT_FRAME_BYTES = 6
#: The first byte of the pong websockets sends a ping: final, opcode 0xA (a server frame is not
#: masked, and permessage-deflate leaves control frames alone).
_PONG = b"\x8a"


def _expired() -> None:
    """A deadline's callback once its connection is lost: it refers to nothing."""


class _BoundedClose(asyncio.Transport):
    """#2176: a connection's transport, as both protocol classes hand it to uvicorn. `close` is the
    transport's own, which waits for the write buffer to drain; past `drain_timeout_s` the
    transport is aborted, so a peer that stops reading cannot keep a closed connection's socket
    and buffer. Every close of either class goes through it, uvicorn's own included (its close
    timer, the end of the app's run, the keep-alive timer, a shutdown), and so does the end of the
    peer's input: `eof_received` closes through it before the loop closes the transport itself.
    The calls uvicorn makes go to the transport; any other raises, as `asyncio.Transport`'s do."""

    def __init__(
        self, transport: asyncio.Transport, loop: asyncio.AbstractEventLoop, drain_timeout_s: float
    ) -> None:
        super().__init__()
        self.inner, self.loop, self.drain_timeout_s = transport, loop, drain_timeout_s
        self.abort_timer: asyncio.TimerHandle | None = None
        self.lost = False

    def close(self) -> None:
        self.inner.close()
        if self.abort_timer is None and not self.lost:
            self.abort_timer = self.loop.call_later(self.drain_timeout_s, self.inner.abort)

    def forget(self) -> None:
        """At the protocol's `connection_lost`: nothing is left to abort."""
        self.lost = True
        if self.abort_timer is not None:
            self.abort_timer.cancel()
            self.abort_timer = None

    def write(self, data: bytes | bytearray | memoryview[Any]) -> None:
        self.inner.write(data)

    def is_closing(self) -> bool:
        return self.inner.is_closing()

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return self.inner.get_extra_info(name, default)

    def set_protocol(self, protocol: asyncio.BaseProtocol) -> None:
        self.inner.set_protocol(protocol)

    def pause_reading(self) -> None:
        self.inner.pause_reading()

    def resume_reading(self) -> None:
        self.inner.resume_reading()


def _bounded(
    transport: asyncio.BaseTransport, loop: asyncio.AbstractEventLoop, drain_timeout_s: float
) -> _BoundedClose:
    """The connection's transport, wrapped once: an upgrade hands the HTTP protocol's on."""
    if isinstance(transport, _BoundedClose):
        return transport
    return _BoundedClose(cast(asyncio.Transport, transport), loop, drain_timeout_s)


class _HeaderDeadline:
    """#2176: one connection's request line and headers deadline, on the timer pattern of
    uvicorn's keep-alive: `arm` starts it unless it runs, `cancel` stops it once they are
    complete, and when it runs out it calls `expire`, which closes the connection. `close`, at
    `connection_lost`, also lets go of `expire`, a method of the protocol, so the two form no
    cycle that only the cyclic GC frees (uvicorn drops its parser there for the same reason)."""

    def __init__(
        self, loop: asyncio.AbstractEventLoop, timeout_s: float, expire: Callable[[], None]
    ) -> None:
        self.loop, self.timeout_s, self.expire = loop, timeout_s, expire
        self.timer: asyncio.TimerHandle | None = None

    def arm(self) -> None:
        if self.timer is None:
            self.timer = self.loop.call_later(self.timeout_s, self.expire)

    def cancel(self) -> None:
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None

    def close(self) -> None:
        self.cancel()
        self.expire = _expired


class CvHttpToolsProtocol(HttpToolsProtocol):
    """uvicorn's HTTP/1.1 protocol (what `http="auto"` picks: httptools is installed), with two
    #2176 bounds on a request line and headers.

    A connection that has not sent them complete within `header_timeout_s` of opening, or of its
    first bytes after a response, is closed by uvicorn's `shutdown`. The deadline runs only while
    no response is in flight, so `shutdown` closes at once; its branch that waits for a response
    in flight is defensive. Any bytes between requests start it: llhttp skips a bare CRLF there,
    while uvicorn stops its keep-alive timer on them. A body starts none. A request answered
    before its body has all come gets its answer, and the answer starts it: uvicorn's own classes
    keep such a connection and let go of the rest of the body, with no timer while it comes, so
    here that rest and the next request line and headers must come within the deadline, or the
    connection is closed.

    Request line and headers that take more than `SERVER_MAX_REQUEST_HEAD_BYTES` get uvicorn's
    400, and the connection is closed. The bytes are counted as they are read, from the end of
    the previous request (CRLFs between requests included), since httptools passes on a header
    only once its line ends. The count can miss up to one read of a request that begins in the
    same read as the end of the one before it (pipelining).

    Its transport, which an upgrade hands on to the WebSocket class, is a `_BoundedClose`: a
    closed connection that has not sent what it holds within `drain_timeout_s` is aborted.

    Live WebSockets are not counted against `limit_concurrency`. uvicorn checks each request
    against the server's sets of connections and tasks, which hold its WebSockets too, while it
    never checks an upgrade; so the limit a request meets is raised by the WebSockets open at its
    headers. A WebSocket's handler still running after its connection is lost counts until it
    returns."""

    def __init__(
        self,
        config: uvicorn.Config,
        server_state: ServerState,
        app_state: dict[str, Any],
        _loop: asyncio.AbstractEventLoop | None = None,
        *,
        header_timeout_s: float = limits.SERVER_READ_HEADER_TIMEOUT_S,
        drain_timeout_s: float = limits.SERVER_CLOSE_DRAIN_TIMEOUT_S,
    ) -> None:
        super().__init__(config, server_state, app_state, _loop)
        self.header_deadline = _HeaderDeadline(self.loop, header_timeout_s, self.shutdown)
        self.drain_timeout_s = drain_timeout_s
        self.reading_head = True  # the next bytes are a request line and headers
        self.head_bytes = 0  # of them, read so far
        self.heads = 0  # request heads read whole, to tell one from the next within a read

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.bounded = _bounded(transport, self.loop, self.drain_timeout_s)
        super().connection_made(self.bounded)
        self.header_deadline.arm()

    def data_received(self, data: bytes) -> None:
        while data:
            if not self.reading_head:  # a body, read as uvicorn reads it
                super().data_received(data)
                return
            if self.cycle is None or self.cycle.response_complete:  # between requests
                self.header_deadline.arm()
            room = limits.SERVER_MAX_REQUEST_HEAD_BYTES - self.head_bytes
            heads, self.head_bytes = self.heads, self.head_bytes + min(len(data), room)
            if room:
                super().data_received(data[:room])
            data = data[room:]
            if self.heads == heads:  # the same request line and headers, still incomplete
                if data and not self.transport.is_closing():
                    msg = "Request line and headers too large."
                    self.logger.warning(msg)
                    self.send_400_response(msg)
                return
            if self.transport.is_closing() or self.parser.should_upgrade():
                return  # as uvicorn, which reads no more of a read that ends in an upgrade

    def on_headers_complete(self) -> None:
        self.header_deadline.cancel()
        self.reading_head, self.head_bytes, self.heads = False, 0, self.heads + 1
        if self.config.limit_concurrency is not None:  # WebSockets are not counted against it
            ws = sum(isinstance(c, CvWebSocketsProtocol) for c in self.connections)
            self.limit_concurrency = self.config.limit_concurrency + ws
        super().on_headers_complete()

    def on_message_complete(self) -> None:
        self.reading_head = True
        super().on_message_complete()

    def on_response_complete(self) -> None:
        # The latest request, answered before its body has all come: the answer starts the
        # deadline, which bounds the rest of the body (uvicorn reads it and lets go of it) and the
        # next request line and headers. A request queued behind the one answered (pipelining) has
        # no response yet: its body may still come.
        if self.cycle.response_complete and self.cycle.more_body:
            self.header_deadline.arm()
        super().on_response_complete()

    def eof_received(self) -> None:
        self.transport.close()  # the peer's end of input, closed with the drain bound

    def connection_lost(self, exc: Exception | None) -> None:
        self.header_deadline.close()
        self.bounded.forget()
        super().connection_lost(exc)


class CvWebSocketsProtocol(WebSocketsSansIOProtocol):
    """uvicorn's WebSocket protocol (what `ws="auto"` picks), with §3.5's compression per
    subprotocol. permessage-deflate is agreed in the upgrade, before the gateway accepts a
    subprotocol, so the §2.2 choice is made here first, on the same offer list uvicorn hands the
    gateway: for `cv.v1.msgpack` the server agrees to no extension.

    #2176: uvicorn hands it the upgrade request its HTTP protocol has read. A request websockets
    refuses (a line over 8 192 bytes, more than 128 headers) gets that refusal, 414 or 431, and is
    closed at once; the request header deadline runs here too, until `handle_connect`. A message
    of more than `WS_MAX_FRAGMENTS_PER_MESSAGE` fragments, or over `ws_max_size` with
    `WS_FRAGMENT_OVERHEAD_BYTES` charged per fragment, is refused as `frame_too_big` is (`1009`,
    `cv_ws_closes_total`), with no `bye`: the gateway never sees it, and its fragments are not
    kept. Every inbound frame (data, continuation, ping, pong)
    takes a token of the connection's frame budget (`WS_INBOUND_FRAME_BURST`, refilled at
    `WS_INBOUND_FRAMES_PER_S`); past it the connection is closed as `client_rate_limited` is
    (`4429`, counted, no `bye`). Frames that arrive after the server's close are not buffered.

    The inbound message queue is bounded: a read is parsed `WS_MAX_QUEUED_MESSAGES` x 6 bytes at
    a time (`_MIN_CLIENT_FRAME_BYTES`), and the next part only once the app has read the queue to
    empty, so the queue never holds more than `WS_MAX_QUEUED_MESSAGES` messages (and the
    disconnect). The rest of the read is held unparsed, with reading paused as uvicorn pauses it
    after a message, until then. While the transport's write buffer is over its high-water mark,
    the client's pings get one pong, for the latest (RFC 6455 §5.5.3 allows that), sent once the
    buffer drains: replies cannot grow it, and reading goes on, so a client whose reads stall can
    still keep the connection alive with its own heartbeats (§9.1)."""

    def __init__(
        self,
        config: uvicorn.Config,
        server_state: ServerState,
        app_state: dict[str, Any],
        _loop: asyncio.AbstractEventLoop | None = None,
        *,
        header_timeout_s: float = limits.SERVER_READ_HEADER_TIMEOUT_S,
        drain_timeout_s: float = limits.SERVER_CLOSE_DRAIN_TIMEOUT_S,
    ) -> None:
        super().__init__(config, server_state, app_state, _loop)
        self.header_deadline = _HeaderDeadline(self.loop, header_timeout_s, self._close)
        self.drain_timeout_s = drain_timeout_s
        self.unread = bytearray()  # of a read, past the part the queue's bound lets be parsed
        self.frame_budget = PongBudget(
            per_second=limits.WS_INBOUND_FRAMES_PER_S, burst=limits.WS_INBOUND_FRAME_BURST
        )  # the gateway's token bucket, here on every frame
        self.frame_clock: Callable[[], float] = self.loop.time
        self.held_pong = b""  # the latest, while the write buffer is over its high-water mark

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.bounded = _bounded(transport, self.loop, self.drain_timeout_s)
        super().connection_made(self.bounded)
        self.header_deadline.arm()

    def connection_lost(self, exc: Exception | None) -> None:
        self.header_deadline.close()
        self.bounded.forget()
        super().connection_lost(exc)

    def eof_received(self) -> None:
        self.transport.close()  # the peer's end of input, closed with the drain bound

    def data_received(self, data: bytes) -> None:
        if not self.handshake_initiated:  # the upgrade request, which uvicorn hands over whole
            super().data_received(data)
            if not self.handshake_initiated and self.conn.handshake_exc is not None:
                self._close()  # uvicorn's own class sends no answer and keeps the socket open
            return
        self.unread += data
        self._parse_unread()

    def _parse_unread(self) -> None:
        part = limits.WS_MAX_QUEUED_MESSAGES * _MIN_CLIENT_FRAME_BYTES
        while self.unread and (self.queue.empty() or self.close_sent):
            if self.transport.is_closing():
                return
            piece = bytes(self.unread[:part])
            del self.unread[:part]
            super().data_received(piece)
        if self.unread and not self.read_paused:
            self.read_paused = True
            self.transport.pause_reading()

    async def receive(self) -> ASGIReceiveEvent:
        message = await super().receive()  # uvicorn resumes reading once the queue is empty
        if self.unread and self.queue.empty():
            self._parse_unread()  # what the read held back comes first
        return message

    def resume_writing(self) -> None:
        super().resume_writing()
        if self.held_pong and not self.transport.is_closing():
            self.transport.write(self.held_pong)
        self.held_pong = b""

    def _close(self) -> None:
        """Send what websockets queued (its refusal of a request, a close frame) and close.
        `close_sent`, as after uvicorn's own refusals: its `shutdown` then only closes."""
        self.close_sent = True
        self.transport.write(b"".join(self.conn.data_to_send()))
        self.transport.close()

    def _refuse(self, reason: str) -> None:
        """Close as the gateway closes for `reason`, counted, with no `bye`, keeping no fragment."""
        code = int(CLOSE_REASONS[reason][0])
        cv_ws_closes_total.labels(reason=reason).inc()
        self.frames = []
        self.conn.fail(code)
        self.queue.put_nowait({"type": "websocket.disconnect", "code": code})
        self._close()

    def _admit(self) -> bool:
        """A frame, before the server's close and within the frame budget."""
        if self.close_sent:  # frames after the server's close are not buffered
            return False
        if self.frame_budget.allow(self.frame_clock()):
            return True
        self._refuse("client_rate_limited")
        return False

    def handle_text(self, event: Frame) -> None:
        if self._admit():
            super().handle_text(event)

    def handle_bytes(self, event: Frame) -> None:
        if self._admit():
            super().handle_bytes(event)

    def handle_ping(self) -> None:
        if not self._admit():
            return
        if self.writable.is_set():  # the write buffer is under its high-water mark
            super().handle_ping()
            return
        writes = self.conn.data_to_send()
        self.held_pong = next((w for w in reversed(writes) if w[:1] == _PONG), self.held_pong)
        self.transport.write(b"".join(w for w in writes if w[:1] != _PONG))

    def handle_pong(self, event: Frame) -> None:
        if self._admit():
            super().handle_pong(event)

    def handle_cont(self, event: Frame) -> None:
        if not self._admit():
            return
        fragments = len(self.frames) + 1  # this message's, this one included
        charged = sum(map(len, self.frames)) + len(event.data)
        charged += fragments * limits.WS_FRAGMENT_OVERHEAD_BYTES
        if fragments <= limits.WS_MAX_FRAGMENTS_PER_MESSAGE and charged <= self.config.ws_max_size:
            super().handle_cont(event)
            return
        self._refuse("frame_too_big")

    def handle_connect(self, event: Request) -> None:
        self.header_deadline.cancel()
        offered = [
            token.strip()
            for header in event.headers.get_all("Sec-WebSocket-Protocol")
            for token in header.split(",")
        ]
        if negotiate_subprotocol(offered) == SUBPROTOCOL_MSGPACK:
            self.conn.available_extensions = []
        super().handle_connect(event)


def uvicorn_kwargs(settings: Settings | None = None) -> dict[str, Any]:
    """Keyword arguments for `uvicorn.run`/`uvicorn.Config`.

    Host/port come from `Settings` (`CV_BIND_HOST` is validated against the wildcard
    address, C-12.9); WS limits from `ws/limits.py` (single source). `timeout_graceful_shutdown`
    bounds uvicorn's drain of open connections and tasks (#2565): past it uvicorn cancels what is
    left and still sends the lifespan `shutdown`, so the module teardown always runs. It is one
    term of the stop budget `Settings` checks (`api_stop_budget_s`), and `Settings` refuses a drain
    shorter than one WS close can need (`MIN_DRAIN_TIMEOUT_S`: the flush plus the audit write), so
    a close within its bounds attempts its `ws.connection.closed` row until its own bound before
    anything is cancelled.

    `proxy_headers=False` (#2275): uvicorn never rewrites `scope["client"]` or the scheme
    from forwarded headers, whatever `FORWARDED_ALLOW_IPS` says, so `scope["client"]` is the
    TCP peer. The only forwarded-header setting is MeshOnly's trusted proxy
    (`CV_MESH_TRUSTED_PROXY_HEADER` and `CV_MESH_TRUSTED_PROXY_ADDRESS`).

    `log_config=None`: uvicorn adds no handlers and no `propagate=False` of its own, so the
    `uvicorn`, `uvicorn.error` and `uvicorn.access` loggers propagate to the root handler that
    `configure_logging()` installs (JSON lines, `RedactionFilter`, `CV_LOG_LEVEL`), as the
    `/metrics` listener already does (`observability/metrics_server.py`).
    """
    cfg = settings if settings is not None else get_settings()
    return {
        "host": cfg.bind_host,
        "port": cfg.bind_port,
        "proxy_headers": False,
        "log_config": None,
        "http": CvHttpToolsProtocol,
        "ws": CvWebSocketsProtocol,
        "ws_max_size": limits.SERVER_WS_MAX_SIZE,
        "ws_per_message_deflate": limits.SERVER_WS_PER_MESSAGE_DEFLATE,
        "ws_ping_interval": HEARTBEAT_INTERVAL_S,
        "ws_ping_timeout": HEARTBEAT_TIMEOUT_S,
        "limit_concurrency": limits.SERVER_LIMIT_CONCURRENCY,
        "timeout_keep_alive": limits.SERVER_KEEP_ALIVE_TIMEOUT_S,
        "timeout_graceful_shutdown": cfg.uvicorn_drain_timeout_s,
    }


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class PlannedShutdownServer(uvicorn.Server):
    """uvicorn's `Server.shutdown` fails every open WebSocket with `1012` before it sends the
    lifespan `shutdown` event (#2546), so the §9.4 planned shutdown in the lifespan teardown
    would reach no client. This server runs it first: it stops accepting connections, runs the
    app's `WsRuntime.stop()` (`shutdown_notice`, grace, `bye` + `1001`), then uvicorn's own
    shutdown. The lifespan's later `stop()` then only stops the sweeper. It first marks the
    gateway's hub as shutting down, so a `1012` that reaches a socket afterwards is attributed to
    the server (`closed_reason`) however the planned shutdown ends: done, cut short, never
    started (a second Ctrl+C first) or failed. The sequence (grace, close flush, uvicorn's bounded
    drain, module teardown) must fit the container's stop budget; `Settings` refuses a config that
    does not (#2565)."""

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        for server in self.servers:
            server.close()  # a connection opened during the grace would miss the notice
        runtime = _ws_runtime(self.config.loaded_app)
        if runtime is not None:
            runtime.hub.shutting_down = True
            if self.force_exit:
                _log_cut_short(started=False)  # a second Ctrl+C within uvicorn's 0.1 s tick
            else:
                await self._planned(runtime)
        await super().shutdown(sockets)

    async def _planned(self, runtime: Any) -> None:
        """`runtime.stop()`, cut short by a second Ctrl+C (`force_exit`), which uvicorn's own
        drain also polls every 0.1 s. A failure is logged and never skips uvicorn's shutdown or
        the module teardown after it. Cutting it short is logged too (`_log_cut_short`). The
        start line counts the open connections, and the ones offered the notice."""
        logger().info(
            "planned ws shutdown (CTRL+C again to force quit)",
            open_connections=len(runtime.hub),
            notified_connections=runtime.hub.authenticated_count(),
        )
        task = spawn(runtime.stop(), name="ws-planned-shutdown")
        try:
            while not task.done() and not self.force_exit:
                await asyncio.wait({task}, timeout=0.1)
        finally:
            task.cancel()  # a no-op once done; else force_exit, or this coroutine was cancelled
        outcome: list[object] = await asyncio.gather(task, return_exceptions=True)
        failure = outcome[0]
        if isinstance(failure, Exception):
            logger().error(
                "planned ws shutdown failed", error=type(failure).__name__, exc_info=failure
            )
        elif task.cancelled():
            _log_cut_short(started=True)


def _log_cut_short(*, started: bool) -> None:
    """A second Ctrl+C ended the planned shutdown (`started`: after it began, else before). uvicorn
    then skips the lifespan teardown too, and the clients get its bare `1012`."""
    logger().warning(
        "planned ws shutdown cut short",
        reason="force_exit",
        lifespan_teardown="skipped",
        started=started,
    )


def _ws_runtime(app: Any) -> Any:
    """`app.state.ws_runtime`, under uvicorn's own wrappers (`ProxyHeadersMiddleware`, ...)."""
    for _ in range(8):
        runtime = getattr(getattr(app, "state", None), "ws_runtime", None)
        if runtime is not None or app is None:
            return runtime
        app = getattr(app, "app", None)
    return None


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    unknown = [a for a in args if a != "--reload"]
    if unknown:
        raise SystemExit(f"unsupported arguments: {unknown}")
    if "--reload" in args:  # dev only: uvicorn's reloader runs a plain server per reload
        uvicorn.run(APP, reload=True, **uvicorn_kwargs())
        return
    server = PlannedShutdownServer(uvicorn.Config(APP, **uvicorn_kwargs()))
    with contextlib.suppress(KeyboardInterrupt):
        server.run()
    if not server.started:
        raise SystemExit(STARTUP_FAILURE)  # as `uvicorn.run` exits


if __name__ == "__main__":
    main()

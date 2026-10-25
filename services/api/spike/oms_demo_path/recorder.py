"""The two recording seams (#843 A4 brief items 3, 5, 6, 7): the adapter's `rest_transport` and
its `private_ws_connect`, the only edges the harness swaps (`ExchangeBybitService`).

`RecordingTransport` wraps the transport every account REST client of the adapter sends through.
It refuses any request that is not `https://api-demo.bybit.com` before anything leaves, registers
the request's key id and its signature with the scrubber (R1S-01: neither reaches any output,
that exchange's or a later one's), times the exchange from send to the whole reply on the
monotonic clock (the RTT at the seam, below the port's M2 signing and audit append), reads the
body there and hands the client a fresh response without the transfer headers (the client
streams and caps it again). Each exchange records how long the seam had been idle before it
(`idle_s`): past httpx's keep-alive expiry (`KEEPALIVE_S`) its connection was a new one, TCP and
TLS included (`cold`), else `warm` (R1C-06); a create is also told apart as a limit opener or a
reduce-only close. A failed exchange is counted by class (R1C-09). Each exchange is an event
and, for its first few replies per call class and code, a fixture candidate; never a header.
Both are handed to the outputs' writer, so the port's call never pays for a scrub (R1C-03). The
key-info read's reply (`NOT_KEPT`) is never a fixture candidate or an error shape: it names the
key, the UID, the key's label and the host's egress addresses; its timing and code are kept.

`RecordingConnector` wraps the private-stream connector: it refuses any URL but the demo
stream's, counts dials, and its sockets register each `auth` op's key id and signature with the
scrubber before the frame leaves. A frame received is timed (the silence before it: the message
gaps) and handed to the outputs' writer as it arrived; `recv` returns at once, and the writer
classifies it, counts pongs and `auth` grants and refusals, keeps each silence between two pongs
(the ping gaps), never records an `auth` frame either way, and tees the rest, scrubbed (R1C-03:
the scrub is never on the receive path, so it is never in a push's measured latency).

Both sit below the adapter's own masking (`rest._mask`, `private_stream._classify`): the raw
traffic holds the key id, the signature, `orderId`, `orderLinkId`, `execId` and the push ids,
which is why nothing here writes a byte the scrubber has not seen.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import httpx

from candleviewer.exchange.bybit.private_stream import PING_INTERVAL_S, WATCHDOG_S, StreamSocket
from spike.oms_demo_path.config import DEMO_PRIVATE_WS, DEMO_REST_HOST
from spike.oms_demo_path.measure import Timings, call_class, gap_stats
from spike.oms_demo_path.outputs import RunOutputs
from spike.oms_demo_path.safety import Refused
from spike.oms_demo_path.scrub import Scrubber

#: Replies kept as fixture candidates per (call class, return code).
FIXTURES_PER_CODE: Final = 3
#: The most of a reply the seam reads (the adapter caps signed replies at 1 MiB itself).
REPLY_CAP: Final = 4 * 1024 * 1024
#: A silence counted as long: past the adapter's 5 s ping by half its slack to the 10 s watchdog
#: (7.5 s), so its pong came late though the socket lived. A silence of the watchdog's length
#: is never seen: the socket ends first, and the next frame comes on another.
LONG_SILENCE_S: Final = PING_INTERVAL_S + (WATCHDOG_S - PING_INTERVAL_S) / 2
#: Silences kept per distribution (C-2.18: a bound; a 24 h soak's pongs, every 5 s, are 17 280).
GAPS_KEPT: Final = 100_000
#: httpx's keep-alive expiry (`httpx.Limits().keepalive_expiry`, the adapter's and the harness's
#: transport alike): an exchange after a longer idle opened a new connection (`cold`).
KEEPALIVE_S: Final = 5.0
_TRANSFER_HEADERS: Final = frozenset({"content-encoding", "content-length", "transfer-encoding"})
_KEY_HEADER: Final = "X-BAPI-API-KEY"
_SIGN_HEADER: Final = "X-BAPI-SIGN"
#: Replies never kept whole (see the module docstring): the key-info read's.
NOT_KEPT: Final = frozenset({"/v5/user/query-api"})


def _wall_ms() -> float:
    return time.time() * 1000


@dataclass(frozen=True, slots=True)
class Exchange:
    """One HTTP exchange at the seam (no header, no body: those go through the scrubber)."""

    path: str
    status: int
    ret_code: int | None
    rtt_ms: float
    sent_wall_ms: float
    received_wall_ms: float
    venue_ms: int | None
    idle_s: float | None = None


async def _capped(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > REPLY_CAP:
            raise httpx.ReadError("a reply above the seam's cap")
        chunks.append(chunk)
    return b"".join(chunks)


def _decoded(body: bytes) -> object:
    try:
        return json.loads(body)
    except ValueError:
        return None


def create_kind(request: httpx.Request) -> str | None:
    """A create told apart: `create_close` (reduce-only), else `create_open`; `None` for any
    other call."""
    if call_class(request.url.path) != "create":
        return None
    body = _decoded(request.content)
    closing = isinstance(body, dict) and body.get("reduceOnly") is True
    return "create_close" if closing else "create_open"


class RecordingTransport(httpx.AsyncBaseTransport):
    """The adapter's account REST transport, recorded (see the module docstring)."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        *,
        scrubber: Scrubber,
        outputs: RunOutputs,
        timings: Timings,
        monotonic: Callable[[], float] = time.monotonic,
        wall_ms: Callable[[], float] = _wall_ms,
    ) -> None:
        self._inner = inner
        self._scrubber = scrubber
        self._outputs = outputs
        self._timings = timings
        self._monotonic = monotonic
        self._wall_ms = wall_ms
        self._kept: Counter[tuple[str, int | None]] = Counter()
        #: When the seam's last exchange ended (monotonic), for the next one's `idle_s`.
        self._idle_since: float | None = None
        self.codes: Counter[int] = Counter()
        #: The first reply of each non-zero code, whole: in memory, scrubbed when written.
        self.shapes: dict[int, object] = {}
        self.last: dict[str, Exchange] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme != "https" or url.host != DEMO_REST_HOST:
            raise Refused("a request to a host off the demo allow-list; nothing was sent")
        self._scrubber.secret(request.headers.get(_KEY_HEADER))
        signature = request.headers.get(_SIGN_HEADER, "")
        self._scrubber.secret(signature)
        sent_wall, started = self._wall_ms(), self._monotonic()
        idle_s = None if self._idle_since is None else started - self._idle_since
        try:
            response = await self._inner.handle_async_request(request)
            try:
                body = await _capped(response)
            finally:
                await response.aclose()
        except Exception as exc:  # counted by class, then the adapter's own handling
            self._idle_since = self._monotonic()
            elapsed = round((self._idle_since - started) * 1000, 2)
            failed = type(exc).__name__
            call = call_class(request.url.path)
            self._timings.failed(request.url.path)
            self._outputs.event("rest_failed", call=call, failure=failed, ms=elapsed)
            raise
        self._idle_since = self._monotonic()
        rtt_ms = (self._idle_since - started) * 1000
        received_wall = self._wall_ms()
        self._record(
            request,
            response.status_code,
            body,
            rtt_ms,
            (sent_wall, received_wall),
            signature,
            idle_s,
        )
        headers = [
            (k, v) for k, v in response.headers.multi_items() if k.lower() not in _TRANSFER_HEADERS
        ]
        return httpx.Response(response.status_code, headers=headers, content=body)

    def _record(
        self,
        request: httpx.Request,
        status: int,
        body: bytes,
        rtt_ms: float,
        wall: tuple[float, float],
        signature: str,
        idle_s: float | None,
    ) -> None:
        """What the measurements need, now (the RTT, its class and temperature, the venue's
        `time`, the code); the event and the fixture candidate, to the outputs' writer."""
        path = request.url.path
        reply = _decoded(body)
        ret_code = reply.get("retCode") if isinstance(reply, dict) else None
        code = ret_code if type(ret_code) is int else None
        venue = reply.get("time") if isinstance(reply, dict) else None
        exchange = Exchange(
            path=path,
            status=status,
            ret_code=code,
            rtt_ms=rtt_ms,
            sent_wall_ms=wall[0],
            received_wall_ms=wall[1],
            venue_ms=venue if type(venue) is int else None,
            idle_s=idle_s,
        )
        self.last[path] = exchange
        cold = idle_s is None or idle_s > KEEPALIVE_S
        self._timings.exchanged(path, rtt_ms, cold=cold, kind=create_kind(request))
        name = call_class(path)
        transient = (signature,) if signature else ()
        sent = _decoded(request.content) if request.method == "POST" else dict(request.url.params)
        self._outputs.event(
            "rest",
            call=name,
            method=request.method,
            status=status,
            ret_code=code,
            rtt_ms=round(rtt_ms, 2),
            idle_s=None if idle_s is None else round(idle_s, 3),
            connection="cold" if cold else "warm",
            request=sent,
            transient=transient,
        )
        if code is not None and code != 0:
            self.codes[code] += 1
            if path not in NOT_KEPT:
                self.shapes.setdefault(code, reply)
        self._kept[(name, code)] += 1
        if self._kept[(name, code)] <= FIXTURES_PER_CODE and path not in NOT_KEPT:
            label = f"{name}_{'none' if code is None else code}_{self._kept[(name, code)]}"
            self._outputs.rest_fixture(label, reply, transient=transient)

    async def aclose(self) -> None:
        await self._inner.aclose()


class RecordingConnector:
    """The adapter's private-stream connector, recorded (see the module docstring)."""

    def __init__(
        self,
        inner: Callable[[str], Awaitable[StreamSocket]],
        *,
        scrubber: Scrubber,
        outputs: RunOutputs,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._scrubber = scrubber
        self._outputs = outputs
        self._monotonic = monotonic
        self.dials = 0
        self.counts: Counter[str] = Counter()
        self.max_silence_s = 0.0
        #: Each silence between two frames of one socket, and between two of its pongs (s).
        self.message_gaps_s: list[float] = []
        self.ping_gaps_s: list[float] = []

    async def __call__(self, url: str) -> StreamSocket:
        if url != DEMO_PRIVATE_WS:
            raise Refused("a private stream off the demo allow-list; nothing was dialled")
        self.dials += 1
        self._outputs.event("dial", n=self.dials)
        return RecordingSocket(await self._inner(url), self)

    def gaps(self) -> dict[str, object]:
        """The ping and message gap distributions, and the threshold of a long silence."""
        return {
            "long_silence_s": LONG_SILENCE_S,
            "ping_gaps_s": gap_stats(self.ping_gaps_s, LONG_SILENCE_S),
            "message_gaps_s": gap_stats(self.message_gaps_s, LONG_SILENCE_S),
        }

    def sent(self, frame: str) -> None:
        message = _decoded(frame.encode())
        op = message.get("op") if isinstance(message, dict) else None
        if op == "auth" and isinstance(message, dict):
            args = message.get("args")
            if isinstance(args, list) and len(args) == 3:
                for value in (args[0], args[2]):
                    self._scrubber.secret(value if isinstance(value, str) else None)
        self.counts[f"sent:{op}"] += 1

    def arrived(self, sock: RecordingSocket, frame: str, now: float, silence_s: float) -> None:
        """The receive path: the silence before the frame, then the frame to the outputs'
        writer as it arrived (`received` runs there: R1C-03)."""
        self.max_silence_s = max(self.max_silence_s, silence_s)
        _kept(self.message_gaps_s, silence_s)
        self._outputs.later(self.received, sock, frame, now)

    def received(self, sock: RecordingSocket, frame: str, now: float) -> str | None:
        """The writer: classify, count and tee one frame (`now`: when it arrived); its label
        (`op_pong` for a pong), `None` if not kept."""
        message = _decoded(frame.encode())
        if not isinstance(message, dict):
            self.counts["received:unreadable"] += 1
            return None
        op, topic = message.get("op"), message.get("topic")
        if op == "auth":
            granted = message.get("success") is True
            self.counts["auth:granted" if granted else "auth:refused"] += 1
            return None  # never recorded (#843 security notes)
        label = str(topic) if isinstance(topic, str) else f"op_{op}"
        self.counts[f"received:{label}"] += 1
        if label == "op_pong":
            sock.ponged(now)
        self._outputs.tee(label.replace(".", "_"), frame)
        return label


def _kept(values: list[float], value: float) -> None:
    if len(values) < GAPS_KEPT:
        values.append(value)


class RecordingSocket:
    """One private socket, recorded through its connector."""

    def __init__(self, inner: StreamSocket, owner: RecordingConnector) -> None:
        self._inner = inner
        self._owner = owner
        self._last = owner._monotonic()
        self._last_pong: float | None = None

    async def send(self, frame: str) -> None:
        self._owner.sent(frame)
        await self._inner.send(frame)

    async def recv(self, max_bytes: int) -> str:
        frame = await self._inner.recv(max_bytes)
        now = self._owner._monotonic()
        self._owner.arrived(self, frame, now, now - self._last)
        self._last = now
        return frame

    def ponged(self, now: float) -> None:
        """A pong that arrived at `now`: the ping gap since this socket's last one."""
        if self._last_pong is not None:
            _kept(self._owner.ping_gaps_s, now - self._last_pong)
        self._last_pong = now

    async def close(self) -> None:
        await self._inner.close()

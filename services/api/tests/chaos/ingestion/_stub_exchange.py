"""Fault-injecting stub exchange for E08-Q03 (the "local proxy" of the ticket).

Sits between the production adapter and the recorded-corpus replayer:

* WS: `socket_factory()` is a `ConnectionManager` `SocketFactory`; every socket
  it returns is a `StubSocket` fed by `emit()` / `replay()`.
* REST: `transport` is an `httpx.MockTransport` handed to the production
  `BybitRestClient`, so retries, mapping, signing and metrics all run for real.

Faults (`_faults.Fault`) are armed with `inject()` and consumed at the seam.
Everything is driven by the injected `VirtualClock` and a seeded RNG; nothing
listens on a port and no host name is ever dialled (C-13.5, SR-140).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from tests._corpus import rest
from tests.chaos.ingestion._clock import VirtualClock
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._oracle import BookOracle, TradeOracle

#: The venue's documented per-IP cap the reconnect-storm guard must stay under (SR-039).
EXCHANGE_CONN_LIMIT, EXCHANGE_CONN_WINDOW_S = 500, 300.0
_HTML_502 = "<html><head><title>502 Bad Gateway</title></head><body>cloudfront</body></html>"


@dataclass
class Trace:
    """Everything the harness observed, in order (the determinism fingerprint)."""

    events: list[tuple[float, str, str]] = field(default_factory=list)

    def add(self, t: float, kind: str, detail: str) -> None:
        self.events.append((round(t, 6), kind, detail))

    def kinds(self, kind: str) -> list[tuple[float, str, str]]:
        return [e for e in self.events if e[1] == kind]


class StubSocket:
    """One accepted connection. `recv` honours RESET / STALL faults."""

    def __init__(self, ex: StubExchange, conn_id: int) -> None:
        self.ex, self.conn_id = ex, conn_id
        self.topics: set[str] = set()
        self.sent: list[dict[str, Any]] = []
        self.duplicate_subscribes = 0
        self.closed = False
        self.stalled = False
        self._q: asyncio.Queue[str | BaseException] = asyncio.Queue()
        self._pending_snapshots: list[tuple[int, str]] = []  # (deliver_after_n_frames, frame)

    # ---- client -> exchange ---------------------------------------------------
    async def send(self, frame: str) -> None:
        msg = json.loads(frame)
        self.sent.append(msg)
        op, args = msg.get("op"), list(msg.get("args", []))
        self.ex.trace.add(self.ex.clock.now, f"ws.{op}", f"{self.conn_id}:{','.join(args)}")
        if op == "unsubscribe":
            self.topics.difference_update(args)
        elif op == "subscribe":
            for topic in args:
                if topic in self.topics:
                    self.duplicate_subscribes += 1
                self.topics.add(topic)
                self._on_subscribed(topic)

    def _on_subscribed(self, topic: str) -> None:
        book = self.ex.books.get(topic)
        if book is None or book.u == 0 or self.ex.is_delisted(book.symbol):
            return
        frame = book.snapshot_frame()  # captured now, delivered after the lag
        lag = self.ex.snapshot_lag_frames
        if lag <= 0:
            self.push(frame)
        else:
            self._pending_snapshots.append((lag, frame))

    async def recv(self, max_bytes: int) -> str:
        item = await self._q.get()
        if isinstance(item, BaseException):
            raise item
        if len(item) > max_bytes:
            raise ValueError("ws frame exceeds max_bytes")  # mirrors `_WsSocket.recv`
        return item

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.ex.trace.add(self.ex.clock.now, "ws.close", str(self.conn_id))
            self._q.put_nowait(ConnectionResetError("closed by client"))

    # ---- exchange -> client ---------------------------------------------------
    def push(self, frame: str) -> None:
        if not self.closed and not self.stalled:
            self._q.put_nowait(frame)

    def tick_pending(self) -> None:
        due = [f for n, f in self._pending_snapshots if n <= 1]
        self._pending_snapshots = [(n - 1, f) for n, f in self._pending_snapshots if n > 1]
        for frame in due:
            self.push(frame)

    def reset(self) -> None:
        self.ex.trace.add(self.ex.clock.now, "fault.reset", str(self.conn_id))
        self._q.put_nowait(ConnectionResetError("connection reset by peer"))


class StubExchange:
    """The fake venue: public WS + public/signed REST, with injectable faults."""

    def __init__(self, clock: VirtualClock, *, seed: int) -> None:
        self.clock = clock
        self.rng = random.Random(seed)  # noqa: S311  (deterministic fault choices)
        self.trace = Trace()
        self.sockets: list[StubSocket] = []
        self.attempts: list[float] = []  # every dial, accepted or refused (SR-039 counter)
        self.books: dict[str, BookOracle] = {}
        self.trades = TradeOracle()
        self.delisted: set[str] = set()
        self.snapshot_lag_frames = 0
        self.host_skew_s = 0.0  # host wall clock minus exchange wall clock
        self.venue_skew_s = 0.0  # venue wall clock minus the scenario's nominal time
        self.rest_calls: list[tuple[float, str]] = []
        self.limit_remaining = 50
        self.catalogue: dict[str, Any] = rest("rest/instruments_before.json")
        self._faults: list[Fault] = []
        self._held: dict[str, str] = {}  # REORDER: the frame waiting for its successor
        self.transport = httpx.MockTransport(self._handle_rest)

    # ---- fault API (also the E08-X02 entry point) ---------------------------
    def inject(self, fault: Fault) -> None:
        self.trace.add(self.clock.now, "inject", f"{fault.kind}:{fault.topic or fault.path}")
        if fault.kind is FaultKind.RESET:
            for sock in self.live_sockets():
                sock.reset()
            return
        if fault.kind is FaultKind.STALL:
            for sock in self.live_sockets():
                sock.stalled = True
            return
        if fault.kind is FaultKind.CLOCK_JUMP:
            self.host_skew_s += fault.seconds
            return
        if fault.kind is FaultKind.VENUE_CLOCK_JUMP:
            self.venue_skew_s += fault.seconds
            return
        if fault.kind is FaultKind.DELIST and fault.symbol is not None:
            self.delisted.add(fault.symbol)
            self.catalogue = rest("rest/instruments_after.json")
            return
        self._faults.append(fault)

    def clear(self, kind: FaultKind, *, path: str | None = None) -> None:
        """The outage is over: drop every armed `kind` fault (on `path`, if given)."""
        self.trace.add(self.clock.now, "clear", f"{kind}:{path}")
        self._faults = [f for f in self._faults if f.kind is not kind or path not in (None, f.path)]

    def _take(
        self, kind: FaultKind, *, topic: str | None = None, path: str | None = None
    ) -> Fault | None:
        for i, f in enumerate(self._faults):
            if f.kind is not kind:
                continue
            if topic is not None and f.topic not in (None, topic):
                continue
            if path is not None and f.path not in (None, path):
                continue
            if f.count <= 1:
                del self._faults[i]
            else:
                self._faults[i] = dataclasses.replace(f, count=f.count - 1)
            return f
        return None

    def is_delisted(self, symbol: str) -> bool:
        return symbol in self.delisted

    def live_sockets(self) -> list[StubSocket]:
        return [s for s in self.sockets if not s.closed]

    # ---- WS ------------------------------------------------------------------
    async def socket_factory(self) -> StubSocket:
        self.attempts.append(self.clock.now)
        if self._take(FaultKind.REFUSE):
            self.trace.add(self.clock.now, "ws.refused", str(len(self.attempts)))
            raise ConnectionRefusedError("stub exchange refused the connection")
        sock = StubSocket(self, len(self.sockets) + 1)
        self.sockets.append(sock)
        self.trace.add(self.clock.now, "ws.open", str(sock.conn_id))
        return sock

    def emit(self, frame: str) -> None:
        """The exchange publishes one frame: truth first, then the faulty wire."""
        msg = json.loads(frame)
        topic = str(msg.get("topic", ""))
        symbol = topic.rsplit(".", 1)[-1]
        if symbol in self.delisted:
            return  # a delisted contract goes silent
        if topic.startswith("orderbook."):
            book = self.books.setdefault(topic, BookOracle(symbol, int(topic.split(".")[1])))
            book.apply(msg)
        # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
        elif topic.startswith("publicTrade."):
            self.trades.apply(msg)
        for sock in self.live_sockets():
            sock.tick_pending()
        if self._take(FaultKind.DROP, topic=topic):
            self.trace.add(self.clock.now, "fault.drop", topic)
            return
        if topic in self._held:
            first = self._held.pop(topic)
            self._deliver(topic, frame)
            self._deliver(topic, first)
            return
        if self._take(FaultKind.REORDER, topic=topic):
            self.trace.add(self.clock.now, "fault.reorder", topic)
            self._held[topic] = frame
            return
        self._deliver(topic, frame)
        if self._take(FaultKind.DUPLICATE, topic=topic):
            self.trace.add(self.clock.now, "fault.duplicate", topic)
            self._deliver(topic, frame)
        if self._take(FaultKind.BOMB, topic=topic):
            self.trace.add(self.clock.now, "fault.bomb", topic)
            self._deliver(topic, frame + " " * (1_048_576 + 1))

    def _deliver(self, topic: str, frame: str) -> None:
        for sock in self.live_sockets():
            if topic in sock.topics:
                sock.push(frame)

    async def replay(self, frames: Iterable[str], *, interval_s: float = 0.1) -> None:
        """Emit frames on a fixed virtual cadence (recorded `ts` is kept)."""
        for frame in frames:
            self.emit(frame)
            await self.clock.advance(interval_s)

    def conn_attempts_in_any_window(self, window_s: float = EXCHANGE_CONN_WINDOW_S) -> int:
        """Max dials inside any sliding `window_s` (what the venue's per-IP cap counts)."""
        ts = sorted(self.attempts)
        best, lo = 0, 0
        for hi, t in enumerate(ts):
            while t - ts[lo] >= window_s:
                lo += 1
            best = max(best, hi - lo + 1)
        return best

    # ---- REST ----------------------------------------------------------------
    def exchange_now_ms(self) -> int:
        """Venue wall time on the scenario's virtual clock. A host clock jump of
        +S s is modelled by the rig's host clock reading S s ahead of the venue
        (only the difference is observable to signing and the server-time probe)."""
        return int((self.clock.wall_s() + self.venue_skew_s) * 1000)

    def _handle_rest(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.rest_calls.append((self.clock.now, path))
        self.trace.add(self.clock.now, "rest", path)
        if (f := self._take(FaultKind.HTTP_STATUS, path=path)) is not None:
            return httpx.Response(f.status, json={})
        if self._take(FaultKind.HTML_502, path=path):
            return httpx.Response(502, text=_HTML_502, headers={"content-type": "text/html"})
        if self._take(FaultKind.MALFORMED_JSON, path=path):
            # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
            return httpx.Response(200, text='{"retCode":0,"result":{"list":[{"execId"')
        if (f := self._take(FaultKind.RATE_LIMIT, path=path)) is not None:
            self.limit_remaining = 0
            reset_ms = self.exchange_now_ms() + int(f.reset_in_s * 1000)
            return httpx.Response(
                200,
                json=rest("rest/error_10018.json"),
                headers={
                    "X-Bapi-Limit-Status": "0",
                    "X-Bapi-Limit": "50",
                    "X-Bapi-Limit-Reset-Timestamp": str(reset_ms),
                },
            )
        # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
        if "X-BAPI-SIGN" in request.headers:
            # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
            sent = int(request.headers["X-BAPI-TIMESTAMP"])
            # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
            window = int(request.headers["X-BAPI-RECV-WINDOW"])
            rejected = self._take(FaultKind.REJECT_SIGNED, path=path) is not None
            if rejected or abs(sent - self.exchange_now_ms()) > window:
                self.trace.add(self.clock.now, "rest.10002", path)
                return httpx.Response(200, json=rest("rest/error_10002.json"))
        self.limit_remaining = min(50, self.limit_remaining + 10)
        headers = {"X-Bapi-Limit-Status": str(self.limit_remaining), "X-Bapi-Limit": "50"}
        return httpx.Response(200, json=self._route(request), headers=headers)

    def _route(self, request: httpx.Request) -> dict[str, Any]:
        path = request.url.path
        if path == "/v5/market/time":
            ns = self.exchange_now_ms() * 1_000_000
            return {
                # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
                "retCode": 0,
                # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
                "retMsg": "OK",
                "result": {"timeSecond": str(ns // 10**9), "timeNano": str(ns)},
                # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
                "retExtInfo": {},
                "time": ns // 1_000_000,
            }
        if path == "/v5/market/recent-trade":
            symbol = request.url.params.get("symbol", "")
            limit = int(request.url.params.get("limit", "1000"))
            body = self.trades.recent_trade_body(symbol, limit)
            if self._take(FaultKind.HOSTILE_JSON, path=path):
                body["result"]["list"].insert(0, {"execId": "x", "symbol": symbol, "price": "NaN"})
            return body
        if path == "/v5/market/instruments-info":
            return dict(self.catalogue)
        # nosemgrep: cv-adapter-isolation,cv-bybit-vocabulary-leak reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31  # noqa: E501
        return {"retCode": 0, "retMsg": "OK", "result": {}, "retExtInfo": {}, "time": 0}

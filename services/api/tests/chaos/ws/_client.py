"""E17-Q02 protocol test client (independent of `apps/web`, like the E17-Q01 client).

Speaks `cv.v1.json` through the proxy and keeps the `23-ws-protocol.md` client obligations the
scenarios need: §9.2 reconnect with full jitter from a seeded RNG (never after 1002/4400/4403),
§9.3 resubscription in priority order (private topics first), §4.3/§9.2 refresh over REST before
reconnecting once the token is within 60 s of expiry or after a `4401`, §9.1 `pong`. It records
every frame, close code and §7.1 sequence gap (a `d` whose `s` is not the last `s` + 1 on that
channel and connection, with no `snap` in between). Each test-side wait is bounded. It models
§16.1 C12: order entry is off after a `shutdown_notice` or an engaged kill switch (`auth_ok` too).
Opt-in: the §9.1 client `ping`, no permessage-deflate, and data frames handed to `on_data`.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import itertools
import json
import random
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.typing import Origin, Subprotocol

from candleviewer.observability.context import spawn
from tests.chaos.ingestion._clock import VirtualClock
from tests.contract.ws._support import ORIGIN

#: §9.2 (delay, jitter) per attempt; attempt 6 and later reuse the last row.
BACKOFF = ((0.5, 0.25), (1.0, 0.5), (2.0, 1.0), (5.0, 2.0), (10.0, 5.0), (30.0, 10.0))
PRIVATE = frozenset({"orders", "positions", "executions", "wallet"})
DATA = frozenset({"d", "snap"})
NO_RECONNECT = frozenset({1002, 4400, 4403})
REFRESH_MARGIN_MS = 60_000
TIMEOUT_S = 5.0
#: §3.6: the largest frame the server sends (snapshots above it are chunked). The client reads
#: under this bound, so a misbehaving gateway cannot make the harness buffer more
#: (`cv-unbounded-read`).
MAX_FRAME_BYTES = 4 * 1024 * 1024
#: `proxy=None`: loopback is never routed through an env-configured proxy; no library pings.
_dial = functools.partial(
    connect,
    origin=Origin(ORIGIN),
    subprotocols=[Subprotocol("cv.v1.json")],
    proxy=None,
    ping_interval=None,
    open_timeout=TIMEOUT_S,
    max_size=MAX_FRAME_BYTES,
)


class Client:
    def __init__(
        self, urls: tuple[str, str], clock: VirtualClock, tokens: tuple[str, str], seed: int
    ) -> None:
        self.url, self.http = urls
        self.clock = clock
        self.access, self.refresh_token = tokens
        self.rng = random.Random(seed)  # noqa: S311  (deterministic jitter)
        self.topics: list[dict[str, Any]] = []
        self.expires_ms: int | None = None
        self.must_refresh = False  # set by a `4401`, cleared by a successful refresh (§9.2)
        self.sessions = 0
        self.frames: list[dict[str, Any]] = []
        self.rx_at: list[float] = []  # loop time each frame arrived, aligned with `frames`
        self.order_entry = True  # the C12 state a UI would show; every change is in `log`
        self.gaps: list[str] = []
        self.closes: list[int] = []
        self.denied: dict[str, str] = {}
        self.snapped: set[str] = set()
        self.log: list[tuple[Any, ...]] = []
        self.backoffs: asyncio.Queue[float] = asyncio.Queue()
        self.seq: dict[str, int] = {}  # last `s` per channel on the current connection
        #: Opt-in, set before `start()`. §9.1: the client's own `ping` every this many seconds of
        #: virtual time. §3.5: whether it offers permessage-deflate (the library's default).
        self.heartbeat_s: float | None = None
        self.deflate = True
        #: Takes every `d` and `snap` of a topic, decoded and as received, in place of `frames`
        #: (`system` frames stay there): for a stream too large to keep, read as it arrives.
        self.on_data: Callable[[dict[str, Any], str | bytes], None] | None = None
        self._tick = asyncio.Event()
        self.task: asyncio.Task[None] | None = None

    def start(self, *topics: dict[str, Any]) -> Client:
        """Connect and hold `topics`: private ones first (§9.3), then the panes' in order."""
        self.topics = sorted(topics, key=lambda e: e["ch"].split(".")[0] not in PRIVATE)
        self.task = spawn(self._run(), name="chaos-ws-client")
        self.task.add_done_callback(lambda _t: self._tick.set())
        return self

    def _note(self, *event: Any) -> None:
        self.log.append((round(self.clock.now, 3), *event))
        self._tick.set()

    async def _run(self) -> None:
        attempt = 0
        while True:
            before = self.sessions
            code = await self._attempt()
            if code in NO_RECONNECT:
                return
            attempt = 1 if self.sessions > before else attempt + 1
            base, jitter = BACKOFF[min(attempt, len(BACKOFF)) - 1]
            delay = base + self.rng.uniform(-jitter, jitter)
            self._note("backoff", attempt, round(delay, 3))
            self.backoffs.put_nowait(delay)
            await self.clock.sleep(delay)

    async def _attempt(self) -> int | None:
        """Refresh first when due, then one socket; the close code, or None if nothing opened."""
        now_ms = self.clock.wall_s() * 1000
        due = self.expires_ms is not None and now_ms >= self.expires_ms - REFRESH_MARGIN_MS
        if (due or self.must_refresh) and not await self._refresh():
            return None
        try:
            dial = _dial(self.url, compression="deflate" if self.deflate else None)
            async with dial as ws, self._beating(ws):
                self._note("open")
                await self._session(ws)
        except ConnectionClosed as exc:
            self.closes.append(exc.rcvd.code if exc.rcvd is not None else 1006)
            self.must_refresh = self.must_refresh or self.closes[-1] == 4401
            self._note("closed", self.closes[-1])
            return self.closes[-1]
        except (OSError, InvalidHandshake, TimeoutError):
            self._note("refused")
        return None

    async def _refresh(self) -> bool:
        """The REST refresh, through the proxy like every other byte to the backend."""
        try:
            async with httpx.AsyncClient(base_url=self.http, trust_env=False) as http:
                res = await http.post("/auth/refresh", json={"refresh_token": self.refresh_token})
                body = res.raise_for_status().json()
        except httpx.HTTPError:
            self._note("refresh", False)
            return False
        self.access, self.refresh_token = body["access_token"], body["refresh_token"]
        self.expires_ms, self.must_refresh = None, False
        self._note("refresh", True)
        return True

    async def _session(self, ws: ClientConnection) -> None:
        self.seq, self.snapped = {"system": 0}, set()  # a new connection: new sequence domains
        hello = {"client": "chaos", "client_version": "1.0.0", "protocol": "cv.v1"}
        await ws.send(json.dumps({"t": "hello", "id": "h", "p": hello}))
        while True:
            text = await ws.recv(decode=True)  # text, <= max_size
            frame: dict[str, Any] = json.loads(text)
            if self.on_data is None or frame["t"] not in DATA or frame["ch"] == "system":
                self.frames.append(frame)
                self.rx_at.append(asyncio.get_running_loop().time())
            else:
                self.on_data(frame, text)
            reply = self._on(frame)
            if reply is not None:
                await ws.send(json.dumps(reply))
            self._tick.set()

    @contextlib.asynccontextmanager
    async def _beating(self, ws: ClientConnection) -> AsyncIterator[None]:
        """§9.1, opt-in: a `ping` every `heartbeat_s` of virtual time while `ws` is open, so a
        socket whose reads stalled still has inbound traffic (`heartbeat_timeout`: 45 s of none)."""
        beat = None if self.heartbeat_s is None else spawn(self._beat(ws), name="chaos-ws-beat")
        try:
            yield
        finally:
            if beat is not None:
                beat.cancel()
                await asyncio.gather(beat, return_exceptions=True)

    async def _beat(self, ws: ClientConnection) -> None:
        for n in itertools.count(1):
            await self.clock.sleep(self.heartbeat_s or 0.0)
            ms = int(self.clock.wall_s() * 1000)
            await ws.send(json.dumps({"t": "ping", "id": f"c-hb-{n}", "p": {"client_ms": ms}}))

    def _on(self, f: dict[str, Any]) -> dict[str, Any] | None:
        t, ch = f["t"], f.get("ch", "")
        p: Any = f.get("p")
        if t == "welcome":
            return {"t": "auth", "id": "a", "p": {"access_token": self.access}}
        if t == "auth_ok":
            self.sessions += 1
            self.expires_ms = p["token_expires_at_ms"]
            self._note("auth_ok", self.sessions)
            self._orders(not p["kill_switch"]["engaged"])
            return {"t": "sub", "id": "s", "p": {"topics": self.topics}}
        if t == "ping":
            return {"t": "pong", "id": f.get("id"), "p": {}}
        if t == "sub_ok":
            refused = {r["ch"]: r["error"]["code"] for r in p["results"] if not r["ok"]}
            self.denied.update(refused)
            self.topics = [e for e in self.topics if e["ch"] not in refused]  # never retried
        elif t in {"snap", "d"} and f.get("s") is not None:  # `s: null` = non-final chunk
            if t == "snap":
                self.snapped.add(ch)
            elif ch not in self.seq or f["s"] != self.seq[ch] + 1:
                self.gaps.append(f"{ch}: s={f['s']} after {self.seq.get(ch)}")
            self.seq[ch] = f["s"]
            if t == "d" and ch == "system":  # C12: order entry follows these two kinds
                if p["kind"] == "shutdown_notice":
                    self._orders(False)
                elif p["kind"] == "kill_switch":
                    self._orders(not p["kill_switch"]["engaged"])
        return None

    def _orders(self, enabled: bool) -> None:
        if enabled != self.order_entry:
            self.order_entry = enabled
            self._note("order_entry", enabled)

    @property
    def synced(self) -> bool:
        """Every topic held is snapshotted on the current connection."""
        return self.snapped == {e["ch"] for e in self.topics}

    def system(self, kind: str) -> list[int]:
        """Indices in `frames` of the `system` frames of this `kind` (§15.9)."""
        sys = ((i, f) for i, f in enumerate(self.frames) if f["t"] == "d" and f["ch"] == "system")
        return [i for i, f in sys if f["p"]["kind"] == kind]

    async def until(self, pred: Callable[[], bool], what: str) -> None:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(TIMEOUT_S):
                while not pred() and self.task is not None and not self.task.done():
                    self._tick.clear()
                    await self._tick.wait()
        if not pred():
            pytest.fail(f"{what}: not reached in {TIMEOUT_S}s; {self.task!r}; log {self.log[-6:]}")

    async def next_backoff(self) -> float:
        """The delay of the client's next backoff sleep, once it is parked in it."""
        try:
            async with asyncio.timeout(TIMEOUT_S):
                return await self.backoffs.get()
        except TimeoutError:
            pytest.fail(f"client never backed off; log tail {self.log[-6:]}")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


async def each(clients: list[Client], pred: Callable[[Client], bool], what: str) -> None:
    """Wait (bounded, per client) until `pred` holds for every client."""
    for c in clients:
        await c.until(functools.partial(pred, c), what)

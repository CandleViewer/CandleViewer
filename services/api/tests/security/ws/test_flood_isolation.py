"""E17-X02 flood isolation (#415 slice d2; threat model `E17-ws-gateway.md` §7, AC-19; budget #6).

One user hits every limit of `23-ws-protocol.md` §16.2 at once on a real uvicorn gateway (the
E17-Q02 chaos rig, flag on) while another user's `book.BTCUSDT.50` stream is timed: the same N
updates on fresh stacks, that user alone, then beside the flood.

The flood is eight sockets of one user. Three hold 200 subscriptions and two hold 40 symbols, and
each sends a 50-topic `sub` that its cap refuses whole on every third update (5.3 frames a second
of gateway time, about the pace of its 300-a-minute limit). One loops `resync` until its stream
is revoked, one sends 40 `ping`s in one go, one stays silent; three more connections come in,
each the ninth. Each refusal is checked whole (frame, close code, metric). The second user must
see every update, in order, with no `revoked`, inside the budget. The rig has no audit sink: the
audit rows of these refusals are slice d1's.

Timing is on the loop clock, from `book_step()` to the frame's arrival at the rig's client
through its proxy, with the flood's sockets in the same loop. That is more than budget #6's span
(book update to outbound frame emitted), so a pass here is a pass there; the gateway's own
`cv_ws_fanout_seconds` reads the rig's virtual clock and cannot show wall time. The gateway's
clock is virtual, so 16 updates take a few milliseconds of real time and the flood arrives about
20 times faster than a client could sustain it. N = 400: the p95 is the 380th sample with 20
above it, so the ten or so ticks with a one-off event and a few scheduler stalls cannot move it,
while a cost on every update does. The tolerance is 8 ms on the median: about three times what the
flood costs here (2 to 2.7 ms), 40 % of the budget. A flood that makes the typical update wait
that much longer is a regression even where the p95 stays under 20 ms. The median, not the p95,
because a loaded runner moves a p95 by a scheduler time slice (several ms), the median by little.

`TCP_NODELAY`: the rig binds its own listening socket (`socket.create_server`), so the sockets it
accepts lack the option asyncio sets on the ones uvicorn binds by host and port. With Nagle on,
more than one update in twenty waits about 40 ms for the client's delayed ACK, which nothing here
causes, so `nodelay_stack` sets it. AC-19 at load scale (8 sockets x 40 symbols of `book.*.200`
and a heatmap) stays with E17-Q03 (#568, k6). `perf`: this runs in `py-perf` (C-13.9).
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import math
import socket
import statistics
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from prometheus_client import REGISTRY
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin, Subprotocol

from candleviewer.observability.context import spawn
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.chaos.ws._proxy import HOST
from tests.chaos.ws._server import BOOK, SEED, Stack, flag_on
from tests.contract.ws._support import ORIGIN
from tests.security.ws._raw import delta

pytestmark = pytest.mark.perf

N = 400  # updates timed in each run
TICK_S = 1 / 16  # gateway time per update: 16 a second, over the 50 ms minimum of `throttle_ms`
BUDGET_MS = 20.0  # budget #6 (06-performance-and-load-standard.md §2): p95 of the fan-out
TOLERANCE_MS = 8.0  # what the flood may add to that user's median: about 3 x its cost, 40 % of 20
TIMEOUT_S = 5.0  # a hang guard on every wait, never a latency bound
LEGIT, FLOODER = uuid.UUID(int=0x2D01), uuid.UUID(int=0x2D02)
CAPS, SYMS, EVERY = 3, 2, 3  # sockets at each cap; each sends on every EVERY-th update
RESYNC_AT, CONNECT_AT, BURST_AT, BURST = 10, (50, 100, 150), 200, 40  # updates; frames in one go
STREAM = "trades.BTCUSDT"
HELD_SUBS = [f"footprint.BTCUSDT.tick.{n}" for n in range(1, 201)]  # 200: the cap
OVER_SUBS = [f"footprint.BTCUSDT.tick.{n}" for n in range(201, 251)]  # 50: the most a `sub` holds
HELD_SYMS = [f"trades.S{n:02d}USDT" for n in range(40)]  # 40 symbols: the cap
OVER_SYMS = [f"trades.S{n:02d}USDT" for n in range(40, 90)]


def p95(ms: list[float]) -> float:
    """Nearest rank: the 380th smallest of 400, so 20 samples sit above it."""
    return sorted(ms)[math.ceil(0.95 * len(ms)) - 1]


def total(name: str) -> float:
    """`name` summed over every label set, so a close or a revocation of anyone shows."""
    return sum(s.value for fam in REGISTRY.collect() for s in fam.samples if s.name == name)


def frame(t: str, id: str, p: dict[str, Any] | None = None, **envelope: Any) -> str:
    return json.dumps({"t": t, "id": id, **envelope, "p": p or {}})


def sub(topics: list[str], id: str) -> str:
    return frame("sub", id, {"topics": [{"ch": ch} for ch in topics]})


OVER_SUBS_FRAME, OVER_SYMS_FRAME = sub(OVER_SUBS, "over"), sub(OVER_SYMS, "over")


def holds(xs: list[float], n: int) -> Callable[[], bool]:
    """True once `xs` has `n` items."""
    return lambda: len(xs) >= n


def whole(f: dict[str, Any]) -> dict[str, Any]:
    """A received frame as documented: its `ts` is the gateway's clock, so only its presence."""
    assert isinstance(f.pop("ts", 0), int)
    return f


def refused(ch: str, code: str, message: str) -> dict[str, Any]:
    return {"ch": ch, "ok": False, "error": {"code": code, "message": message, "retryable": True}}


def err(id: str, code: ErrorCode, **envelope: Any) -> dict[str, Any]:
    meta = ERROR_META[code]
    p = {"code": code.value, "message": meta.title, "retryable": meta.retryable, "close": False}
    return {"t": "err", "id": id, **envelope, "p": p}


def bye(reason: str, message: str, **more: Any) -> dict[str, Any]:
    """§4.4: each close of these legs is `4429` with `reconnect: true`."""
    p = {"code": 4429, "reason": reason, "message": message, "reconnect": True, **more}
    return {"t": "bye", "p": p}


class Raw:
    """A socket of the flooding user, dialled straight at the gateway. It sends what it likes
    and keeps every frame it is sent as text, parsed after the run and off the timed path."""

    def __init__(self, ws: ClientConnection) -> None:
        self.ws, self.texts, self._tick = ws, list[str](), asyncio.Event()
        self.task = spawn(self._read(), name="flood-reader")

    async def _read(self) -> None:
        with contextlib.suppress(ConnectionClosed):
            async for text in self.ws:
                self.texts.append(str(text))
                self._tick.set()
        self._tick.set()

    async def until(self, pred: Callable[[], bool], what: str) -> None:
        try:
            async with asyncio.timeout(TIMEOUT_S):
                while not pred():
                    self._tick.clear()
                    await self._tick.wait()
        except TimeoutError:
            pytest.fail(f"{what}: still waiting after {TIMEOUT_S}s; last frames {self.texts[-3:]}")

    def count(self, t: str) -> int:
        return sum(text.startswith(f'{{"t":"{t}"') for text in self.texts)

    def frames(self, *, of: str | None = None, id: str | None = None) -> list[dict[str, Any]]:
        parsed = [json.loads(text) for text in self.texts]
        return [f for f in parsed if of in (None, f["t"]) and id in (None, f.get("id"))]


async def dial(stack: Stack, token: str) -> Raw:
    """A socket that has said `hello` and `auth` and holds its `auth_ok`."""
    ws = await connect(
        f"ws://{HOST}:{stack.port}/ws",
        origin=Origin(ORIGIN),
        subprotocols=[Subprotocol("cv.v1.json")],
        proxy=None,
        ping_interval=None,
        open_timeout=TIMEOUT_S,
        max_size=4 * 1024 * 1024,
    )
    raw = Raw(ws)
    await ws.send(frame("hello", "h", {"client": "flood", "protocol": "cv.v1"}))
    await raw.until(lambda: raw.count("welcome") == 1, "welcome")
    await ws.send(frame("auth", "a", {"access_token": token}))
    await raw.until(lambda: raw.count("auth_ok") == 1, "auth_ok")
    return raw


async def fill(raw: Raw, topics: list[str]) -> Raw:
    """Subscribe to `topics`, 50 to a `sub`, and wait for every snapshot: nothing is in flight."""
    for i in range(0, len(topics), 50):
        await raw.ws.send(sub(topics[i : i + 50], f"f{i}"))
    await raw.until(lambda: raw.count("snap") == len(topics), "snapshots")
    return raw


@dataclass
class Flood:
    """The flooding user's eight sockets, and what each sends ahead of each update."""

    stack: Stack
    token: str
    idle: Raw
    caps: list[Raw]
    syms: list[Raw]
    resync: Raw
    burst: Raw
    extra: list[Raw] = field(default_factory=list)
    dialing: asyncio.Task[Raw] | None = None
    sent: Counter[Raw] = field(default_factory=Counter)
    again: int = 0

    @classmethod
    async def open(cls, stack: Stack) -> Flood:
        token = (await stack.sessions.mint(str(FLOODER))).access_token
        idle = await dial(stack, token)
        await stack.clock.advance(TICK_S)  # the rest are heard from later: this is the oldest idle
        caps = [await fill(await dial(stack, token), HELD_SUBS) for _ in range(CAPS)]
        syms = [await fill(await dial(stack, token), HELD_SYMS) for _ in range(SYMS)]
        resync = await fill(await dial(stack, token), [STREAM])
        return cls(stack, token, idle, caps, syms, resync, await dial(stack, token))

    def sockets(self) -> list[Raw]:
        return [self.idle, *self.caps, *self.syms, self.resync, self.burst, *self.extra]

    async def close(self) -> None:
        if self.dialing is not None:
            self.dialing.cancel()
        for raw in self.sockets():
            with contextlib.suppress(ConnectionClosed):
                await raw.ws.close()
        await asyncio.gather(*(raw.task for raw in self.sockets()), return_exceptions=True)

    async def tick(self, i: int) -> None:
        """What the flood sends ahead of update `i`, and the start of a connection."""
        for k, raw in enumerate([*self.caps, *self.syms]):
            if i % EVERY == k % EVERY:
                await raw.ws.send(OVER_SUBS_FRAME if k < CAPS else OVER_SYMS_FRAME)
                self.sent[raw] += 1
        if RESYNC_AT <= i < RESYNC_AT + 6:  # the sixth in a minute is a loop
            await self.resync.ws.send(frame("resync", f"r{i}", {"reason": "manual"}, ch=STREAM))
        elif i > RESYNC_AT + 5 and i % 4 == 0:  # the revoked stream's five are spent for a minute
            await self.resync.ws.send(sub([STREAM], "again"))
            self.again += 1
        if i % 4 == 2 and i < BURST_AT:  # heard from, so never the oldest idle
            await self.burst.ws.send(frame("ping", "k"))
        if i in CONNECT_AT:
            self.dialing = spawn(dial(self.stack, self.token), name="flood-dial")
        if i == BURST_AT:
            with contextlib.suppress(ConnectionClosed):  # the second refusal closes the socket
                for n in range(BURST):
                    await self.burst.ws.send(frame("ping", f"b{n}"))

    async def settle(self) -> None:
        if self.dialing is not None:
            self.extra.append(await self.dialing)
            self.dialing = None


@contextlib.asynccontextmanager
async def nodelay_stack() -> AsyncIterator[Stack]:
    """The rig's flag-on stack, its accepted sockets with `TCP_NODELAY` (module doc)."""
    async with flag_on() as stack:
        stack._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        yield stack


async def measure(stack: Stack, flood: Flood | None) -> tuple[list[float], list[tuple[int, Any]]]:
    """N updates of the recorded book to a user on `book`, each timed from its publish to its
    arrival: its milliseconds, and the `(s, body)` of each `d`. The flood, if any, sends ahead of
    each update, so its frames are in the loop at the publish. The user must see all of them."""
    loop = asyncio.get_running_loop()
    arrived, stream = list[float](), list[tuple[int, Any]]()

    def tap(f: dict[str, Any], _text: str | bytes) -> None:
        if f["t"] == "d" and f["ch"] == BOOK:
            arrived.append(loop.time())
            stream.append((f["s"], f["p"]))

    b = stack.client(await stack.sessions.mint(str(LEGIT)), SEED)
    b.on_data = tap
    await b.start({"ch": BOOK}).until(lambda: b.synced, "first snapshot")
    ms = list[float]()
    gc.collect()
    gc.disable()  # a full collection of this process's heap stalls the loop for ~100 ms, once
    try:
        for i in range(N):
            if flood is not None:
                await flood.tick(i)
            published = loop.time()
            stack.book_step()
            await b.until(holds(arrived, i + 1), "update")
            ms.append((arrived[i] - published) * 1000)
            if flood is not None:
                await flood.settle()
            await stack.clock.advance(TICK_S)
    finally:
        gc.enable()
    assert [s for s, _ in stream] == list(range(2, N + 2))  # the snapshot took `s` 1: no gap
    assert (b.gaps, b.closes, b.sessions) == ([], [], 1)  # never closed, never reconnected
    assert not {f["t"] for f in b.frames} & {"bye", "err", "revoked"}  # nothing refused or revoked
    return ms, stream


def marks() -> dict[str, Callable[[], float]]:
    """The counters the flood's refusals move, each read as the change since now."""
    series = {
        "caps": ("cv_ws_subscribe_total", {"topic": "footprint", "result": "subscription_limit"}),
        "syms": ("cv_ws_subscribe_total", {"topic": "trades", "result": "subscription_limit"}),
        "again": ("cv_ws_subscribe_total", {"topic": "trades", "result": "resync_rate_limited"}),
        "resync_err": ("cv_ws_errors_total", {"code": "resync_rate_limited"}),
        "revoked": ("cv_ws_revoked_total", {"reason": "resync_rate_limited"}),
        "rate_err": ("cv_ws_errors_total", {"code": "client_rate_limited"}),
        "rate_closed": ("cv_ws_closes_total", {"reason": "client_rate_limited"}),
        "evicted": ("cv_ws_closes_total", {"reason": "too_many_connections"}),
    }
    return {key: delta(name, **labels) for key, (name, labels) in series.items()}


def check_flood(f: Flood, moved: dict[str, float]) -> None:
    """Every leg of the flood got its documented refusal or close, whole."""
    for group, over, text in (
        (f.caps, OVER_SUBS, "200 subscriptions reached."),
        (f.syms, OVER_SYMS, "40 symbols per connection reached."),
    ):  # WS-D04: each refused topic of each frame, and the socket held open
        results = [refused(ch, "subscription_limit", text) for ch in over]
        reply: dict[str, Any] = {"t": "sub_ok", "id": "over", "p": {"results": results}}
        for raw in group:
            assert [whole(x) for x in raw.frames(id="over")] == [reply] * f.sent[raw]
            assert raw.frames(of="bye") == [] and raw.ws.close_code is None
    seen = f.resync.frames()
    shown = [x for x in seen if x["t"] in {"snap", "err", "revoked"} or x.get("id") == "again"]
    assert [x["t"] for x in shown] == ["snap"] * 6 + ["err", "revoked"] + ["sub_ok"] * f.again
    assert [x["meta"]["reason"] for x in shown[:6]] == ["initial"] + ["client_resync"] * 5
    last = f"r{RESYNC_AT + 5}"  # AC-17: the sixth resync of the minute
    assert shown[6] == err(last, ErrorCode.RESYNC_RATE_LIMITED, ch=STREAM)
    held = f.resync.frames(of="sub_ok")[0]["p"]["results"][0]["sub_id"]
    p: dict[str, Any] = {"reason": "resync_rate_limited", "resubscribe_allowed": False}
    p |= {"message": "Too many resyncs on this topic.", "sub_id": held}
    assert whole(shown[7]) == {"t": "revoked", "ch": STREAM, "p": p}
    text = "Rebuild budget spent (5 a minute per topic); not subscribed."
    spent = refused(STREAM, "resync_rate_limited", text)
    again = {"t": "sub_ok", "id": "again", "p": {"results": [spent]}}
    assert [whole(x) for x in shown[8:]] == [again] * f.again  # the stream cannot restart
    window = sum(1 for j in range(BURST_AT) if j % 4 == 2 and (BURST_AT - j) * TICK_S < 1.0)
    passed = 30 - window  # AC-11: 30 frames in the second, the 31st is refused
    pongs = [x["id"] for x in f.burst.frames(of="pong") if x["id"].startswith("b")]
    assert pongs == [f"b{n}" for n in range(passed)]
    refusals = [whole(x) for x in f.burst.frames() if x["t"] in {"err", "bye"}]
    limited = bye("client_rate_limited", "Inbound frame rate exceeded.", retry_after_ms=1000)
    assert refusals == [err(f"b{passed}", ErrorCode.CLIENT_RATE_LIMITED), limited]
    first = bye("too_many_connections", "Connection limit per user exceeded; oldest idle closed.")
    for raw in (f.idle, *f.extra[:2]):  # AC-15: each ninth connection closes the oldest idle one
        assert whole(raw.frames()[-1]) == first
    assert [raw.count("auth_ok") for raw in f.extra] == [1, 1, 1]  # and is admitted itself
    held_open = [*f.caps, *f.syms, f.resync, f.extra[2]]
    assert [raw.ws.close_code for raw in held_open] == [None] * 7
    assert [raw.ws.close_code for raw in (f.idle, *f.extra[:2], f.burst)] == [4429] * 4
    assert moved == {
        "caps": 50 * sum(f.sent[raw] for raw in f.caps),
        "syms": 50 * sum(f.sent[raw] for raw in f.syms),
        "again": f.again,
        "resync_err": 1,
        "revoked": 1,
        "rate_err": 1,
        "rate_closed": 1,
        "evicted": 3,
    }


def figures(ms: list[float]) -> str:
    s = sorted(ms)
    p50, p99 = s[len(s) // 2], s[math.ceil(0.99 * len(s)) - 1]
    return f"p50 {p50:.2f}, p95 {p95(ms):.2f}, p99 {p99:.2f}, max {s[-1]:.2f} ms"


async def test_x02_ac_19_a_flood_of_every_limit_leaves_anothers_book_stream_in_budget() -> None:
    async with nodelay_stack() as quiet:
        alone, bodies = await measure(quiet, None)
    moved, closes, revokes = marks(), total("cv_ws_closes_total"), total("cv_ws_revoked_total")
    async with nodelay_stack() as loud:
        flood = await Flood.open(loud)
        try:
            beside, same = await measure(loud, flood)
            check_flood(flood, {key: read() for key, read in moved.items()})
            # Nothing but the flood's own sockets was closed or revoked: not the second user.
            assert total("cv_ws_closes_total") - closes == 4  # three evictions and the burst
            assert total("cv_ws_revoked_total") - revokes == 1  # the resync loop
        finally:
            await flood.close()
    assert same == bodies  # the same bodies, in the same order, as without the flood
    print(f"#415 d2: alone {figures(alone)}; beside the flood {figures(beside)}")
    assert p95(beside) <= BUDGET_MS, f"p95 {p95(beside):.2f} ms past budget #6 ({BUDGET_MS} ms)"
    added = statistics.median(beside) - statistics.median(alone)
    assert added <= TOLERANCE_MS, f"the flood added {added:.2f} ms to the median"

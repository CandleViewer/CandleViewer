"""E17-X02 flood isolation (#415 slice d2; threat model `E17-ws-gateway.md` §7, AC-19; budget #6).

AC-19's isolation clause (no other client sees a sequence gap or a latency regression), at a
sustained pace. One user hits the five limits the test drives, all at once, on a real uvicorn
gateway (the E17-Q02 chaos rig, flag on): 200 subscriptions and 40 symbols per connection, 8
connections per user, 30 frames a second inbound and 5 resyncs a minute per topic
(`23-ws-protocol.md` §16.2). Another user's `book.BTCUSDT.50` stream is timed meanwhile: the same
N updates on fresh stacks, that user alone, then beside the flood. Scope: sustained pace (about
the 300-a-minute limit), refusals only, flag on, JSON, no audit sink; other rates and shapes are
not measured here. AC-19's own action (8 sockets x 40 symbols of `book.*.200` and a heatmap)
stays with E17-Q03 (#568, k6).

The flood is eight sockets of one user. Three hold 200 subscriptions and two hold 40 symbols, and
each sends a 50-topic `sub` that its cap refuses whole on every third update (5.3 frames a second
of gateway time, about the pace of its 300-a-minute limit; that limit caps N). One loops `resync`
until its stream is revoked, one sends 40 `ping`s in one go, one stays silent; three more
connections come in, each the ninth. Each refusal is checked whole (frame, close code, metric).
The second user must see every update, in order, with no `revoked`, inside the budget.

The rig passes the gateway no audit sink, so no audit write is in the timing. The rows exist: the
four closes write `ws.connection.closed` (asserted by slice d1) and the revocation writes
`ws.subscription.revoked` (`tests/unit/ws/test_ws_audit_trail.py`). The cap and resync refusals
on these public topics write no `ws.subscribe.denied` row, by design: only authorisation refusals
and refusals of private topics are audited.

Timing is on the loop clock, from `book_step()` to the frame's arrival at the rig's client
through its proxy, with the flood's sockets in the same loop. That is more than budget #6's span
(book update to outbound frame emitted), so a pass here is a pass there; the gateway's own
`cv_ws_fanout_seconds` reads the rig's virtual clock and cannot show wall time. The gateway's
clock is virtual too: a second of it (16 updates) takes about 50 ms of real time. The flood's
frames (one or two refused `sub`s on each tick, the other legs' frames on theirs, the 40 `ping`s
once) are written ahead of each update, so they are queued in the loop at the publish. Since the
fair fix (#3884) the reader yields after each frame, and the update is delivered before they are
handled: the cost of handling them falls between one update's arrival and the next tick, outside
the timed span. So this test pins the other user's budget beside the flood, through that user's
own path, and not the cost of the flooding user's own handling: a slower refusal path does not
move it. The fair fix's own real-gateway test pins the scheduling. N = 400: the p95 is the 380th
sample with 20 above it, so the ten or so ticks with a one-off event and a few scheduler stalls
cannot move it, while a cost on every update does. Those ticks have a loose bound of their own,
`STALL_MS` on the slowest update: 5 times the budget and 3.7 times the slowest update seen when
it was chosen, with the loop's CPUs shared with two busy loops (27 ms): a stall, not noise. The
tolerance is 8 ms on the median: about three times what the flood costs here (2 to 2.7 ms), 40 %
of the budget. A flood that makes the typical update wait that much longer is a regression even
where the p95 stays under 20 ms. The median, not the p95, because a loaded runner moves a p95 by
a scheduler time slice (several ms), the median by little.

`TCP_NODELAY`: the rig binds its own listening socket (`socket.create_server`), so the sockets it
accepts lack the option asyncio sets on the ones uvicorn binds by host and port. With Nagle on,
more than one update in twenty waits about 40 ms for the client's delayed ACK, which nothing here
causes, so `nodelay_stack` sets it. `perf`: this runs in `py-perf` (C-13.9).
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import gc
import json
import math
import socket
import statistics
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import msgpack
import pytest
from prometheus_client import REGISTRY
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin, Subprotocol

import candleviewer.ws.gateway as gateway
from candleviewer.observability.context import spawn
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from candleviewer.ws.codec import MAX_MSGPACK_VALUES, decode_client_frame
from candleviewer.ws.lifecycle import (
    MAX_CONNECTIONS_PER_USER,
    RATE_PER_MINUTE,
    RATE_PER_SECOND,
    DecodeBudget,
    InboundRateLimiter,
)
from candleviewer.ws.limits import (
    MAX_INBOUND_FRAME_BYTES,
    MAX_JSON_CONTAINERS,
    inbound_frame_weight,
    json_values_over_count,
)
from tests.chaos.ws._proxy import HOST
from tests.chaos.ws._server import BOOK, SEED, Stack, flag_on
from tests.contract.ws._support import ORIGIN
from tests.security.ws._raw import delta

pytestmark = pytest.mark.perf

N = 400  # updates timed in each run; the cap sockets' own minute limit caps it (`SETUP_FRAMES`)
TICK_S = 1 / 16  # gateway time per update: 16 a second, over the 50 ms minimum of `throttle_ms`
BUDGET_MS = 20.0  # budget #6 (06-performance-and-load-standard.md §2): p95 of the fan-out
TOLERANCE_MS = 8.0  # what the flood may add to that user's median: about 3 x its cost, 40 % of 20
STALL_MS = 100.0  # the slowest of the N updates: 5 x the budget, a stall bound, not a latency one
TIMEOUT_S = 5.0  # a hang guard on every wait, never a latency bound
LEGIT, FLOODER, SECOND = uuid.UUID(int=0x2D01), uuid.UUID(int=0x2D02), uuid.UUID(int=0x2D03)
CAPS, SYMS, EVERY = 3, 2, 3  # sockets at each cap; each sends on every EVERY-th update
RESYNC_AT, CONNECT_AT, BURST_AT, BURST = 10, (50, 100, 150), 200, 40  # updates; frames in one go
STREAM = "trades.BTCUSDT"
HELD_SUBS = [f"footprint.BTCUSDT.tick.{n}" for n in range(1, 201)]  # 200: the cap
OVER_SUBS = [f"footprint.BTCUSDT.tick.{n}" for n in range(201, 251)]  # 50: the most a `sub` holds
HELD_SYMS = [f"trades.S{n:02d}USDT" for n in range(40)]  # 40 symbols: the cap
OVER_SYMS = [f"trades.S{n:02d}USDT" for n in range(40, 90)]
SETUP_FRAMES = 2 + len(HELD_SUBS) // 50  # what a cap socket sent before the run: hello, auth, subs


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
    """A received frame as documented, `ts` aside: the gateway's clock, an int where the frame has
    one (an `err` has none, §3.1), so that is all that is checked of it."""
    assert isinstance(f.pop("ts", 0), int)
    return f


def refused(ch: str, code: str, message: str) -> dict[str, Any]:
    return {"ch": ch, "ok": False, "error": {"code": code, "message": message, "retryable": True}}


def err(id: str | None, code: ErrorCode, **envelope: Any) -> dict[str, Any]:
    """An `err` frame; one with no `id` answers a frame that was never read."""
    meta = ERROR_META[code]
    p = {"code": code.value, "message": meta.title, "retryable": meta.retryable, "close": False}
    return {"t": "err", **({} if id is None else {"id": id}), **envelope, "p": p}


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
            async for text in self.ws:  # a MessagePack frame is kept as its JSON text
                kept = text if isinstance(text, str) else _as_text(msgpack.unpackb(text))
                self.texts.append(kept)
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
        """Frames of type `t` on the topics this test subscribed to: the `system` snap every
        socket gets after `auth_ok` (23 §12.1, #4992) is not one of them."""
        return sum(
            text.startswith(f'{{"t":"{t}"') and '"ch":"system"' not in text for text in self.texts
        )

    def frames(self, *, of: str | None = None, id: str | None = None) -> list[dict[str, Any]]:
        parsed = [json.loads(text) for text in self.texts]
        return [f for f in parsed if of in (None, f["t"]) and id in (None, f.get("id"))]

    async def close(self) -> None:
        with contextlib.suppress(ConnectionClosed):
            await self.ws.close()
        await asyncio.gather(self.task, return_exceptions=True)


def _as_text(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


async def dial(stack: Stack, token: str, subprotocol: str = "cv.v1.json") -> Raw:
    """A socket that has said `hello` and `auth` and holds its `auth_ok`; one that fails on the
    way is closed, not left to the teardown."""

    def wire(text: str) -> str | bytes:
        if subprotocol == "cv.v1.json":
            return text
        packed: bytes = msgpack.packb(json.loads(text))
        return packed

    ws = await connect(
        f"ws://{HOST}:{stack.port}/ws",
        origin=Origin(ORIGIN),
        subprotocols=[Subprotocol(subprotocol)],
        proxy=None,
        ping_interval=None,
        open_timeout=TIMEOUT_S,
        max_size=4 * 1024 * 1024,
    )
    raw = Raw(ws)
    try:
        await ws.send(wire(frame("hello", "h", {"client": "flood", "protocol": "cv.v1"})))
        await raw.until(lambda: raw.count("welcome") == 1, "welcome")
        await ws.send(wire(frame("auth", "a", {"access_token": token})))
        await raw.until(lambda: raw.count("auth_ok") == 1, "auth_ok")
    except BaseException:
        await raw.close()
        raise
    return raw


async def send(raw: Raw, text: str | bytes) -> bool:
    """Send `text`; False if the gateway had closed the socket (the end of the run checks which)."""
    with contextlib.suppress(ConnectionClosed):
        await raw.ws.send(text)
        return True
    return False


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
        async with contextlib.AsyncExitStack() as dialled:  # a dial that fails closes the earlier

            async def new(topics: list[str] | None = None) -> Raw:
                raw = await dial(stack, token)
                dialled.push_async_callback(raw.close)
                return raw if topics is None else await fill(raw, topics)

            idle = await new()
            await stack.clock.advance(TICK_S)  # the rest are heard from later: this is the oldest
            caps = [await new(HELD_SUBS) for _ in range(CAPS)]
            syms = [await new(HELD_SYMS) for _ in range(SYMS)]
            resync = await new([STREAM])
            flood = cls(stack, token, idle, caps, syms, resync, await new())
            dialled.pop_all()  # the flood owns them now: `close`
        return flood

    def sockets(self) -> list[Raw]:
        return [self.idle, *self.caps, *self.syms, self.resync, self.burst, *self.extra]

    async def close(self) -> None:
        if self.dialing is not None:
            self.dialing.cancel()
            (late,) = await asyncio.gather(self.dialing, return_exceptions=True)
            if isinstance(late, Raw):  # it finished before the cancel: closed with the others
                self.extra.append(late)
        for raw in self.sockets():
            await raw.close()

    async def tick(self, i: int) -> None:
        """What the flood sends ahead of update `i`, and the start of a connection."""
        for k, raw in enumerate([*self.caps, *self.syms]):
            over = OVER_SUBS_FRAME if k < CAPS else OVER_SYMS_FRAME
            if i % EVERY == k % EVERY and await send(raw, over):
                self.sent[raw] += 1
        if RESYNC_AT <= i < RESYNC_AT + 6:  # the sixth in a minute is a loop
            await send(self.resync, frame("resync", f"r{i}", {"reason": "manual"}, ch=STREAM))
        elif i > RESYNC_AT + 5 and i % 4 == 0:  # the revoked stream's five are spent for a minute
            if await send(self.resync, sub([STREAM], "again")):
                self.again += 1
        if i % 4 == 2 and i < BURST_AT:  # heard from, so never the oldest idle
            await send(self.burst, frame("ping", "k"))
        if i in CONNECT_AT:
            self.dialing = spawn(dial(self.stack, self.token), name="flood-dial")
        if i == BURST_AT:
            for n in range(BURST):  # the second refusal closes the socket: the rest are moot
                if not await send(self.burst, frame("ping", f"b{n}")):
                    break

    async def settle(self) -> None:
        if self.dialing is not None:
            self.extra.append(await self.dialing)
            self.dialing = None


@contextlib.asynccontextmanager
async def nodelay_stack() -> AsyncIterator[Stack]:
    """The rig's flag-on stack, its accepted sockets with `TCP_NODELAY` (module doc). The rig has
    no accessor for its listening socket and is not edited here, so this reaches `_sock`: one
    line in `Stack._boot` would make it unnecessary."""
    async with flag_on() as stack:
        stack._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        yield stack


async def measure(
    stack: Stack, flood: Flood | HeavyFlood | SyncFlood | TwoFloods | None
) -> tuple[list[float], list[tuple[int, Any]]]:
    """N updates of the recorded book to a user on `book`, each timed from its publish to its
    arrival: its milliseconds, and the `(s, body)` of each `d`. The flood, if any, sends ahead of
    each update, so its frames are queued in the loop at the publish; the fair fix handles them
    after the update is delivered, so their handling is not in the timed span. The user must see
    all of them."""
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
    assert refusals == [err(None, ErrorCode.CLIENT_RATE_LIMITED), limited]  # unread: no `id`
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


async def test_x02_ac_19_isolation_clause_at_sustained_pace_book_stream_stays_in_budget() -> None:
    # N is capped by the cap sockets' own limit: a frame every EVERY updates is 320 a minute at
    # TICK_S, over RATE_PER_MINUTE, so a run long enough to send that many of them is refused.
    sent = math.ceil(N / EVERY) + SETUP_FRAMES
    assert sent <= RATE_PER_MINUTE, f"N = {N}: {sent} frames from a socket, over {RATE_PER_MINUTE}"
    async with nodelay_stack() as quiet:
        alone, bodies = await measure(quiet, None)
    moved, closes, revokes = marks(), total("cv_ws_closes_total"), total("cv_ws_revoked_total")
    async with nodelay_stack() as loud:
        flood = await Flood.open(loud)
        try:
            beside, same = await measure(loud, flood)
            print(f"#415 d2: alone {figures(alone)}; beside the flood {figures(beside)}")
            check_flood(flood, {key: read() for key, read in moved.items()})
            # Nothing but the flood's own sockets was closed or revoked: not the second user.
            assert total("cv_ws_closes_total") - closes == 4  # three evictions and the burst
            assert total("cv_ws_revoked_total") - revokes == 1  # the resync loop
        finally:
            await flood.close()
    assert same == bodies  # the same bodies, in the same order, as without the flood
    assert p95(beside) <= BUDGET_MS, f"p95 {p95(beside):.2f} ms past budget #6 ({BUDGET_MS} ms)"
    added = statistics.median(beside) - statistics.median(alone)
    assert added <= TOLERANCE_MS, f"the flood added {added:.2f} ms to the median"
    assert max(beside) <= STALL_MS, f"an update took {max(beside):.2f} ms, past {STALL_MS} ms"


# -- frames at the inbound caps, as fast as the inbound rate admits them (#4924) ---------------
#
# The same user's eight sockets, the per-user cap, each send `ping`s at every inbound cap at once:
# the frame cap, the container cap and the value bound (`codec.MAX_MSGPACK_VALUES`, over-counted
# on the text), in three shapes: values that are numbers, values that are short escaped strings,
# or one string. Each frame takes `inbound_frame_weight` tokens of its socket's inbound rate. Seven
# send them as often as that rate admits over the run (`paced_every`), and twice a frame of
# numbers up to the frame cap, past the value bound; the eighth spends a second's tokens at once
# and sends two more. Every frame is charged before it is decoded, and none past the bound is
# decoded (a spy on the JSON decoder): each gets `frame_malformed` with no `id`, a strike of three.
# The paced frames and the burst's first are admitted and answered; the two the rate refuses are
# never decoded, get their `err` with no `id` and the `4429` close, and move the metrics. The
# other user's stream is timed as above. The refusals' audit row is the close's
# (`test_limits_abuse.py`).

HEAVY_AT = 200  # the update before which the eighth socket spends its second
OVER_AT = (100, 300)  # the updates before which each paced socket sends a frame past the bound
HEAVY_MIN = MAX_INBOUND_FRAME_BYTES // 2  # what the `_parse` spy counts as one of these frames


def weight_of(text: str) -> int:
    """The tokens a JSON frame takes before it is decoded (§8.5): its bytes and its values."""
    counted = min(json_values_over_count(text), MAX_MSGPACK_VALUES + 1)
    return inbound_frame_weight(len(text.encode()), counted)


def paced_every(weight: int, spent: int, other: int = 0) -> int:
    """The fewest updates between a socket's frames of `weight` tokens that its inbound rate admits
    for the whole run (all of it inside one minute): the minute's tokens, less `hello`, `auth` and
    the `spent` other tokens, spread over the N updates; and in any second those frames and one
    `other` frame (0: none) within its 30."""
    run_s = N * TICK_S
    assert run_s < 60.0  # one window of the minute holds the run
    every = math.ceil(N / ((RATE_PER_MINUTE - 2 - spent) // weight))
    while math.ceil(1 / (every * TICK_S)) * weight + other > RATE_PER_SECOND:
        every += 1
    return every


SHAPES = {"numbers": "123456789", "escaped-strings": '"\\u00e9x"', "one-string": None}


def heavy(id: str, value: str | None) -> str:
    """A `ping` at the frame cap with `MAX_JSON_CONTAINERS` `[` and `{` in all (the envelope, `p`
    and its list hold three), then `value`s up to the value bound if any, then one string up to the
    frame cap."""
    head, tail = f'{{"t":"ping","id":"{id}","p":{{"pad":[', ',""]}}'
    body = ",".join(["[]"] * (MAX_JSON_CONTAINERS - 3))
    if value is not None:
        body += f",{value}" * (MAX_MSGPACK_VALUES - json_values_over_count(head + body + tail))
    pad = "x" * (MAX_INBOUND_FRAME_BYTES - len(head + body + tail))
    text = f'{head}{body},"{pad}"]}}}}'
    assert text.count("[") + text.count("{") == MAX_JSON_CONTAINERS
    assert len(text) == MAX_INBOUND_FRAME_BYTES
    assert (json_values_over_count(text) == MAX_MSGPACK_VALUES) is (value is not None)
    return text


def over(id: str) -> str:
    """A `ping` of numbers up to the frame cap: within the container cap, past the value bound."""
    head, tail = f'{{"t":"ping","id":"{id}","p":{{"pad":[0', "]}}"
    text = head + ",0" * ((MAX_INBOUND_FRAME_BYTES - len(head + tail)) // 2) + tail
    assert json_values_over_count(text) > MAX_MSGPACK_VALUES
    return text


class UserBudget:
    """The flooding user's decode budget as the gateway keeps it (`lifecycle.DecodeBudget`, its
    defaults), on the updates' clock: what the flood may send without a refusal. It starts full
    and is never ahead of the gateway's, whose earlier frames found it full too."""

    def __init__(self) -> None:
        self.budget = DecodeBudget()

    def admits(self, i: int, frames: list[tuple[int, int]]) -> bool:
        """Whether frames of `(tokens taken before decode, tokens given back after it)` sent in
        turn ahead of update `i` all pass; if so they are taken."""
        trial = copy.deepcopy(self.budget)
        for before, back in frames:
            if not trial.can(i * TICK_S, before):
                return False
            trial.take(before)
            trial.refund(back)
        self.budget = trial
        return True


@dataclass
class HeavyFlood:
    """The flooding user's sockets: `paced` at the per-socket pace, `burst` past the per-second
    limit once. `sent` counts the frames each paced socket sent that are answered with a `pong`."""

    paced: list[Raw]
    burst: Raw
    value: str | None
    sent: Counter[Raw] = field(default_factory=Counter)
    overs: Counter[Raw] = field(default_factory=Counter)
    user: UserBudget = field(default_factory=UserBudget)
    burst_admitted: int = 0

    @property
    def weight(self) -> int:
        return weight_of(heavy("h0", self.value))

    @property
    def every(self) -> int:
        other = weight_of(over("o0"))
        return paced_every(self.weight, len(OVER_AT) * other, other)

    @classmethod
    async def open(cls, stack: Stack, value: str | None) -> HeavyFlood:
        token = (await stack.sessions.mint(str(FLOODER))).access_token
        async with contextlib.AsyncExitStack() as dialled:  # a dial that fails closes the earlier
            sockets = list[Raw]()
            for _ in range(MAX_CONNECTIONS_PER_USER):
                sockets.append(raw := await dial(stack, token))
                dialled.push_async_callback(raw.close)
            flood = cls(sockets[:-1], sockets[-1], value)
            dialled.pop_all()  # the flood owns them now: `close`
        return flood

    async def close(self) -> None:
        for raw in (*self.paced, self.burst):
            await raw.close()

    async def tick(self, i: int) -> None:
        """What the flood sends ahead of update `i`. The burst is handled before the update: it
        ends in the socket's close, which the reader of the client waits for."""
        every, extra, over_extra = self.every, self.weight - 1, weight_of(over("o0")) - 1
        for k, raw in enumerate(self.paced):  # each only when the user's budget admits it too
            if i % every == k % every and self.user.admits(i, [(extra, 0)]):
                assert await send(raw, heavy(f"h{i}", self.value))
                self.sent[raw] += 1
            if i in OVER_AT and self.user.admits(i, [(over_extra, 0)]):
                assert await send(raw, over(f"o{i}"))
                self.overs[raw] += 1
        if i == HEAVY_AT:  # as many as its second's tokens and the user's budget admit, then two
            while self.burst_admitted < RATE_PER_SECOND // self.weight and self.user.admits(
                i, [(extra, 0)]
            ):
                self.burst_admitted += 1
            for n in range(self.burst_admitted + 2):  # the second refusal closes it
                if not await send(self.burst, heavy(f"b{n}", self.value)):
                    break
            await self.burst.until(lambda: self.burst.count("bye") == 1, "the burst's close")

    async def settle(self) -> None:
        """Each paced frame is answered before the next update: its handling is done."""
        for raw in self.paced:
            await raw.until(lambda raw=raw: raw.count("pong") == self.sent[raw], "pongs")


@pytest.mark.parametrize("value", list(SHAPES.values()), ids=list(SHAPES))
async def test_heavy_frames_from_every_socket_as_fast_as_admitted_stay_in_budget(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    parsed, decoded = list[int](), list[int]()
    parse, loads = gateway._Connection._parse, json.loads

    def spy_parse(conn: gateway._Connection, raw: str | bytes, *rest: Any) -> Any:
        if len(raw) > HEAVY_MIN:
            parsed.append(len(raw))
        return parse(conn, raw, *rest)

    def spy_loads(text: str) -> Any:
        decoded.append(json_values_over_count(text))
        return loads(text)

    async with nodelay_stack() as quiet:
        alone, bodies = await measure(quiet, None)
    errors = delta("cv_ws_errors_total", code="client_rate_limited")
    closes = delta("cv_ws_closes_total", reason="client_rate_limited")
    malformed = delta("cv_ws_errors_total", code="frame_malformed")
    monkeypatch.setattr(gateway._Connection, "_parse", spy_parse)
    monkeypatch.setattr(gateway, "json", SimpleNamespace(loads=spy_loads, dumps=json.dumps))
    async with nodelay_stack() as loud:
        flood = await HeavyFlood.open(loud, value)
        sent = math.ceil(N / flood.every) * flood.weight + len(OVER_AT) * weight_of(over("o0"))
        assert sent + 2 <= RATE_PER_MINUTE, f"{sent} tokens from a socket, past the minute's"
        try:
            beside, same = await measure(loud, flood)
            print(f"#4924 {value}: alone {figures(alone)}; beside the flood {figures(beside)}")
            unread = err(None, ErrorCode.FRAME_MALFORMED)
            for raw in flood.paced:  # every paced frame within the bounds admitted and answered
                assert raw.count("pong") == flood.sent[raw] > 0
                assert [whole(x) for x in raw.frames(of="err")] == [unread] * flood.overs[raw]
                assert raw.frames(of="bye") == []
            pongs = [x["id"] for x in flood.burst.frames(of="pong")]
            assert pongs == [f"b{n}" for n in range(flood.burst_admitted)]
            refusals = [whole(x) for x in flood.burst.frames() if x["t"] in {"err", "bye"}]
            limited = bye(
                "client_rate_limited", "Inbound frame rate exceeded.", retry_after_ms=1000
            )
            assert refusals == [err(None, ErrorCode.CLIENT_RATE_LIMITED), limited]
            assert flood.burst.ws.close_code == 4429
        finally:
            await flood.close()
    # Charged before decode: the two frames the rate refused never reached `_parse`, and no frame
    # past the value bound reached the decoder.
    over_bound = sum(flood.overs.values())
    assert len(parsed) == sum(flood.sent.values()) + over_bound + flood.burst_admitted
    assert max(decoded) <= MAX_MSGPACK_VALUES
    assert (errors(), closes(), malformed()) == (1, 1, over_bound)
    assert same == bodies  # the same bodies, in the same order, as without the flood
    assert p95(beside) <= BUDGET_MS, f"p95 {p95(beside):.2f} ms past budget #6 ({BUDGET_MS} ms)"
    added = statistics.median(beside) - statistics.median(alone)
    assert added <= TOLERANCE_MS, f"the flood added {added:.2f} ms to the median"
    assert max(beside) <= STALL_MS, f"an update took {max(beside):.2f} ms, past {STALL_MS} ms"


# -- frames at the value bound, every socket in the same round (#4924) ---------------------------
#
# The same user's eight sockets each hold a small frame with many values: in JSON, the container
# cap's empty lists and `0`s up to the value bound (under 32 KiB); in MessagePack, lists of nils
# that the decoder charges the bound exactly (about 16 KiB), or about 4 000 nils in under 4 KiB,
# which its size charges nothing past the first token. All eight send one in the same round, as
# often as the gateway admits: each socket's rate at the tokens it takes for one such frame, read
# off the rate itself (a spy) on a probe before the run, and the user's decode budget, which the
# eight share (`UserBudget`, the gateway's own bucket on the updates' clock). A round is sent only
# when both admit all eight. Every frame is answered; the other user's stream is timed as above.

SYNC_SHAPES = {
    "json": "cv.v1.json",
    "msgpack": "cv.v1.msgpack",
    "msgpack-under-4-kib": "cv.v1.msgpack",
    "msgpack-empty-arrays": "cv.v1.msgpack",
    "msgpack-empty-maps": "cv.v1.msgpack",
    "msgpack-chains": "cv.v1.msgpack",
}


def _chain(depth: int) -> list[Any]:
    """`depth` lists, each the only item of the one around it."""
    value: list[Any] = []
    for _ in range(depth - 1):
        value = [value]
    return value


#: Frames at the container cap (1 024, with the envelope, `p` and `pad`) in about 1 KiB.
_CONTAINER_DENSE: dict[str, Any] = {
    "msgpack-empty-arrays": [[[] for _ in range(n)] for n in [127] * 7 + [124]],
    "msgpack-empty-maps": [[{} for _ in range(n)] for n in [127] * 7 + [124]],
    "msgpack-chains": [_chain(29) for _ in range(35)] + [_chain(6)],  # 32 deep with the envelope
}


def at_bound(id: str, shape: str) -> str | bytes:
    """A `ping` of `shape` (`SYNC_SHAPES`)."""
    if shape == "json":
        head, tail = f'{{"t":"ping","id":"{id}","p":{{"pad":[', "]}}"
        lists = ",".join(["[]"] * (MAX_JSON_CONTAINERS - 3))
        zeros = ",0" * (MAX_MSGPACK_VALUES - json_values_over_count(head + lists + tail))
        text = head + lists + zeros + tail
        assert json_values_over_count(text) == MAX_MSGPACK_VALUES and len(text) < 32 * 1024
        return text
    if shape in _CONTAINER_DENSE:
        packed: bytes = msgpack.packb(
            {"t": "ping", "id": id, "p": {"pad": _CONTAINER_DENSE[shape]}}
        )
        charged: list[int] = []
        decode_client_frame(packed, charged=charged)
        assert charged[1] == MAX_JSON_CONTAINERS and len(packed) < 4 * 1024
        return packed
    if shape == "msgpack":
        # 7 for the envelope, 3 for `p`, 1 + 127 for `pad` and 1 + n for each of its 127 lists
        pad = [[None] * n for n in [128] * 125 + [119, 0]]
        values, under = MAX_MSGPACK_VALUES, 32 * 1024
    else:  # 7 + 3 + (1 + 31) + 31 x 128 = 4 010 values
        pad, values, under = [[None] * 127 for _ in range(31)], 4_010, 4 * 1024
    packed = msgpack.packb({"t": "ping", "id": id, "p": {"pad": pad}})
    charged = []
    decode_client_frame(packed, charged=charged)
    assert charged[0] == values and len(packed) < under
    return packed


class _Taken(InboundRateLimiter):
    """The inbound rate, recording the tokens the last frame any connection admitted took before
    its decode (`before`) and kept after it (`kept`)."""

    before = kept = 0

    def allow(self, now: float, weight: int = 1) -> bool:
        ok = super().allow(now, weight)
        if ok:
            _Taken.before = _Taken.kept = weight
        return ok

    def refund(self, tokens: int) -> None:
        super().refund(tokens)
        _Taken.kept = max(1, _Taken.kept - tokens)


@dataclass
class SyncFlood:
    """The flooding user's sockets, all sending a frame at the value bound in the same round."""

    sockets: list[Raw]
    shape: str
    every: int
    shared: tuple[
        int, int
    ]  # one frame's draw on the user's budget: taken before decode, back after
    user: UserBudget = field(default_factory=UserBudget)
    sent: int = 0
    offset: int = 0  # the update, within `every`, of its rounds

    @classmethod
    async def open(cls, stack: Stack, shape: str, user: uuid.UUID = FLOODER) -> SyncFlood:
        token = (await stack.sessions.mint(str(user))).access_token
        async with contextlib.AsyncExitStack() as dialled:  # a dial that fails closes the earlier
            sockets = list[Raw]()
            for _ in range(MAX_CONNECTIONS_PER_USER):
                sockets.append(raw := await dial(stack, token, SYNC_SHAPES[shape]))
                dialled.push_async_callback(raw.close)
            probe = sockets[0]  # one frame's tokens, as the rate takes them
            await send(probe, at_bound("probe", shape))
            await probe.until(lambda: probe.count("pong") == 1, "the probe's pong")
            before, kept = _Taken.before, _Taken.kept
            shared = (before - 1, before - kept)  # past the first token: taken, and given back
            flood = cls(sockets, shape, paced_every(before, before), shared)
            assert flood.user.admits(0, [shared])  # the probe's draw, as early as the run's
            dialled.pop_all()  # the flood owns them now: `close`
        return flood

    async def close(self) -> None:
        for raw in self.sockets:
            await raw.close()

    async def tick(self, i: int) -> None:
        if i % self.every == self.offset and self.user.admits(i, [self.shared] * len(self.sockets)):
            frame = at_bound(f"v{i}", self.shape)
            for raw in self.sockets:
                assert await send(raw, frame)
            self.sent += 1

    async def settle(self) -> None:
        """Each frame is answered before the next update: its handling is done."""
        for k, raw in enumerate(self.sockets):
            want = self.sent + (k == 0)  # the probe's pong too
            await raw.until(lambda raw=raw, want=want: raw.count("pong") == want, "pongs")


@pytest.mark.parametrize("shape", list(SYNC_SHAPES))
async def test_value_bound_frames_from_every_socket_in_the_same_round_stay_in_budget(
    monkeypatch: pytest.MonkeyPatch, shape: str
) -> None:
    async with nodelay_stack() as quiet:
        alone, bodies = await measure(quiet, None)
    monkeypatch.setattr(gateway, "InboundRateLimiter", _Taken)
    async with nodelay_stack() as loud:
        flood = await SyncFlood.open(loud, shape)
        try:
            beside, same = await measure(loud, flood)
            print(
                f"#4924 sync {shape} {flood.sent} rounds: alone {figures(alone)}; "
                f"beside the flood {figures(beside)}"
            )
            for raw in flood.sockets:  # every frame admitted and answered, none refused
                assert raw.frames(of="err") == raw.frames(of="bye") == []
        finally:
            await flood.close()
    assert same == bodies  # the same bodies, in the same order, as without the flood
    assert p95(beside) <= BUDGET_MS, f"p95 {p95(beside):.2f} ms past budget #6 ({BUDGET_MS} ms)"
    added = statistics.median(beside) - statistics.median(alone)
    assert added <= TOLERANCE_MS, f"the flood added {added:.2f} ms to the median"
    assert max(beside) <= STALL_MS, f"an update took {max(beside):.2f} ms, past {STALL_MS} ms"


@dataclass
class TwoFloods:
    """Two users' synchronised floods, sending in the same rounds."""

    floods: tuple[SyncFlood, SyncFlood]

    @property
    def sent(self) -> int:
        return sum(f.sent for f in self.floods)

    async def tick(self, i: int) -> None:
        for flood in self.floods:
            await flood.tick(i)

    async def settle(self) -> None:
        for flood in self.floods:
            await flood.settle()


async def test_value_bound_frames_of_two_users_in_the_same_round_stay_in_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two users, each with every socket it may hold, send JSON frames at the value bound in
    synchronised rounds, each as often as the gateway admits it, the second user's rounds half a
    period after the first's, so twice as many of the other user's updates meet a round. Each
    user's frames of more than one token are decoded one at a time, each to the end of its loop
    turn (its decode turn), so the other user's stream gets its turns between them."""
    async with nodelay_stack() as quiet:
        alone, bodies = await measure(quiet, None)
    monkeypatch.setattr(gateway, "InboundRateLimiter", _Taken)
    async with nodelay_stack() as loud:
        first = await SyncFlood.open(loud, "json")
        second = await SyncFlood.open(loud, "json", SECOND)
        second.offset = second.every // 2
        floods = TwoFloods((first, second))
        try:
            beside, same = await measure(loud, floods)
            print(
                f"#4924 sync json, two users, {floods.sent} rounds: alone {figures(alone)}; "
                f"beside the flood {figures(beside)}"
            )
            for raw in (*first.sockets, *second.sockets):  # every frame admitted and answered
                assert raw.frames(of="err") == raw.frames(of="bye") == []
        finally:
            await first.close()
            await second.close()
    assert same == bodies  # the same bodies, in the same order, as without the flood
    assert p95(beside) <= BUDGET_MS, f"p95 {p95(beside):.2f} ms past budget #6 ({BUDGET_MS} ms)"
    added = statistics.median(beside) - statistics.median(alone)
    assert added <= TOLERANCE_MS, f"the flood added {added:.2f} ms to the median"
    assert max(beside) <= STALL_MS, f"an update took {max(beside):.2f} ms, past {STALL_MS} ms"

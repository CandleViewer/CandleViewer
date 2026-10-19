"""#410 scenario 2: a client that stops reading for 60 s is harmless (G4, P6; §8.4, ruling D8;
C-13.6 #11, backpressure: a slow WS client).

E17-T03's flag is on (`_server.flag_on`: the default 8 MiB / 2 000-frame budget). A client holding
the reference workspace's feedable topics (§16.3: `book.BTCUSDT.50` and the tape; no bar builder is
wired into the harness for its 1 m `bars` and 5 m `footprint` panes) stops reading behind a
`PAUSE`d lane for 60 s of virtual time while the hub publishes the recorded book and tape every
tick. Its §9.1 `ping`s keep the socket alive, as a client whose reads stall but whose timers run;
it offers no permessage-deflate, so what loopback holds in flight (~0.6 to 0.7 MB) is counted in the
frames' own bytes. The pause opens with two quiet seconds (the book only, a few KB), so the
sleeper's writer is still running at its classification of t=2 s: the RTT probe it never answered
is then 1 s old, so it reads `saturated` (§8.6, C6) before the tape picks up, and its windows are
x4 from then on, holding pending bytes between flushes. The test asserts that class and those
bytes. Every `Backpressure.check` and `drain`, and every `OutboundQueue.push`, passes through a spy
that only reads: D8 is asserted at every check.

The tape is replayed at 2 000 prints/s, ~235 KiB/s with the book: inside §16.3's 350 KiB/s for the
workspace, and enough to cross 8 MiB with a third of the pause left (at K01's measured 154 KiB/s
the crossing would come only at the pause's end). The healthy clients keep the default
`throttle_ms`, so `TICK_S` makes each update a leading edge (§8.1), and each tick waits until every
healthy client has its frames: a frame held by pacing, or by a class the sleeper degraded, fails
the tick. Their streams are compared, byte for byte, with a run without the sleeper. Loop times
are printed, not asserted: the loopback proxy hop stalls ~40 ms once a classification interval in
both runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import statistics
import tracemalloc
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.metrics import cv_ws_closes_total, cv_ws_overflow_total
from candleviewer.ws.outbound import DRAIN_PCT, Backpressure, LadderEvent, OutboundQueue, Queued
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.pipeline import ConnectionPipeline
from tests.chaos.ws._client import BACKOFF, Client, each
from tests.chaos.ws._proxy import Fault, Proxy
from tests.chaos.ws._server import BOOK, BUFFERS, ORDERS, SEED, TRADES, Stack, flag_on
from tests.unit.ws._seq_support import ACC_A

pytestmark = pytest.mark.chaos

TICK_S = 1 / 8  # the book and the tape each tick: leading edges (`throttle_ms` 50 and 100)
PAUSE_TICKS, AFTER_TICKS = 480, 32  # 60 s asleep, then 4 s awake
QUIET_TICKS = 17  # the book only, to t=2 s: the sleeper's second classification comes first
PRINTS = 250  # per tick: 2 000 prints/s
ORDERS_PER_TICK = 16  # s2b: 128 updates/s of account A's orders
HEARTBEAT_S = 15.0  # §9.1 `heartbeat.interval_ms`
TOPICS = ({"ch": BOOK}, TRADES)
CHANNELS = (BOOK, TRADES["ch"])
HEALTHY = (uuid.UUID(int=0x201), uuid.UUID(int=0x202))
SLEEPER = uuid.UUID(int=0x203)
BUDGET = BackpressureConfig()  # `flag_on`'s, checked against the sleeper's queue
Acct = tuple[int, int, int]  # queued bytes, pending window bytes, frames


@dataclass(frozen=True, slots=True)
class Check:
    """One `Backpressure.check` at virtual time `at`, after `pushed` pushes to its queue: the
    accounting on entry and on return, what it fired, and on return the droppable bytes still
    queued, the topics marked for a `backpressure` snapshot, the lanes' and windows' bytes
    recounted and the class. `held`: `drain` was queuing a snapshot (checked once whole).
    `ranked`: when it was over budget on entry, the topics by queued plus pending bytes then,
    largest first, recounted from the lanes and windows (`_ranked`); else empty."""

    at: float
    pushed: int
    entry: Acct
    exit: Acct
    events: tuple[LadderEvent, ...]
    held: bool
    droppable: int
    marked: tuple[str, ...]
    recount: tuple[int, int]
    cls: str
    ranked: tuple[str, ...]

    def over(self) -> bool:
        return _over(self.exit)


def _over(acct: Acct) -> bool:
    queued, pending, frames = acct
    return queued + pending > BUDGET.max_bytes or frames > BUDGET.max_frames


def _acct(ladder: Backpressure) -> Acct:
    return ladder.queue.bytes, ladder.pacer.pending_bytes, len(ladder.queue)


def _ranked(ladder: Backpressure) -> tuple[str, ...]:
    """The topics by queued plus pending bytes, largest first, ties by name, at most five (§8.4
    step 3), recounted from both lanes' data frames (`orders` and `executions` included, `system`
    aside: #3365's ruling) and the windows rather than from the queue's per-key counters."""
    costs: dict[str, int] = defaultdict(int)
    for frame in (*ladder.queue._priority, *ladder.queue._normal):
        if frame.key is not None and frame.key[0] != "system":
            costs[frame.key[0]] += len(frame.payload)
    for lane in ladder.pacer.lanes.values():
        costs[lane.sub.ch] += lane.queue.pending_bytes
    order = sorted((-n, ch) for ch, n in costs.items() if n)
    return tuple(ch for _, ch in order[:5])


class Spy:
    """Pass-through wrappers on `Backpressure.check` and `drain`, and a count of
    `OutboundQueue.push` calls, on every connection: the same arguments in, the same result out;
    they only read. After `keep` they record one connection's ladder alone."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.checks: dict[Backpressure, list[Check]] = defaultdict(list)
        self.drains: dict[Backpressure, list[tuple[float, tuple[LadderEvent, ...]]]]
        self.drains = defaultdict(list)
        self.pushes: dict[OutboundQueue, int] = defaultdict(int)
        self.only: Backpressure | None = None
        check, drain, push = Backpressure.check, Backpressure.drain, OutboundQueue.push

        def pushed(queue: OutboundQueue, frame: Queued) -> None:
            self.pushes[queue] += 1
            push(queue, frame)

        def checked(ladder: Backpressure, subs: Iterable[Subscription]) -> list[LadderEvent]:
            if self.only not in (None, ladder):
                return check(ladder, subs)
            q, pacer = ladder.queue, ladder.pacer
            held, n, entry = ladder._draining, self.pushes[q], _acct(ladder)
            ranked = _ranked(ladder) if _over(entry) else ()
            events = check(ladder, subs)
            lanes = sum(len(f.payload) for f in (*q._priority, *q._normal))
            windows = sum(lane.queue.pending_bytes for lane in pacer.lanes.values())
            marked = tuple(sorted(s.ch for s in pacer.resnapshot_required.values()))
            left, now, cls = sum(q.key_bytes().values()), pacer.emitter.clock(), pacer.cls.value
            out, fired, recount = _acct(ladder), (*events,), (lanes, windows)
            record = Check(now, n, entry, out, fired, held, left, marked, recount, cls, ranked)
            self.checks[ladder].append(record)
            return events

        def drained(
            ladder: Backpressure, live: Mapping[str, Subscription] | None = None
        ) -> list[LadderEvent]:
            if self.only not in (None, ladder):
                return drain(ladder, live)
            depth = ladder.queue.pct(ladder.pacer.pending_bytes)
            events = drain(ladder, live)
            self.drains[ladder].append((depth, (*events,)))
            return events

        monkeypatch.setattr(OutboundQueue, "push", pushed)
        monkeypatch.setattr(Backpressure, "check", checked)
        monkeypatch.setattr(Backpressure, "drain", drained)

    def keep(self, ladder: Backpressure) -> None:
        """Record `ladder` alone from now on, and drop the others' records: the D8 trace then holds
        no record the test does not read."""
        self.only = ladder
        self.checks = defaultdict(list, {ladder: self.checks[ladder]})
        self.drains = defaultdict(list, {ladder: self.drains[ladder]})

    def events(self, ladder: Backpressure) -> list[LadderEvent]:
        return [e for c in self.checks[ladder] for e in c.events]


def assert_d8(checks: list[Check]) -> Acct:
    """D8 at every check: the counters equal the recount; on return the accounting is within the
    budget unless the check closed (step 3 frees both lanes) or `drain` holds it, the check that
    `drain` replays coming next. Between two checks at most one frame is pushed (counted at the
    queue, so the writer's pops cannot hide one), and every paced update ends in a check, so on
    entry it is over by at most one push or one update (§8.6). Returns the peak on entry."""
    for prev, c in zip([None, *checks], checks, strict=False):
        assert c.recount == c.exit[:2], c
        assert c.held or any(e.action == "close" for e in c.events) or not c.over(), c
        if prev is not None:
            assert c.pushed - prev.pushed <= 1, (prev, c)
            assert not (prev.held and c.held), (prev, c)
    assert not checks[-1].held, checks[-1]
    return max((c.entry for c in checks), key=lambda a: a[0] + a[1])


def series(metric: Any) -> dict[str, float]:
    samples = (s for fam in metric.collect() for s in fam.samples if s.name.endswith("_total"))
    return {s.labels["reason"]: s.value for s in samples}


def grew(metric: Any, before: dict[str, float]) -> dict[str, float]:
    return {k: v - before.get(k, 0.0) for k, v in series(metric).items() if v != before.get(k)}


def pct(xs: Sequence[float], q: int) -> float:
    return statistics.quantiles(xs, n=100)[q - 1]


@contextlib.contextmanager
def traced() -> Iterator[list[int]]:
    """tracemalloc across the block (started for it unless it already runs): `[peak]` after."""
    peak, started = [0], not tracemalloc.is_tracing()
    if started:
        tracemalloc.start()
    tracemalloc.reset_peak()
    try:
        yield peak
        peak[0] = tracemalloc.get_traced_memory()[1]
    finally:
        if started:
            tracemalloc.stop()


@dataclass
class Tap:
    """A healthy client's `on_data`: a digest of its data frames as received, its prints, and per
    `d` the loop time since its tick's publish and the virtual ms since its oldest print's."""

    stack: Stack
    tick: list[float]
    digest: Any = field(default_factory=hashlib.sha256)
    prints: int = 0
    size: int = 0
    wall: list[float] = field(default_factory=list)
    late: list[int] = field(default_factory=list)

    def __call__(self, frame: dict[str, Any], text: str | bytes) -> None:
        raw = text if isinstance(text, bytes) else text.encode()
        self.digest.update(raw)
        self.size += len(raw)
        if frame["t"] != "d":
            return
        self.wall.append(asyncio.get_running_loop().time() - self.tick[0])
        if frame["ch"] == TRADES["ch"]:
            trades = frame["p"]["trades"]
            self.prints += len(trades)
            self.late.append(self.stack.wall_ms() - min(t["ts_ms"] for t in trades))


@dataclass
class Run:
    """The steady stream and the healthy clients that must keep up with it."""

    stack: Stack
    healthy: list[Client] = field(default_factory=list)
    taps: list[Tap] = field(default_factory=list)
    tick: list[float] = field(default_factory=lambda: [0.0])
    base: dict[Client, dict[str, int]] = field(default_factory=dict)
    books: int = 0
    tapes: int = 0
    orders: int = 0  # account A's updates a subscriber took

    async def connect(self, users: Iterable[uuid.UUID]) -> Run:
        for n, uid in enumerate(users):
            c = self.stack.client(await self.stack.sessions.mint(str(uid)), SEED + n)
            tap = Tap(self.stack, self.tick)
            c.heartbeat_s, c.on_data = HEARTBEAT_S, tap
            self.healthy.append(c.start(*TOPICS))
            self.taps.append(tap)
        await each(self.healthy, lambda c: c.synced, "first snapshots")
        self.base = {c: dict(c.seq) for c in self.healthy}
        return self

    def current(self, c: Client) -> bool:
        """`c` has every update published so far, one `d` each."""
        want = {BOOK: self.books, TRADES["ch"]: self.tapes}
        return all(c.seq.get(ch) == self.base[c][ch] + n for ch, n in want.items())

    async def feed(
        self,
        ticks: int,
        orders: int = 0,
        until: Callable[[], bool] | None = None,
        *,
        tape: bool = True,
    ) -> None:
        """`ticks` of the stream (the book, and the tape unless `tape` is off), plus `orders`
        updates of account A each tick. Each tick waits, bounded, until every healthy client has
        its frames, then moves time on. `until()` runs right after a tick's publishes, in their
        synchronous turn, before anything awaits; the feed ends there once it holds."""
        for _ in range(ticks):
            self.tick[0] = asyncio.get_running_loop().time()
            self.stack.book_step()
            self.books += 1
            if tape:
                self.stack.trades_step(PRINTS)
                self.tapes += 1
            for _ in range(orders):
                self.orders += self.stack.private("orders", ACC_A)
            if until is not None and until():
                return
            await each(self.healthy, self.current, "every update in its tick")
            await self.stack.clock.advance(TICK_S)


async def sleeper(
    stack: Stack, *topics: dict[str, Any]
) -> tuple[Client, Proxy, ConnectionPipeline, Backpressure]:
    """The client that will stop reading: on its own lane, its §9.1 pings on, no deflate."""
    lane = await stack.lane()
    c = stack.client(await stack.sessions.mint(str(SLEEPER)), SEED + 9, via=lane)
    c.heartbeat_s, c.deflate = HEARTBEAT_S, False
    await c.start(*topics).until(lambda: c.synced, "first snapshots")
    (conn,) = stack.gateway.of_user(SLEEPER)
    assert conn.pipeline is not None and conn.pipeline.ladder is not None
    queue = conn.pipeline.queue
    assert (queue.max_bytes, queue.max_frames) == (BUDGET.max_bytes, BUDGET.max_frames)
    return c, lane, conn.pipeline, conn.pipeline.ladder


def snaps(c: Client, ch: str) -> list[str]:
    """`ch` on `c` as its snapshots' reasons, each run of `d` frames between them as one `d`."""
    kinds = [
        f["meta"]["reason"] if f["t"] == "snap" else "d" for f in c.frames if f.get("ch") == ch
    ]
    return [k for i, k in enumerate(kinds) if k != "d" or i == 0 or kinds[i - 1] != "d"]


def loop_ms(r: Run) -> str:
    wall = [1000 * x for t in r.taps for x in t.wall]
    return f"p50 {pct(wall, 50):.2f}, p95 {pct(wall, 95):.2f}"


async def test_s2_sleeping_client_stays_in_its_budget_and_costs_the_others_nothing(
    stack_on: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    run = await Run(stack_on).connect(HEALTHY)
    slow, lane, _, ladder = await sleeper(stack_on, *TOPICS)
    spy.keep(ladder)
    overflow, closes = series(cv_ws_overflow_total), series(cv_ws_closes_total)

    lane.inject(Fault.PAUSE)
    with traced() as peak:  # this run only: D8's evidence, and lane time
        await run.feed(QUIET_TICKS, tape=False)
        await run.feed(PAUSE_TICKS - QUIET_TICKS)
    # D8 at every budget check of the sleeper's connection while it slept (again below, awake),
    # the windows' pending bytes in it: the class path is `saturated` (module docstring).
    asleep = list(spy.checks[ladder])
    queued, pending, frames = assert_d8(asleep)
    assert any(c.exit[1] for c in asleep)
    assert queued + pending > BUDGET.max_bytes  # the pause took it there; the drop answered
    # §8.4 in order. Step 1, once, asleep: on the check that went over, both topics' queued
    # frames and windows go and both are marked; only control frames are left.
    (drop,) = [c for c in asleep if c.events]
    assert [(e.reason, e.topics) for e in drop.events] == [("drop", CHANNELS)]
    assert (drop.droppable, drop.exit[1], drop.marked, drop.cls) == (0, 0, CHANNELS, "saturated")
    assert grew(cv_ws_overflow_total, overflow) == {"drop": 2}  # once per topic, nothing else
    lane.inject(Fault.HEAL)
    await run.feed(AFTER_TICKS)
    stream = ["initial", "d", "backpressure", "d"]
    recovered = f"recovered ({BUFFERS})"  # a stall here can be a buffer under its floor
    await slow.until(lambda: all(snaps(slow, ch) == stream for ch in CHANNELS), recovered)
    assert_d8(spy.checks[ladder])
    # Step 2, awake: one `backpressure` snapshot per drain, each begun below 50 % of the budget.
    sent = [(depth, e.topics) for depth, events in spy.drains[ladder] for e in events]
    assert sorted(t for _, t in sent) == [(ch,) for ch in CHANNELS]  # nothing else from a drain
    assert all(depth < DRAIN_PCT for depth, _ in sent)
    # Step 3 never: what was left could always be dropped. The sleeper recovered through the
    # snapshots: what was in flight before the drop, the snapshot, the stream again, no gap.
    assert [e.reason for e in spy.events(ladder)] == ["drop"]
    assert grew(cv_ws_overflow_total, overflow) == {"drop": 2, "resnapshot": 2}
    assert grew(cv_ws_closes_total, closes) == {} and slow.gaps == [] and slow.closes == []

    # Healthy clients: every update in its tick (no class the sleeper degraded, no frame held),
    # no gap, no print lost or doubled, and the same stream, frame for frame, as a run without
    # the sleeper (same seed, same stream).
    async with flag_on() as other:
        control = await Run(other).connect(HEALTHY)
        await control.feed(QUIET_TICKS, tape=False)
        await control.feed(PAUSE_TICKS - QUIET_TICKS + AFTER_TICKS)
    for r in (run, control):
        assert all(c.gaps == [] and c.closes == [] for c in r.healthy)
        assert all(t.prints == r.tapes * PRINTS for t in r.taps)
    assert [t.digest.digest() for t in run.taps] == [t.digest.digest() for t in control.taps]
    late, before = ([x for t in r.taps for x in t.late] for r in (run, control))
    assert pct(late, 95) <= 1.1 * pct(before, 95) and max(late) == 0  # the Gherkin's 10 %
    acct, rate = queued + pending, run.taps[0].size / (run.tapes * TICK_S) / 1024
    print(
        f"D8 #410 s2: tracemalloc peak {peak[0]} B over the 60 s pause; accounted peak {acct} B "
        f"(queued {queued} + pending {pending}, {frames} frames); ratio {peak[0] / acct:.3f}; "
        f"step 1 at {drop.at:.3f} s, class {drop.cls}; the stream {rate:.0f} KiB/s; healthy "
        f"loop ms with the sleeper (pause traced) {loop_ms(run)}, without (untraced) "
        f"{loop_ms(control)}"
    )


async def test_s2b_sleeper_holding_orders_it_cannot_shed_closes_4429_then_resyncs(
    stack_on: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 3: the sleeper also holds account A's blotter, and A's orders keep changing. Those
    frames are never dropped (§8.4), so after step 1 has shed the market topics the orders alone
    go over budget and the connection closes `slow_consumer` 4429. The lane heals in the close's
    own synchronous turn (the feed's `until`), inside its 2 s flush with no await between, and the
    client backs off (§9.2) and re-snapshots every topic, private first (§9.3)."""
    spy = Spy(monkeypatch)
    run = await Run(stack_on).connect(HEALTHY[:1])
    slow, lane, pipe, ladder = await sleeper(stack_on, ORDERS, *TOPICS)
    spy.keep(ladder)
    overflow, closes = series(cv_ws_overflow_total), series(cv_ws_closes_total)

    healed: list[float] = []  # loop seconds from the close to the heal

    def wake() -> bool:
        """Once the close is taken, heal the lane before anything awaits."""
        if pipe.terminal is None or pipe.deadline is None:
            return False
        lane.inject(Fault.HEAL)
        closed = pipe.deadline - pipe.config.close_flush_s
        healed.append(asyncio.get_running_loop().time() - closed)
        return True

    lane.inject(Fault.PAUSE)
    await run.feed(PAUSE_TICKS, ORDERS_PER_TICK, until=wake)
    assert pipe.terminal is not None, "no step 3 inside the 60 s pause"
    closed_at = stack_on.clock.now
    assert (len(pipe.queue), pipe.queue.bytes) == (0, 0)  # the close freed both lanes at once
    await slow.until(lambda: slow.closes == [4429], "bye, then 4429 (the close's 2 s flush)")

    assert_d8(spy.checks[ladder])
    drop, close = spy.events(ladder)  # steps 1, then 3, on two checks
    assert (drop.reason, drop.topics, close.reason) == ("drop", CHANNELS, "close_budget")
    (dropping,) = [c for c in spy.checks[ladder] if drop in c.events]
    (closing,) = [c for c in spy.checks[ladder] if close in c.events]
    # Only when what remains cannot be dropped: nothing droppable left, still over the budget.
    assert closing.events == (close,) and closing.droppable == closing.exit[1] == 0
    assert closing.over()
    bye = slow.frames[-1]  # the first socket's last frame: nothing follows the `bye`
    assert bye["t"] == "bye"
    p, want = bye["p"], {"code": 4429, "reason": "slow_consumer", "retry_after_ms": 3000}
    assert {k: p[k] for k in want} == want and p["reconnect"] is True  # §8.4's step 3 `bye`
    assert p["message"] == "Client is not draining its outbound queue."
    # The hint is the ranking taken when the overflow began (#3365): at the check that went over
    # and shed the market topics, recounted here on entry with the orders queued then, and kept
    # until the close. A ranking taken at the closing check would name the orders alone.
    assert p["hint"] == {"most_expensive_topics": list(close.topics)}
    assert close.topics == dropping.ranked == (TRADES["ch"], ORDERS["ch"], BOOK)  # by bytes
    assert closing.ranked == (ORDERS["ch"],)
    # The close cleared both lanes: of the orders it took, those still queued never went out.
    assert sum(f["t"] == "d" and f["ch"] == "orders" for f in slow.frames) < run.orders
    assert grew(cv_ws_overflow_total, overflow) == {"drop": 2, "close_budget": 1}
    assert grew(cv_ws_closes_total, closes) == {"slow_consumer": 1}

    delay = await slow.next_backoff()
    assert abs(delay - BACKOFF[0][0]) <= BACKOFF[0][1]  # §9.2 attempt 1
    await stack_on.clock.advance(delay)
    await slow.until(lambda: slow.sessions == 2 and slow.synced, "resubscribed")
    second = slow.frames[[f["t"] for f in slow.frames].index("welcome", 1) :]
    resnaps = [(f["ch"], f["meta"]["reason"]) for f in second if f["t"] == "snap"]
    assert resnaps == [(ch, "initial") for ch in ("orders", *CHANNELS)]
    assert slow.gaps == [] and run.healthy[0].gaps == [] and run.healthy[0].closes == []
    print(f"#410 s2b: step 3 after {closed_at:.3f} s asleep, healed {healed[0] * 1e3:.2f} ms after")

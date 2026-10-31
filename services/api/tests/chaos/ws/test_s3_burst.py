"""#410 scenario 3: a burst of 5 000 book updates a second is coalesced, not lost (§8; the chaos
row of 23 §16.4, "5 000 msg/s burst on one symbol; assert coalescing and no sequence break"), and
the other nine symbols keep their frames and their fan-out budget meanwhile (06 §9's isolation
clause, budget #6). C-13.6 has no row for it: the nearest is #11, backpressure.

On E17-T03's pipeline (`_server.granted`), which coalesces (§8.2). One client holds
`book.BTCUSDT.50` structured, and the hub gets 5 000 updates a second of virtual time from a
`Loop` (`_book`): a recorded stretch of the book, as the book publisher (#604) will send it. A tick
of 250 ms publishes its 1 250 updates in one go, moves the virtual clock, and waits until the
client holds every update published. So each window closes before the next tick's first update
arrives, and the frames are deterministic (`windows`): the first update of a cold lane leaves alone
(§8.6, D12), the rest of its tick leaves as one window, and each later tick is one window of all
its updates. The tick is longer than the slowest window the book can get, its 50 ms throttle x4
(`saturated`, §8.3): the class follows RTT samples read on the virtual clock, so a `pong` that
crosses ticks can raise it (scenario 1 met that at 125 ms), and a window that outlasts its tick
waits for a clock the waiting tick never moves.

The client's frames are the disclosure the gateway owes: each after the first `coalesced`, with a
`coalesced_count` of the updates its window merged, the counts summing to what was published, `s`
contiguous, no snapshot but the first. After every tick its `Replica` equals the server's book (23
§16.4, unit: the coalescer equals applying every source update). The pacer's own series agree with
the frames (`merged`), and nothing was dropped, closed or re-snapshotted. The 10 s run (50 000
updates) is in the PR lane; the 60 s one (300 000), marked `harness`, runs nightly
(`chaos-ws-nightly`).

The other nine symbols (06 §3.2's ten) are clones of the recorded book, each from its own place in
it, with its own user and client, at 8 updates a second: one a half tick. So the isolation tests
cut each tick in two, and at its start and at mid-tick publish one update of each of the nine and
half the burst's 1 250, 25 burst updates at a time with one of the nine ahead of each of the first
nine slices: all but the first of the nine publish while the burst's window is open (it opens in
the first slice). A half tick is shorter than the slowest window (a `saturated` book lane leaves
one frame per 200 ms, five a second), so these tests hold every connection `healthy`, where a
book's window is 50 ms: before the clock moves, every RTT probe a client got is answered and read
(`Ten.answered`), so no sample spans a move, and no queue nears `lagging`'s 25 %; no class notice
reaches a client (asserted). Each update of the nine then leaves at its publish, and the burst's
frames are the burst test's at half the lump. A tick's own grid cannot carry them: the 50 ms
window closes before mid-tick, so any stop there leaves the next lump a leading edge again. On the
virtual clock (10 s in the PR lane, 60 s nightly) the nine's clients get, byte for byte, the
frames of a control run in which the burst symbol gets one update a half tick: each `d` at its
publish, no gap, no snapshot but the first, no resync, and the series move for the burst's windows
alone (for none in the control).

Budget #6 is wall time, judged nightly (`harness`) on stacks with `TCP_NODELAY` and the collector
off, the clients checking nothing (their own cost is not the gateway's), the burst 5 updates a
slice with a yield after each. A warm-up run is dropped, then the control and the burst run ABBA,
30 s each, so neither warm caches nor drift favour either. Every client must still end clean
(`CLEAN`). The nine's publish-to-arrival p95 must stay within 20 ms and their median within 8 ms
of the control's: 40 % of the budget and about five times what the burst should add. A frame of
the nine waits out six slices, its publish's own and one in each of the five loop turns that carry
it (the writer's send, the proxy's read and its pipe's write, the client's read and its task's),
so the burst adds about 6 x 5 updates x 50 to 60 us, 1.5 to 1.8 ms. At most 9 of their updates
may take over 100 ms, a stall: one stall holds every update then in flight, at most a half tick's
nine, so a run may have one (a p99.9 would let 4 of the 4 320 pass, fewer than one stall can hold).
That cap counts the updates a stall holds, not for how long, so none may take over 1 s (10 x that).
The burst's window must land within 20 ms (p95) of the move that releases it: budget #6 starts at
the release (23 §8.6, D7), and the writer's real poll (at most 5 ms) and the move's settling stay
inside the span, an upper bound. A negative control, in the PR lane too, holds the loop 25 ms in
each slice that carries one of the nine and again before each move, so each of their updates and
each burst window waits at least that long, and both budget #6 checks and the median must fail.
The loop's own test, with no server, is the last: two laps from two places in the recording,
window and book equal at every update, and back where they began at the end of each.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import hashlib
import math
import statistics
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from candleviewer.ws.metrics import (
    COALESCED_UPDATES,
    cv_ws_closes_total,
    cv_ws_conflated_total,
    cv_ws_overflow_total,
    cv_ws_rtt_seconds,
)
from candleviewer.ws.pacing import _MULTIPLIER, RTT_PROBE_PREFIX, ConnectionClass
from candleviewer.ws.sequencing import SequencingHub, cv_ws_resync_total
from candleviewer.ws.topics import effective_throttle_ms, parse_topic
from tests.chaos.ingestion._clock import VirtualClock
from tests.chaos.ws._book import LAP, BookTap, Delta, Loop, Replica, structured
from tests.chaos.ws._client import TIMEOUT_S, Client, each
from tests.chaos.ws._server import BOOK, DEPTH, SEED, SYM, Stack, granted
from tests.unit.ws._seq_support import Conn, Source

pytestmark = pytest.mark.chaos

RATE = 5_000  # book updates a second of virtual time
TICK_S = 0.25
PER_TICK = round(RATE * TICK_S)
#: The client's §9.1 pings, on the virtual clock, well inside the 45 s of silence. A whole number of
#: ticks: no virtual timer then fires between two, and a window flushed off the tick grid would
#: leave the next tick's first update a leading edge again.
HEARTBEAT_S = 5.0
#: At import, so drift fails here, not as a 5 s timeout: the tick exceeds the slowest window (§8.3):
#: the topic's throttle as `sub_ok` reports it (a book's follows its depth) x the top class's.
assert effective_throttle_ms(parse_topic(BOOK), None) * max(_MULTIPLIER.values()) / 1000 < TICK_S
assert HEARTBEAT_S % TICK_S == 0
USER = uuid.UUID(int=0x401)
#: The other nine symbols (06 §3.2's ten): clone n of the recorded book starts `SPREAD` * (n + 1)
#: deltas into it, so no two are in lockstep, and laps `NINE_LAP` updates and its bridge.
NINE = tuple(f"{base}USDT" for base in "ETH SOL XRP DOGE ADA LINK AVAX DOT LTC".split())
NINE_USERS = tuple(uuid.UUID(int=0x402 + n) for n in range(len(NINE)))
SPREAD, NINE_LAP = 500, 40
#: The isolation tests' half tick (module docstring): at a tick's start and at mid-tick, one update
#: of each of the nine (8 a second) and half the burst's tick. It is shorter than the slowest
#: window, so those tests hold every connection `healthy` (`Ten.answered`; no class notice,
#: asserted), and the healthy window, a book's 50 ms throttle, must close inside it. Two make a
#: tick, so the heartbeat and the 1 s classification grid stay whole numbers of them.
HALF_S, PER_HALF = TICK_S / 2, PER_TICK // 2
assert PER_HALF * 2 == PER_TICK
assert (
    effective_throttle_ms(parse_topic(BOOK), None) * _MULTIPLIER[ConnectionClass.HEALTHY] / 1000
    < HALF_S
)
#: The burst's updates a slice of a half tick (`Ten.step`), one of the nine ahead of each of the
#: first nine. A timed run's slice is smaller, a yield after each: a frame of the nine waits out six
#: (module docstring), so the burst adds about 30 updates' publish time to its median, 1.5 to 1.8 ms
#: at 50 to 60 us an update, where 25 a slice (the isolation tests') would add 7.5 to 9 ms.
SLICE, TIMED_SLICE = 25, 5
assert all(len(NINE) <= PER_HALF // n for n in (SLICE, TIMED_SLICE))  # a slice for each of the nine
BUDGET_MS = 20.0  # budget #6 (06-performance-and-load-standard.md §2): a fan-out's p95
#: What the burst may add to the nine's median: 40 % of budget #6, about five times this test's own
#: cost model (`TIMED_SLICE`). test_flood_isolation has the same 8 ms, there about three times its
#: flood's cost (2 to 2.7 ms): that is its calibration, not this test's.
TOLERANCE_MS = 8.0
#: An update of the nine slower than this is a stall, not a latency (5 x budget #6). One stall holds
#: every update in flight, at most a half tick's nine, so a run may have one: `len(NINE)` over it.
#: That cap counts the updates a stall holds, not for how long: none may take 10 x this (1 s).
STALL_MS = 100.0
TIMED_S, WARM_S = 60, 1  # the wall-clock samples, nightly (two runs of each, ABBA); the warm-up
#: The negative control: 1 s, the loop held 25 ms in each slice of the nine and before each move.
NEGATIVE_S, HOLD_S = 1, 0.025


def series() -> dict[str, float]:
    """The series the burst is judged by, as `name{label}`: the pacer's conflation counters and
    `cv_ws_coalesced_updates`'s count and sum, and the counters that would say a client was shed
    (`cv_ws_overflow_total`), closed or re-snapshotted."""
    out: dict[str, float] = {}
    for metric in (
        cv_ws_conflated_total,
        cv_ws_overflow_total,
        cv_ws_closes_total,
        cv_ws_resync_total,
    ):
        for family in metric.collect():
            for sample in family.samples:
                if sample.name.endswith("_total"):
                    (label,) = sample.labels.values()
                    out[f"{sample.name}{{{label}}}"] = sample.value
    cumulative, total = COALESCED_UPDATES.reading()
    out["cv_ws_coalesced_updates_count"], out["cv_ws_coalesced_updates_sum"] = cumulative[-1], total
    return out


def moved(before: dict[str, float]) -> dict[str, float]:
    """What `series()` has gained since `before`: only the series that changed."""
    return {k: v - before.get(k, 0.0) for k, v in series().items() if v != before.get(k, 0.0)}


def windows(per: int, steps: int) -> list[Delta]:
    """The burst's `d` frames when each of `steps` steps publishes `per` updates at one instant
    and the clock's next move closes its window (module docstring)."""
    return [
        Delta(2, False, None),  # s 1 was the snapshot: the cold lane's first update, no disclosure
        Delta(3, True, per - 1),  # the others of its step, as one window
        *(Delta(s, True, per) for s in range(4, steps + 3)),  # then a window a step
    ]


def merged(published: int, frames: int) -> dict[str, float]:
    """What `series()` gains when `published` updates leave in `frames` frames, each a window but
    the leading edge: absorbed, and nothing dropped, closed or re-snapshotted."""
    return {
        "cv_ws_conflated_total{book}": published - frames,  # n - 1 for each window of n
        "cv_ws_coalesced_updates_count": frames - 1,  # one for each frame but the leading edge
        "cv_ws_coalesced_updates_sum": published - 1,
    }


@pytest.mark.parametrize(
    "seconds", [10, pytest.param(60, marks=pytest.mark.harness)], ids=["10s", "60s"]
)
async def test_s3_a_burst_of_5000_book_updates_a_second_is_coalesced_not_lost(
    stack_on: Stack, seconds: int
) -> None:
    feed, tap = Loop(stack_on.source), BookTap()
    c = stack_on.client(await stack_on.sessions.mint(str(USER)), SEED)
    c.heartbeat_s, c.on_data = HEARTBEAT_S, tap
    await c.start(structured(BOOK)).until(lambda: c.synced, "first snapshot")
    ticks, publishing, before = seconds * RATE // PER_TICK, 0.0, series()
    began = time.perf_counter()
    for tick in range(1, ticks + 1):
        spent = time.perf_counter()
        for _ in range(PER_TICK):
            assert feed.publish(stack_on.hub) == 1, "an update the subscription did not take"
        publishing += time.perf_counter() - spent
        await stack_on.clock.advance(TICK_S)
        await c.until(
            lambda: tap.updates == feed.published, f"tick {tick}: every update in a frame"
        )
        assert tap.replica.matches(feed.book, DEPTH), f"tick {tick}: the replica left the book"
    took = time.perf_counter() - began

    published, frames = feed.published, len(tap.deltas)
    assert published == seconds * RATE and tap.updates == published
    assert tap.deltas == windows(PER_TICK, ticks)
    assert c.gaps == [] and tap.replica.gaps == 0 and c.closes == [] and c.sessions == 1
    assert moved(before) == merged(published, frames)
    print(
        f"#410 s3 {seconds} s: {published} updates in {frames} frames (x{published / frames:.0f}), "
        f"{ticks} windows of {PER_TICK}, {len(c.system('connection_quality'))} class notices; "
        f"{took:.2f} s of wall time, {1e6 * publishing / published:.1f} us of it an update"
    )


def hold(seconds: float) -> None:
    """The negative control's slow hub: the loop held `seconds`, busy, not asleep."""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


def rtt_samples() -> float:
    """The RTT samples the gateway has taken (`cv_ws_rtt_seconds`' count, summed over any label
    set): one a probe answered."""
    return sum(
        s.value for f in cv_ws_rtt_seconds.collect() for s in f.samples if s.name.endswith("_count")
    )


def probes(c: Client) -> int:
    """The RTT probes (§9.1) `c` got, each a `ping` the client answers as it reads it."""
    return sum(f["t"] == "ping" and f["id"].startswith(RTT_PROBE_PREFIX) for f in c.frames)


@dataclass
class Watch:
    """One symbol and its client's `on_data`: its `Loop`, the updates its `d` frames carry, and
    the (virtual, loop) time of each update `publish` sent and of each `d` that came. `checked`
    (the PR lane): a `BookTap` (each `d` schema-validated, about 2 ms) and a digest of the raw
    data frames too; a timed run leaves the client's own cost out of the gateway's."""

    clock: VirtualClock
    feed: Loop
    checked: bool
    tap: BookTap = field(default_factory=BookTap)
    digest: Any = field(default_factory=hashlib.sha256)
    updates: int = 0
    sent: list[tuple[float, float]] = field(default_factory=list)
    got: list[tuple[float, float]] = field(default_factory=list)

    def __call__(self, frame: dict[str, Any], text: str | bytes) -> None:
        if frame["t"] == "d":
            self.got.append((self.clock.now, asyncio.get_running_loop().time()))
            self.updates += frame["p"].get("coalesced_count") or 1
        if self.checked:
            self.tap(frame, text)
            self.digest.update(text if isinstance(text, bytes) else text.encode())

    def publish(self, hub: SequencingHub) -> None:
        self.sent.append((self.clock.now, asyncio.get_running_loop().time()))
        took = self.feed.publish(hub)
        assert took == 1, f"{self.feed.ch}: {took} subscriptions took an update, not its client"

    def current(self) -> bool:
        return self.updates == self.feed.published


#: How a client ended: its gaps, closes, sessions and class notices (`connection_quality`).
End = tuple[list[str], list[int], int, list[int]]
CLEAN: End = ([], [], 1, [])  # no gap, no close, no reconnect, `healthy` throughout


@dataclass
class Ten:
    """The burst symbol and the nine on one stack, the burst's client first; per half tick, the
    loop time of the move that releases the burst's window and of the arrival of its frame; and,
    read before the teardown (`end`), what `series()` moved by and how each client ended."""

    stack: Stack
    burst: Watch
    nine: list[Watch]
    clients: list[Client]
    rtt0: float  # `rtt_samples()` once connected: no probe goes out before the first second
    released: list[float] = field(default_factory=list)
    landed: list[float] = field(default_factory=list)
    moved: dict[str, float] = field(default_factory=dict)
    ends: list[End] = field(default_factory=list)

    @classmethod
    async def connect(cls, stack: Stack, *, checked: bool) -> Ten:
        clones = (Loop(stack.source, s, SPREAD * (n + 1), NINE_LAP) for n, s in enumerate(NINE))
        feeds = (Loop(stack.source), *clones)
        watches = [Watch(stack.clock, feed, checked) for feed in feeds]
        clients = []
        for n, (uid, watch) in enumerate(zip((USER, *NINE_USERS), watches, strict=True)):
            c = stack.client(await stack.sessions.mint(str(uid)), SEED + n)
            c.heartbeat_s, c.on_data = HEARTBEAT_S, watch
            clients.append(c.start(structured(watch.feed.ch)))
        await each(clients, lambda c: c.synced, "first snapshots")
        return cls(stack, watches[0], watches[1:], clients, rtt_samples())

    async def step(self, burst: int, *, timed: bool = False, hold_s: float = 0.0) -> None:
        """A half tick: an update of each of the nine and `burst` of the burst symbol, `SLICE` at
        a time (timed, `TIMED_SLICE`), one of the nine ahead of each of the first nine slices, as
        a publisher's awaits would interleave them, so all but the first of the nine publish while
        the burst's window is open; then, each wait bounded, the nine's frames before the clock
        moves (so each arrives at its publish), the probes read (`answered`), the move (stamped as
        it starts, `released`), and the burst's window it closes (`landed`). `timed` (wall clock):
        a yield after each slice. `hold_s` (the negative control): the loop held that long in each
        slice that carries one of the nine, and again between the stamp and the move, so the
        nine's updates and the burst's window each wait it out."""
        hub, loop, nine = self.stack.hub, asyncio.get_running_loop(), iter(self.nine)
        size = TIMED_SLICE if timed else SLICE
        for start in range(0, PER_HALF, size):
            ahead = next(nine, None)
            if ahead is not None:
                ahead.publish(hub)
            for _ in range(min(size, burst - start)):
                took = self.burst.feed.publish(hub)
                assert took == 1, f"{took} subscriptions took a burst update, not its client"
            if hold_s and ahead is not None:
                hold(hold_s)
            if timed:
                await asyncio.sleep(0)
        for watch, c in zip(self.nine, self.clients[1:], strict=True):
            await c.until(watch.current, f"{watch.feed.ch}: its update, at its publish")
            got, sent = len(watch.got), len(watch.sent)
            assert got == sent, f"{watch.feed.ch}: {sent} updates in {got} frames, one merged"
        await self.answered()
        self.released.append(loop.time())  # the move releases the window: budget #6's span starts
        if hold_s and timed:
            hold(hold_s)  # a slow release: `landed - released` is at least `hold_s`
        await self.stack.clock.advance(HALF_S)
        await self.clients[0].until(self.burst.current, "the burst's window, closed by the move")
        self.landed.append(self.burst.got[-1][1])

    async def answered(self) -> None:
        """Every RTT probe a client got is answered and read before the clock moves, so no RTT
        sample spans a move: each reads 0 (`HALF_S`). A probe queued at a stop goes out ahead of
        a frame that stop waits for (the writer classifies before it pops), so the clients have
        all of them by now; the gateway's reads are what this waits for, bounded."""
        want = sum(map(probes, self.clients))
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(TIMEOUT_S):
                while rtt_samples() - self.rtt0 < want:
                    await self.stack.clock.settle()
        read = rtt_samples() - self.rtt0
        assert read == want, f"{read:.0f} of {want} RTT probes read in {TIMEOUT_S} s"

    def end(self, before: dict[str, float]) -> None:
        """Read what the teardown would change: it drops the links (a close each) and the series."""
        self.moved = moved(before)
        self.ends = [
            (list(c.gaps), list(c.closes), c.sessions, c.system("connection_quality"))
            for c in self.clients
        ]

    def fanout_ms(self) -> list[float]:
        """Each of the nine's updates from its publish to its `d`'s arrival, loop time, in ms."""
        pairs = (zip(watch.sent, watch.got, strict=True) for watch in self.nine)
        return [1000 * (got - sent) for pair in pairs for (_, sent), (_, got) in pair]

    def burst_ms(self) -> list[float]:
        """Each half tick's burst window, from the move that releases it to its frame's arrival,
        in ms (with the burst on: a lone update leaves at its publish, before the move). Budget
        #6's span starts at the release (23 §8.6, D7); the writer's real poll (at most 5 ms, the
        rig's `tick_s`) and the move's settling stay inside this one, so it is an upper bound."""
        pairs = zip(self.released, self.landed, strict=True)
        return [1000 * (got - released) for released, got in pairs]


async def drive(burst: int, seconds: float, *, timed: bool = False, hold_s: float = 0.0) -> Ten:
    """`seconds` of half ticks on a fresh flag-on stack, the burst symbol at `burst` updates a half
    tick, every client's end read before the teardown. Untimed (the isolation tests), every frame
    is checked (`Watch`); timed (wall clock), the stack has `TCP_NODELAY`, each slice of
    `TIMED_SLICE` ends in a yield (`Ten.step`), and the collector is off for the run (a full
    collection stalls the loop about 100 ms: test_flood_isolation)."""
    async with granted(nodelay=timed) as stack:
        ten = await Ten.connect(stack, checked=not timed)
        before = series()
        if timed:
            gc.collect()
            gc.disable()
        try:
            for _ in range(round(seconds / HALF_S)):
                await ten.step(burst, timed=timed, hold_s=hold_s)
        finally:
            if timed:
                gc.enable()
        ten.end(before)
    return ten


@pytest.mark.parametrize(
    "seconds", [10, pytest.param(60, marks=pytest.mark.harness)], ids=["10s", "60s"]
)
async def test_s3_the_other_nine_symbols_see_the_same_frames_as_without_the_burst(
    seconds: int,
) -> None:
    began = time.perf_counter()
    loud, calm = await drive(PER_HALF, seconds), await drive(1, seconds)  # calm: the control
    halves, burst = round(seconds / HALF_S), loud.burst
    published, frames = burst.feed.published, len(burst.tap.deltas)
    assert published == burst.tap.updates == halves * PER_HALF  # the burst ran, all of it in frames
    assert burst.tap.deltas == windows(PER_HALF, halves)  # the burst test's frames, half the lump
    assert loud.moved == merged(published, frames)  # its windows alone: none of the nine's
    assert calm.moved == {}  # the control merged, dropped and re-snapshotted nothing
    singles = [Delta(s, False, None) for s in range(2, halves + 2)]  # after the snap, `s` 1
    assert calm.burst.tap.deltas == singles
    for run, ten in (("loud", loud), ("calm", calm)):
        for watch in ten.nine:  # one `d` an update, at its publish, no other snap
            ch, tap = f"{run}: {watch.feed.ch}", watch.tap
            assert tap.deltas == singles, ch
            # Zero lateness is structural, not a finding: the clock cannot move until all nine
            # have arrived (`Ten.step`), so this pins the harness, not the gateway.
            assert [v for v, _ in watch.got] == [v for v, _ in watch.sent], ch
            assert tap.replica.gaps == 0 and tap.replica.matches(watch.feed.book, DEPTH), ch
    assert loud.ends == calm.ends == [CLEAN] * (1 + len(NINE))
    digests = [{w.feed.ch: w.digest.hexdigest() for w in ten.nine} for ten in (loud, calm)]
    assert digests[0] == digests[1]  # byte for byte, every data frame the nine's clients got
    print(
        f"#410 s3 isolation {seconds} s: {len(NINE)} symbols x {halves} updates, each its own "
        f"frame at its publish and byte for byte the control's, beside {published} burst updates "
        f"in {frames} frames; {sum(map(probes, loud.clients))} RTT probes, each read before the "
        f"clock moved, no class notice; {time.perf_counter() - began:.2f} s of wall time, both runs"
    )


def p95(ms: list[float]) -> float:
    """Nearest rank: of the nine's 4 320 updates in 60 s, 216 sit above it."""
    return sorted(ms)[math.ceil(0.95 * len(ms)) - 1]


def stalls(ms: list[float]) -> int:
    """How many of `ms` are over `STALL_MS`: stalls, not latencies."""
    return sum(x > STALL_MS for x in ms)


def figures(ms: list[float]) -> str:
    return (
        f"p50 {statistics.median(ms):.2f}, p95 {p95(ms):.2f}, max {max(ms):.2f} ms, "
        f"{stalls(ms)} over {STALL_MS:.0f} ms"
    )


#: The wall-clock checks by name (`verdict`), the negative control's asserted ones among them.
NINE_P95 = "budget #6: the nine's p95"
ADDED_MEDIAN = "the median the burst adds to the nine"
STALL_COUNT = f"the nine's updates over {STALL_MS:.0f} ms (one stall's worth)"
STALL_CEILING = "the nine's slowest update (how long a stall may hold one)"
WINDOW_P95 = "budget #6: the burst's window from its release, p95"


def verdict(what: str, loud: list[Ten], calm: list[Ten]) -> dict[str, tuple[float, float]]:
    """Each wall-clock check by name, (measured, bound), failing above its bound: ms, but for the
    count of stalls; the runs of each kind pooled. Printed with the figures, for the report."""
    nine = [ms for ten in loud for ms in ten.fanout_ms()]
    quiet = [ms for ten in calm for ms in ten.fanout_ms()]
    burst = [ms for ten in loud for ms in ten.burst_ms()]
    assert min(burst) >= 0, f"a burst window left {-min(burst):.2f} ms before its release"
    checks = {
        NINE_P95: (p95(nine), BUDGET_MS),
        ADDED_MEDIAN: (statistics.median(nine) - statistics.median(quiet), TOLERANCE_MS),
        STALL_COUNT: (stalls(nine), len(NINE)),
        STALL_CEILING: (max(nine), 10 * STALL_MS),
        WINDOW_P95: (p95(burst), BUDGET_MS),
    }
    print(
        f"#410 s3 {what}: the nine beside the burst {figures(nine)}; without it {figures(quiet)}; "
        f"the burst's window from its release {figures(burst)}; failed: {failed(checks)}"
    )
    return checks


def failed(checks: dict[str, tuple[float, float]]) -> list[str]:
    return [name for name, (measured, bound) in checks.items() if measured > bound]


@pytest.mark.harness
async def test_s3_fanout_p95_of_the_other_nine_symbols_stays_in_budget_6_during_the_burst() -> None:
    await drive(PER_HALF, WARM_S, timed=True)  # a warm-up, dropped: it pays the cold start
    abba = [await drive(n, TIMED_S / 2, timed=True) for n in (1, PER_HALF, PER_HALF, 1)]
    calm, loud = abba[::3], abba[1:3]  # neither warm caches nor drift favour one
    assert [ten.ends for ten in abba] == [[CLEAN] * (1 + len(NINE))] * 4  # a harness fault
    checks = verdict(f"budget #6, {TIMED_S} s of each (ABBA)", loud, calm)
    assert failed(checks) == [], checks


async def test_s3_the_p95_measure_fails_when_the_hub_is_slow() -> None:
    calm = await drive(1, NEGATIVE_S, timed=True)
    slow = await drive(PER_HALF, NEGATIVE_S, timed=True, hold_s=HOLD_S)
    assert slow.ends == calm.ends == [CLEAN] * (1 + len(NINE))  # slow, yet nothing lost or degraded
    held = f"negative control, {HOLD_S * 1000:.0f} ms held in each slice of the nine and each move"
    checks = verdict(held, [slow], [calm])
    # Each of the nine waits at least `HOLD_S`, and so does each window: both budget #6 checks and
    # the median fail by construction. The stall count fails too and the ceiling holds (the
    # slowest of the nine crosses six holds, 150 ms and up: `SCENARIOS.md`), unasserted.
    assert {NINE_P95, ADDED_MEDIAN, WINDOW_P95} <= set(failed(checks)), checks


class Quiet(Conn):
    """A `Conn` that does not validate each frame against the schemas (about 2 ms a frame)."""

    def push(self, frame: dict[str, Any]) -> None:
        self.out.append(frame)


@pytest.mark.parametrize(
    ("sym", "start"), [(SYM, 0), ("ETHUSDT", LAP)], ids=["from_the_start", "a_lap_in"]
)
def test_s3_loop_feed_returns_to_its_start_window_every_lap_and_matches_the_server_book(
    sym: str, start: int
) -> None:
    source, hub, replica = Source(), SequencingHub(), Replica()
    feed = Loop(source, sym, start)
    conn = Quiet(source)
    hub.register(conn.authz, conn.emitter)
    conn.sub(structured(feed.ch))
    for frame in conn.take():  # the snapshot of the book as the lap begins
        replica.feed(frame)
    opened = dict(replica.bids), dict(replica.asks)
    assert len(opened[0]) == len(opened[1]) == DEPTH and replica.matches(feed.book, DEPTH)
    for lap in range(2):
        for n in range(1, len(feed) + 1):
            assert feed.publish(hub) == 1
            (frame,) = conn.take()
            replica.feed(frame)
            assert replica.matches(feed.book, DEPTH), f"lap {lap}, update {n}"
            if n == len(feed) - 1:  # the bridge has something to take back
                assert (replica.bids, replica.asks) != opened
        assert (replica.bids, replica.asks) == opened, f"lap {lap}: the window did not return"
        assert (feed.book.bids, feed.book.asks) == feed.opening, f"lap {lap}: nor the book"
    assert replica.gaps == 0

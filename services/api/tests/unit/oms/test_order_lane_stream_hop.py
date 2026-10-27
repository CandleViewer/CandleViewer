"""#913 L1d-3, the hop measurement (ruling Q2 of 2026-10-25 22:26Z; L1d-2's ruling (9) of
2026-10-26 16:50Z): how long the order lane's bridge (`oms_streams.LaneStreams`, L1d-2b) takes to
carry a private stream's event from the serving loop, where the adapter's registry reads and
parses it, to the lane.

The span: from the registry's queue taking the event (`put_events`, after its frame's parse, so
never `ts_ingest`, which is stamped before it) to its batch landing on the lane, both read on
`CLOCK`, `time.monotonic`, which is system-wide, so the two threads' readings compare (`Stamps`).
The conditions, a case each, over the adapter's own registry (`PrivateStreams`) and the fake
venue: the burst (`HEAVY`), its `MAX_STREAMS` streams each pushing 4 frames of 8 fills, with one
frame of `FRAME_ROWS_MAX` fills mid-burst, 3,048 fills in all, while a platform task keeps the
serving loop busy for `BUSY_SLICES` slices of CPU, each `BUSY_SLICE_S`, turning it between them,
a fixed work however long the burst takes (`busy`), or only wakes it every `TICK_S` (`ticker`); and
the light burst (`LIGHT`), one fill on each stream, under the ticker. The control: the same burst
and load, each consumer reading the registry on the serving loop, with no hop. Recorded, as each
case's `numbers` property and in its assertions' messages: the p50 and p99 of each, the hop's wake
(from the serving loop's answer to a read to its batch landing on the lane) and batch sizes, the
parse's cost a fill by frame size, the load's turns and `sys.getswitchinterval()`. The ruling's
5 ms at p99 is the orchestrator's threshold for an amendment proposal on #2701, not a bound of
this test, which asserts only the span and its conditions.

The measurement is `perf`-marked, so CI's `py-perf` job owns its timing; the span's definition
test runs in the unit lane, on the measurement's own path and a clock that counts its readings.
No network (C-13.5)."""

from __future__ import annotations

import asyncio
import itertools
import sys
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import AccountRef, PrivateEvent, PrivateStreamStatus
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.exchange.bybit import private_parse
from candleviewer.exchange.bybit import private_stream as ps
from candleviewer.exchange.bybit.private_parse import FRAME_ROWS_MAX, Push
from candleviewer.exchange.bybit.private_stream import MAX_STREAMS, PrivateStreams
from candleviewer.observability.metrics import Metrics
from candleviewer.oms_lane import HOP_TIMEOUT_S, OrderLane, Serving
from candleviewer.oms_streams import LaneStreams
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private import push, row
from tests.unit.exchange.bybit._private_venue import PrivateVenue, VenueSocket, make_streams, until
from tests.unit.exchange.bybit._trading import account, link
from tests.unit.oms.quantile import quantile

#: The clock both ends of the span are read on (ruling (9)): system-wide, so the threads' compare.
CLOCK: Callable[[], float] = time.monotonic
#: The burst's accounts: as many streams as the registry holds.
ACCOUNTS = MAX_STREAMS
#: The busy load: CPU in slices this long, back to back, this many of them, a fixed work.
BUSY_SLICE_S, BUSY_SLICES = 0.001, 1_000
#: The ticker's period: the serving loop woken this often, with no CPU of its own.
TICK_S = 0.001
#: A bound on each of the test's waits, never a time it expects.
BOUND_S = 120.0

#: One fill's span: its start and end readings, and the threads that read them.
type Reading = tuple[float, float, threading.Thread, threading.Thread]
#: The serving loop's other work while a burst crosses, until `done`: how many turns it took.
type Load = Callable[[asyncio.Event], Coroutine[Any, Any, int]]


@dataclass(frozen=True)
class Shape:
    """A burst's shape: each stream's `frames` pushes of `rows` fills, and with `big`, one frame
    of `FRAME_ROWS_MAX` fills on the first stream before the middle round."""

    frames: int
    rows: int
    big: bool


#: The L1d plan's burst: 4 frames of 8 fills on each of the 64 streams and one of 1,000: 3,048.
HEAVY = Shape(frames=4, rows=8, big=True)
#: One fill on each stream: the hop's own wake, with no parse saturating the serving loop.
LIGHT = Shape(frames=1, rows=1, big=False)


class Stamps:
    """The span's two ends (ruling (9)), each read on `clock`: its start as the registry's queue
    takes the event (`taken`), after its frame's parse, on the serving loop; its end as the event
    reaches its consumer, on the lane as its read's batch lands there (`landed`), or in the
    control as the consumer reads it on the serving loop (`read`). Each fill's readings and the
    threads that took them are kept (`readings`); each batch that landed, its size (`batches`)
    and the hop's wake, from the serving loop's answer to the read to that landing (`wakes`); and
    each frame's parse, from `_classify` to `_rows`'s answer, by its fills (`parses`). A fill that
    reaches its consumer with no start is counted (`unstarted`), never raised there."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self.clock = clock
        self._taken: dict[int, tuple[float, threading.Thread]] = {}
        self._parsing = 0.0
        self.readings: list[Reading] = []
        self.batches: list[int] = []
        self.wakes: list[float] = []
        self.parses: list[tuple[int, float]] = []
        self.unstarted = 0

    def parsing(self) -> None:
        self._parsing = self.clock()

    def parsed(self, fills: int) -> None:
        self.parses.append((fills, self.clock() - self._parsing))

    def taken(self, events: Sequence[PrivateEvent]) -> None:
        at, by = self.clock(), threading.current_thread()
        for event in events:
            self._taken[id(event)] = (at, by)

    def landed(self, batch: Sequence[object], answered: float) -> None:
        at = self.clock()
        self._ended(batch, at)
        self.batches.append(len(batch))
        self.wakes.append(at - answered)

    def read(self, item: object) -> None:
        self._ended((item,), self.clock())

    def _ended(self, items: Sequence[object], at: float) -> None:
        by = threading.current_thread()
        for item in items:
            if not isinstance(item, PrivateEvent):
                continue
            if (began := self._taken.pop(id(item), None)) is None:
                self.unstarted += 1
                continue
            start, taker = began
            self.readings.append((start, at, taker, by))

    def spans(self) -> list[float]:
        return [end - start for start, end, _, _ in self.readings]


def stamping(monkeypatch: pytest.MonkeyPatch, stamps: Stamps) -> None:
    """The span's start: the registry's queue takes each event (`_Queue.put_events`), its frame
    parsed (`_classify`, then `_rows`) and its room checked just before; and each frame's parse,
    timed from `_classify` to `_rows`'s answer, which run back to back on the serving loop."""
    put_events = ps._Queue.put_events
    classify, rows = ps._PrivateConn._classify, ps._PrivateConn._rows

    def taken(self: Any, events: Any) -> None:
        stamps.taken(events)
        put_events(self, events)

    def classified(self: Any, frame: str) -> Any:
        stamps.parsing()
        return classify(self, frame)

    def read(self: Any, pushed: Any) -> Any:
        events = rows(self, pushed)
        if events:
            stamps.parsed(len(events))
        return events

    monkeypatch.setattr(ps._Queue, "put_events", taken)
    monkeypatch.setattr(ps._PrivateConn, "_classify", classified)
    monkeypatch.setattr(ps._PrivateConn, "_rows", read)


class Landing(Serving):
    """`Serving`, the bridge's way back to the serving loop, reading the span's end on the lane as
    each read's batch (`_take`'s answer) lands there, and the hop's wake: from `_take`'s answer on
    the serving loop to that landing."""

    def __init__(self, loop: asyncio.AbstractEventLoop, stamps: Stamps) -> None:
        super().__init__(loop, Metrics("demo"))
        self.stamps = stamps

    async def call[T](self, coro: Coroutine[Any, Any, T], *, timeout_s: float = HOP_TIMEOUT_S) -> T:
        if getattr(coro, "__qualname__", "") != "_take":
            return await super().call(coro, timeout_s=timeout_s)
        answered: list[float] = []

        async def take() -> T:
            answer = await coro
            answered.append(self.stamps.clock())
            return answer

        answer = await super().call(take(), timeout_s=timeout_s)
        if isinstance(answer, tuple):
            self.stamps.landed(answer, answered[0])
        return answer


@dataclass
class Burst:
    """A fill burst, each frame built ahead: per round, one frame of each account's; any largest
    frame, sent before the middle round on the first account's stream; each account's fills."""

    refs: list[AccountRef]
    rounds: list[list[str]]
    big: str | None
    fills: list[int]


def fills(ref: AccountRef, seqs: range) -> str:
    """One execution push of `ref`'s fills, one of each of its orders `seqs` name."""
    rows = [
        row("execution")
        | {
            "orderLinkId": link(ref.account_id, seq=seq),
            "execId": str(uuid5(NAMESPACE_URL, f"{ref.account_id}/{seq}")),
            "seq": seq,
        }
        for seq in seqs
    ]
    return push("execution.linear", *rows)


def burst(shape: Shape, accounts: int = ACCOUNTS) -> Burst:
    refs = [account(AccountId(UUID(int=0xB000 + n)), uid=str(300_001 + n)) for n in range(accounts)]
    rounds = [
        [fills(ref, range(r * shape.rows, (r + 1) * shape.rows)) for ref in refs]
        for r in range(shape.frames)
    ]
    big = fills(refs[0], range(2_000, 2_000 + FRAME_ROWS_MAX)) if shape.big else None
    first = FRAME_ROWS_MAX if shape.big else 0  # the largest frame's, each of its own order
    counts = [shape.frames * shape.rows + (first if n == 0 else 0) for n in range(accounts)]
    return Burst(refs, rounds, big, counts)


@asynccontextmanager
async def lane_running() -> AsyncIterator[OrderLane]:
    lane = OrderLane()
    await lane.start()
    try:
        yield lane
    finally:
        await lane.stop()


async def live(venue: PrivateVenue, registry: PrivateStreams, ref: AccountRef) -> None:
    """Until the account's stream has queued its first epoch's `heartbeat` and `resyncing`."""
    queued = registry._conns[ref.account_id].queue.pending
    await until(venue.clock, lambda: queued() == 2, within_s=5, what="live")


async def consume(
    streams: Sequence[PrivateStream],
    counts: Sequence[int],
    primed: threading.Event,
    read: Callable[[object], None] | None,
) -> None:
    """Each stream read by its own consumer, at once, until it has taken its fills: first its two
    opening statuses, `primed` set once every consumer has them; with `read`, the control's, each
    fill's end is read as the consumer takes it."""
    left = len(streams)

    async def one(stream: PrivateStream, count: int) -> None:
        nonlocal left
        for _ in range(2):
            assert isinstance(await anext(stream), PrivateStreamStatus)
        left -= 1
        if not left:
            primed.set()
        while count:
            item = await anext(stream)
            if isinstance(item, PrivateEvent):
                count -= 1
                if read is not None:
                    read(item)

    await asyncio.gather(*(one(s, n) for s, n in zip(streams, counts, strict=True)))


async def busy(done: asyncio.Event) -> int:
    """The serving loop's other work, busy: `BUSY_SLICES` slices of CPU, each `BUSY_SLICE_S`,
    back to back, the loop turned between them, a fixed work however long the burst takes, `done`
    or not; how many of them began before `done`, while the burst crossed."""
    during = BUSY_SLICES
    for n in range(BUSY_SLICES):
        if during == BUSY_SLICES and done.is_set():
            during = n
        end = time.perf_counter() + BUSY_SLICE_S
        while time.perf_counter() < end:
            pass
        await asyncio.sleep(0)
    return during


async def ticker(done: asyncio.Event) -> int:
    """The serving loop's other work, light: a timer every `TICK_S`, with no CPU of its own, until
    `done`; how many times it ticked."""
    ticks = 0
    while not done.is_set():
        await asyncio.sleep(TICK_S)
        ticks += 1
    return ticks


#: Each case's load, by its name.
LOADS: dict[str, Load] = {"busy": busy, "ticker": ticker}


async def pushed(sockets: Sequence[VenueSocket], fill_burst: Burst) -> None:
    """The venue's side of the burst, on the serving loop: each round's frames, one per account,
    any largest frame before the middle round, the loop turned between rounds."""
    for n, frames in enumerate(fill_burst.rounds):
        if fill_burst.big is not None and n == len(fill_burst.rounds) // 2:
            sockets[0].push(fill_burst.big)
        for sock, frame in zip(sockets, frames, strict=True):
            sock.push(frame)
        await asyncio.sleep(0)


async def bursting(
    monkeypatch: pytest.MonkeyPatch,
    stamps: Stamps,
    sockets: Sequence[VenueSocket],
    fill_burst: Burst,
    reading: Awaitable[None],
    load: Load,
) -> int:
    """The burst, its fills stamped as the registry queues them, while `load` runs on the serving
    loop, until every consumer has taken its fills: how many turns the load took meanwhile."""
    with monkeypatch.context() as patched:
        stamping(patched, stamps)
        done = asyncio.Event()
        running = asyncio.ensure_future(load(done))
        try:
            await pushed(sockets, fill_burst)
            await reading
        finally:
            done.set()
            turns = await running
        return turns


async def over_the_hop(
    monkeypatch: pytest.MonkeyPatch, fill_burst: Burst, load: Load
) -> tuple[Stamps, int]:
    """The burst read on the lane across the bridge, each stream opened through it."""
    stamps, venue = Stamps(CLOCK), PrivateVenue(VirtualClock())
    registry = make_streams(venue)
    bridge = LaneStreams(registry.open, Landing(asyncio.get_running_loop(), stamps))
    async with lane_running() as lane:
        streams = []
        for ref in fill_burst.refs:
            streams.append(await lane.call(bridge.open(ref)))
            await live(venue, registry, ref)
        primed = threading.Event()
        reading = lane.call(consume(streams, fill_burst.fills, primed, None))
        assert await asyncio.to_thread(primed.wait, BOUND_S)
        stamps.batches.clear()  # the opening statuses' batches, and their wakes
        stamps.wakes.clear()
        turns = await bursting(monkeypatch, stamps, venue.sockets, fill_burst, reading, load)
        for stream in streams:
            await lane.call(stream.aclose())
    await registry.aclose()
    return stamps, turns


async def on_the_serving_loop(
    monkeypatch: pytest.MonkeyPatch, fill_burst: Burst, load: Load
) -> tuple[Stamps, int]:
    """The control: the burst read from the registry on the serving loop, no hop."""
    stamps, venue = Stamps(CLOCK), PrivateVenue(VirtualClock())
    registry = make_streams(venue)
    streams = []
    for ref in fill_burst.refs:
        streams.append(await registry.open(ref))
        await live(venue, registry, ref)
    primed = threading.Event()
    reading = asyncio.ensure_future(consume(streams, fill_burst.fills, primed, stamps.read))
    assert await asyncio.to_thread(primed.wait, BOUND_S)
    turns = await bursting(monkeypatch, stamps, venue.sockets, fill_burst, reading, load)
    for stream in streams:
        await stream.aclose()
    await registry.aclose()
    return stamps, turns


def summary(samples: Sequence[float]) -> str:
    p50, p99 = quantile(samples, 0.50), quantile(samples, 0.99)
    return f"n {len(samples)}, p50 {p50 * 1e3:.3f} ms, p99 {p99 * 1e3:.3f} ms"


def batch_sizes(batches: Sequence[int]) -> str:
    full = batches.count(max(batches))
    return (
        f"{len(batches)} batches, median {quantile(batches, 0.5):g}, max {max(batches)} "
        f"({full} of it), of 1: {batches.count(1)}"
    )


def parse_costs(parses: Sequence[tuple[int, float]]) -> str:
    """Each frame's parse a fill, at the median, by its fills."""
    by_size: dict[int, list[float]] = {}
    for size, seconds in parses:
        by_size.setdefault(size, []).append(seconds / size)
    return ", ".join(
        f"{size}-fill frames {quantile(each, 0.5) * 1e6:.0f} us ({len(each)})"
        for size, each in sorted(by_size.items())
    )


@pytest.mark.perf
@pytest.mark.parametrize(
    ("shape", "load"),
    [
        pytest.param(HEAVY, "busy", id="burst-busy"),
        pytest.param(HEAVY, "ticker", id="burst-ticker"),
        pytest.param(LIGHT, "ticker", id="light-ticker"),
    ],
)
async def test_the_bridges_hop_measured_under_a_fill_burst(
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
    shape: Shape,
    load: str,
) -> None:
    fill_burst = burst(shape)
    async with asyncio.timeout(BOUND_S):
        hop, hop_turns = await over_the_hop(monkeypatch, fill_burst, LOADS[load])
        control, control_turns = await on_the_serving_loop(monkeypatch, fill_burst, LOADS[load])
    here, total = threading.current_thread(), sum(fill_burst.fills)
    counted = (
        f"of {total} fills, hop {len(hop.readings)} ({hop.unstarted} unstarted), "
        f"control {len(control.readings)} ({control.unstarted} unstarted)"
    )
    assert len(hop.readings) == len(control.readings) == total, counted  # each fill, once
    assert hop.unstarted == control.unstarted == 0, counted
    numbers = (
        f"{total} fills, {load}, switch interval {sys.getswitchinterval() * 1e3:g} ms; hop: "
        f"{summary(hop.spans())}, wake {summary(hop.wakes)}, {batch_sizes(hop.batches)}, "
        f"{load} turns {hop_turns}, parse a fill {parse_costs(hop.parses)}; control: "
        f"{summary(control.spans())}, {load} turns {control_turns}, parse a fill "
        f"{parse_costs(control.parses)}"
    )
    record_property("numbers", numbers)
    hopped = {(taker, lander is here) for *_, taker, lander in hop.readings}
    assert hopped == {(here, False)}, numbers  # read on the serving loop, landed on the lane
    assert {(taker, lander) for *_, taker, lander in control.readings} == {(here, here)}, numbers
    assert hop_turns and control_turns, numbers  # the load ran on the serving loop meanwhile


# --- the span's definition, on the measurement's own path and a clock that counts its readings ---


class Ticks:
    """A clock for the span's definition: each reading the next integer, whichever thread reads
    it, so the readings' order is the order they were taken in; each reading it gave is kept
    (`given`)."""

    def __init__(self) -> None:
        self._next = itertools.count()
        self.given: set[float] = set()

    def __call__(self) -> float:
        tick = float(next(self._next))
        self.given.add(tick)
        return tick


async def test_the_span_starts_as_the_registry_queues_a_fill_after_its_frames_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling (9)'s span, on the measurement's own path (`over_the_hop`, `on_the_serving_loop`)
    over a burst of 3 fills: each fill's start read on the serving loop as the registry's queue
    takes it (`put_events`), after its frame's parse (`classify`, then `read_push`), never before
    it as `ts_ingest` is; its end on the lane as its read's batch lands there, or in the control
    as its consumer reads it on the serving loop; and each read on `CLOCK`, which is
    `time.monotonic`, as ruled: a clock that counts, put in its place, gives every reading."""
    assert CLOCK is time.monotonic
    ticks, parse = Ticks(), list[float]()
    classify, read_push = private_parse.classify, private_parse.read_push

    def classified(frame: str) -> Any:
        began, item = ticks(), classify(frame)
        if isinstance(item, Push):  # a push's frame; each reply is classified too
            parse.append(began)
        return item

    def read(pushed: Any, ref: AccountRef, *, now_us: int) -> Any:
        events = read_push(pushed, ref, now_us=now_us)
        parse.append(ticks())
        return events

    monkeypatch.setattr(ps, "classify", classified)
    monkeypatch.setattr(ps, "read_push", read)
    monkeypatch.setattr(sys.modules[__name__], "CLOCK", ticks)
    three, here = burst(Shape(frames=1, rows=3, big=False), accounts=1), threading.current_thread()
    for measured, on_lane in ((over_the_hop, True), (on_the_serving_loop, False)):
        parse.clear()
        async with asyncio.timeout(BOUND_S):
            stamps, _ = await measured(monkeypatch, three, ticker)
        began, parsed = parse  # the fills' frame: its parse began, then its rows were read
        assert len(stamps.readings) == 3
        for start, end, taker, lander in stamps.readings:
            assert began < parsed < start < end
            assert {start, end} <= ticks.given  # read on `CLOCK`
            assert taker is here and (lander is not here) is on_lane

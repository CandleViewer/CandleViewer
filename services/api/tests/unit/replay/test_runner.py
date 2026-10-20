"""`ReplayRun` (E26-T03): one session's playback end to end through the real clock, injector,
replay books and bus, on fake time only (C-13.7). The Gherkin at the run level: backpressure
slows and never drops; a gap is honoured explicitly (skip and stop) and a book-stream gap
resets that symbol's replay book; replay traffic never reaches live state. Then the loop wrap
(US-RPL-008): new ids under the next generation, the same ids for the same controls (C-2.15),
and never a race with a pause or a close; and destroy: no task left, every source closed once."""

from __future__ import annotations

import asyncio
import itertools
import uuid
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.book.resync import BookEngine
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic, is_replay_env, replay_env
from candleviewer.domain.events import MarketEvent
from candleviewer.exchange.base.models import BookDelta, BookSnapshot, TradeEvent
from candleviewer.replay import (
    STEP,
    UNBOUNDED,
    ClockConfig,
    PlaybackStats,
    ReplayClock,
    ReplayClockStateError,
    ReplayConfigInvalid,
    ReplayGap,
    ReplayInjector,
    ReplayItem,
    ReplayRequestInvalid,
    ReplayRun,
    StopReason,
)
from candleviewer.replay.injector import replay_event_id
from candleviewer.replay_wiring import (
    LIVE_EVENT_MODELS,
    ReplayBooks,
    build_replay_injector,
    build_replay_run,
    replay_source_factory,
)
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import (
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedEvent,
    RecordedTrade,
)
from tests.unit.book._builders import delta as live_delta
from tests.unit.book._builders import lvl
from tests.unit.book._builders import snap as live_snap
from tests.unit.replay._events import SECOND, SYM, T0, Harness, request
from tests.unit.replay._playback import ListStream
from tests.unit.replay._time import FakeTime

SESSION = uuid.UUID("0b7c5e1a-3f2d-4c8e-9a61-5d0e7b2c4f18")
ENV = replay_env(SESSION)
TICK = Decimal("0.1")
TRADES, DELTAS, SNAPSHOTS = (
    StreamKind.TRADES,
    StreamKind.ORDERBOOK_DELTA,
    StreamKind.ORDERBOOK_SNAPSHOT,
)
REEMITTED = (TRADES, DELTAS, SNAPSHOTS)


def px(text: str) -> Decimal:
    return Decimal(text)


def tape(offset_us: int, n: int, *, price: str = "100.1", side: str = "buy") -> RecordedEvent:
    payload = RecordedTrade(side, px(price), px("0.5"), f"r{n}", None)
    return RecordedEvent(T0 + offset_us, n, SYM, TRADES, (f"r{n}",), payload)


def book_row(offset_us: int, update_id: int, side: str, price: str, size: str) -> RecordedEvent:
    """One recorded `orderbook_deltas` row (a level), as recorded before E26-T03."""
    payload = RecordedBookDelta(200, side, px(price), px(size), update_id, None)
    key = (update_id, 200, side, px(price))
    return RecordedEvent(T0 + offset_us, update_id, SYM, DELTAS, key, payload)


def book_snapshot(offset_us: int, update_id: int) -> RecordedEvent:
    payload = RecordedBookSnapshot(
        200, update_id, None, ((px("100.0"), px("1")),), ((px("100.2"), px("1")),)
    )
    return RecordedEvent(T0 + offset_us, update_id, SYM, SNAPSHOTS, (update_id, 200, -1), payload)


def gap(start_s: int, end_s: int, stream: StreamKind = TRADES) -> ReplayGap:
    return ReplayGap(
        T0 + start_s * SECOND,
        SYM,
        stream,
        T0 + start_s * SECOND,
        T0 + end_s * SECOND,
        "ws_disconnect",
    )


#: A recorded stretch of BTCUSDT: a snapshot, one book update of two rows, two trades.
RECORDING: list[ReplayItem] = [
    book_snapshot(1 * SECOND, 500),
    book_row(2 * SECOND, 501, "ask", "100.2", "0"),
    book_row(2 * SECOND, 501, "bid", "100.1", "3"),
    tape(3 * SECOND, 1),
    tape(4 * SECOND, 2, price="100.2", side="sell"),
]
#: Its re-emitted events (one per update), with their replay times.
PASS_TS = [T0 + 1 * SECOND, T0 + 2 * SECOND, T0 + 3 * SECOND, T0 + 4 * SECOND]


class LoggingBus(Bus):
    """The real bus, also noting every `(fake time, topic, event)` published."""

    def __init__(self, time: FakeTime | None = None) -> None:
        super().__init__()
        self.time = time
        self.log: list[tuple[float, Topic, object]] = []

    async def publish(self, topic: Topic, event: object) -> None:
        self.log.append((0.0 if self.time is None else self.time.now(), topic, event))
        await super().publish(topic, event)

    def market(self, start: int = 0) -> list[MarketEvent]:
        return [e for _, _, e in self.log[start:] if isinstance(e, MarketEvent)]

    def trade_ids(self) -> list[str]:
        return [e.trade_id for e in self.market() if isinstance(e, TradeEvent)]


class RecordingPort:
    """`ReplayRunPort` double: every notice, in order; `on_loop_hook` runs on each wrap."""

    def __init__(self, time: FakeTime | None = None) -> None:
        self.time = time
        self.progress: list[tuple[float, PlaybackStats]] = []
        self.gaps: list[tuple[ReplayGap, bool, int]] = []
        self.edges: list[bool] = []
        self.loops: list[int] = []
        self.stops: list[tuple[StopReason, Exception | None]] = []
        self.last: PlaybackStats | None = None
        self.on_loop_hook: Callable[[int], None] | None = None

    def on_progress(self, stats: PlaybackStats) -> None:
        self.progress.append((0.0 if self.time is None else self.time.now(), stats))

    def on_gap(self, gap: ReplayGap, *, stopped: bool, stats: PlaybackStats) -> None:
        self.gaps.append((gap, stopped, stats.gap_warnings))

    def on_backpressure(self, active: bool, stats: PlaybackStats) -> None:
        self.edges.append(active)

    def on_loop(self, generation: int, stats: PlaybackStats) -> None:
        self.loops.append(generation)
        self.last = stats
        if self.on_loop_hook is not None:
            self.on_loop_hook(generation)

    def on_stop(self, reason: StopReason, error: Exception | None, stats: PlaybackStats) -> None:
        self.stops.append((reason, error))
        self.last = stats


class Sources:
    """A `SourceFactory` over a recording: every open is a fresh `ListStream` of the items at or
    after the position. `opened` and `positions` record each open; `streams`, if given, serves
    those streams, in turn, instead."""

    def __init__(
        self, items: Iterable[ReplayItem], *, streams: Sequence[ListStream] | None = None
    ) -> None:
        self.items = list(items)
        self.queue = list(streams or ())
        self.opened: list[ListStream] = []
        self.positions: list[int] = []
        self.fail_on: int | None = None  # the open (0-based) that raises

    def __call__(self, at_us: int) -> ListStream:
        if self.fail_on == len(self.opened):
            raise ReplayConfigInvalid("the source cannot be opened")
        stream = (
            self.queue.pop(0)
            if self.queue
            else ListStream(i for i in self.items if i.ts_us >= at_us)
        )
        self.opened.append(stream)
        self.positions.append(at_us)
        return stream


async def settle() -> None:
    for _ in range(200):
        await asyncio.sleep(0)


def make_run(
    sources: Sources,
    *,
    bus: Bus,
    port: RecordingPort | None = None,
    time: FakeTime | None = None,
    speed: float = 1.0,
    loop: bool = False,
    config: ClockConfig | None = None,
    end_s: int = 60,
    injector: ReplayInjector | None = None,
    progress_interval_s: float = 1.0,
) -> ReplayRun:
    req = request(streams=REEMITTED, end_us=end_s * SECOND)
    return ReplayRun(
        request=req,
        open_source=sources,
        injector=injector
        or build_replay_injector(session_id=SESSION, request=req, tick_sizes={SYM: TICK}, bus=bus),
        port=port or RecordingPort(),
        time=time or FakeTime(),
        speed=speed,
        loop=loop,
        config=config,
        progress_interval_s=progress_interval_s,
    )


# --- AC 2: backpressure slows, never drops -------------------------------------------------


async def test_backpressure_slows_playback_and_every_event_still_arrives_once_in_order() -> None:
    """Ticket AC 2 at the run level: at 10x a trade is due every 1 ms, and a `NEVER_DROP` bus
    subscriber takes one every 2 ms of fake time (half the rate). Every recorded trade still
    arrives once and in order, and the run reports an achieved rate below the requested one."""
    time, bus = FakeTime(), Bus()
    items = [tape(i * 10_000, i) for i in range(300)]
    sub = bus.subscribe("slow", f"{ENV}.md.{SYM}.trade", QueuePolicy.NEVER_DROP, maxsize=4)
    got: list[str] = []

    async def consume() -> None:
        while len(got) < len(items):
            event = await sub.get()
            assert isinstance(event, TradeEvent) and event.source == "replay"
            got.append(event.trade_id)
            time.advance(0.002)
            await asyncio.sleep(0)

    port = RecordingPort(time)
    config = ClockConfig(max_lag_s=0.02, rate_window_s=0.1)
    run = make_run(
        Sources(items), bus=bus, port=port, time=time, speed=10.0, config=config,
        progress_interval_s=0.05,
    )  # fmt: skip
    async with run:
        consumer = asyncio.ensure_future(consume())
        assert await run.play() == "range_end"
        await consumer
    assert got == [f"r{i}" for i in range(300)]
    paced = [s for _, s in port.progress if s.achieved_ratio is not None]
    assert paced and all(s.achieved_speed is not None and s.achieved_speed < 10.0 for s in paced)
    ratio = paced[-1].achieved_ratio
    assert ratio is not None and 0.3 < ratio < 0.7
    assert port.edges[0] is True and run.stats().backpressure_s > 0
    assert port.stops == [("range_end", None)]


# --- AC 5: a gap is honoured explicitly ----------------------------------------------------


async def test_a_skipped_gap_jumps_to_its_end_counts_it_and_tells_the_session() -> None:
    time = FakeTime()
    bus, port = LoggingBus(time), RecordingPort(time)
    marker = gap(3, 600)
    items = [tape(1 * SECOND, 1), tape(2 * SECOND, 2), marker, tape(600 * SECOND, 3)]
    run = make_run(Sources(items), bus=bus, port=port, time=time, end_s=700)
    start = time.now()
    async with run:
        assert await run.play() == "range_end"
    assert bus.trade_ids() == ["r1", "r2", "r3"]
    at = [t for t, _, e in bus.log if isinstance(e, TradeEvent)]
    assert at[-1] - start == pytest.approx(3.0)  # 597 empty seconds compressed, not waited
    assert run.stats().gap_warnings == 1
    assert port.gaps == [(marker, False, 1)]
    assert port.stops == [("range_end", None)]


async def test_stop_at_gap_pauses_at_the_boundary_and_play_goes_on_after_it() -> None:
    bus, port = LoggingBus(), RecordingPort()
    marker = gap(3, 600)
    items = [tape(1 * SECOND, 1), tape(2 * SECOND, 2), marker, tape(600 * SECOND, 3)]
    config = ClockConfig(gap_policy="stop")
    run = make_run(Sources(items), bus=bus, port=port, end_s=700, config=config)
    async with run:
        assert await run.play() == "gap"
        assert bus.trade_ids() == ["r1", "r2"] and run.now_us() == T0 + 3 * SECOND
        assert port.gaps == [(marker, True, 1)] and port.stops == [("gap", None)]
        assert not run.playing
        assert await run.play() == "range_end"
    assert bus.trade_ids() == ["r1", "r2", "r3"]
    assert port.stops == [("gap", None), ("range_end", None)]


#: A book that chains across a recording gap: the legacy `prev_update_id` of update 502 is 501.
CHAINED_BOOK: list[ReplayItem] = [
    book_snapshot(1 * SECOND, 500),
    book_row(2 * SECOND, 501, "bid", "100.1", "3"),
    book_row(6 * SECOND, 502, "bid", "100.0", "2"),
    book_snapshot(8 * SECOND, 600),
    book_row(9 * SECOND, 601, "ask", "100.3", "1"),
]


async def _replay_book(items: list[ReplayItem]) -> LoggingBus:
    bus = LoggingBus()
    async with make_run(Sources(items), bus=bus, speed=UNBOUNDED) as run:
        assert await run.play() == "range_end"
    return bus


@pytest.mark.parametrize("stream", [DELTAS, SNAPSHOTS])
async def test_a_book_stream_gap_resets_that_books_replay_until_the_next_snapshot(
    stream: StreamKind,
) -> None:
    """24 Sec.13.7, "A derivation never hides a gap": the clock keeps the marker from the
    injector and update 502 still chains onto 501, so without the reset the replay book would
    bridge the gap. With it, the book leaves LIVE before the next event and waits for snapshot
    600; 502 is never applied."""
    applied = [
        e.update_id for e in (await _replay_book(CHAINED_BOOK)).market() if isinstance(e, BookDelta)
    ]
    assert applied == [501, 502, 601]  # the control: no marker, nothing to notice
    bus = await _replay_book([*CHAINED_BOOK[:2], gap(3, 5, stream), *CHAINED_BOOK[2:]])
    assert [e.update_id for e in bus.market() if isinstance(e, BookDelta)] == [501, 601]
    statuses = [(s.state, s.reason) for _, _, s in bus.log if isinstance(s, BookStatus)]
    assert statuses == [
        (BookPhase.LIVE, "live"),
        (BookPhase.DESYNCED, "recording_gap"),
        (BookPhase.LIVE, "live"),
    ]
    assert {topic.key for _, topic, _ in bus.log} == {f"{ENV}.md.{SYM}.book"}


async def test_a_gap_on_another_stream_leaves_the_replay_book_live() -> None:
    bus = await _replay_book([*CHAINED_BOOK[:2], gap(3, 5, TRADES), *CHAINED_BOOK[2:]])
    assert [e.update_id for e in bus.market() if isinstance(e, BookDelta)] == [501, 502, 601]


class ResetFailed(Exception):
    """What a replay book's reset raises when it fails."""


class FailsFirstGapReset:
    """`ReplayBookHook` over the session's real replay books whose first per-symbol reset (a
    recording gap's) raises before it touches a book: one transient failure."""

    def __init__(self, bus: Bus) -> None:
        self.books = ReplayBooks(bus, SESSION)
        self.resets: list[str | None] = []  # the `symbol` of every reset asked for, in order
        self.failure = ResetFailed("the replay book reset failed")
        self._failed = False

    async def apply(self, event: MarketEvent) -> None:
        await self.books.apply(event)

    async def reset(self, reason: str, *, symbol: str | None = None) -> None:
        self.resets.append(symbol)
        if symbol is not None and not self._failed:
            self._failed = True
            raise self.failure
        await self.books.reset(reason, symbol=symbol)


async def test_a_failed_gap_reset_is_retried_before_the_next_event_is_delivered() -> None:
    """The run keeps a symbol marked until its book reset is done, so a transient failure never
    lets the book bridge the gap (24 Sec.13.7): the playback ends `error` with the next event,
    update 502 (which still chains onto 501), pending, and the next `play()` resets the book
    first. 502 is never applied, and the book ends as it does after a reset that never failed."""
    bus, port = LoggingBus(), RecordingPort()
    hook = FailsFirstGapReset(bus)
    req = request(streams=REEMITTED, end_us=60 * SECOND)
    injector = ReplayInjector(
        session_id=SESSION,
        request=req,
        tick_sizes={SYM: TICK},
        bus=bus,
        books=hook,
        models=LIVE_EVENT_MODELS,
    )
    sources = Sources([*CHAINED_BOOK[:2], gap(3, 5, DELTAS), *CHAINED_BOOK[2:]])

    def published() -> list[int]:
        return [e.update_id for e in bus.market() if isinstance(e, BookDelta)]

    async with make_run(sources, bus=bus, port=port, speed=UNBOUNDED, injector=injector) as run:
        assert await run.play() == "error"
        assert port.stops == [("error", hook.failure)]
        assert hook.resets == [SYM] and published() == [501]  # 502 waits, undelivered
        assert await run.play() == "range_end"
    assert hook.resets == [SYM, SYM]  # retried, once more and then no more
    assert published() == [501, 601]  # 502 never applied: the reset came first
    statuses = [(s.state, s.reason) for _, _, s in bus.log if isinstance(s, BookStatus)]
    assert statuses == [
        (BookPhase.LIVE, "live"),
        (BookPhase.DESYNCED, "recording_gap"),
        (BookPhase.LIVE, "live"),
    ]
    assert port.stops == [("error", hook.failure), ("range_end", None)]


# --- loop wrap (US-RPL-008) -----------------------------------------------------------------


def _ids(generation: int) -> list[uuid.UUID]:
    return [replay_event_id(ts, SESSION, generation, i) for i, ts in enumerate(PASS_TS)]


def _shape(event: MarketEvent) -> dict[str, object]:
    """An event without its identity (and a book's republish label: the engine names its first
    snapshot `subscribe`, later ones `resync`)."""
    skip = {"event_id", "reason"} if isinstance(event, BookSnapshot) else {"event_id"}
    return event.model_dump(exclude=skip)


async def _loop_twice(speed: float = UNBOUNDED) -> tuple[LoggingBus, RecordingPort, list[int]]:
    """Play with the loop on and turn it off at the first wrap: two passes. Returns the bus, the
    port and where each pass starts in the bus log."""
    bus, port, sources = LoggingBus(), RecordingPort(), Sources(RECORDING)
    run = make_run(sources, bus=bus, port=port, loop=True, speed=speed)
    starts = [0]

    def wrapped(generation: int) -> None:
        starts.append(len(bus.log))
        run.set_loop(False)  # the second pass is the last

    port.on_loop_hook = wrapped
    async with run:
        assert await run.play() == "range_end"
        assert run.generation == 1 and not run.loop
    assert sources.positions == [T0, T0] and [s.closes for s in sources.opened] == [1, 1]
    return bus, port, starts


@pytest.mark.parametrize("speed", [UNBOUNDED, 1.0])
async def test_a_loop_replays_the_range_under_the_next_generation_with_new_ids(
    speed: float,
) -> None:
    bus, port, (_, second) = await _loop_twice(speed)
    one, two = bus.market(0)[: len(PASS_TS)], bus.market(second)
    assert [e.event_id for e in one] == _ids(0)  # generation 0, ordinals 0..3
    assert [e.event_id for e in two] == _ids(1)  # generation 1, the ordinal back to 0
    assert [_shape(e) for e in one] == [_shape(e) for e in two]
    assert port.loops == [1] and port.stops == [("range_end", None)]
    assert port.last is not None and port.last.cursor_us == T0 + 60 * SECOND


async def test_the_same_controls_reproduce_the_same_ids_c_2_15() -> None:
    first, _, _ = await _loop_twice()
    again, _, _ = await _loop_twice()
    ids = [e.event_id for e in first.market()]
    assert ids == [e.event_id for e in again.market()] and len(set(ids)) == len(ids) == 8


async def test_a_wrap_resets_the_replay_book_which_rebuilds_from_the_recording() -> None:
    bus, _, (_, second) = await _loop_twice()
    statuses = [
        (s.state, s.reason) for _, _, s in bus.log[second - 1 :] if isinstance(s, BookStatus)
    ]
    assert statuses[0] == (BookPhase.DESYNCED, "replay_restart")
    assert statuses[-1] == (BookPhase.LIVE, "live")


async def test_a_range_with_nothing_reemitted_is_not_looped() -> None:
    port = RecordingPort()
    sources = Sources([gap(1, 2)])  # only a marker: looping it would spin
    async with make_run(sources, bus=Bus(), port=port, loop=True) as run:
        assert await run.play() == "range_end"
    assert (port.loops, port.stops, len(sources.opened)) == ([], [("range_end", None)], 1)


async def test_a_pass_that_finds_the_recording_gone_ends_the_loop() -> None:
    """The second pass re-emits nothing (the range was pruned meanwhile): no third wrap."""
    port = RecordingPort()
    sources = Sources(RECORDING, streams=[ListStream(RECORDING), ListStream([])])
    async with make_run(sources, bus=Bus(), port=port, loop=True) as run:
        assert await run.play() == "range_end"
    assert (port.loops, port.stops, len(sources.opened)) == ([1], [("range_end", None)], 2)


class GatedBooks:
    """`ReplayBookHook` double whose whole-session reset (a wrap's) parks on `gate`."""

    def __init__(self) -> None:
        self.entered, self.gate = asyncio.Event(), asyncio.Event()
        self.resets: list[str] = []

    async def apply(self, event: MarketEvent) -> None:
        return None

    async def reset(self, reason: str, *, symbol: str | None = None) -> None:
        if symbol is None:
            self.entered.set()
            await self.gate.wait()
        self.resets.append(reason)


def gated_run(
    sources: Sources, books: GatedBooks, bus: LoggingBus, port: RecordingPort
) -> ReplayRun:
    req = request(streams=REEMITTED, end_us=60 * SECOND)
    injector = ReplayInjector(
        session_id=SESSION,
        request=req,
        tick_sizes={SYM: TICK},
        bus=bus,
        books=books,
        models=LIVE_EVENT_MODELS,
    )
    return make_run(sources, bus=bus, port=port, loop=True, speed=UNBOUNDED, injector=injector)


async def test_a_pause_during_a_wrap_lets_it_finish_and_nothing_plays_after_it() -> None:
    """The loop wrap never races a pause: the pause waits for the wrap in progress, which
    completes (one generation more, the cursor at range_start), and playback does not resume.
    The next `play()` plays the new pass under that generation."""
    books, bus, port, sources = GatedBooks(), LoggingBus(), RecordingPort(), Sources(RECORDING)
    async with gated_run(sources, books, bus, port) as run:
        done = run.play()
        await books.entered.wait()  # the driver is inside the wrap's book reset
        pausing = asyncio.ensure_future(run.pause())
        await settle()
        assert not pausing.done() and run.playing
        books.gate.set()
        await pausing
        assert await done == "paused" and not run.playing
        assert (run.generation, run.now_us(), port.loops) == (1, T0, [1])
        assert port.stops == [("paused", None)]
        assert bus.trade_ids() == ["r1", "r2"]  # the first pass only
        assert [s.closes for s in sources.opened] == [1, 0]  # the old one closed, the new held
        run.set_loop(False)
        assert await run.play() == "range_end"
    assert bus.trade_ids() == ["r1", "r2", "r1", "r2"]
    assert [e.event_id for e in bus.market() if isinstance(e, TradeEvent)][2:] == _ids(1)[2:]
    assert [s.closes for s in sources.opened] == [1, 1]


async def test_speed_zero_during_a_wrap_stops_playback_once_it_is_done() -> None:
    books, bus, port, sources = GatedBooks(), LoggingBus(), RecordingPort(), Sources(RECORDING)
    async with gated_run(sources, books, bus, port) as run:
        done = run.play()
        await books.entered.wait()
        run.set_speed(STEP)
        books.gate.set()
        assert await done == "paused"
        assert (run.generation, port.stops) == (1, [("paused", None)])
        assert await run.step_events(2) == "step"  # step mode, from range_start
        assert (run.stats().events_emitted, run.generation) == (6, 1)
    assert bus.trade_ids() == ["r1", "r2"]  # the step re-emitted the snapshot and the update


class GatedCloseStream(ListStream):
    """A `ListStream` whose close parks on `gate`, as a source stopping its producer can."""

    def __init__(self, items: Iterable[ReplayItem]) -> None:
        super().__init__(items)
        self.closing, self.gate = asyncio.Event(), asyncio.Event()

    async def aclose(self) -> None:
        self.closing.set()
        await self.gate.wait()
        await super().aclose()


async def test_a_close_during_a_wraps_book_reset_cancels_it_and_leaves_nothing_behind() -> None:
    before = asyncio.all_tasks()
    books, bus, port, sources = GatedBooks(), LoggingBus(), RecordingPort(), Sources(RECORDING)
    async with gated_run(sources, books, bus, port) as run:
        done = run.play()
        await books.entered.wait()
        await run.aclose()  # the session is destroyed mid-wrap
        assert done.cancelled() and not run.playing
        assert (run.generation, port.loops, port.stops) == (0, [], [])
    assert [s.closes for s in sources.opened] == [1]  # no new source was opened for the wrap
    assert asyncio.all_tasks() - before == set()


async def test_a_close_while_a_wrap_closes_the_old_source_closes_both_exactly_once() -> None:
    before = asyncio.all_tasks()
    old = GatedCloseStream(RECORDING)
    sources = Sources(RECORDING, streams=[old])
    bus, port = LoggingBus(), RecordingPort()
    async with make_run(sources, bus=bus, port=port, loop=True, speed=UNBOUNDED) as run:
        done = run.play()
        await old.closing.wait()  # the wrap swapped sources and is closing the old one
        closing = asyncio.ensure_future(run.aclose())
        await settle()
        assert done.cancelled() and not closing.done()  # waiting for the old source's close
        old.gate.set()
        await closing
        assert (run.generation, port.stops) == (1, [])
    assert [s.closes for s in sources.opened] == [1, 1]
    assert asyncio.all_tasks() - before == set()


async def test_destroy_mid_play_cancels_the_delivery_in_flight_and_leaves_no_task() -> None:
    """Destroy while playback is held back by a consumer that never reads: the delivery in flight
    is cancelled, the source closes once and no task of the run is left."""
    before = asyncio.all_tasks()
    bus, sources = Bus(), Sources([tape(i * SECOND, i) for i in range(1, 6)])
    stuck = bus.subscribe("stuck", f"{ENV}.md.{SYM}.trade", QueuePolicy.NEVER_DROP, maxsize=1)
    run = make_run(sources, bus=bus, speed=UNBOUNDED)
    owner = asyncio.ensure_future(run.serve())
    await settle()
    done = run.play()
    await settle()
    assert run.playing and stuck.qsize() == 1  # the second trade waits for room
    await run.aclose()
    await owner
    assert done.cancelled() and not run.playing
    assert [s.closes for s in sources.opened] == [1] and stuck.qsize() == 1
    assert asyncio.all_tasks() - before == set()
    await run.aclose()  # idempotent
    with pytest.raises(ReplayClockStateError, match="not open"):
        run.play()
    with pytest.raises(ReplayClockStateError, match="closed"):
        await run.step_event()
    with pytest.raises(ReplayClockStateError, match="opened once"):
        await run.__aenter__()


async def test_cancelling_the_session_task_closes_the_run() -> None:
    """The replay sessions' TaskGroup stopping cancels each session task: `serve()` leaves the
    run closed, its source closed once and no task behind."""
    before = asyncio.all_tasks()
    sources = Sources([tape(i * SECOND, i) for i in range(1, 6)])
    run = make_run(sources, bus=Bus(), time=FakeTime(auto=False))
    owner = asyncio.ensure_future(run.serve())
    await settle()
    run.play()
    await settle()
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    assert [s.closes for s in sources.opened] == [1] and not run.playing
    assert asyncio.all_tasks() - before == set()


async def test_closing_a_run_that_never_opened_closes_its_source() -> None:
    sources = Sources(RECORDING)
    run = make_run(sources, bus=Bus())
    await run.aclose()
    assert [s.closes for s in sources.opened] == [1]


# --- refusals, controls, steps, progress, failures -----------------------------------------


@pytest.mark.parametrize(
    "stream", [StreamKind.TICKERS, StreamKind.KLINES, StreamKind.FUNDING_RATES]
)
def test_a_session_reading_a_stream_not_reemitted_is_refused_before_any_source_opens(
    stream: StreamKind,
) -> None:
    sources = Sources(RECORDING)
    good = request(streams=REEMITTED)
    injector = build_replay_injector(
        session_id=SESSION, request=good, tick_sizes={SYM: TICK}, bus=Bus()
    )
    with pytest.raises(ReplayRequestInvalid, match=f"streams {stream.value} are not re-emitted"):
        ReplayRun(
            request=request(streams=(TRADES, stream)),
            open_source=sources,
            injector=injector,
            port=RecordingPort(),
            time=FakeTime(),
        )
    assert sources.opened == []


@pytest.mark.parametrize(
    ("speed", "interval", "error"),
    [(0.05, 1.0, ReplayRequestInvalid), (1.0, 0.0, ReplayConfigInvalid)],
)
def test_a_bad_speed_or_progress_interval_is_refused_before_any_source_opens(
    speed: float, interval: float, error: type[Exception]
) -> None:
    sources = Sources(RECORDING)
    with pytest.raises(error):
        make_run(sources, bus=Bus(), speed=speed, progress_interval_s=interval)
    assert sources.opened == []


async def test_controls_the_run_refuses_while_playing_and_before_opening() -> None:
    run = make_run(Sources(RECORDING), bus=Bus(), time=FakeTime(auto=False))
    with pytest.raises(ReplayClockStateError, match="not open"):
        run.play()
    async with run:
        with pytest.raises(ReplayClockStateError, match="opened once"):
            await run.__aenter__()
        done = run.play()
        await settle()
        with pytest.raises(ReplayClockStateError, match="already running"):
            run.play()
        with pytest.raises(ReplayClockStateError, match="pause playback"):
            await run.step_event()
        await run.pause()
        assert await done == "paused" and not run.playing
        await run.pause()  # idle: a no-op
        run.set_speed(STEP)
        with pytest.raises(ReplayClockStateError, match="step mode"):
            run.play()
        assert run.stats().speed == STEP


class Probe:
    """A count bar of two events: `step_bar` stops on its closing event."""

    def __init__(self) -> None:
        self.seen = 0

    def due_us(self) -> int | None:
        return None

    def apply(self, event: RecordedEvent) -> bool:
        self.seen += 1
        return self.seen % 2 == 0

    def tick(self, now_us: int) -> bool:
        return False


async def test_the_steps_are_the_clocks_and_never_wrap_the_loop() -> None:
    bus, port = LoggingBus(), RecordingPort()
    async with make_run(Sources(RECORDING), bus=bus, port=port, loop=True, speed=STEP) as run:
        assert run.bar_probe is None
        run.bar_probe = probe = Probe()
        assert await run.step_event() == "step"  # the snapshot
        assert await run.step_bar() == "step"  # the update closes the two-event bar
        assert (probe.seen, bus.trade_ids()) == (2, [])
        assert await run.step_ms(500) == "step"  # nothing in the next 500 ms
        assert run.now_us() == T0 + 2_500_000
        assert await run.step_events(5) == "range_end"  # the last trade, then the end
        assert (run.generation, port.loops, port.stops) == (0, [], [])
    assert bus.trade_ids() == ["r1", "r2"]


async def test_progress_is_reported_at_most_once_per_interval_while_events_flow() -> None:
    time = FakeTime()
    port = RecordingPort(time)
    items = [tape(i * 250_000, i) for i in range(1, 41)]  # 10 s of trades, one every 250 ms
    run = make_run(Sources(items), bus=Bus(), port=port, time=time)
    start = time.now()
    async with run:
        assert await run.play() == "range_end"
    at = [start, *(t for t, _ in port.progress)]
    assert 8 <= len(port.progress) <= 10
    assert all(b - a >= 1.0 - 1e-9 for a, b in itertools.pairwise(at))
    emitted = [s.events_emitted for _, s in port.progress]
    assert emitted == sorted(emitted) and emitted[-1] < 40  # each counts the events before it
    cursors = [s.cursor_us for _, s in port.progress]
    assert cursors == sorted(cursors) and all(s.speed == 1.0 for _, s in port.progress)


async def test_a_wrap_that_cannot_open_its_source_stops_with_error() -> None:
    port, sources = RecordingPort(), Sources(RECORDING)
    sources.fail_on = 1  # the wrap's open
    async with make_run(sources, bus=Bus(), port=port, loop=True, speed=UNBOUNDED) as run:
        assert await run.play() == "error"
        [(reason, error)] = port.stops
        assert reason == "error" and isinstance(error, ReplayConfigInvalid)
        assert not run.playing
    assert [s.closes for s in sources.opened] == [1]


async def test_a_refused_reposition_closes_the_source_the_wrap_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(self: ReplayClock, source: object, *, at_us: int) -> None:
        raise ReplayClockStateError("refused")

    monkeypatch.setattr(ReplayClock, "reposition", refuse)
    port, sources = RecordingPort(), Sources(RECORDING)
    async with make_run(sources, bus=Bus(), port=port, loop=True, speed=UNBOUNDED) as run:
        assert await run.play() == "error"
        assert isinstance(port.stops[0][1], ReplayClockStateError)
    assert [s.closes for s in sources.opened] == [1, 1]


async def test_a_source_failure_reports_the_error_the_clock_stopped_with() -> None:
    failing = ListStream(RECORDING, fail_at=3, error=ReplayConfigInvalid("broken"))
    port = RecordingPort()
    async with make_run(Sources([], streams=[failing]), bus=Bus(), port=port, loop=True) as run:
        assert await run.play() == "error"
    [(reason, error)] = port.stops
    assert reason == "error" and isinstance(error, ReplayConfigInvalid) and port.loops == []


# --- AC 4 at the run level, through the production wiring ----------------------------------


#: The rows the recorder stored for `RECORDING` (what the in-memory hot tier serves).
STORED = [i for i in RECORDING if isinstance(i, RecordedEvent)]


async def test_a_full_run_with_a_loop_never_reaches_the_live_book_or_live_topics() -> None:
    """Ticket AC 4: a live `BookEngine` for BTCUSDT holds its book while a session for BTCUSDT,
    built by `build_replay_run` over the read path (`ReplaySource` on in-memory tiers), plays
    the range three times. The live book and its topics are untouched, live subscribers see
    nothing, and every replayed event is `source="replay"` on the session's namespace."""
    bus = LoggingBus()
    live_topic = Topic(env="live", domain="md", symbol=SYM, detail="book")

    async def publish_live(obj: object) -> None:
        await bus.publish(live_topic, obj)

    async def no_resubscribe() -> None:
        return None

    live = BookEngine(
        symbol=SYM, depth=200, publish=publish_live, resubscribe=no_resubscribe, now_us=lambda: 1
    )
    await live.start()
    await live.on_event(live_snap(10, [lvl(990, 1)], [lvl(1010, 1)]))
    await live.on_event(live_delta(11, 10, [lvl(990, 2)]))
    recorders = [
        bus.subscribe(f"rec-{d}", f"live.md.{SYM}.{d}", QueuePolicy.NEVER_DROP)
        for d in ("trade", "book")
    ]
    book_before, seen = live.live_snapshot(), len(bus.log)

    harness = Harness(hot=STORED, req=request(streams=REEMITTED, end_us=60 * SECOND))
    port = RecordingPort()
    run = build_replay_run(
        session_id=SESSION,
        request=harness.req,
        tick_sizes={SYM: TICK},
        tiers=harness.tiers,
        bus=bus,
        port=port,
        speed=UNBOUNDED,
        loop=True,
        time=FakeTime(),
    )
    port.on_loop_hook = lambda generation: run.set_loop(generation < 2)
    async with run:
        assert await run.play() == "range_end"
    assert port.loops == [1, 2] and run.generation == 2
    assert live.phase is BookPhase.LIVE and live.last_u == 11
    assert live.live_snapshot() == book_before
    assert all(sub.qsize() == 0 for sub in recorders)
    replayed = bus.log[seen:]
    assert {topic.key for _, topic, _ in replayed} == {
        f"{ENV}.md.{SYM}.trade",
        f"{ENV}.md.{SYM}.book",
    }
    assert all(is_replay_env(topic.env) for _, topic, _ in replayed)
    events = [e for _, _, e in replayed if isinstance(e, MarketEvent)]
    assert len(events) == 3 * len(PASS_TS) and all(e.source == "replay" for e in events)
    assert all(isinstance(e, MarketEvent | BookStatus) for _, _, e in replayed)


async def test_the_source_factory_opens_the_sessions_request_at_a_position() -> None:
    """The hook E26-T04's seek opens sources through: the session's request from `at_us` on."""
    harness = Harness(hot=STORED, req=request(streams=REEMITTED, end_us=60 * SECOND))
    open_source = replay_source_factory(harness.req, harness.tiers)
    whole, later = open_source(T0), open_source(T0 + 3 * SECOND)
    try:
        assert [i async for i in whole] == STORED
        assert [i async for i in later] == STORED[3:]
    finally:
        await whole.aclose()
        await later.aclose()
    with pytest.raises(ReplayRequestInvalid):
        open_source(T0 + 60 * SECOND)  # the window's end: nothing left to open


@settings(max_examples=40)
@given(
    offsets=st.lists(st.integers(0, 59 * SECOND), min_size=1, max_size=12, unique=True),
    wraps=st.integers(1, 3),
)
def test_every_wrap_reemits_the_pass_under_the_next_generation(
    offsets: list[int], wraps: int
) -> None:
    """Pass k of a loop re-emits the recorded trades with the ids of generation k, ordinals from
    0 (24 Sec.13.7 `event_id`): never an id twice, never a different event."""
    items = [tape(offset, i) for i, offset in enumerate(sorted(offsets))]

    async def main() -> list[TradeEvent]:
        bus, port = LoggingBus(), RecordingPort()
        run = make_run(Sources(items), bus=bus, port=port, loop=True, speed=UNBOUNDED)
        port.on_loop_hook = lambda generation: run.set_loop(generation < wraps)
        async with run:
            assert await run.play() == "range_end"
        assert port.loops == list(range(1, wraps + 1))
        return [e for e in bus.market() if isinstance(e, TradeEvent)]

    trades, n = asyncio.run(main()), len(items)
    assert len(trades) == n * (wraps + 1)
    for k in range(wraps + 1):
        one = trades[k * n : (k + 1) * n]
        assert [e.event_id for e in one] == [
            replay_event_id(item.ts_us, SESSION, k, i) for i, item in enumerate(items)
        ]
        assert [_shape(e) for e in one] == [_shape(e) for e in trades[:n]]

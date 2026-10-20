"""`ReplayRun`: one replay session's playback, in one structured scope (E26-T03).

It composes, for one session, what playback needs, and re-implements none of it: a
`SourceFactory` that opens the session's `ReplaySource` at a replay position, wrapped in a
`RegroupedStream`; the `ReplayClock`, which paces it; the session's `ReplayInjector`, the
clock's sink; and the `PlaybackObserver` that hands what the clock reports to the session layer
as notices on a `ReplayRunPort`. The session layer (E26-T01's service; E26-T05/E36 wire it)
owns B12 and turns the notices into B12 events and row writes, so the run is plain code on the
hot path and never calls a statechart (C-2.20, C-2.21). It exposes the controls B12's actions
drive: `play` (`start_clock`), `pause` (`stop_clock`), `set_speed`, the steps
(`emit_one_step`) and `set_loop`. `replay_wiring.build_replay_run` builds one for a session.

**Ownership** (20 Sec.4.1 "TaskGroup: replay sessions"). `async with run`, or `serve()`, the
session task's body, enters the clock, whose `asyncio.TaskGroup` runs the playback task, and
the run's own TaskGroup, which runs the driver: the task that awaits each playback, wraps the
loop and reports how playback ended. Leaving it, or `aclose()` from any task (session destroy),
cancels and awaits the driver; the clock then cancels playback, closes the source exactly once
and waits for any old source a wrap is still closing. Every caller awaits one shielded close,
so a closer cancelled again meanwhile leaves no task and no source behind. A step runs in its
caller's task, as the clock's steps do, and is refused while the driver runs (B12 never
destroys a stepping session).

**Loop** (US-RPL-008). The session row has only `loop_enabled`, so a loop is the whole range.
When playback ends at the range end with the loop on, the driver wraps: the injector's
`restart_loop()` (the next generation, the ordinal back to the loop start's, 0) resets every
replay book, a fresh source opens at `range_start`, `clock.reposition` moves there (the only way
the cursor moves back, INV-B12-b) and playback goes on, until a pause, a close, speed 0, or the
loop is turned off. A wrap never races a pause or a close: it runs whole, and playback resumes
only if no pause came meanwhile, so the generation grows by exactly one per wrap whatever a
pause's timing (C-2.15); a close cancels it, and every source is still closed exactly once. A
range that re-emitted nothing since its start is not looped (that would spin): it ends as
`range_end`. Steps never wrap.

**Gaps.** The clock counts each `ReplayGap` and the run forwards it with the counters (the
client is told either way, INV-B12-d); under `stop`, playback ends with `gap`. A gap marker
never reaches the injector, so a gap on a symbol's book stream whose update ids still chain
would go unnoticed until the next snapshot: the run resets that symbol's replay book
(`ReplayInjector.reset_book`) before the next event is re-emitted, and the book waits for its
next recorded snapshot (24 Sec.13.7, "A derivation never hides a gap").

**Progress.** While events flow, the port hears `on_progress` at most once per
`progress_interval_s` (1 s): the throttled cursor and counters the session persists (24
Sec.13.7: at most one cursor write a second) and the achieved rate, SCR-097's honesty figure.
It costs one clock read and one comparison per event.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Coroutine
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any, Final, Protocol, Self

import structlog

from candleviewer.observability import spawn, spawn_child
from candleviewer.replay.clock import ReplayClock
from candleviewer.replay.errors import (
    ReplayClockStateError,
    ReplayConfigInvalid,
    ReplayRequestInvalid,
)
from candleviewer.replay.injector import ReplayInjector, check_reemitted
from candleviewer.replay.models import ReplayGap, ReplayRequest
from candleviewer.replay.playback import (
    STEP,
    BarProbe,
    ClockConfig,
    MonotonicTime,
    PlaybackStats,
    ReplayStream,
    StopReason,
    check_speed,
)
from candleviewer.replay.regroup import RegroupedStream
from candleviewer.storage.repositories.recorded import BOOK_STREAMS, RecordedEvent

#: Opens the session's recorded stream at a replay position (epoch µs): a `ReplaySource` over
#: the session's request from there. E26-T03 opens it at `range_start`, at the start and on
#: every loop wrap; E26-T04's seek is to open it at its anchor.
SourceFactory = Callable[[int], ReplayStream]

#: How often, at most, the port hears `on_progress` (24 Sec.13.7: one cursor write a second).
DEFAULT_PROGRESS_INTERVAL_S: Final = 1.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ReplayRunPort(Protocol):
    """The session layer's side of one run. Each notice is synchronous and non-blocking (no
    I/O: queue a row write, schedule a B12 send), because it runs on the playback path; it must
    not raise, and the only call it may make back into the run is `set_loop`. Each carries the
    run's `PlaybackStats` at that instant (`achieved_*` only while playback runs)."""

    def on_progress(self, stats: PlaybackStats) -> None:
        """At most once per `progress_interval_s` while events flow: the cursor and counters to
        persist (`cursor_ts`, `events_emitted`, `gap_warnings`) and the achieved rate."""
        ...

    def on_gap(self, gap: ReplayGap, *, stopped: bool, stats: PlaybackStats) -> None:
        """A recording gap was reached and counted (`stats.gap_warnings`): skipped, or stopped
        at (`stopped`). The client is told either way (INV-B12-d)."""
        ...

    def on_backpressure(self, active: bool, stats: PlaybackStats) -> None:
        """A consumer started (`True`: B12 `CONSUMER_SLOW`) or stopped holding playback back."""
        ...

    def on_loop(self, generation: int, stats: PlaybackStats) -> None:
        """Playback reached the range end and wrapped to `range_start` (US-RPL-008); the events
        re-emitted from here carry `generation`."""
        ...

    def on_stop(self, reason: StopReason, error: Exception | None, stats: PlaybackStats) -> None:
        """Playback ended: `range_end` (B12 `RANGE_END`; with the loop on, only when there is
        nothing to loop), `error` (B12 `SOURCE_ERROR`: the source failed, the sink refused an
        event, or a loop wrap failed; `error` says which), `gap` (a stop-at-gap boundary: the
        session pauses), or `paused` (a pause, or speed 0)."""
        ...


def _child(
    group: asyncio.TaskGroup, coro: Coroutine[Any, Any, StopReason]
) -> asyncio.Task[StopReason]:
    """The driver: a task of the run's TaskGroup, under an explicit copy of the caller's context
    as `observability.spawn` runs one (E04-T02)."""
    return spawn_child(group, coro, name="replay-run")


class _Playback:
    """The clock's `ReplaySink` and `PlaybackObserver` for one run."""

    __slots__ = ("_run",)

    def __init__(self, run: ReplayRun) -> None:
        self._run = run

    async def deliver(self, event: RecordedEvent) -> None:
        """The injector, behind the run's pending book resets and its progress notice."""
        run = self._run
        if run._gapped:
            await run._reset_gapped()
        now = run._time.now()
        if now >= run._progress_at:
            run._progress_at = now + run._interval
            run._port.on_progress(run.stats())
        await run._injector.deliver(event)

    def on_gap(self, gap: ReplayGap, *, stopped: bool) -> None:
        run = self._run
        if gap.stream in BOOK_STREAMS:
            run._gapped[gap.symbol] = None
        run._port.on_gap(gap, stopped=stopped, stats=run.stats())

    def on_backpressure(self, active: bool) -> None:
        run = self._run
        run._port.on_backpressure(active, run.stats())

    def on_stop(self, reason: StopReason, error: Exception | None) -> None:
        self._run._error = error  # the driver reports the stop, once it knows about the loop


class ReplayRun:
    """One replay session's playback over its whole range (see module doc). `injector` is the
    session's own, fresh: the run sets its loop start to `range_start`. A request reading a
    stream the replay does not re-emit is refused before any source opens, with the injector's
    `ReplayRequestInvalid`; so is a bad speed or progress interval."""

    def __init__(
        self,
        *,
        request: ReplayRequest,
        open_source: SourceFactory,
        injector: ReplayInjector,
        port: ReplayRunPort,
        time: MonotonicTime,
        speed: float = 1.0,
        loop: bool = False,
        config: ClockConfig | None = None,
        progress_interval_s: float = DEFAULT_PROGRESS_INTERVAL_S,
    ) -> None:
        check_reemitted(request)
        speed = check_speed(speed)
        if not (math.isfinite(progress_interval_s) and progress_interval_s > 0):
            raise ReplayConfigInvalid("progress_interval_s must be a positive, finite number")
        self._start_us = request.start_us
        self._open, self._injector, self._port, self._time = open_source, injector, port, time
        self._loop, self._speed, self._interval = loop, speed, progress_interval_s
        self._progress_at = math.inf  # armed by `play()` and by every step
        self._gapped: dict[str, None] = {}  # symbols whose book a gap left to reset, in order
        self._error: Exception | None = None  # what the clock's last stop reported
        self._halt = False  # a pause or a close came: the driver plays no more
        self._group: asyncio.TaskGroup | None = None
        self._stack: AsyncExitStack | None = None
        self._driver: asyncio.Task[StopReason] | None = None
        self._closing: asyncio.Task[None] | None = None
        self._closed = asyncio.Event()
        injector.set_loop_start(self._start_us)  # a loop is the whole range
        playback = _Playback(self)
        self._clock = ReplayClock(
            RegroupedStream(open_source(self._start_us)),
            playback,
            playback,
            time=time,
            start_us=self._start_us,
            end_us=request.end_us,
            speed=speed,
            config=config,
        )

    # -- lifecycle -----------------------------------------------------------------------------
    async def __aenter__(self) -> Self:
        if self._stack is not None or self._closing is not None:
            raise ReplayClockStateError("a replay run is opened once")
        stack = AsyncExitStack()
        try:
            await stack.enter_async_context(self._clock)
            self._group = await stack.enter_async_context(asyncio.TaskGroup())
        except BaseException:
            await stack.aclose()
            raise
        stack.push_async_callback(self.aclose)  # runs first on exit: the driver, then the clock
        self._stack = stack
        return self

    async def __aexit__(
        self, et: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> bool | None:
        stack, self._stack = self._stack, None
        return None if stack is None else await stack.__aexit__(et, exc, tb)

    async def serve(self) -> None:
        """The session task's body: open the run and hold it until `aclose()` (the session is
        destroyed) or until the task is cancelled (the replay sessions' TaskGroup stops)."""
        async with self:
            await self._closed.wait()

    async def aclose(self) -> None:
        """Destroy (idempotent): cancel the driver, a wrap in progress included, then close the
        clock, which cancels playback and closes every source exactly once."""
        self._halt = True
        if self._closing is None:
            self._closing = spawn(self._shutdown(), name="replay-run-close")
        await asyncio.shield(self._closing)

    async def _shutdown(self) -> None:
        driver = self._driver
        try:
            if driver is not None and not driver.done():
                driver.cancel()
                await asyncio.wait({driver})
        finally:
            try:
                await self._clock.aclose()
            finally:
                self._closed.set()

    # -- state ---------------------------------------------------------------------------------
    @property
    def env(self) -> str:
        """The session's bus namespace, `replay-{session_id}`."""
        return self._injector.env

    @property
    def generation(self) -> int:
        """Grows by one on every loop wrap (24 Sec.13.7 `event_id`)."""
        return self._injector.generation

    @property
    def loop(self) -> bool:
        return self._loop

    @property
    def playing(self) -> bool:
        """Playback runs, or the driver is wrapping the loop or reporting a stop."""
        return self._driver is not None and not self._driver.done()

    @property
    def bar_probe(self) -> BarProbe | None:
        """The session's active-`BarSpec` probe, which `step_bar` needs (the clock's)."""
        return self._clock.bar_probe

    @bar_probe.setter
    def bar_probe(self, probe: BarProbe | None) -> None:
        self._clock.bar_probe = probe

    def stats(self) -> PlaybackStats:
        return self._clock.stats()

    def now_us(self) -> int:
        """Replay "now" for downstream clocks (the clock's)."""
        return self._clock.now_us()

    # -- controls ------------------------------------------------------------------------------
    def play(self) -> asyncio.Future[StopReason]:
        """Start playback at the current speed (B12 `start_clock`); with the loop on it wraps
        at the range end. The clock's refusals raise here, before anything starts. The result
        resolves to the reason `on_stop` reports; cancelling an await of it stops nothing."""
        group = self._group
        if group is None or self._closing is not None:
            raise ReplayClockStateError("the replay run is not open")
        if self.playing:
            raise ReplayClockStateError("playback is already running or still stopping")
        task = self._clock.play()
        self._halt, self._progress_at = False, self._time.now() + self._interval
        self._driver = _child(group, self._drive(task))
        return asyncio.shield(self._driver)

    async def pause(self) -> None:
        """Stop playback after the event in flight (B12 `stop_clock`) and return once it has
        stopped: a loop wrap in progress finishes, then nothing plays. A no-op when idle."""
        driver = self._driver
        if driver is None or driver.done():
            return
        self._halt = True
        await self._clock.pause()
        await asyncio.wait({driver})

    def set_speed(self, speed: float) -> None:
        """B12 `set_speed` (the clock's): speed 0 pauses playback, and a wrap then stops."""
        speed = check_speed(speed)
        self._clock.set_speed(speed)
        self._speed = speed

    def set_loop(self, enabled: bool) -> None:
        """`loop_enabled`: it decides at the next range end; a wrap in progress completes."""
        self._loop = enabled

    async def step_events(self, count: int = 1) -> StopReason:
        """Deliver the next `count` market events at once (the clock's)."""
        self._steppable()
        return await self._clock.step_events(count)

    async def step_event(self) -> StopReason:
        """The ticket's `step_event`: `step_events(1)`."""
        return await self.step_events(1)

    async def step_ms(self, ms: int) -> StopReason:
        """Deliver everything in the next `ms` of replay time (the clock's)."""
        self._steppable()
        return await self._clock.step_ms(ms)

    async def step_bar(self) -> StopReason:
        """Deliver until the active `BarSpec` closes exactly one bar (the clock's)."""
        self._steppable()
        return await self._clock.step_bar()

    def _steppable(self) -> None:
        """Steps run in the caller's task and never beside the driver; they never wrap."""
        if self._closing is not None:
            raise ReplayClockStateError("the replay run is closed")
        if self.playing:
            raise ReplayClockStateError("pause playback before stepping")
        self._progress_at = self._time.now() + self._interval

    # -- the driver ----------------------------------------------------------------------------
    async def _drive(self, task: asyncio.Task[StopReason]) -> StopReason:
        """Await each playback; at the range end with the loop on, wrap and play on; then tell
        the port how playback ended."""
        while True:
            await asyncio.wait({task})  # never cancels playback: a pause or a close stops it
            if task.cancelled() or task.exception() is not None:
                return "error"  # a raising port failed the clock's TaskGroup, which reports it
            reason, error = task.result(), self._error
            self._error = None
            if reason == "range_end" and self._loop:
                try:
                    wrapped = await self._wrap()
                except Exception as exc:  # the session errs instead of looping half-way
                    _log().warning("replay_loop_wrap_failed", error_type=type(exc).__name__)
                    reason, error = "error", exc
                else:
                    if wrapped:
                        self._port.on_loop(self._injector.generation, self._clock.stats())
                        if not self._halt and self._speed != STEP:
                            task = self._clock.play()
                            continue
                        reason = "paused"
            self._port.on_stop(reason, error, self._clock.stats())
            return reason

    async def _wrap(self) -> bool:
        """Back to `range_start` under the next generation. False, with nothing changed, when
        nothing was re-emitted since the loop start: a loop of nothing would spin."""
        injector = self._injector
        start = injector.loop_start_ordinal
        if start is None or injector.next_ordinal <= start:
            return False
        await injector.restart_loop()  # resets every replay book: no gap reset is left to do
        self._gapped.clear()
        stream = RegroupedStream(self._open(self._start_us))
        try:
            await self._clock.reposition(stream, at_us=self._start_us)
        except (ReplayRequestInvalid, ReplayClockStateError):  # refused: the stream is ours
            await stream.aclose()
            raise
        _log().info("replay_loop_wrapped", generation=injector.generation)
        return True

    async def _reset_gapped(self) -> None:
        """Reset the book of each symbol a book-stream gap was reported for, in order; a symbol
        leaves the set only once its reset is done, so a failed one is tried again."""
        gapped = self._gapped
        while gapped:
            symbol = next(iter(gapped))
            await self._injector.reset_book(symbol)
            gapped.pop(symbol, None)

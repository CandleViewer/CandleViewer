"""`ReplayClock`: paced, gap-aware playback of one replay session (E26-T03).

Plain code on the hot path: it never calls a statechart (C-2.20). The session layer (E26-T01)
drives it from B12's actions (`28-statechart-catalogue.md` Sec.B12): `start_clock` calls `play()`,
`stop_clock` calls `pause()`, `set_speed` calls `set_speed()`, the `emit_one_step` service calls a
`step_*` and `seek_and_prime` ends in `reposition()`. The layer maps what the `PlaybackObserver`
hears to B12 events: a stop to `RANGE_END`/`SOURCE_ERROR`, a backpressure edge to `CONSUMER_SLOW`.

**Ownership.** `async with ReplayClock(...)` opens the session's `asyncio.TaskGroup`
(`20-architecture.md` Sec.4.1 "TaskGroup: replay sessions"), held by the session's runner task.
Playback runs as a task of that group. Leaving the block (session destroy) cancels it and closes
the source, exactly once (INV-B12-e).

**Pacing.** `replay.pacing` sets each deadline from one anchor, so pacing is drift-free and a
speed change is continuous. A sink that holds an event back past `max_lag_s` slows the clock
(re-anchor) instead of a drop or a catch-up burst (24 Sec.13.7, INV-B12-c); the wall time lost
gives the achieved rate (`stats()`). An event due within `min_wait_s` goes out without a wait;
after `yield_every` deliveries without one the clock yields to the loop (C-2.17).

**Steps** (`24-internal-schemas.md` Sec.13.7) deliver at once while not playing: `step_events(n)`
the next n market events, `step_ms(n)` everything in the next n ms of replay time, and
`step_bar()` everything until the session's `BarProbe` closes exactly one bar (US-RPL-001). At a
gap, `stop` ends the step at its boundary; `skip` reports it and steps on.

**Metrics** (ticket observability; served by `replay.metrics`): `replay_clock_lag_ms` observes the
largest lag of each rate window; `replay_events_emitted_total` is flushed per window and at every
stop, not per event; `replay_backpressure_seconds_total` is the wall time given up to slow sinks;
`replay_achieved_speed_ratio` is the lowest ratio among paced sessions (1 when none plays).
`replay_gap_warnings_total` already counts every gap marker at the source (E26-T02).

**Cursor.** `cursor_us` is the replay time reached and only moves forward; only `reposition`
(a seek, or a loop wrap back to the loop start, US-RPL-008) moves it back (INV-B12-b). `now_us()`
is the replay "now" for downstream clocks; it never passes an event not yet delivered, so a bar
never closes ahead of its own trades.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
from collections.abc import AsyncIterator, Coroutine
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any, Self

import structlog

from candleviewer.observability.metrics import Counter, Gauge, Histogram
from candleviewer.replay.errors import ReplayClockStateError, ReplayError, ReplayRequestInvalid
from candleviewer.replay.models import ReplayGap, ReplayItem
from candleviewer.replay.pacing import Pacer, RateWindow
from candleviewer.replay.playback import (
    STEP,
    BarProbe,
    ClockConfig,
    MonotonicTime,
    PlaybackObserver,
    PlaybackStats,
    ReplaySink,
    ReplayStream,
    StopReason,
    check_speed,
)
from candleviewer.storage.repositories.recorded import RecordedEvent

replay_clock_lag_ms = Histogram(
    "replay_clock_lag_ms",
    "Largest lag behind schedule in each rate window of a paced replay clock.",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000),
)
replay_events_emitted_total = Counter(
    "replay_events_emitted_total", "Recorded events replay clocks delivered."
)
replay_backpressure_seconds_total = Counter(
    "replay_backpressure_seconds_total", "Wall time replay clocks gave up to slow consumers."
)
replay_achieved_speed_ratio = Gauge(
    "replay_achieved_speed_ratio", "Lowest achieved/requested speed of the paced replay clocks."
)
replay_achieved_speed_ratio.set(1.0)  # nothing plays yet: nothing is behind
#: Last achieved ratio per playing clock (by id), behind `replay_achieved_speed_ratio`.
_RATIOS: dict[int, float] = {}


def _set_ratio(clock: int, ratio: float | None) -> None:
    if ratio is None:
        _RATIOS.pop(clock, None)
    else:
        _RATIOS[clock] = ratio
    replay_achieved_speed_ratio.set(min(_RATIOS.values(), default=1.0))


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _child(
    group: asyncio.TaskGroup, coro: Coroutine[Any, Any, StopReason]
) -> asyncio.Task[StopReason]:
    """A task of the session's TaskGroup, run under an explicit copy of the caller's context as
    `observability.spawn` does (E04-T02)."""
    # nosemgrep: cv-bare-create-task reason=taskgroup owner=@CandleViewer/backend review=2027-04-12
    return group.create_task(coro, name="replay-clock", context=contextvars.copy_context())


class ReplayClock:
    """Playback of one session's `ReplayStream` over `[start_us, end_us)` (see module doc)."""

    def __init__(
        self,
        source: ReplayStream,
        sink: ReplaySink,
        observer: PlaybackObserver,
        *,
        time: MonotonicTime,
        start_us: int,
        end_us: int,
        speed: float = 1.0,
        config: ClockConfig | None = None,
    ) -> None:
        if end_us <= start_us:
            raise ValueError("the replay range must end after it starts")
        self._source, self._sink, self._obs, self._time = source, sink, observer, time
        self._cfg = config or ClockConfig()
        self._range = (start_us, end_us)
        self._end_us, self._cursor, self._speed = end_us, start_us, check_speed(speed)
        self._pending: ReplayItem | None = None
        self._drained = self._stop = self._closed = self._stepping = False
        self._pacer: Pacer | None = None
        self._window = RateWindow(self._cfg.rate_window_s)
        self._wake = asyncio.Event()
        self._task: asyncio.Task[StopReason] | None = None
        self._stack: AsyncExitStack | None = None
        self._group: asyncio.TaskGroup | None = None
        self._emitted = self._gaps = 0
        self._lost_s = 0.0
        self._backpressured = self._slow_in_window = False
        self._max_lag, self._flushed = 0.0, 0
        #: The session's active-`BarSpec` probe: `step_bar` needs it; every delivery feeds it.
        self.bar_probe: BarProbe | None = None

    async def __aenter__(self) -> Self:
        if self._closed or self._stack is not None:
            raise ReplayClockStateError("a replay clock is opened once")
        stack = AsyncExitStack()
        self._group = await stack.enter_async_context(asyncio.TaskGroup())
        stack.push_async_callback(self.aclose)  # runs first on exit: cancel, then close
        self._stack = stack
        return self

    async def __aexit__(
        self, et: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> bool | None:
        stack, self._stack = self._stack, None
        return None if stack is None else await stack.__aexit__(et, exc, tb)

    async def aclose(self) -> None:
        """Destroy: cancel playback and close the source, exactly once. Idempotent."""
        if self._closed:
            return
        self._closed = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task})
        await self._source.aclose()

    @property
    def playing(self) -> bool:
        return self._task is not None and not self._task.done()

    def play(self) -> asyncio.Task[StopReason]:
        """Start playback at the current speed (B12 `start_clock`). The task's result, the stop
        reason, also goes to `PlaybackObserver.on_stop`."""
        group = self._group
        if group is None or self._closed:
            raise ReplayClockStateError("the replay clock is not open")
        if self.playing or self._stepping:
            raise ReplayClockStateError("playback is already running or still stopping")
        if self._speed == STEP:
            raise ReplayClockStateError("speed 0 is step mode: step instead of playing")
        now, self._stop = self._time.now(), False  # the schedule starts when play is pressed
        self._pacer = Pacer(self._speed, wall=now, ts_us=self._cursor) if self._speed > 0 else None
        self._window.restart(wall=now, lost_s=self._lost_s, position_us=self._cursor)
        self._task = _child(group, self._play())
        return self._task

    async def pause(self) -> None:
        """Stop playback after the event in flight (B12 `stop_clock`); a delivery is never
        cancelled half-way."""
        task = self._task
        if task is not None and not task.done():
            self._stop = True
            self._wake.set()
            await asyncio.wait({task})

    def set_speed(self, speed: float) -> None:
        """Change speed (B12 `set_speed`). While paced, the schedule continues from the current
        position, so the change is continuous; `STEP` pauses."""
        speed = check_speed(speed)
        _log().info("replay_speed_changed", speed_from=self._speed, speed_to=speed)
        self._speed = speed
        if self.playing:
            now = self._time.now()
            self._cursor = here = self._position(now)
            if speed == STEP:
                self._stop = True
            elif speed < 0:
                self._pacer = None
            elif self._pacer is None:
                self._pacer = Pacer(speed, wall=now, ts_us=here)
            else:
                self._pacer.set_speed(speed, wall=now, position_us=here)
            self._window.restart(wall=now, lost_s=self._lost_s, position_us=here)
            self._wake.set()

    async def step_events(self, count: int = 1) -> StopReason:
        """Deliver the next `count` market events at once (B12 `emit_one_step`)."""
        if count < 1:
            raise ReplayRequestInvalid("a step covers at least one event")
        async with self._step():
            for _ in range(count):
                item = await self._step_item()
                if not isinstance(item, RecordedEvent):
                    return "range_end" if item is None else item
                await self._deliver(item)
            return "step"

    async def step_ms(self, ms: int) -> StopReason:
        """Deliver everything in the next `ms` of replay time; the cursor lands at its end."""
        if ms < 1:
            raise ReplayRequestInvalid("a step covers at least 1 ms")
        async with self._step():
            target = min(self._cursor + ms * 1_000, self._end_us)
            while isinstance(item := await self._step_item(before_us=target), RecordedEvent):
                await self._deliver(item)
            if item == "gap":
                return "gap"
            self._cursor = max(self._cursor, target)
            return "range_end" if self._cursor >= self._end_us else "step"

    async def step_bar(self) -> StopReason:
        """Deliver until the active `BarSpec` closes exactly one bar: on an event (a count bar)
        or when replay time reaches its close (a time bar, closed by `BarProbe.tick`)."""
        probe = self.bar_probe
        if probe is None:
            raise ReplayClockStateError("step_bar needs the session's bar probe")
        async with self._step():
            probe.tick(self._cursor)  # a close already due at the cursor is not this step's
            while True:
                due = probe.due_us()
                due = None if due is None or due > self._end_us else due
                item = await self._step_item(before_us=due)
                if isinstance(item, RecordedEvent):
                    if await self._deliver(item):
                        return "step"
                elif item == "gap":
                    return "gap"
                elif due is None:
                    return "range_end"
                else:  # replay time reaches the open bar's close before any later event
                    self._cursor = max(self._cursor, due)
                    probe.tick(due)
                    return "step"

    async def reposition(
        self, source: ReplayStream, *, at_us: int, end_us: int | None = None
    ) -> None:
        """Continue from `source`, positioned at `at_us`, up to `end_us` (default: the current
        end). It is the seek hook (B12 `seek_and_prime`, E26-T04, which rebuilds downstream state
        first) and the loop wrap (US-RPL-008: back to the loop start, `end_us` the loop end). The
        old source is closed. Only this moves the cursor back (INV-B12-b)."""
        end = self._end_us if end_us is None else end_us
        if not self._range[0] <= at_us < end <= self._range[1]:
            raise ReplayRequestInvalid("a reposition must stay inside the session's range")
        async with self._step():
            old, self._source = self._source, source
            self._cursor, self._end_us, self._pending, self._drained = at_us, end, None, False
            await old.aclose()

    def now_us(self) -> int:
        """Replay "now" for downstream clocks: one clock for every pane (US-RPL-005)."""
        return self._position(self._time.now())

    def stats(self) -> PlaybackStats:
        """The session's view: cursor, counters and, while playing, the last window's achieved
        rate (the SCR-097 speed-limit honesty figure)."""
        window, live = self._window, self.playing
        return PlaybackStats(
            cursor_us=self.now_us(),
            speed=self._speed,
            events_emitted=self._emitted,
            gap_warnings=self._gaps,
            backpressured=self._backpressured,
            backpressure_s=self._lost_s,
            achieved_speed=window.speed if live else None,
            achieved_ratio=window.ratio if live else None,
        )

    # -- playback ------------------------------------------------------------------------------
    async def _play(self) -> StopReason:
        error: ReplayError | None = None
        try:
            reason = await self._run()
        except ReplayError as exc:  # a source failure: every event before it was delivered
            reason, error = "error", exc
            _log().warning("replay_source_failed", code=exc.code)
        finally:
            self._pacer = None
            self._flush()
            _set_ratio(id(self), None)
        self._obs.on_stop(reason, error)
        return reason

    async def _run(self) -> StopReason:
        """The playback hot path: per event, one deadline, one lag comparison and the delivery;
        everything else (re-anchoring, window figures, metrics) runs only when due."""
        time, sink, window = self._time, self._sink, self._window
        min_wait, max_lag, yield_every = (
            self._cfg.min_wait_s,
            self._cfg.max_lag_s,
            self._cfg.yield_every,
        )
        burst = 0
        while True:
            if self._stop:
                self._cursor = self._position(time.now())
                return "paused"
            item = await self._peek()
            pacer, now, lag = self._pacer, time.now(), 0.0
            if pacer is not None:
                lag = now - pacer.due(self._end_us if item is None else item.ts_us)
                if lag < -min_wait:
                    self._wake.clear()
                    await time.wait_until(now - lag, self._wake)
                    burst = 0
                    continue
            if item is None:
                self._cursor = self._end_us
                return "range_end"
            self._pending = None
            if isinstance(item, ReplayGap):
                if self._gap(item, now):
                    return "gap"
                continue
            if lag > 0.0 and pacer is not None:
                if lag > self._max_lag:
                    self._max_lag = lag
                if lag > max_lag:
                    lag = self._slow(pacer, item.ts_us, now)
            if item.ts_us > self._cursor:
                self._cursor = item.ts_us
            await sink.deliver(item)
            self._emitted += 1
            probe = self.bar_probe
            if probe is not None:
                probe.apply(item)
            if now >= window.closes_at and window.update(
                wall=now,
                lost_s=self._lost_s + max(lag, 0.0),
                position_us=self._cursor,
                requested=self._speed,
            ):
                self._window_closed()
            burst += 1
            if burst >= yield_every:  # catching up without waits: let the loop run
                burst = 0
                await asyncio.sleep(0)

    @contextlib.asynccontextmanager
    async def _step(self) -> AsyncIterator[None]:
        """Steps and repositions run alone: never while playing, never two at once."""
        if self._group is None or self._closed:
            raise ReplayClockStateError("the replay clock is not open")
        if self.playing or self._stepping:
            raise ReplayClockStateError("pause playback before stepping")
        self._stepping = True
        try:
            yield
        finally:
            self._stepping = False
            self._flush()

    async def _step_item(
        self, *, before_us: int | None = None
    ) -> RecordedEvent | StopReason | None:
        """The next market event of a step, if before `before_us`: `"gap"` at a gap the policy
        stops at, `None` at the bound or the end of the range (nothing past them is consumed)."""
        while (item := await self._peek()) is not None:
            if before_us is not None and item.ts_us >= before_us:
                return None
            self._pending = None
            if not isinstance(item, ReplayGap):
                return item
            if self._gap(item, self._time.now()):
                return "gap"
        return None

    async def _peek(self) -> ReplayItem | None:
        """The next item before the range end, read ahead by one and kept until consumed."""
        item = self._pending
        if item is None:
            if self._drained:
                return None
            try:
                item = await anext(self._source)
            except StopAsyncIteration:
                self._drained = True
                return None
            self._pending = item
        return item if item.ts_us < self._end_us else None

    async def _deliver(self, event: RecordedEvent) -> bool:
        """Hand `event` to the sink; `True` if it closed a bar of the active probe."""
        self._cursor = max(self._cursor, event.ts_us)
        await self._sink.deliver(event)
        self._emitted += 1
        probe = self.bar_probe
        return probe is not None and probe.apply(event)

    def _gap(self, gap: ReplayGap, now: float) -> bool:
        """Count and report a gap; `True` if the policy stops at it. `skip` compresses the gap's
        empty time: the clock jumps to its end, and whatever other streams recorded inside it is
        delivered without waits, never dropped."""
        self._gaps += 1
        stop = self._cfg.gap_policy == "stop"
        self._cursor = max(self._cursor, gap.ts_us)
        if not stop and self._pacer is not None:
            self._pacer.skip_to(min(gap.gap_end_us, self._end_us), wall=now)
        _log().info(
            "replay_gap",
            stream=gap.stream.value,
            cause=gap.cause,
            gap_start_us=gap.gap_start_us,
            gap_end_us=gap.gap_end_us,
            policy=self._cfg.gap_policy,
        )
        self._obs.on_gap(gap, stopped=stop)
        return stop

    def _slow(self, pacer: Pacer, ts_us: int, now: float) -> float:
        """The event is later than `max_lag_s` behind schedule: re-anchor the clock at it (slow
        down) and book the lost wall time. It is on schedule again, so nothing is left behind."""
        lag = pacer.late(ts_us, wall=now, max_lag_s=self._cfg.max_lag_s)
        self._lost_s += lag
        replay_backpressure_seconds_total.inc(lag)
        self._slow_in_window = True
        if not self._backpressured:
            self._backpressured = True
            _log().info("replay_backpressure", active=True)
            self._obs.on_backpressure(True)
        return 0.0

    def _window_closed(self) -> None:
        if self._backpressured and not self._slow_in_window:
            self._backpressured = False
            _log().info("replay_backpressure", active=False)
            self._obs.on_backpressure(False)
        self._slow_in_window = False
        if self._pacer is not None:
            replay_clock_lag_ms.observe(self._max_lag * 1_000)
            _set_ratio(id(self), self._window.ratio)
        self._max_lag = 0.0
        self._flush()

    def _flush(self) -> None:
        replay_events_emitted_total.inc(self._emitted - self._flushed)
        self._flushed = self._emitted

    def _position(self, now: float) -> int:
        """While paced: the schedule's position, capped at the next item not yet delivered (the
        range end once the source is drained). Otherwise the cursor."""
        pacer, pending = self._pacer, self._pending
        if pacer is None or (pending is None and not self._drained):
            return self._cursor
        cap = self._end_us if pending is None else min(pending.ts_us, self._end_us)
        return max(self._cursor, min(pacer.position(now), cap))

"""`ReplayClock`: paced, gap-aware playback of one replay session (E26-T03).

Plain code on the hot path: it never calls a statechart (C-2.20). The session layer (E26-T01)
drives it from B12's actions (`28-statechart-catalogue.md` Sec.B12): `start_clock` calls `play()`,
`stop_clock` calls `pause()` and `set_speed` calls `set_speed()`. The layer maps what the
`PlaybackObserver` hears to B12 events: a stop to `RANGE_END`/`SOURCE_ERROR`, a backpressure edge
to `CONSUMER_SLOW`.

**Ownership.** `async with ReplayClock(...)` opens the session's `asyncio.TaskGroup`
(`20-architecture.md` Sec.4.1 "TaskGroup: replay sessions"), held by the session's runner task.
Playback runs as a task of that group. Leaving the block (session destroy) cancels it and closes
the source exactly once (INV-B12-e), even if the runner is cancelled again meanwhile.

**Pacing.** `replay.pacing` sets each deadline from one anchor, so pacing is drift-free and a
speed change is continuous. The schedule starts once the first event is read, so a cold source's
first read is not lateness. A sink that holds an event back past `max_lag_s` slows the clock
(re-anchor) instead of a drop or a catch-up burst (24 Sec.13.7, INV-B12-c); the wall time lost
gives the achieved rate (`stats()`). An event due within `min_wait_s` goes out without a wait;
after `yield_slice_s` of work without one the clock yields to the loop (C-2.17).

**Cursor.** `cursor_us` is the replay time reached and only moves forward during playback
(INV-B12-b). `now_us()` is the replay "now" for downstream clocks; it never passes an event not
yet delivered, so a bar never closes ahead of its own trades.

**Failures.** A source `ReplayError` stops playback (`error`) after every event before it, and the
clock then refuses to play from that source. If the sink raises, playback stops (`error`) with the
event still pending, and the next `play()` delivers it first: nothing is lost.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Coroutine
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any, Self

import structlog

from candleviewer.observability import spawn
from candleviewer.replay.errors import ReplayClockStateError, ReplayError
from candleviewer.replay.models import ReplayGap, ReplayItem
from candleviewer.replay.pacing import Pacer, RateWindow
from candleviewer.replay.playback import (
    STEP,
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
        self._end_us, self._cursor, self._speed = end_us, start_us, check_speed(speed)
        self._pending: ReplayItem | None = None
        self._failed: ReplayError | None = None
        self._drained = self._stop = self._closed = False
        self._pacer: Pacer | None = None
        self._window = RateWindow(self._cfg.rate_window_s)
        self._wake = asyncio.Event()
        self._task: asyncio.Task[StopReason] | None = None
        self._stack: AsyncExitStack | None = None
        self._group: asyncio.TaskGroup | None = None
        self._closing: asyncio.Task[None] | None = None
        self._emitted = self._gaps = 0
        self._lost_s = 0.0
        self._backpressured = self._slow_in_window = False

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
        """Destroy: cancel playback, then close the source exactly once. Every caller awaits the
        same shielded close, so a caller cancelled again meanwhile cannot leave the source open."""
        self._closed = True
        if self._closing is None:
            self._closing = spawn(self._shutdown(), name="replay-clock-close")
        await asyncio.shield(self._closing)

    async def _shutdown(self) -> None:
        task = self._task
        try:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.wait({task})
        finally:
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
        if self._failed is not None:
            raise ReplayClockStateError("the replay source failed: replay cannot continue from it")
        if self.playing:
            raise ReplayClockStateError("playback is already running or still stopping")
        if self._speed == STEP:
            raise ReplayClockStateError("speed 0 is step mode: step instead of playing")
        self._stop = False
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
        error: Exception | None = None
        try:
            await self._peek()  # prime: a cold source's first read is not lateness
            now = self._time.now()
            if self._speed > 0:  # the schedule starts once the first event is read
                self._pacer = Pacer(self._speed, wall=now, ts_us=self._cursor)
            self._window.restart(wall=now, lost_s=self._lost_s, position_us=self._cursor)
            reason = await self._run()
        except Exception as exc:  # the source failed (`_failed`), or the sink raised: nothing lost
            reason, error = "error", exc
            _log().warning(
                "replay_playback_failed",
                error_type=type(exc).__name__,
                source_failed=exc is self._failed,
            )
        finally:  # keep the position reached, even on destroy: the cursor never moves back
            self._cursor = self._position(self._time.now())
            self._pacer = None
        self._obs.on_stop(reason, error)
        return reason

    async def _run(self) -> StopReason:
        time, cfg = self._time, self._cfg
        sliced = time.now()  # when the clock last yielded or waited
        while True:
            self._wake.clear()  # before every check of `_stop`, so no wake-up is lost
            if self._stop:
                return "paused"
            item = await self._peek()
            if self._stop:  # paused during the source read
                return "paused"
            pacer, now = self._pacer, time.now()
            due = None if pacer is None else pacer.due(self._end_us if item is None else item.ts_us)
            if due is not None and due - now > cfg.min_wait_s:
                await time.wait_until(due, self._wake)
                sliced = time.now()
                continue
            if item is None:
                self._cursor = self._end_us
                return "range_end"
            if isinstance(item, ReplayGap):
                self._pending = None
                if self._gap(item, now):
                    return "gap"
                continue
            behind = 0.0 if pacer is None else self._check_lag(pacer, item.ts_us, now)
            await self._deliver(item)
            lost = self._lost_s + behind
            if self._window.update(
                wall=now, lost_s=lost, position_us=self._cursor, requested=self._speed
            ):
                self._window_closed()
            if now - sliced >= cfg.yield_slice_s:  # catching up without waits: let the loop run
                await asyncio.sleep(0)
                sliced = time.now()

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
            except ReplayError as exc:  # a storage failure ends the source: remember it
                self._failed = exc
                raise
            self._pending = item
        return item if item.ts_us < self._end_us else None

    async def _deliver(self, event: RecordedEvent) -> None:
        """Hand `event` to the sink. It stays pending until the sink returns: if the sink raises,
        the next `play()` delivers it again instead of losing it."""
        await self._sink.deliver(event)
        self._pending = None
        self._cursor = max(self._cursor, event.ts_us)
        self._emitted += 1

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

    def _check_lag(self, pacer: Pacer, ts_us: int, now: float) -> float:
        """Slow the clock if the event is later than `max_lag_s` behind schedule; returns how far
        behind it still is (counted in the achieved rate, so it reads smoothly)."""
        lag = pacer.late(ts_us, wall=now, max_lag_s=self._cfg.max_lag_s)
        if lag <= self._cfg.max_lag_s:
            return max(0.0, lag)
        self._lost_s += lag
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

    def _position(self, now: float) -> int:
        """While paced: the schedule's position, capped at the next item not yet delivered (the
        range end once the source is drained). Otherwise the cursor."""
        pacer, pending = self._pacer, self._pending
        if pacer is None or (pending is None and not self._drained):
            return self._cursor
        cap = self._end_us if pending is None else min(pending.ts_us, self._end_us)
        return max(self._cursor, min(pacer.position(now), cap))

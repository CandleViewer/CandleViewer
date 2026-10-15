"""Playback models and ports of the replay clock (E26-T03).

The clock (`replay.clock`) paces a `ReplayStream` (a `ReplaySource`) and hands each recorded
event to a `ReplaySink`. It reads time only through the injected `MonotonicTime`: production uses
`LoopTime`, tests a fake. Gap markers never reach the sink. The clock reports them, with
backpressure edges and the reason it stopped, to a `PlaybackObserver`. That observer is the
session layer (E26-T01), which turns them into B12 events (`28-statechart-catalogue.md` Sec.B12):
the hot path is plain code and never calls a statechart (C-2.20, C-2.21).

Speeds follow `24-internal-schemas.md` Sec.13.7: 0.1 to 100 is paced, `STEP` (0) is step mode
and `UNBOUNDED` (-1) emits as fast as the sink accepts.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from candleviewer.replay.errors import ReplayRequestInvalid
from candleviewer.replay.models import ReplayGap, ReplayItem
from candleviewer.storage.repositories.recorded import RecordedEvent

STEP: Final = 0.0
UNBOUNDED: Final = -1.0
MIN_SPEED: Final = 0.1
MAX_SPEED: Final = 100.0

#: What the clock does at a `ReplayGap`: compress its empty time, or stop at its start.
GapPolicy = Literal["skip", "stop"]
#: Why playback or a step ended: `paused` on request, `step` when a step completed, `range_end`
#: at the end of the range (B12 `RANGE_END`), `gap` at a stop-at-gap boundary, and `error` when
#: the source failed or the sink raised (B12 `SOURCE_ERROR`).
StopReason = Literal["paused", "step", "range_end", "gap", "error"]


def check_speed(speed: float) -> float:
    """`speed` if it is `STEP`, `UNBOUNDED` or within 0.1 to 100, else `ReplayRequestInvalid`."""
    if speed in (STEP, UNBOUNDED) or MIN_SPEED <= speed <= MAX_SPEED:
        return float(speed)
    raise ReplayRequestInvalid(f"replay speed must be 0, -1 or {MIN_SPEED}..{MAX_SPEED}")


class MonotonicTime(Protocol):
    """The clock's only time source: monotonic seconds and an interruptible wait."""

    def now(self) -> float:
        """Monotonic seconds; the origin is the implementation's."""
        ...

    async def wait_until(self, deadline: float, wake: asyncio.Event) -> None:
        """Return at `deadline` (a `now()` value) or as soon as `wake` is set, whichever is
        first. Cancellation propagates."""
        ...


class LoopTime:
    """Production `MonotonicTime`: the running event loop's monotonic clock."""

    def now(self) -> float:
        return asyncio.get_running_loop().time()

    async def wait_until(self, deadline: float, wake: asyncio.Event) -> None:
        if wake.is_set():
            return
        with contextlib.suppress(TimeoutError):  # the deadline passed; an outer cancel propagates
            async with asyncio.timeout_at(deadline):
                await wake.wait()


class ReplayStream(Protocol):
    """What the clock reads: the ordered items of a `ReplaySource`, which it closes once."""

    def __anext__(self) -> Awaitable[ReplayItem]: ...

    async def aclose(self) -> None: ...


class ReplaySink(Protocol):
    """Where the clock hands recorded events, one at a time and in order (the injector)."""

    async def deliver(self, event: RecordedEvent) -> None:
        """Accept `event`. Awaiting is backpressure: the clock slows and never drops. If this
        raises, the clock stops (`on_stop("error", exc)`) with `event` still pending: the next
        `play()` delivers it again before anything after it (at-least-once for that event)."""
        ...


class PlaybackObserver(Protocol):
    """Session-layer callbacks. Each one is synchronous and non-blocking (no I/O), because it
    runs on the playback path."""

    def on_gap(self, gap: ReplayGap, *, stopped: bool) -> None:
        """A recording gap was reached: skipped (`stopped=False`) or stopped at."""
        ...

    def on_backpressure(self, active: bool) -> None:
        """The sink started (`True`) or stopped (`False`) holding the clock back."""
        ...

    def on_stop(self, reason: StopReason, error: Exception | None) -> None:
        """Playback ended. `error` is set only for `reason == "error"`: the source's `ReplayError`
        (the source is done, so the clock refuses to play until repositioned), or whatever the
        sink raised (its event stays pending for a retry)."""
        ...


@dataclass(frozen=True, slots=True)
class ClockConfig:
    """Pacing bounds of one session's clock. `max_lag_s`: an event later than this behind its
    schedule re-anchors the clock (slows it) instead of a catch-up burst; shorter lateness
    self-corrects, as every deadline is absolute. `min_wait_s`: events due sooner go out without a
    wait. `rate_window_s`: the achieved-rate window. `yield_slice_s`: the longest the clock works
    without yielding to the event loop (C-2.17 caps blocking at 50 ms; 2 ms stays well inside).
    `gap_policy`: what to do at a `ReplayGap`."""

    max_lag_s: float = 0.25
    min_wait_s: float = 0.001
    rate_window_s: float = 1.0
    yield_slice_s: float = 0.002
    gap_policy: GapPolicy = "skip"

    def __post_init__(self) -> None:
        if min(self.max_lag_s, self.min_wait_s, self.rate_window_s, self.yield_slice_s) <= 0:
            raise ValueError("clock bounds must be positive")


@dataclass(frozen=True, slots=True)
class PlaybackStats:
    """A point-in-time view of one clock, for the session layer (E26-T01 persists `cursor_us`,
    `events_emitted` and `gap_warnings` on `replay_sessions`).

    `achieved_ratio` is the achieved speed over the requested one in the last full rate window
    (`None` before the first window, while not paced, or in step mode). `achieved_speed` is the
    replay seconds per wall second in that window."""

    cursor_us: int
    speed: float
    events_emitted: int
    gap_warnings: int
    backpressured: bool
    backpressure_s: float
    achieved_speed: float | None
    achieved_ratio: float | None

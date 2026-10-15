"""Pacing math of the replay clock (E26-T03): replay time to monotonic wall time, drift-free.

`due(ts)` is `anchor_wall + (ts - anchor_ts) / speed`, measured from one anchor and never from the
previous event. Each wait therefore targets an absolute deadline, and oversleeping one wait never
carries into the next (`24-internal-schemas.md` Sec.13.7; the ticket's 0.5 % over one hour). A
speed change re-anchors at the current position, so it takes effect continuously instead of
jumping. An event later than `max_lag_s` behind schedule re-anchors at that event: the clock slows
instead of bursting to catch up, and the wall time it gave up is booked in `lost_s`.

Replay time at or before the anchor is due at the anchor. After a skipped gap (`skip_to`), the
stretch it compressed plays without waits and never early.
"""

from __future__ import annotations

from typing import Final

US_PER_S: Final = 1_000_000


class Pacer:
    """One paced schedule: `speed` replay seconds per wall second from `(anchor_wall, anchor_ts)`.

    Wall times are `MonotonicTime.now()` seconds; replay times are integer µs."""

    __slots__ = ("_rate", "anchor_ts", "anchor_wall", "lost_s", "speed")

    def __init__(self, speed: float, *, wall: float, ts_us: int) -> None:
        if speed <= 0:
            raise ValueError("a paced speed is positive")
        self.speed = speed
        self._rate = speed * US_PER_S
        self.anchor_wall = wall
        self.anchor_ts = ts_us
        self.lost_s = 0.0

    def due(self, ts_us: int) -> float:
        """Wall time at which replay time `ts_us` is due."""
        ahead = ts_us - self.anchor_ts
        return self.anchor_wall + ahead / self._rate if ahead > 0 else self.anchor_wall

    def position(self, wall: float) -> int:
        """Replay time the schedule has reached at `wall` (the anchor until then)."""
        if wall <= self.anchor_wall:
            return self.anchor_ts
        return self.anchor_ts + int((wall - self.anchor_wall) * self._rate)

    def set_speed(self, speed: float, *, wall: float, position_us: int) -> None:
        """Continue at `speed` from `position_us`, reached at `wall`."""
        if speed <= 0:
            raise ValueError("a paced speed is positive")
        self.anchor_wall, self.anchor_ts = wall, position_us
        self.speed, self._rate = speed, speed * US_PER_S

    def skip_to(self, ts_us: int, *, wall: float) -> None:
        """Compress replay time up to `ts_us` (a skipped gap's end): it is due at `wall`. Never
        moves the schedule back."""
        self.anchor_ts = max(ts_us, self.position(wall))
        self.anchor_wall = wall

    def late(self, ts_us: int, *, wall: float, max_lag_s: float) -> float:
        """Lateness in seconds of the event at `ts_us` delivered at `wall`. Beyond `max_lag_s`
        the clock slows: it re-anchors at the event (never back in replay time) and books the
        lateness in `lost_s`."""
        lag = wall - self.due(ts_us)
        if lag > max_lag_s:
            self.lost_s += lag
            self.anchor_wall, self.anchor_ts = wall, max(ts_us, self.anchor_ts)
        return lag


class RateWindow:
    """Achieved speed over windows of at least `span_s` wall seconds.

    Paced, the schedule advances at the requested speed except for the wall time lost to
    backpressure, so `ratio = 1 - lost / elapsed` (clamped to 0..1) and `speed = requested *
    ratio`. Skipped gaps never inflate it. Unbounded (`requested <= 0`), `speed` is the replay
    time covered per wall second and `ratio` is `None`."""

    __slots__ = ("_lost", "_pos", "_wall", "ratio", "span_s", "speed")

    def __init__(self, span_s: float) -> None:
        self.span_s = span_s
        self._wall, self._lost, self._pos = 0.0, 0.0, 0
        self.speed: float | None = None
        self.ratio: float | None = None

    def restart(self, *, wall: float, lost_s: float, position_us: int) -> None:
        """Open a new window at `wall`, keeping the last closed window's figures."""
        self._wall, self._lost, self._pos = wall, lost_s, position_us

    def update(self, *, wall: float, lost_s: float, position_us: int, requested: float) -> bool:
        """Close the window if `span_s` elapsed; `True` if it did."""
        elapsed = wall - self._wall
        if elapsed < self.span_s:
            return False
        if requested > 0:
            self.ratio = min(1.0, max(0.0, 1.0 - (lost_s - self._lost) / elapsed))
            self.speed = requested * self.ratio
        else:
            self.ratio = None
            self.speed = (position_us - self._pos) / US_PER_S / elapsed
        self.restart(wall=wall, lost_s=lost_s, position_us=position_us)
        return True

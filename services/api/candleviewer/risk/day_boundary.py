"""The trading day's bounds from the one column (E29-S06 #981 slice 4; 24 Sec.8.13 "The day
boundary", BQ-3 and BQ-4; 21 Sec.3.11 `rp_day`).

`risk_policy.day_boundary_utc_offset_minutes` is the offset, in minutes east of UTC, whose
midnight starts the day; `day_containing` is the half-open day holding an instant at one fixed
offset (24 Sec.8.13: +180 starts it at 21:00:00.000Z of the previous UTC date, -300 at
05:00:00.000Z). `DayBoundary` is the one resolver the order path's daily-loss figure and the
closed-PnL view take: `resolve(at)` answers `TradingDay(day_start, next_start,
utc_offset_minutes)`, and a reader takes `next_start` as served.

**The change rule** (24 Sec.8.13). The resolver keeps the day in progress in memory and answers it
for every instant inside it, reading nothing, so a change of the column never moves that day. It
reads the column for its first day and once an instant reaches the day's `next_start`: a changed
offset takes effect there, the day after running to the new offset's first midnight after that
`next_start` (`day_after`). It answers the day before too, as served, for a caller whose clock is a
little behind another's.

**Fail closed.** A read that fails, outlasts `READ_TIMEOUT_S` or finds an offset outside `rp_day`
raises `DayBoundaryUnavailable`, never UTC midnight; so does an instant before the day before,
which it keeps no record of.

**Not across a restart.** No write path for the column exists yet (E39's), so the day in progress
lives in this process alone: after a restart the first day is the column's as read then, which
moves the day in progress if the column changed during it, and a change made in a day nothing has
resolved yet takes effect at that day's start. Surviving a restart needs the record E39's write
keeps of the offset it replaces and the instant the new one takes effect (24 Sec.8.13), carried to
E39-K01 (#880).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

import structlog

from candleviewer.risk.errors import RiskError

#: `rp_day`'s bounds (21 Sec.3.11): UTC-12 to UTC+14, in minutes east of UTC.
OFFSET_MIN: Final = -720
OFFSET_MAX: Final = 840
#: A fixed offset has no daylight saving: a day the column does not change is 24 h.
DAY: Final = timedelta(hours=24)
#: The bound on one read of the column (C-2.18).
READ_TIMEOUT_S: Final = 2.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class DayBoundaryUnavailable(RiskError):
    """The day cannot be resolved (module docstring): its reader's figure is unknown, never one at
    UTC midnight."""


@dataclass(frozen=True, slots=True)
class TradingDay:
    """The day `[day_start, next_start)` and the offset it runs by (22 `ClosedPnlWindow`)."""

    day_start: datetime
    next_start: datetime
    utc_offset_minutes: int

    def holds(self, at: datetime) -> bool:
        return self.day_start <= at < self.next_start


class RiskPolicyReads(Protocol):
    """The column, as `storage.repositories.risk_policy_sqlalchemy` reads it."""

    async def day_boundary_utc_offset_minutes(self) -> int: ...


class TradingDays(Protocol):
    """The resolver as its readers take it."""

    async def resolve(self, at: datetime) -> TradingDay: ...


def _offset_in_range(offset: object) -> bool:
    if isinstance(offset, bool) or not isinstance(offset, int):
        return False
    return OFFSET_MIN <= offset <= OFFSET_MAX


def day_containing(at: datetime, offset_minutes: int) -> TradingDay:
    """The day holding `at` at a fixed offset: `day_start` the latest instant at or before `at`
    whose wall time at UTC+offset is 00:00:00.000, `next_start` 24 h later."""
    if at.utcoffset() is None:
        raise ValueError("an instant must be timezone-aware")
    if not _offset_in_range(offset_minutes):
        raise ValueError(f"an offset is {OFFSET_MIN}..{OFFSET_MAX} minutes (rp_day)")
    shift = timedelta(minutes=offset_minutes)
    wall = at.astimezone(UTC) + shift
    start = wall.replace(hour=0, minute=0, second=0, microsecond=0) - shift
    return TradingDay(start, start + DAY, offset_minutes)


def day_after(day: TradingDay, offset_minutes: int) -> TradingDay:
    """The day from `day.next_start` to the first instant after it whose wall time at the offset
    is 00:00:00.000: 24 h at `day`'s own offset or when the two midnights coincide, shorter on the
    day a change takes effect."""
    start = day.next_start
    return TradingDay(start, day_containing(start, offset_minutes).next_start, offset_minutes)


class DayBoundary:
    """`TradingDays` over the column (module docstring); one per process, shared by its readers."""

    def __init__(self, policy: RiskPolicyReads, *, timeout_s: float = READ_TIMEOUT_S) -> None:
        self._policy, self._timeout_s = policy, timeout_s
        self._days: tuple[TradingDay, ...] = ()  # the day before, as served; the day in progress

    async def day_start(self, at: datetime) -> datetime:
        """The start of the day holding `at` (`ClosedPnlSync`'s reach)."""
        return (await self.resolve(at)).day_start

    async def resolve(self, at: datetime) -> TradingDay:
        if at.utcoffset() is None:
            raise ValueError("an instant must be timezone-aware")
        while True:
            days = self._days
            for day in days:
                if day.holds(at):
                    return day
            if days and at < days[-1].day_start:
                raise DayBoundaryUnavailable("the instant is before the days this process kept")
            offset = await self._offset()
            if self._days is not days:  # another call moved the day meanwhile: look again
                continue
            if not days:
                self._days = (day_containing(at, offset),)
                return self._days[0]
            last = days[-1]
            after = day_after(last, offset)
            current = after if after.holds(at) else day_containing(at, offset)
            if offset != last.utc_offset_minutes:
                _log().info("risk_day_boundary_changed", from_offset=last.utc_offset_minutes,
                            to_offset=offset, at=after.day_start.isoformat())  # fmt: skip
            self._days = (last, current)
            return current

    async def _offset(self) -> int:
        try:
            async with asyncio.timeout(self._timeout_s):
                offset = await self._policy.day_boundary_utc_offset_minutes()
        except Exception as exc:  # unread or late: fail closed, never UTC midnight
            _log().warning("risk_day_boundary_unread", error=type(exc).__name__)
            raise DayBoundaryUnavailable("the day boundary could not be read") from None
        if not _offset_in_range(offset):
            _log().error("risk_day_boundary_out_of_range")
            raise DayBoundaryUnavailable("the day boundary is outside rp_day's range")
        return offset

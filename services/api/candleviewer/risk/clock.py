"""The risk day key (E39-T01, M17; E39-K01 §5.6): one key per deployment, fixed-minute offset.

A key is the half-open span `[start, end)` between two midnights of `UTC + offset` minutes, the
offset bounded -720..840 (`risk_policy.day_boundary_utc_offset_minutes`); no time-zone names and no
daylight saving. Times are the exchange-synchronised clock's, passed in; nothing here reads a clock.
A key is in UTC whatever offset the time passed in carries.

An offset change never shortens the key in progress: it keeps its start and runs to the first
boundary of the new offset at or after its old end, so one change gives a key of 24 h to under
48 h; whole days on the new grid follow (`21:4329`, SR-E39-09). Each further change in the same key
adds under 24 h more (0, then +60, then -720 minutes gives 60 h): longer, never shorter, so a loss
is never forgotten early. Single asyncio loop, no `await`: no lock is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

MIN_OFFSET: Final = -720
MAX_OFFSET: Final = 840
_DAY: Final = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class DayKey:
    start: datetime
    end: datetime

    def __contains__(self, at: datetime) -> bool:
        return self.start <= at < self.end


def _check(offset_minutes: int, at: datetime) -> None:
    if not MIN_OFFSET <= offset_minutes <= MAX_OFFSET:
        raise ValueError(f"day boundary offset must be in {MIN_OFFSET}..{MAX_OFFSET} minutes")
    if at.utcoffset() is None:  # naive, or a tzinfo with no offset
        raise ValueError("risk times must be timezone-aware")


def grid_key(at: datetime, offset_minutes: int) -> DayKey:
    """The key of `at` on the plain grid of `offset_minutes`."""
    _check(offset_minutes, at)
    shift = timedelta(minutes=offset_minutes)
    local = at.astimezone(UTC) + shift
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) - shift
    return DayKey(start, start + _DAY)


def first_boundary_at_or_after(at: datetime, offset_minutes: int) -> datetime:
    key = grid_key(at, offset_minutes)
    return key.start if key.start == at else key.end


class DayCalendar:
    """The current key: advanced by the clock, stretched (never shortened) by an offset change."""

    def __init__(self, offset_minutes: int, now: datetime) -> None:
        self._offset = offset_minutes
        self._key = grid_key(now, offset_minutes)

    @property
    def offset_minutes(self) -> int:
        return self._offset

    @property
    def key(self) -> DayKey:
        return self._key

    def advance(self, now: datetime) -> bool:
        """Roll to `now`'s key when the current one has ended; True on a rollover."""
        _check(self._offset, now)
        if now < self._key.end:
            return False
        self._key = grid_key(now, self._offset)
        return True

    def change_offset(self, offset_minutes: int, now: datetime) -> DayKey:
        """Apply a new offset from the first new-offset boundary at or after the current end."""
        _check(offset_minutes, now)
        self.advance(now)
        if offset_minutes != self._offset:
            end = first_boundary_at_or_after(self._key.end, offset_minutes)
            self._key = DayKey(self._key.start, end)
            self._offset = offset_minutes
        return self._key

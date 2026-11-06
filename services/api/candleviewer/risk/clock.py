"""The risk day key (E39-T01, M17; E39-K01 §5.6): one key per deployment, fixed-minute offset.

A key is the half-open span `[start, end)` between two midnights of `UTC + offset` minutes, the
offset bounded -720..840 (`risk_policy.day_boundary_utc_offset_minutes`); no time-zone names and no
daylight saving. Times are the exchange-synchronised clock's, passed in; nothing here reads a clock.
A key is in UTC whatever offset the time passed in carries.

An offset change never moves the key in progress (`24` §8.13, SR-E39-09): that key keeps the offset
it started with and its scheduled end, so a loss it has counted stays counted. The new offset takes
effect there: the next key runs from that end to the first instant after it that is a midnight of
the new offset, so that one key is shorter than 24 h (24 h when the two midnights coincide), and
whole days on the new grid follow. A later change in the same key replaces a pending one. Once E32
S4's resolver merges, this module wraps it. Single asyncio loop, no `await`: no lock is needed.
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


class DayCalendar:
    """The current key, advanced by the clock; an offset change waits for the key's end."""

    def __init__(self, offset_minutes: int, now: datetime) -> None:
        self._offset = self._pending = offset_minutes
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
        # The next key runs from this end: after an offset change, the one shortened key.
        self._offset, start = self._pending, self._key.end
        self._key = DayKey(start, grid_key(start, self._offset).end)
        if now >= self._key.end:
            self._key = grid_key(now, self._offset)
        return True

    def change_offset(self, offset_minutes: int, now: datetime) -> DayKey:
        """Take `offset_minutes` from the current key's end (module docstring); the key stays."""
        _check(offset_minutes, now)
        self.advance(now)
        self._pending = offset_minutes
        return self._key

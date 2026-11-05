"""E39-T01 (#881) slice 2: the day key (E39-K01 §5.6) and its transitional-key rule.

An offset change never moves the key in progress (`24` §8.13, SR-E39-09): the new offset takes
effect at its end, and the next key, to the new offset's first midnight after it, is the short one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.risk.clock import (
    MAX_OFFSET,
    MIN_OFFSET,
    DayCalendar,
    DayKey,
    grid_key,
)

H = timedelta(hours=1)
US = timedelta(microseconds=1)
MIDNIGHT = datetime(2026, 11, 4, tzinfo=UTC)


@pytest.mark.parametrize(
    ("offset", "start"),
    [
        (0, MIDNIGHT),
        (60, MIDNIGHT - H),
        (-60, MIDNIGHT + H),
        (840, MIDNIGHT - 14 * H),
        (-720, MIDNIGHT - 12 * H),
    ],
)
def test_grid_key_starts_at_local_midnight(offset: int, start: datetime) -> None:
    key = grid_key(MIDNIGHT + 6 * H, offset)
    assert key == DayKey(start, start + 24 * H)


def test_grid_key_a_boundary_instant_opens_the_new_key() -> None:
    key = grid_key(MIDNIGHT, 0)
    assert key.start == MIDNIGHT and MIDNIGHT in key and key.end not in key


@pytest.mark.parametrize("offset", [-721, 841])  # literals: the bounds themselves are pinned
def test_grid_key_out_of_range_offset_raises(offset: int) -> None:
    with pytest.raises(ValueError, match="offset"):
        grid_key(MIDNIGHT, offset)
    with pytest.raises(ValueError, match="offset"):
        DayCalendar(0, MIDNIGHT).change_offset(offset, MIDNIGHT)


def test_grid_key_naive_time_raises() -> None:
    with pytest.raises(ValueError, match="timezone"):
        grid_key(datetime(2026, 11, 4), 0)
    with pytest.raises(ValueError, match="timezone"):
        DayCalendar(0, MIDNIGHT).advance(datetime(2026, 11, 4))


def test_calendar_advance_rolls_only_at_the_end() -> None:
    cal = DayCalendar(0, MIDNIGHT + H)
    assert not cal.advance(MIDNIGHT + 23 * H)
    assert cal.advance(MIDNIGHT + 24 * H)
    assert cal.key.start == MIDNIGHT + 24 * H and cal.offset_minutes == 0


@pytest.mark.parametrize(
    ("old", "new", "hours"),
    [(0, -720, 12), (0, -60, 1), (0, 60, 23), (0, 840, 10), (-720, 720, 24)],
)
def test_change_offset_keeps_the_day_and_shortens_the_next(old: int, new: int, hours: int) -> None:
    cal = DayCalendar(old, MIDNIGHT + 13 * H)  # K01 §4.4's cases, and two coinciding midnights
    day = cal.key
    assert cal.change_offset(new, MIDNIGHT + 14 * H) == day and cal.offset_minutes == old
    assert not cal.advance(day.end - US) and cal.advance(day.end)
    assert cal.key == DayKey(day.end, day.end + hours * H) and cal.offset_minutes == new
    end = cal.key.end
    assert cal.advance(end) and cal.key == DayKey(end, end + 24 * H)


def test_change_offset_every_offset_from_utc_keeps_the_day_then_whole_days() -> None:
    for offset in range(MIN_OFFSET, MAX_OFFSET + 1):
        cal = DayCalendar(0, MIDNIGHT + H)
        assert cal.change_offset(offset, MIDNIGHT + H) == DayKey(MIDNIGHT, MIDNIGHT + 24 * H)
        assert cal.advance(MIDNIGHT + 24 * H), offset
        key = cal.key
        assert key.start == MIDNIGHT + 24 * H and 0 * H < key.end - key.start <= 24 * H, offset
        assert grid_key(key.end, offset).start == key.end, offset  # ends on the new grid


def test_calendar_keeps_its_offset_across_days() -> None:
    cal = DayCalendar(60, MIDNIGHT)
    end = cal.key.end
    assert cal.advance(end) and (cal.key, cal.offset_minutes) == (DayKey(end, end + 24 * H), 60)


def test_change_offset_same_offset_keeps_the_key() -> None:
    cal = DayCalendar(60, MIDNIGHT)
    before = cal.key
    assert cal.change_offset(60, MIDNIGHT + H) == before
    assert cal.advance(before.end) and cal.key == DayKey(before.end, before.end + 24 * H)


@pytest.mark.parametrize(("second", "hours"), [(-720, 12), (0, 24)])
def test_change_offset_twice_in_one_key_the_later_one_wins(second: int, hours: int) -> None:
    cal = DayCalendar(0, MIDNIGHT + H)
    cal.change_offset(60, MIDNIGHT + H)
    assert cal.change_offset(second, MIDNIGHT + 2 * H) == DayKey(MIDNIGHT, MIDNIGHT + 24 * H)
    assert cal.advance(MIDNIGHT + 24 * H) and cal.key.end == MIDNIGHT + (24 + hours) * H


def test_change_offset_rolls_first_when_the_key_has_ended() -> None:
    cal = DayCalendar(0, MIDNIGHT)
    assert cal.change_offset(-60, MIDNIGHT + 30 * H) == DayKey(MIDNIGHT + 24 * H, MIDNIGHT + 48 * H)
    assert cal.advance(MIDNIGHT + 48 * H) and cal.key.end == MIDNIGHT + 49 * H


@pytest.mark.parametrize("hours", [25, 30])  # at the short key's end, and past it
def test_advance_past_the_short_key_lands_on_the_new_grid(hours: int) -> None:
    cal = DayCalendar(0, MIDNIGHT)
    cal.change_offset(-60, MIDNIGHT + H)
    assert cal.advance(MIDNIGHT + hours * H)
    assert cal.key == DayKey(MIDNIGHT + 25 * H, MIDNIGHT + 49 * H)


@given(
    at=st.datetimes(
        min_value=datetime(2020, 1, 1), max_value=datetime(2035, 1, 1), timezones=st.just(UTC)
    ),
    first=st.integers(MIN_OFFSET, MAX_OFFSET),
    second=st.integers(MIN_OFFSET, MAX_OFFSET),
    later=st.integers(0, 47 * 3600),
)
def test_change_offset_never_moves_the_key_in_progress(
    at: datetime, first: int, second: int, later: int
) -> None:
    cal = DayCalendar(first, at)
    before = cal.key
    now = min(at + timedelta(seconds=later), before.end - US)
    assert cal.change_offset(second, now) == before
    assert cal.advance(before.end)
    after = cal.key
    assert after.start == before.end and timedelta(0) < after.end - after.start <= 24 * H
    assert grid_key(after.end, second).start == after.end


@pytest.mark.parametrize(
    ("offset", "start"), [(0, MIDNIGHT), (90, MIDNIGHT - 90 * timedelta(minutes=1))]
)
def test_grid_key_starts_at_midnight_from_any_instant(offset: int, start: datetime) -> None:
    at = datetime(2026, 11, 4, 13, 47, 31, 123_456, tzinfo=UTC)
    assert grid_key(at, offset).start == start  # BQ-10: minutes, seconds and micros all cleared


class _NoOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return None


def test_grid_key_refuses_a_zone_with_no_offset() -> None:
    with pytest.raises(ValueError, match=r"^risk times must be timezone-aware$"):
        grid_key(datetime(2026, 11, 4, tzinfo=_NoOffset()), 0)


@pytest.mark.parametrize("hours", [10, -9, 14])
def test_grid_key_is_in_utc_whatever_offset_the_time_carries(hours: int) -> None:
    at = MIDNIGHT + 23 * H  # 23:00Z: on a +10:00 wall clock it is 09:00 the next day
    local = at.astimezone(timezone(timedelta(hours=hours)))
    for offset in (0, 60, -720, 840):
        assert grid_key(local, offset) == grid_key(at, offset)
    assert grid_key(local, 0) == DayKey(MIDNIGHT, MIDNIGHT + 24 * H)
    calendar = DayCalendar(0, MIDNIGHT)
    assert not calendar.advance(local) and calendar.key == DayKey(MIDNIGHT, MIDNIGHT + 24 * H)

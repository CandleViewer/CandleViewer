"""E39-T01 (#881) slice 2: the day key (E39-K01 §5.6) and its transitional-key rule.

An offset change never shortens the key in progress (`21:4329`, SR-E39-09): it keeps its start and
ends at the first new-offset boundary at or after its old end, 24 h to under 48 h.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.risk.clock import (
    MAX_OFFSET,
    MIN_OFFSET,
    DayCalendar,
    DayKey,
    first_boundary_at_or_after,
    grid_key,
)

H = timedelta(hours=1)
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
    assert first_boundary_at_or_after(MIDNIGHT, 0) == MIDNIGHT
    assert first_boundary_at_or_after(MIDNIGHT + H, 0) == MIDNIGHT + 24 * H


@pytest.mark.parametrize("offset", [MIN_OFFSET - 1, MAX_OFFSET + 1])
def test_grid_key_out_of_range_offset_raises(offset: int) -> None:
    with pytest.raises(ValueError, match="offset"):
        grid_key(MIDNIGHT, offset)


def test_grid_key_naive_time_raises() -> None:
    with pytest.raises(ValueError, match="timezone"):
        grid_key(datetime(2026, 11, 4), 0)


def test_calendar_advance_rolls_only_at_the_end() -> None:
    cal = DayCalendar(0, MIDNIGHT + H)
    assert not cal.advance(MIDNIGHT + 23 * H)
    assert cal.advance(MIDNIGHT + 24 * H)
    assert cal.key.start == MIDNIGHT + 24 * H and cal.offset_minutes == 0


@pytest.mark.parametrize(("offset", "hours"), [(-720, 36), (-60, 25), (60, 47), (840, 34)])
def test_change_offset_the_spike_cases(offset: int, hours: int) -> None:  # K01 §4.4
    cal = DayCalendar(0, MIDNIGHT + H)
    key = cal.change_offset(offset, MIDNIGHT + 2 * H)
    assert key.start == MIDNIGHT and key.end - key.start == hours * H


def test_change_offset_every_offset_from_utc_never_shortens_then_whole_days() -> None:
    for offset in range(MIN_OFFSET, MAX_OFFSET + 1):
        cal = DayCalendar(0, MIDNIGHT + H)
        key = cal.change_offset(offset, MIDNIGHT + H)
        assert key.start == MIDNIGHT, offset
        assert 24 * H <= key.end - key.start < 48 * H, offset
        assert grid_key(key.end, offset).start == key.end, offset  # ends on the new grid
        assert cal.advance(key.end)
        assert cal.key == grid_key(key.end, offset), offset


def test_change_offset_same_offset_keeps_the_key() -> None:
    cal = DayCalendar(60, MIDNIGHT)
    before = cal.key
    assert cal.change_offset(60, MIDNIGHT + H) == before


def test_change_offset_twice_in_one_key_stretches_it_to_60_hours() -> None:
    cal = DayCalendar(0, MIDNIGHT + H)
    assert cal.change_offset(60, MIDNIGHT + H).end == MIDNIGHT + 47 * H
    key = cal.change_offset(-720, MIDNIGHT + 2 * H)
    assert key == DayKey(MIDNIGHT, MIDNIGHT + 60 * H)  # longer, never shorter (module docstring)


def test_change_offset_rolls_first_when_the_key_has_ended() -> None:
    cal = DayCalendar(0, MIDNIGHT)
    key = cal.change_offset(-60, MIDNIGHT + 30 * H)
    assert key.start == MIDNIGHT + 24 * H and key.end == MIDNIGHT + 49 * H


@given(
    at=st.datetimes(
        min_value=datetime(2020, 1, 1), max_value=datetime(2035, 1, 1), timezones=st.just(UTC)
    ),
    first=st.integers(MIN_OFFSET, MAX_OFFSET),
    second=st.integers(MIN_OFFSET, MAX_OFFSET),
    later=st.integers(0, 47 * 3600),
)
def test_change_offset_never_shortens_the_key(
    at: datetime, first: int, second: int, later: int
) -> None:
    cal = DayCalendar(first, at)
    now = min(at + timedelta(seconds=later), cal.key.end - timedelta(microseconds=1))
    before = cal.key
    after = cal.change_offset(second, now)
    assert after.start == before.start and after.end >= before.end
    assert after.end - after.start < 48 * H
    assert grid_key(after.end, second).start == after.end

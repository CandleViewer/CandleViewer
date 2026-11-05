"""The day-boundary resolver (E29-S06 #981 slice 4; 24 Sec.8.13 "The day boundary", 21 Sec.3.11
`rp_day`): the day at a fixed offset, east-positive and half-open, 24 h, at both ends of the range;
the change rule, which keeps the day in progress until its `next_start`; and failing closed, never
at UTC midnight. The column is a fake read and every instant is passed in: no clock, no sleep."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.risk.day_boundary import (
    DAY,
    OFFSET_MAX,
    OFFSET_MIN,
    DayBoundary,
    DayBoundaryUnavailable,
    TradingDay,
    day_after,
    day_containing,
)

T = datetime(2026, 10, 26, 9, 30, tzinfo=UTC)
H, US = timedelta(hours=1), timedelta(microseconds=1)
OFFSETS = st.integers(OFFSET_MIN, OFFSET_MAX)
INSTANTS = st.datetimes(datetime(2000, 1, 2), datetime(2099, 12, 30), timezones=st.just(UTC))


@dataclass
class Policy:
    """`RiskPolicyReads`: the column's `offset`, each read counted; `failure` raised instead, and a
    read waits for `gate` when one is set."""

    offset: int = 0
    failure: Exception | None = None
    reads: int = 0
    gate: asyncio.Event | None = None

    async def day_boundary_utc_offset_minutes(self) -> int:
        self.reads += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.failure is not None:
            raise self.failure
        return self.offset


def _z(day: TradingDay) -> tuple[str, str, int]:
    """The day as 22's `ClosedPnlWindow` writes it, to the millisecond."""
    start, end = (at.isoformat(timespec="milliseconds") for at in (day.day_start, day.next_start))
    return start, end, day.utc_offset_minutes


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (180, ("2026-10-25T21:00:00.000+00:00", "2026-10-26T21:00:00.000+00:00", 180)),
        (-300, ("2026-10-26T05:00:00.000+00:00", "2026-10-27T05:00:00.000+00:00", -300)),
        (0, ("2026-10-26T00:00:00.000+00:00", "2026-10-27T00:00:00.000+00:00", 0)),
        (OFFSET_MIN, ("2026-10-25T12:00:00.000+00:00", "2026-10-26T12:00:00.000+00:00", -720)),
        (OFFSET_MAX, ("2026-10-25T10:00:00.000+00:00", "2026-10-26T10:00:00.000+00:00", 840)),
    ],
    ids=["plus_180", "minus_300", "zero", "range_low", "range_high"],
)
async def test_the_day_is_east_positive_at_each_offset(
    offset: int, expected: tuple[str, str, int]
) -> None:
    """24 Sec.8.13: +180 starts at 21:00:00.000Z of the previous UTC date, -300 at 05:00:00.000Z."""
    assert _z(day_containing(T, offset)) == expected
    assert _z(await DayBoundary(Policy(offset)).resolve(T)) == expected


@pytest.mark.parametrize("offset", [OFFSET_MIN - 1, OFFSET_MAX + 1, cast(int, True)])
async def test_an_offset_outside_rp_day_is_refused_never_read_as_utc(offset: int) -> None:
    with pytest.raises(ValueError, match="rp_day"):
        day_containing(T, offset)
    with pytest.raises(DayBoundaryUnavailable):
        await DayBoundary(Policy(offset)).resolve(T)


async def test_the_day_is_half_open_at_its_boundary_minute() -> None:
    days = DayBoundary(Policy(180))
    start = datetime(2026, 10, 25, 21, tzinfo=UTC)
    before = await days.resolve(start - US)
    assert before.next_start == start and not before.holds(start)  # `next_start` is the next day's
    assert (await days.resolve(start)).day_start == start
    assert (await days.resolve(start + DAY - US)).next_start == start + DAY


@given(at=INSTANTS, offset=OFFSETS)
async def test_property_each_instant_lies_in_one_24_h_day_from_its_latest_local_midnight(
    at: datetime, offset: int
) -> None:
    day = await DayBoundary(Policy(offset)).resolve(at)
    assert day == day_containing(at, offset)
    assert day.day_start <= at < day.next_start and day.next_start - day.day_start == DAY
    local = day.day_start + timedelta(minutes=offset)
    assert (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0)
    assert day.day_start > at - DAY  # the latest such midnight, not an earlier one


@given(at=INSTANTS, offset=OFFSETS, zone=st.integers(-23, 23))
def test_property_the_day_does_not_depend_on_the_instants_own_zone(
    at: datetime, offset: int, zone: int
) -> None:
    seen = at.astimezone(timezone(timedelta(hours=zone)))
    assert day_containing(seen, offset) == day_containing(at, offset)


async def test_a_change_waits_for_next_start_and_that_day_runs_to_the_new_offsets_midnight() -> (
    None
):
    """The column moves from 0 to +180 at 12:00Z: the day in progress keeps 0 until its
    `next_start`, the day after runs 21 h, to 21:00Z, and the next ones are 24 h at +180."""
    policy = Policy(0)
    days = DayBoundary(policy)
    first = await days.resolve(datetime(2026, 10, 26, 10, tzinfo=UTC))
    policy.offset = 180
    assert await days.resolve(datetime(2026, 10, 26, 12, tzinfo=UTC)) == first  # not mid-day
    assert await days.resolve(first.next_start - US) == first
    change = await days.resolve(first.next_start)
    assert _z(change) == ("2026-10-27T00:00:00.000+00:00", "2026-10-27T21:00:00.000+00:00", 180)
    assert change.next_start != change.day_start + DAY  # `next_start` as served
    after = await days.resolve(change.next_start)
    assert _z(after) == ("2026-10-27T21:00:00.000+00:00", "2026-10-28T21:00:00.000+00:00", 180)
    assert policy.reads == 3  # the first day, then once at each `next_start`


@given(
    old=OFFSETS, new=OFFSETS, at=INSTANTS, into=st.integers(0, 86_399_999_999), late=st.booleans()
)
async def test_property_a_change_takes_effect_at_next_start_never_inside_the_day(
    old: int, new: int, at: datetime, into: int, late: bool
) -> None:
    policy = Policy(old)
    days = DayBoundary(policy)
    first = await days.resolve(at)
    policy.offset = new
    assert await days.resolve(first.day_start + timedelta(microseconds=into)) == first
    change = await days.resolve(first.next_start)
    assert change == day_after(first, new) and change.day_start == first.next_start
    assert TradingDay(change.day_start, change.next_start, new) == change
    span = change.next_start - change.day_start
    assert timedelta(0) < span <= DAY and (span == DAY) is ((new - old) % 1440 == 0)
    local = change.next_start + timedelta(minutes=new)
    assert (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0)
    later = change.next_start + (DAY if late else timedelta(0))
    assert await days.resolve(later) == day_containing(later, new)  # 24 h days at the new offset


async def test_offsets_a_day_apart_change_on_a_24_h_day() -> None:
    """UTC-12 to UTC+12: the two midnights coincide, so the change's day is 24 h."""
    policy = Policy(OFFSET_MIN)
    days = DayBoundary(policy)
    first = await days.resolve(T)
    policy.offset = 720
    change = await days.resolve(first.next_start)
    assert change.next_start - change.day_start == DAY and change.utc_offset_minutes == 720


@pytest.mark.parametrize(
    "failure", [OSError("postgres unreachable"), LookupError("no policy row")], ids=["io", "row"]
)
async def test_a_policy_that_cannot_be_read_fails_closed_never_at_utc_midnight(
    failure: Exception,
) -> None:
    days = DayBoundary(Policy(180, failure=failure))
    with pytest.raises(DayBoundaryUnavailable):
        await days.resolve(T)
    with pytest.raises(DayBoundaryUnavailable):
        await days.day_start(T)


async def test_a_policy_read_that_outlasts_its_bound_fails_closed() -> None:
    days = DayBoundary(Policy(0, gate=asyncio.Event()), timeout_s=0)
    with pytest.raises(DayBoundaryUnavailable):
        await days.resolve(T)


async def test_the_day_in_progress_reads_nothing_and_is_never_served_past_next_start() -> None:
    """Inside the day the column is not read, so a read that would fail changes nothing; at its
    `next_start` the failed read fails closed rather than keep the ended day, then recovers."""
    policy = Policy(-300)
    days = DayBoundary(policy)
    first = await days.resolve(T)
    policy.failure = OSError("postgres unreachable")
    assert await days.resolve(first.next_start - US) == first and policy.reads == 1
    with pytest.raises(DayBoundaryUnavailable):
        await days.resolve(first.next_start)
    policy.failure = None
    assert await days.resolve(first.next_start) == day_containing(first.next_start, -300)


async def test_an_instant_before_the_kept_days_fails_closed() -> None:
    days = DayBoundary(Policy(0))
    first = await days.resolve(T)
    await days.resolve(first.next_start)
    assert await days.resolve(first.day_start) == first  # the day before, as served
    with pytest.raises(DayBoundaryUnavailable):
        await days.resolve(first.day_start - US)


async def test_resolves_racing_the_first_read_answer_one_day() -> None:
    gate = asyncio.Event()
    policy = Policy(180, gate=gate)
    days = DayBoundary(policy)
    async with asyncio.TaskGroup() as group:
        one, two = (group.create_task(days.resolve(T + n * H)) for n in (0, 1))
        await asyncio.sleep(0)  # each runs to its read's gate
        assert policy.reads == 2  # both read before either keeps a day
        gate.set()
    assert one.result() is two.result() == day_containing(T, 180)


async def test_a_naive_instant_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        day_containing(T.replace(tzinfo=None), 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        await DayBoundary(Policy()).resolve(T.replace(tzinfo=None))

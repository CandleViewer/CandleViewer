"""The clock halt (E29-T04 #913; 24-internal-schemas.md Sec.8.6, `10002`): a trip refuses order
entry until a measurement taken after it passes `assert_healthy()`, and an unhealthy clock refuses
it untripped too. Each refusal is a fresh `ClockDriftBlocked`, 503 `clock_drift` with its
`Retry-After`. The fake clock answers as `ingestion.clock.ClockGuard` does."""

from __future__ import annotations

import math
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import ClockDriftError
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.oms.clock_halt import CLOCK_HALT_RETRY_AFTER_S, ClockHalt
from candleviewer.oms.errors import ClockDriftBlocked, problem_for
from candleviewer.oms.fakes import FakeClockHealth


class Clock:
    """A monotonic clock, in seconds, that the test moves."""

    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def rig(**kwargs: Any) -> tuple[ClockHalt, FakeClockHealth, Clock]:
    """A halt over a fake clock measured healthy at 100 s."""
    clock = Clock()
    health = FakeClockHealth(clock)
    health.measure()
    return ClockHalt(health, monotonic=clock, **kwargs), health, clock


def refused(halt: ClockHalt) -> bool:
    refusal = halt.refusal()
    return isinstance(refusal, ClockDriftBlocked)


def test_order_entry_goes_on_while_the_clock_is_healthy_and_untripped() -> None:
    halt, _, clock = rig()
    clock.now = 1_000.0
    assert halt.refusal() is None


@pytest.mark.parametrize("offset_ms", [None, 2_000.5, -2_500.0])
def test_an_unhealthy_clock_refuses_order_entry_untripped(offset_ms: float | None) -> None:
    """E08-S07 "Hard drift blocks trading": never measured, or past the hard threshold."""
    clock = Clock()
    health = FakeClockHealth(clock)
    if offset_ms is not None:
        health.measure(offset_ms)
    halt = ClockHalt(health, monotonic=clock)
    assert refused(halt)
    health.measure(1_999.0)
    assert halt.refusal() is None


def test_a_trip_refuses_until_a_measurement_taken_after_it_is_healthy() -> None:
    """24 Sec.8.6: a `10002` blocks all order entry until a resync; a measurement from before
    the trip never clears it, however long it is waited on."""
    halt, health, clock = rig()
    clock.now = 110.0
    halt.trip()
    refusal = halt.refusal()
    assert isinstance(refusal, ClockDriftBlocked)
    assert refusal.retry_after_s == CLOCK_HALT_RETRY_AFTER_S == 5
    clock.now = 10_000.0
    assert refused(halt)  # the measurement at 100 s predates the trip
    health.measure()
    clock.now = 10_000.5
    assert halt.refusal() is None
    assert halt.refusal() is None  # cleared for good


def test_a_measurement_taken_at_the_trip_does_not_clear_it() -> None:
    """It must be younger than the trip, not as old."""
    halt, health, clock = rig()
    clock.now = 110.0
    health.measure()
    halt.trip()
    clock.now = 120.0
    assert refused(halt)


def test_a_fresh_measurement_that_is_unhealthy_keeps_the_halt() -> None:
    halt, health, clock = rig()
    clock.now = 110.0
    halt.trip()
    clock.now = 111.0
    health.measure(3_000.0)
    assert refused(halt)
    clock.now = 112.0
    health.measure(-15.0)
    assert halt.refusal() is None


def test_a_second_trip_restarts_the_wait() -> None:
    halt, health, clock = rig()
    clock.now = 110.0
    halt.trip()
    clock.now = 111.0
    health.measure()
    clock.now = 112.0
    halt.trip()  # another `10002` before any order asked
    assert refused(halt)  # measured at 111 s, before the latest trip
    clock.now = 113.0
    health.measure()
    assert halt.refusal() is None


class _Unreadable:
    """A healthy clock whose age reads `age`."""

    def __init__(self, age: float) -> None:
        self.age = age

    def assert_healthy(self) -> None:
        return None

    def offset_age_s(self) -> float:
        return self.age

    async def resync_after_signature_failure(self, *, reason: str) -> int:
        return 0


@pytest.mark.parametrize("age", [math.nan, math.inf])
def test_an_age_that_shows_no_measurement_since_the_trip_fails_closed(age: float) -> None:
    clock = Clock()
    halt = ClockHalt(_Unreadable(age), monotonic=clock)
    assert halt.refusal() is None
    halt.trip()
    clock.now = 1e9
    assert refused(halt)


def test_each_refusal_is_a_fresh_503_clock_drift_with_its_retry_after() -> None:
    clock = Clock()
    halt = ClockHalt(FakeClockHealth(clock), monotonic=clock, retry_after_s=7)
    first, second = halt.refusal(), halt.refusal()
    assert isinstance(first, ClockDriftBlocked) and isinstance(second, ClockDriftBlocked)
    assert first is not second and (first.retry_after_s, second.retry_after_s) == (7, 7)
    problem = problem_for(first)
    assert (problem.status, problem.code, problem.retry_after) == (503, "clock_drift", True)


@pytest.mark.parametrize(
    ("retry_after_s", "error"),
    [(0, ValueError), (-5, ValueError), (True, TypeError), (2.5, TypeError)],
)
def test_a_retry_after_that_is_not_whole_seconds_from_one_is_refused(
    retry_after_s: Any, error: type[Exception]
) -> None:
    clock = Clock()
    with pytest.raises(error, match="retry_after_s"):
        ClockHalt(FakeClockHealth(clock), monotonic=clock, retry_after_s=retry_after_s)


def test_a_trip_and_its_clearing_are_logged_once_each() -> None:
    halt, health, clock = rig()
    with capture_logs() as logs:
        clock.now = 110.0
        halt.trip()
        halt.trip()
        halt.refusal()
        clock.now = 111.0
        health.measure()
        clock.now = 112.0
        halt.refusal()
        halt.refusal()
    assert [(log["event"], log["log_level"]) for log in logs] == [
        ("oms_clock_halt_tripped", "warning"),
        ("oms_clock_halt_tripped", "warning"),
        ("oms_clock_halt_cleared", "info"),
    ]
    assert [logs[0]["already_halted"], logs[1]["already_halted"]] == [False, True]
    assert logs[2]["halted_s"] == 2.0


@given(measured=st.integers(0, 10**6), tripped=st.integers(0, 10**6), later=st.integers(0, 10**6))
def test_property_a_halt_clears_only_on_a_measurement_younger_than_its_trip(
    measured: int, tripped: int, later: int
) -> None:
    """Whole seconds keep the float arithmetic exact; at one instant, the measurement first."""
    clock = Clock(0.0)
    health = FakeClockHealth(clock)
    halt = ClockHalt(health, monotonic=clock)
    for at, is_trip in sorted([(measured, False), (tripped, True)]):
        clock.now = float(at)
        if is_trip:
            halt.trip()
        else:
            health.measure()
    clock.now = float(max(measured, tripped) + later)
    assert (halt.refusal() is None) == (measured > tripped)


async def test_the_fake_clock_answers_as_the_guard_does() -> None:
    """Before any measurement: unhealthy, its age `inf`. A failed resync leaves that standing; a
    resync that answers measures, and its age runs from then."""
    clock = Clock()
    health = FakeClockHealth(clock, hard_threshold_ms=500.0)
    assert health.offset_age_s() == math.inf
    with pytest.raises(ClockDriftError):
        health.assert_healthy()
    health.resync_error = TimeoutError("no sample answered")
    with pytest.raises(TimeoutError):
        await health.resync_after_signature_failure(reason="order_10002")
    assert health.offset_age_s() == math.inf
    health.resync_error, health.resync_offset_ms = None, 12.5
    assert await health.resync_after_signature_failure(reason="order_10002") == 12_500
    assert health.resyncs == ["order_10002", "order_10002"]
    health.assert_healthy()
    clock.now += 3.0
    assert health.offset_age_s() == 3.0
    health.measure(-500.5)
    with pytest.raises(ClockDriftError):
        health.assert_healthy()


async def test_the_clock_guard_as_it_stands_is_the_halts_clock() -> None:
    """Slice 3 wires `ingestion.clock.ClockGuard` itself: unmeasured, it refuses order entry; a
    trip clears on the resync the order path asks for."""
    mono = Clock()

    async def server_time() -> tuple[int, float, float]:
        return 1_700_000_000_000_000, 1_700_000_000.0, 0.0  # no offset, no round trip

    guard = ClockGuard(
        server_time, sample_count=1, clock=mono, wall_ns=lambda: 0, mono_ns=lambda: 0
    )
    halt = ClockHalt(guard, monotonic=mono)
    assert refused(halt)
    await guard.measure_once()
    assert halt.refusal() is None
    mono.now = 110.0
    halt.trip()
    assert refused(halt)
    mono.now = 111.0
    await guard.resync_after_signature_failure(reason="order_10002")
    mono.now = 112.0
    assert halt.refusal() is None

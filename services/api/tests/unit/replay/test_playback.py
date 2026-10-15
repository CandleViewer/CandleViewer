"""Playback ports and models of the replay clock (E26-T03): speeds, bounds, and the
`MonotonicTime` contract that `LoopTime` (production) and `FakeTime` (tests) share."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from candleviewer.replay import (
    STEP,
    UNBOUNDED,
    ClockConfig,
    LoopTime,
    MonotonicTime,
    ReplayRequestInvalid,
    check_speed,
)
from tests.unit.replay._time import FakeTime


@pytest.mark.parametrize("speed", [STEP, UNBOUNDED, 0.1, 1, 4.0, 100])
def test_check_speed_accepts_step_unbounded_and_the_paced_range(speed: float) -> None:
    assert check_speed(speed) == float(speed)


@pytest.mark.parametrize("speed", [0.05, 100.5, -2.0, float("nan"), float("inf")])
def test_check_speed_refuses_anything_else(speed: float) -> None:
    with pytest.raises(ReplayRequestInvalid, match="replay speed"):
        check_speed(speed)


@pytest.mark.parametrize("field", ["max_lag_s", "min_wait_s", "rate_window_s", "yield_every"])
def test_clock_config_refuses_a_bound_that_is_not_positive(field: str) -> None:
    bounds: dict[str, Any] = {field: 0}
    with pytest.raises(ValueError, match="positive"):
        ClockConfig(**bounds)


def _times() -> list[MonotonicTime]:
    return [LoopTime(), FakeTime(auto=False)]


@pytest.mark.parametrize("time", _times(), ids=["loop", "fake"])
async def test_wait_until_returns_at_once_when_already_woken(time: MonotonicTime) -> None:
    wake = asyncio.Event()
    wake.set()
    deadline = time.now() + 3_600.0
    await time.wait_until(deadline, wake)
    assert time.now() < deadline


@pytest.mark.parametrize("time", _times(), ids=["loop", "fake"])
async def test_wait_until_returns_once_the_deadline_has_passed(time: MonotonicTime) -> None:
    await time.wait_until(time.now() - 1.0, asyncio.Event())


@pytest.mark.parametrize("time", _times(), ids=["loop", "fake"])
async def test_wait_until_returns_early_when_woken_meanwhile(time: MonotonicTime) -> None:
    wake = asyncio.Event()
    deadline = time.now() + 3_600.0
    asyncio.get_running_loop().call_soon(wake.set)
    await time.wait_until(deadline, wake)
    assert time.now() < deadline


async def test_fake_time_parks_a_wait_until_advanced_past_its_deadline() -> None:
    time = FakeTime(auto=False)
    waiter = asyncio.ensure_future(time.wait_until(time.now() + 5.0, asyncio.Event()))
    for _ in range(10):
        await asyncio.sleep(0)
    assert not waiter.done()
    time.advance(5.0)
    await waiter
    assert time.waits == 1

"""`ReplayLoopBudget` (#2668 G1, slice 1): the replay share of the event loop.

One `FakeTime` is both the budget's `time` and its `measure`, so a lane's work is the fake time it
advances while it runs, and a hold is the fake time it waits (C-13.7: no sleeps, no wall clock).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

import pytest
from prometheus_client import REGISTRY

from candleviewer.replay import BudgetLane, LoopTime, ReplayConfigInvalid, ReplayLoopBudget
from candleviewer.replay.budget import MAX_CHARGE_S
from tests.unit.replay._time import FakeTime

SLICE = 0.002  # the clock's longest turn (ClockConfig.yield_slice_s)
SHARE, BURST = 0.25, 0.05


def _budget(time: FakeTime, *, share: float = SHARE, burst_s: float = BURST) -> ReplayLoopBudget:
    return ReplayLoopBudget(share, burst_s, time, measure=time.now)


def _sample(name: str) -> float:
    return REGISTRY.get_sample_value(name) or 0.0


@pytest.fixture
def waiters() -> Callable[[], float]:
    """Lanes waiting now, beyond the gauge's value when the test started (the gauge is
    process-wide)."""
    base = _sample("replay_budget_waiters")
    return lambda: _sample("replay_budget_waiters") - base


async def _settle(rounds: int = 20) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


def _work(time: FakeTime, lane: BudgetLane, seconds: float) -> None:
    """`seconds` of loop work on `lane`, measured from a fresh `start()`."""
    lane.start()
    time.advance(seconds)


@pytest.mark.parametrize(
    ("share", "burst_s"),
    [(0.049, 0.05), (0.751, 0.05), (0.25, 0.0049), (0.25, 0.251), (float("nan"), 0.05)],
)
def test_budget_outside_its_bounds_is_refused(share: float, burst_s: float) -> None:
    """C-4.14: no configuration turns the budget off or past its bounds."""
    with pytest.raises(ReplayConfigInvalid):
        ReplayLoopBudget(share, burst_s, FakeTime())


async def test_budget_work_within_the_burst_is_not_held() -> None:
    time = FakeTime()
    lane = _budget(time).lane("s1")
    _work(time, lane, BURST)

    assert await lane.breathe() == 0.0
    assert time.waits == 0


async def test_budget_debt_is_held_until_refilled_at_the_share() -> None:
    time = FakeTime()
    lane = _budget(time).lane("s1")
    _work(time, lane, BURST + 0.010)  # the bucket was full, so its refill is capped: 10 ms of debt
    expected = 0.010 / SHARE

    held = await lane.breathe()

    assert held == pytest.approx(expected, abs=1e-9)
    assert time.waits >= 1


async def test_budget_refill_is_capped_at_the_burst() -> None:
    time = FakeTime()
    budget = _budget(time)
    lane = budget.lane("s1")
    time.advance(3_600.0)  # an idle hour banks no more than the burst
    _work(time, lane, BURST + 0.004)

    assert await lane.breathe() > 0.0


async def test_budget_charge_counts_only_time_since_the_last_start_or_charge() -> None:
    time = FakeTime()
    lane = _budget(time).lane("s1")
    _work(time, lane, 0.003)
    assert lane.charge() == pytest.approx(0.003)
    assert lane.charge() == 0.0  # charged once, never twice
    time.advance(5.0)  # a natural wait, between a charge and the next start: not loop work
    _work(time, lane, 0.001)
    assert lane.charge() == pytest.approx(0.001)


async def test_budget_breathe_restarts_the_lane_after_the_hold() -> None:
    time = FakeTime()
    lane = _budget(time).lane("s1")
    _work(time, lane, BURST + 0.010)
    await lane.breathe()

    assert lane.charge() == 0.0  # the hold itself is not charged


async def _busy(time: FakeTime, lane: BudgetLane, until: float, done: list[float]) -> None:
    lane.start()
    while time.now() < until:
        time.advance(SLICE)
        done.append(SLICE)
        await lane.breathe()


@pytest.mark.parametrize("lanes", [1, 2, 4, 8])
async def test_budget_share_holds_for_busy_lanes_and_splits_fairly(lanes: int) -> None:
    """Over 10 s of wall time, N always-busy lanes together get the share plus the burst and
    about one slice per lane, and each lane gets its fair part within 10 %."""
    time = FakeTime()
    budget = _budget(time)
    start, span = time.now(), 10.0
    work: list[list[float]] = [[] for _ in range(lanes)]

    async with asyncio.TaskGroup() as tg:
        for i in range(lanes):
            tg.create_task(_busy(time, budget.lane(f"s{i}"), start + span, work[i]))

    elapsed = time.now() - start
    total = sum(sum(w) for w in work)
    assert total / elapsed >= SHARE * 0.95
    assert total <= SHARE * elapsed + BURST + (lanes + 1) * SLICE
    per_lane = [sum(w) for w in work]
    mean = total / lanes
    assert all(abs(p - mean) <= 0.10 * mean for p in per_lane), per_lane


def _indebt(time: FakeTime, budget: ReplayLoopBudget) -> None:
    """Put `budget` 50 ms into debt (a full bucket refills nothing): 200 ms of refill."""
    debtor = budget.lane("debtor")
    _work(time, debtor, BURST + 0.050)
    debtor.charge()


async def test_budget_admits_waiters_first_in_first_out(waiters: Callable[[], float]) -> None:
    """The lanes queue in the order b, c, a while their tasks run in the order c, a, b: once the
    debt is paid they are admitted in queue order, never in task order."""
    time = FakeTime(auto=False)
    budget = _budget(time)
    _indebt(time, budget)
    gates = {name: asyncio.Event() for name in ("c", "a", "b")}
    admitted: list[str] = []

    async def wait(name: str) -> None:
        await gates[name].wait()
        await budget.lane(name).breathe()
        admitted.append(name)

    async with asyncio.TaskGroup() as tg:
        for name in gates:
            tg.create_task(wait(name))
        for name in ("b", "c", "a"):
            gates[name].set()
            await _settle()
        assert waiters() == 3
        time.advance(1.0)

    assert admitted == ["b", "c", "a"]
    assert waiters() == 0


async def test_budget_a_later_lane_queues_behind_a_waiter_even_with_the_debt_paid() -> None:
    time = FakeTime(auto=False)
    budget = _budget(time)
    _indebt(time, budget)
    order: list[str] = []

    async def first() -> None:
        lane = budget.lane("first")
        await lane.breathe()
        time.advance(BURST + 0.050)  # its turn puts the budget back into debt
        lane.charge()
        order.append("first")

    async def advance_later() -> None:
        await _settle()
        time.advance(1.0)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(first())
        await _settle()
        time.advance(1.0)  # the debt is paid, but "first" has not run yet
        tg.create_task(advance_later())
        late = budget.lane("late")
        late.start()
        held = await late.breathe()
        order.append("late")

    assert order == ["first", "late"]
    assert held > 0.0  # it waited for the debt "first" ran up, instead of overtaking


async def test_budget_a_cancelled_waiter_leaves_and_the_next_is_admitted(
    waiters: Callable[[], float],
) -> None:
    time = FakeTime(auto=False)
    budget = _budget(time)
    _indebt(time, budget)
    head = asyncio.create_task(budget.lane("head").breathe())
    await _settle()
    nxt = asyncio.create_task(budget.lane("next").breathe())
    await _settle()
    assert waiters() == 2

    head.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await head
    assert waiters() == 1
    time.advance(1.0)

    assert await nxt > 0.0
    assert waiters() == 0


@pytest.mark.parametrize("position", ["head", "behind"])
async def test_budget_wake_cuts_a_hold_short(position: str, waiters: Callable[[], float]) -> None:
    time = FakeTime(auto=False)
    budget = _budget(time)
    _indebt(time, budget)
    ahead = None
    if position == "behind":
        ahead = asyncio.create_task(budget.lane("ahead").breathe())
        await _settle()
    wake = asyncio.Event()
    held = asyncio.create_task(budget.lane("woken").breathe(wake))
    await _settle()
    time.advance(0.001)

    wake.set()

    assert await held == pytest.approx(0.001)
    if ahead is not None:
        assert not ahead.done()  # the wake ended only its own hold
        time.advance(1.0)
        await ahead
    assert waiters() == 0


async def test_budget_metrics_count_loop_work_holds_and_waiters(
    waiters: Callable[[], float],
) -> None:
    time = FakeTime()
    lane = _budget(time).lane("s1")
    work0 = _sample("replay_loop_seconds_total")
    held0 = _sample("replay_budget_held_seconds_total")
    _work(time, lane, BURST + 0.010)

    held = await lane.breathe()

    assert _sample("replay_loop_seconds_total") - work0 == pytest.approx(BURST + 0.010)
    assert _sample("replay_budget_held_seconds_total") - held0 == pytest.approx(held)
    assert waiters() == 0


def test_budget_lane_keeps_its_key() -> None:
    assert _budget(FakeTime()).lane("session-1").key == "session-1"


async def test_budget_breathe_yields_even_when_wake_is_already_set_in_debt() -> None:
    """A set wake skips the hold, never the yield: every `breathe` lets the loop run once."""
    time = FakeTime(auto=False)
    budget = _budget(time)
    _indebt(time, budget)
    lane, wake, ticks = budget.lane("woken"), asyncio.Event(), 0
    wake.set()

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    try:
        before = ticks
        for _ in range(100):
            _work(time, lane, SLICE)
            assert await lane.breathe(wake) == 0.0
        assert ticks - before >= 100
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_budget_one_long_charge_is_counted_in_full_but_bounds_the_debt() -> None:
    """A 5 s suspension charged at once (a sink that held the lane) is visible in the loop
    series, yet the debt it leaves holds no lane longer than 0.25 s / share."""
    time = FakeTime()
    budget = _budget(time)
    slow, other = budget.lane("slow"), budget.lane("other")
    work0 = _sample("replay_loop_seconds_total")
    _work(time, slow, 5.0)

    held_slow = await slow.breathe()
    _work(time, other, BURST + SLICE)
    held_other = await other.breathe()

    assert _sample("replay_loop_seconds_total") - work0 == pytest.approx(5.0 + BURST + SLICE)
    assert 0.0 < held_slow <= MAX_CHARGE_S / SHARE
    assert 0.0 < held_other <= MAX_CHARGE_S / SHARE


def test_budget_is_built_with_loop_time_outside_a_running_loop() -> None:
    """Composition may build the budget before the loop runs: nothing reads the time yet."""
    budget = ReplayLoopBudget(SHARE, BURST, LoopTime())

    async def run() -> float:
        lane = budget.lane("s1")
        lane.start()
        return await lane.breathe()

    assert asyncio.run(run()) == 0.0

"""The replay clock and source on the loop budget (#2668 G1). `Work` is the budget's `measure`:
it moves only with work, never with a hold or a wait; `FakeTime` is its `time` (C-13.7)."""

from __future__ import annotations

import asyncio

from prometheus_client import REGISTRY

from candleviewer.replay import (
    STEP,
    UNBOUNDED,
    ClockConfig,
    ReplayClock,
    ReplayItem,
    ReplayLoopBudget,
    ReplaySource,
)
from candleviewer.replay.budget import BudgetLane
from candleviewer.storage.repositories.recorded import RecordedEvent
from tests.unit.replay._events import SECOND, T0, Harness, request, trade
from tests.unit.replay._playback import ListStream, RecordingObserver, RecordingSink
from tests.unit.replay._source import SMALL, many
from tests.unit.replay._time import FakeTime

SHARE, BURST, SLICE = 0.25, 0.05, ClockConfig().yield_slice_s
COST = 0.0005  # fake seconds of loop work per delivered event


class Work:
    """Loop work done so far, in fake seconds: the budget's `measure`."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t


class WorkSink(RecordingSink):
    """A CPU-bound consumer: each event is `cost_s` of work and of fake time; it never suspends."""

    def __init__(self, time: FakeTime, work: Work, *, cost_s: float = COST) -> None:
        super().__init__(time, cost_s=cost_s)
        self.work = work

    async def deliver(self, event: RecordedEvent) -> None:
        self.at.append(self.time.now())
        self.events.append(event)
        self.time.advance(self.cost_s)
        self.work.t += self.cost_s


def _events(count: int, every_us: int) -> list[ReplayItem]:
    return [trade(i * every_us, trade_id=f"t{i:06}") for i in range(count)]


def _clock(
    items: list[ReplayItem],
    sink: RecordingSink,
    lane: BudgetLane | None,
    *,
    speed: float = STEP,
    end_s: int = 120,
    obs: RecordingObserver | None = None,
) -> ReplayClock:
    return ReplayClock(
        ListStream(items),
        sink,
        obs or RecordingObserver(),
        time=sink.time,
        start_us=T0,
        end_us=T0 + end_s * SECOND,
        speed=speed,
        budget_lane=lane,
    )


def _turns(work: Work) -> tuple[list[float], asyncio.Task[None]]:
    """The work done between two turns of another task: each is one replay turn."""
    turns: list[float] = []

    async def other() -> None:
        last = work.t
        while True:
            turns.append(work.t - last)
            last = work.t
            await asyncio.sleep(0)

    return turns, asyncio.ensure_future(other())


async def test_clock_a_long_step_breathes_every_slice_and_keeps_to_the_share() -> None:
    time, work = FakeTime(), Work()
    budget = ReplayLoopBudget(SHARE, BURST, time, measure=work.now)
    sink = WorkSink(time, work)
    turns, other = _turns(work)
    began = time.now()
    async with _clock(_events(100_000, 1_000), sink, budget.lane("s")) as clock:
        assert await clock.step_events(100_000) == "step"
    other.cancel()
    elapsed = time.now() - began
    assert len(sink.events) == 100_000
    assert max(turns) <= SLICE + COST + 1e-9  # a charged turn: one slice plus one event
    assert len(turns) >= work.t / (SLICE + COST)
    assert work.t <= SHARE * elapsed + BURST + SLICE + COST  # the share, the burst, one turn


async def test_clock_a_hold_slows_playback_without_backpressure_or_a_catch_up_burst() -> None:
    """Paced at 1x, events 2 ms apart and 1 ms of work each: half the loop, so the budget holds
    the clock. The hold slides the schedule and is booked as lost time: the achieved ratio
    falls, nothing reads as backpressure, and replay time never runs ahead of wall time."""
    time, work = FakeTime(), Work()
    budget = ReplayLoopBudget(SHARE, BURST, time, measure=work.now)
    sink, obs, ratios = (
        WorkSink(time, work, cost_s=0.001),
        RecordingObserver(),
        list[float | None](),
    )
    slow = REGISTRY.get_sample_value("replay_backpressure_seconds_total") or 0.0
    clock = _clock(_events(5_000, 2_000), sink, budget.lane("s"), speed=1.0, end_s=10, obs=obs)

    async def watch() -> None:
        while True:
            ratios.append(clock.stats().achieved_ratio)
            await asyncio.sleep(0)

    watcher = asyncio.ensure_future(watch())
    async with clock:
        assert await clock.play() == "range_end"
    watcher.cancel()
    stats = clock.stats()
    assert len(sink.events) == 5_000 and stats.backpressure_s > 1.0
    assert stats.backpressured is False and obs.edges == []
    assert (REGISTRY.get_sample_value("replay_backpressure_seconds_total") or 0.0) == slow
    last = [r for r in ratios if r is not None][-1]
    assert 0.3 <= last <= 0.7
    span = [(e.ts_us - T0) / SECOND for e in sink.events]
    for i in range(len(span) - 5):  # five events ahead: never faster than 1x (+ min_wait, cost)
        assert span[i + 5] - span[i] <= sink.at[i + 5] - sink.at[i] + 0.002 + 1e-9


async def test_clock_two_clocks_share_one_cap_evenly() -> None:
    time, work = FakeTime(), Work()
    budget = ReplayLoopBudget(SHARE, BURST, time, measure=work.now)
    sinks = [WorkSink(time, work), WorkSink(time, work)]
    clocks = [_clock(_events(20_000, 1_000), s, budget.lane(f"s{n}")) for n, s in enumerate(sinks)]
    began = time.now()
    async with clocks[0], clocks[1]:
        steps = [asyncio.ensure_future(c.step_events(20_000)) for c in clocks]
        await asyncio.sleep(0)
        first_done = await next(iter(asyncio.as_completed(steps)))
        assert first_done == "step"
        done_at, share_each = time.now(), [len(s.events) for s in sinks]
        await asyncio.gather(*steps)
    elapsed = done_at - began
    assert sum(share_each) * COST <= SHARE * elapsed + BURST + 2 * (SLICE + COST)
    assert min(share_each) >= 0.8 * max(share_each)  # first in, first out: an even split


async def test_clock_pause_ends_a_hold_at_once() -> None:
    time, work = FakeTime(auto=False), Work()
    budget = ReplayLoopBudget(SHARE, BURST, time, measure=work.now)
    other = budget.lane("other")
    other.start()
    work.t += 0.2  # another session's turn left the budget 0.15 s in debt: a 0.6 s hold
    other.charge()
    sink, began = WorkSink(time, work), time.now()
    async with _clock(_events(1_000, 1_000), sink, budget.lane("s"), speed=UNBOUNDED) as clock:
        task = clock.play()
        for _ in range(50):
            await asyncio.sleep(0)
        held_at = len(sink.events)
        assert 0 < held_at < 1_000  # the clock works its first slice, then is held
        await clock.pause()
        assert task.result() == "paused" and len(sink.events) == held_at
    assert time.now() - began < 0.6  # the pause did not wait the hold out


class SpyLane:
    """A lane that counts its calls, around a real one."""

    def __init__(self, lane: BudgetLane) -> None:
        self.lane, self.starts, self.charges, self.breaths = lane, 0, 0, 0

    def start(self) -> None:
        self.starts += 1
        self.lane.start()

    def charge(self) -> float:
        self.charges += 1
        return self.lane.charge()

    async def breathe(self, wake: asyncio.Event | None = None) -> float:
        self.breaths += 1
        return await self.lane.breathe(wake)


async def test_source_producer_breathes_per_batch_and_is_held_in_debt() -> None:
    time, work = FakeTime(auto=False), Work()
    budget = ReplayLoopBudget(SHARE, BURST, time, measure=work.now)
    debtor = budget.lane("other")
    debtor.start()
    work.t += 0.2  # 0.15 s in debt: held for 0.6 s
    debtor.charge()
    spy = SpyLane(budget.lane("s"))
    harness = Harness(hot=many(1_000), req=request(end_us=60 * SECOND))
    async with ReplaySource(harness.req, harness.tiers, config=SMALL, lane=spy) as source:
        await source.__anext__()
        for _ in range(50):
            await asyncio.sleep(0)
        assert spy.breaths == 1 and source.buffered_events == 0  # held after its first batch
        time.advance(0.6)
        for _ in range(50):
            await asyncio.sleep(0)
        assert source.buffered_events > 0 and spy.breaths > 1
        assert spy.charges >= spy.breaths  # every await of the producer is charged first

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
    ReplayClockStateError,
    ReplayItem,
    ReplayLoopBudget,
    ReplaySource,
)
from candleviewer.replay.budget import BudgetLane
from candleviewer.storage.repositories.recorded import RecordedEvent
from tests.unit.replay._events import SECOND, T0, BoundedTier, Harness, request, trade
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


def _charged() -> float:
    return REGISTRY.get_sample_value("replay_loop_seconds_total") or 0.0


async def _settle(rounds: int = 50) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


def _indebt(budget: ReplayLoopBudget, work: Work) -> None:
    """Another session's turn leaves the budget 0.15 s in debt: a 0.6 s hold at the share."""
    other = budget.lane("other")
    other.start()
    work.t += 0.2
    other.charge()


async def test_clock_destroy_during_a_natural_wait_charges_no_idle_time() -> None:
    """Review M1: a cancelled deadline wait restarts the lane, so the wait is never charged."""
    time = FakeTime(auto=False)
    budget, sink = ReplayLoopBudget(SHARE, BURST, time, measure=time.now), RecordingSink(time)
    clock = _clock(_events(3, 10 * SECOND), sink, budget.lane("s"), speed=1.0)
    async with clock:
        clock.play()
        await _settle()
        time.advance(5.0)  # idle, waiting for the second event
        before = _charged()
        await clock.aclose()
    assert len(sink.events) == 1 and _charged() - before < 0.01


async def test_source_destroy_with_the_producer_parked_charges_no_idle_time() -> None:
    time = FakeTime(auto=False)
    budget = ReplayLoopBudget(SHARE, BURST, time, measure=time.now)
    harness = Harness(hot=many(1_000), req=request(end_us=60 * SECOND))
    source = ReplaySource(harness.req, harness.tiers, config=SMALL, lane=budget.lane("s"))
    async with source:
        await source.__anext__()
        await _settle()  # the producer parks on the full queue
        time.advance(600.0)
        before = _charged()
    assert _charged() - before < 0.01


async def test_source_a_storage_wait_is_not_charged_as_loop_time() -> None:
    """Review M1 (security lens): a read that waits off the loop charges only loop work."""
    time = FakeTime()
    reads = list[int]()

    class WaitingTier(BoundedTier):
        async def read(self, *args: object, **kwargs: object) -> list[RecordedEvent]:
            reads.append(1)
            time.advance(0.03)  # 30 ms waiting on storage, no loop work
            await asyncio.sleep(0)
            return await super().read(*args, **kwargs)  # type: ignore[arg-type]

    harness = Harness(req=request(end_us=60 * SECOND))
    harness.replace_ports(hot=WaitingTier(many(1_000)))
    lane = ReplayLoopBudget(SHARE, BURST, time, measure=time.now).lane("s")
    before = _charged()
    async with ReplaySource(harness.req, harness.tiers, config=SMALL, lane=lane) as source:
        assert len([i async for i in source]) == 1_000
    assert reads and _charged() - before < 0.01  # merge work is 0 fake seconds here


async def test_clock_destroy_ends_a_step_hold() -> None:
    """Review m2: a step held by the budget ends when the session is destroyed."""
    time, work = FakeTime(auto=False), Work()
    budget = ReplayLoopBudget(SHARE, BURST, time, measure=work.now)
    _indebt(budget, work)
    clock = _clock(_events(1_000, 1_000), WorkSink(time, work), budget.lane("s"))
    async with clock:
        step = asyncio.ensure_future(clock.step_events(1_000))
        await _settle()
        assert not step.done()  # held
        await clock.aclose()
        await _settle()
        assert step.done() and isinstance(step.exception(), ReplayClockStateError)


async def test_clock_a_speed_change_does_not_end_a_hold() -> None:
    """Review m3: only a pause or a destroy ends a hold; a speed change re-anchors and waits on."""
    time, work = FakeTime(auto=False), Work()
    budget = ReplayLoopBudget(SHARE, BURST, time, measure=work.now)
    _indebt(budget, work)
    sink = WorkSink(time, work)
    async with _clock(_events(1_000, 100), sink, budget.lane("s"), speed=1.0) as clock:
        task = clock.play()
        await _settle()
        held_at = len(sink.events)
        clock.set_speed(2.0)
        await _settle()
        assert len(sink.events) == held_at  # still held
        await clock.pause()
        assert task.result() == "paused"


async def test_clock_speed_zero_ends_a_hold() -> None:
    """Speed 0 (STEP) pauses playback, so like a pause it ends a hold at once."""
    time, work = FakeTime(auto=False), Work()
    budget = ReplayLoopBudget(SHARE, BURST, time, measure=work.now)
    _indebt(budget, work)
    async with _clock(_events(1_000, 100), WorkSink(time, work), budget.lane("s"), speed=1.0) as c:
        task = c.play()
        await _settle()
        c.set_speed(STEP)
        await _settle()
        assert task.done() and task.result() == "paused"


async def test_clock_destroy_during_a_parked_source_read_charges_no_idle_time() -> None:
    """Review (Fable m2): the clock waits on a source whose producer is parked in a slow read; a
    destroy 5 s later charges nothing for the wait."""
    time = FakeTime(auto=False)
    budget = ReplayLoopBudget(SHARE, BURST, time, measure=time.now)

    class ParkedTier(BoundedTier):
        async def read(self, *args: object, **kwargs: object) -> list[RecordedEvent]:
            await asyncio.Event().wait()  # storage never answers
            raise AssertionError("unreachable")

    harness = Harness(req=request(end_us=60 * SECOND))
    harness.replace_ports(hot=ParkedTier(many(10)))
    lane = budget.lane("s")
    source = ReplaySource(harness.req, harness.tiers, config=SMALL, lane=lane)
    clock = _clock([], RecordingSink(time), lane, speed=1.0)
    clock._source = source  # the clock reads the parked source
    async with clock:
        clock.play()
        await _settle()
        time.advance(5.0)
        before = _charged()
        await clock.aclose()
    assert _charged() - before < 0.01

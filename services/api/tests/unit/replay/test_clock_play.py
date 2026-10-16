"""`ReplayClock` playback (E26-T03): faithful drift-free pacing, speed changes, pause and resume,
unbounded mode, gaps, backpressure, steps, loop wrap, failures and per-session task ownership.
Fake time only (C-13.7)."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from hypothesis import given
from hypothesis import strategies as st
from prometheus_client import REGISTRY

from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.time_builder import TimeBarBuilder, bucket_bounds
from candleviewer.replay import (
    STEP,
    UNBOUNDED,
    ClockConfig,
    GapPolicy,
    ReplayClock,
    ReplayClockStateError,
    ReplayGap,
    ReplayItem,
    ReplayRequestInvalid,
    ReplaySourceUnavailable,
    StopReason,
)
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import RecordedEvent, RecordedTrade
from tests.unit.bars._trades import trade as bar_trade
from tests.unit.replay._events import SECOND, SYM, T0, delta, trade
from tests.unit.replay._playback import ListStream, RecordingObserver, RecordingSink
from tests.unit.replay._time import FakeTime


@dataclass
class Rig:
    clock: ReplayClock
    stream: ListStream
    sink: RecordingSink
    obs: RecordingObserver
    time: FakeTime


def rig(
    items: Sequence[ReplayItem],
    *,
    end_s: int,
    speed: float = 1.0,
    time: FakeTime | None = None,
    stream: ListStream | None = None,
    sink: RecordingSink | None = None,
    config: ClockConfig | None = None,
) -> Rig:
    t = time or FakeTime()
    src, snk, obs = stream or ListStream(items), sink or RecordingSink(t), RecordingObserver()
    clock = ReplayClock(
        src, snk, obs, time=t, start_us=T0, end_us=T0 + end_s * SECOND, speed=speed, config=config
    )
    return Rig(clock, src, snk, obs, t)


def every_second(count: int) -> list[ReplayItem]:
    return [trade(i * SECOND, trade_id=f"t{i:05}") for i in range(count)]


async def settle() -> None:
    for _ in range(200):
        await asyncio.sleep(0)


async def run_for(time: FakeTime, seconds: float, *, step: float = 0.05) -> None:
    """Let `seconds` of fake time pass in steps well inside `max_lag_s`, as a punctual sleeper
    would (one big jump is a 1 s oversleep, which the clock rightly treats as falling behind).
    It settles first, so a just-started `play()` reads its first event and anchors before."""
    await settle()
    for _ in range(round(seconds / step)):
        time.advance(step)
        await settle()


async def test_one_hour_at_1x_is_faithful_and_drift_free() -> None:
    """Ticket AC 1: every wait oversleeps up to 4 ms, yet the hour ends within 0.5 % of an hour
    and the last event is no later against its schedule than the first."""
    r = rig(every_second(3_600), end_s=3_600, time=FakeTime(oversleep_s=0.004))
    start = r.time.now()
    async with r.clock as clock:
        assert await clock.play() == "range_end"
    assert abs((r.time.now() - start) - 3_600.0) <= 0.005 * 3_600.0
    drift = [at - start - i for i, at in enumerate(r.sink.at)]
    assert 0.0 <= min(drift) and max(drift) <= 0.004 + 1e-9
    assert abs(drift[-1] - drift[0]) <= 0.004 + 1e-9
    assert r.sink.events == every_second(3_600)
    assert r.obs.stops == [("range_end", None)]
    assert r.clock.now_us() == T0 + 3_600 * SECOND


async def test_pause_stops_at_the_reached_position_and_play_resumes_from_it() -> None:
    r = rig(every_second(10), end_s=10, time=FakeTime(auto=False))
    async with r.clock as clock:
        first = clock.play()
        await run_for(r.time, 2.5)
        await clock.pause()
        assert (first.result(), len(r.sink.events)) == ("paused", 3)
        assert clock.now_us() == T0 + 2_500_000
        r.time.advance(100.0)
        second = clock.play()
        await run_for(r.time, 0.5)  # t3 is due 0.5 s after resuming at 2.5 s
        assert len(r.sink.events) == 4
        await run_for(r.time, 7.5)
        assert await second == "range_end"
    assert r.sink.events == every_second(10)


async def test_a_destroy_cancelled_again_still_closes_the_source_exactly_once() -> None:
    """Regression R2: the sink awaits during its cancel cleanup, and the runner is cancelled a
    second time meanwhile. The source still closes, once, and a destroyed session reports no
    stop."""
    release, tasks = asyncio.Event(), list[asyncio.Task[StopReason]]()

    class StuckSink(RecordingSink):
        async def deliver(self, event: RecordedEvent) -> None:
            try:
                await asyncio.Event().wait()  # a consumer that never takes the event
            except asyncio.CancelledError:
                await release.wait()  # cleanup that itself awaits
                raise

    stream, obs, time = ListStream(every_second(3)), RecordingObserver(), FakeTime(auto=False)
    clock = ReplayClock(stream, StuckSink(time), obs, time=time, start_us=T0, end_us=T0 + SECOND)

    async def session() -> None:
        async with clock:
            tasks.append(clock.play())
            await asyncio.Event().wait()  # lives until destroyed

    runner = asyncio.ensure_future(session())
    for _ in range(2):  # destroy, then cancel the runner again mid-destroy
        await settle()
        runner.cancel()
    release.set()
    await settle()
    assert runner.cancelled() and tasks[0].cancelled() and stream.closes == 1
    await clock.aclose()
    assert (stream.closes, obs.stops) == (1, [])


@pytest.mark.parametrize("late_s", [0.0, 2.0])  # 2.0: the parked read returns a due event
async def test_a_pause_during_a_parked_source_read_is_not_lost(late_s: float) -> None:
    """Regression R1: pause() arrives while the source read is parked. Once the read returns,
    the clock stops at once, with no fake time passing (before the fix it waited for the next
    event's deadline)."""
    gate = asyncio.Event()

    class ParkedStream(ListStream):
        async def __anext__(self) -> ReplayItem:
            if self._next == 1:  # the second read parks
                await gate.wait()
            return await super().__anext__()

    r = rig([], end_s=5, time=FakeTime(auto=False), stream=ParkedStream(every_second(5)))
    start = r.time.now()
    async with r.clock as clock:
        task = clock.play()
        await settle()
        pausing = asyncio.ensure_future(clock.pause())
        await settle()
        r.time.advance(late_s)
        gate.set()
        await settle()
        assert pausing.done() and task.result() == "paused"
    assert (r.time.now(), len(r.sink.events)) == (start + late_s, 1)


async def test_destroying_a_playing_session_keeps_the_cursor_it_reached() -> None:
    r = rig(every_second(5), end_s=5, time=FakeTime(auto=False))
    async with r.clock as clock:
        clock.play()
        await run_for(r.time, 2.5)
        assert clock.now_us() == T0 + 2_500_000
    assert r.clock.now_us() == T0 + 2_500_000  # not the last delivered event, 2 s


async def test_inter_event_deltas_are_scaled_by_speed() -> None:
    r = rig(every_second(20), end_s=20, speed=4.0)
    start = r.time.now()
    async with r.clock as clock:
        await clock.play()
    assert [at - start for at in r.sink.at] == pytest.approx([i / 4 for i in range(20)])
    assert r.time.now() - start == pytest.approx(5.0)


async def test_unbounded_speed_delivers_everything_without_waiting() -> None:
    r = rig(every_second(500), end_s=500, speed=UNBOUNDED)
    async with r.clock as clock:
        assert await clock.play() == "range_end"
    assert (len(r.sink.events), r.time.waits) == (500, 0)


async def test_a_source_failure_stops_playback_after_every_earlier_event() -> None:
    error = ReplaySourceUnavailable(tier="questdb", symbol="BTCUSDT", stream=None, reason="io")
    stream = ListStream(every_second(5), fail_at=3, error=error)
    r = rig([], end_s=5, speed=UNBOUNDED, stream=stream)
    async with r.clock as clock:
        assert await clock.play() == "error"
        with pytest.raises(ReplayClockStateError, match="source failed"):
            clock.play()  # it used to report a false range_end from the dead source
    assert r.sink.events == every_second(3)
    assert r.obs.stops == [("error", error)]


class BusySink(RecordingSink):
    """Takes 1 ms of fake time per event and never suspends: a CPU-bound consumer, so only the
    clock's own time-sliced yields let the rest of the loop run (C-2.17)."""

    async def deliver(self, event: RecordedEvent) -> None:
        self.events.append(event)
        self.time.advance(0.001)


async def test_catching_up_yields_to_the_event_loop_every_time_slice() -> None:
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    background = asyncio.ensure_future(ticker())
    time, config = FakeTime(), ClockConfig(yield_slice_s=0.002)
    sink = BusySink(time)
    r = rig(every_second(1_000), end_s=1_000, speed=UNBOUNDED, time=time, sink=sink, config=config)
    async with r.clock as clock:
        await clock.play()
    background.cancel()
    assert len(r.sink.events) == 1_000 and ticks >= 250  # a yield about every 3 ms of work


async def test_control_calls_the_clock_state_refuses() -> None:
    with pytest.raises(ValueError, match="end after it starts"):
        rig([], end_s=0)
    r = rig(every_second(3), end_s=3, time=FakeTime(auto=False))
    with pytest.raises(ReplayClockStateError, match="not open"):
        r.clock.play()
    async with r.clock as clock:
        await clock.pause()  # nothing plays: a silent no-op, which B12's stop_clock relies on
        clock.play()
        with pytest.raises(ReplayClockStateError, match="already running"):
            clock.play()
        await clock.pause()
    with pytest.raises(ReplayClockStateError, match="opened once"):
        await r.clock.__aenter__()
    async with rig([], end_s=1, speed=STEP).clock as stepping:
        with pytest.raises(ReplayClockStateError, match="step mode"):
            stepping.play()


async def test_an_event_the_sink_failed_on_is_delivered_again_on_retry() -> None:
    """The consumer-raises contract: playback stops with `error`, the event stays pending, and
    the next play() delivers it first. Before the fix it was lost on retry."""
    boom, time = RuntimeError("consumer down"), FakeTime()

    class FlakySink(RecordingSink):
        failed = False

        async def deliver(self, event: RecordedEvent) -> None:
            if len(self.events) == 2 and not self.failed:  # fail the third event, once
                self.failed = True
                raise boom
            await super().deliver(event)

    r = rig(every_second(5), end_s=5, speed=UNBOUNDED, time=time, sink=FlakySink(time))
    async with r.clock as clock:
        assert await clock.play() == "error"
        assert await clock.play() == "range_end"
    assert r.sink.events == every_second(5)
    assert r.obs.stops == [("error", boom), ("range_end", None)]


async def test_the_schedule_starts_after_a_slow_first_read() -> None:
    """A cold source's first read (0.3 s here) is not lateness: the events after it keep their
    0.1 s spacing instead of arriving in a catch-up burst."""
    time = FakeTime()

    class ColdStream(ListStream):
        async def __anext__(self) -> ReplayItem:
            if self._next == 0:
                time.advance(0.3)
            return await super().__anext__()

    items = [trade(i * 100_000, trade_id=f"t{i}") for i in range(5)]
    r = rig([], end_s=1, time=time, stream=ColdStream(items))
    async with r.clock as clock:
        await clock.play()
    assert [round(b - a, 6) for a, b in itertools.pairwise(r.sink.at)] == [0.1] * 4
    assert (r.clock.stats().backpressure_s, r.obs.edges) == (0.0, [])  # primed, not booked


async def test_speed_change_takes_effect_from_the_current_position() -> None:
    r = rig(every_second(60), end_s=60, time=FakeTime(auto=False))
    async with r.clock as clock:
        task = clock.play()
        await run_for(r.time, 10.0)
        assert len(r.sink.events) == 11
        clock.set_speed(10.0)
        await run_for(r.time, 1.0)  # 10 s of replay at 10x
        assert len(r.sink.events) == 21
        clock.set_speed(STEP)
        assert await task == "paused"
    assert r.clock.now_us() == T0 + 20 * SECOND


async def test_switching_to_unbounded_mid_playback_stops_waiting() -> None:
    r = rig(every_second(60), end_s=60, time=FakeTime(auto=False))
    async with r.clock as clock:
        task = clock.play()
        await settle()
        clock.set_speed(UNBOUNDED)
        assert await task == "range_end"
    assert len(r.sink.events) == 60


@pytest.mark.parametrize(("policy", "reason"), [("skip", "range_end"), ("stop", "gap")])
async def test_a_gap_is_counted_reported_and_handled_per_policy(
    policy: GapPolicy, reason: StopReason
) -> None:
    """Ticket AC 5: skip jumps the clock to the gap end; stop pauses at the boundary."""
    two, end = T0 + 2 * SECOND, T0 + 600 * SECOND
    marker = ReplayGap(two, "BTCUSDT", StreamKind.TRADES, two, end, "ws_disconnect")
    items: list[ReplayItem] = [*every_second(2), marker, trade(601 * SECOND, trade_id="after")]
    r = rig(items, end_s=602, config=ClockConfig(gap_policy=policy))
    start = r.time.now()
    async with r.clock as clock:
        assert await clock.play() == reason
        assert clock.stats().gap_warnings == 1
    assert r.obs.gaps == [(marker, policy == "stop")]
    if policy == "skip":
        assert r.sink.at[-1] - start == pytest.approx(3.0)  # 598 empty seconds compressed
    else:
        assert (len(r.sink.events), r.clock.now_us()) == (2, two)


async def _play_sampling(r: Rig, *, recover_after: int = 1 << 30) -> list[float]:
    """Play to the end, sampling the live achieved ratio; the sink speeds up after
    `recover_after` events."""
    ratios: list[float] = []
    async with r.clock as clock:
        task = clock.play()
        while not task.done():
            await asyncio.sleep(0)
            if len(r.sink.events) >= recover_after:
                r.sink.cost_s = 0.0
            ratio = clock.stats().achieved_ratio
            if ratio is not None:
                ratios.append(ratio)
        assert task.result() == "range_end"
    return ratios


async def test_backpressure_at_half_rate_slows_the_clock_and_drops_nothing() -> None:
    """Ticket AC 2: at 10x, a consumer needing 20 ms per event accepts half the required rate.
    Every event still arrives in order and the session reports an achieved rate below 10x."""
    items = [trade(i * 100_000, trade_id=f"t{i:04}") for i in range(600)]
    r = rig(items, end_s=60, speed=10.0)
    r.sink.cost_s = 0.02
    ratios = await _play_sampling(r)
    assert r.sink.events == items
    assert ratios and all(0.4 < ratio < 0.6 for ratio in ratios)
    stats = r.clock.stats()  # backpressure ends with playback
    assert (stats.events_emitted, stats.backpressured, r.obs.edges) == (600, False, [True, False])
    assert stats.backpressure_s > 0


async def test_backpressure_clears_once_the_consumer_keeps_up_again() -> None:
    items = [trade(i * 100_000, trade_id=f"t{i:04}") for i in range(600)]
    r = rig(items, end_s=60, speed=10.0)
    r.sink.cost_s = 0.02
    ratios = await _play_sampling(r, recover_after=200)
    assert r.obs.edges == [True, False]
    assert ratios[-1] == 1.0 and not r.clock.stats().backpressured


@given(
    offsets=st.lists(st.integers(0, 30 * SECOND), max_size=40),
    speed=st.sampled_from([0.5, 1.0, 10.0, 100.0, UNBOUNDED]),
    cost_ms=st.integers(0, 40),
)
def test_playback_never_drops_reorders_or_runs_early_and_the_cursor_never_goes_back(
    offsets: list[int], speed: float, cost_ms: int
) -> None:
    items: list[ReplayItem] = [trade(o, trade_id=f"t{i:03}") for i, o in enumerate(sorted(offsets))]

    async def main() -> tuple[Rig, list[int], float]:
        r = rig(items, end_s=31, speed=speed)
        r.sink.cost_s, start, cursors = cost_ms / 1_000, r.time.now(), []
        async with r.clock as clock:
            task = clock.play()
            while not task.done():
                cursors.append(clock.now_us())
                await asyncio.sleep(0)
        return r, cursors, start

    r, cursors, start = asyncio.run(main())
    assert r.sink.events == items
    assert cursors == sorted(cursors) and all(T0 <= c <= T0 + 31 * SECOND for c in cursors)
    if speed > 0:
        for event, at in zip(r.sink.events, r.sink.at, strict=True):
            assert at - start >= (event.ts_us - T0) / (speed * SECOND) - 0.001 - 1e-9


@pytest.mark.parametrize("resent", [(1.0,), (1.01, 1.0)], ids=["same", "alternating"])
async def test_speed_resends_never_forgive_lateness_or_hide_backpressure(
    resent: tuple[float, ...],
) -> None:
    """Regression: the UI re-sends a speed after every event while the sink falls 50 ms behind
    per event. The same speed is a no-op, and a real change re-anchors from the schedule's own
    position, so the lateness builds up and is booked. Before the fix every re-send forgave it."""
    time, speeds = FakeTime(), itertools.cycle(resent)
    ratios: list[float | None] = []

    class ResendingSink(RecordingSink):
        clock: ReplayClock | None = None

        async def deliver(self, event: RecordedEvent) -> None:
            await super().deliver(event)
            if self.clock is not None:
                ratios.append(self.clock.stats().achieved_ratio)
                self.clock.set_speed(next(speeds))

    sink = ResendingSink(time, cost_s=0.15)
    items = [trade(i * 100_000, trade_id=f"t{i}") for i in range(30)]
    r = rig(items, end_s=3, time=time, sink=sink)
    sink.clock = r.clock
    async with r.clock as clock:
        assert await clock.play() == "range_end"
    assert r.clock.stats().backpressure_s > 0 and r.obs.edges[:1] == [True]
    if resent == (1.0,):  # a no-op leaves the rate window alone: the achieved rate is reported
        assert any(ratio is not None for ratio in ratios)


async def test_an_event_exactly_at_the_range_end_is_not_delivered() -> None:
    """The range is half-open: `[start, end)`."""
    r = rig([*every_second(2), trade(2 * SECOND, trade_id="at-end")], end_s=2, speed=UNBOUNDED)
    async with r.clock as clock:
        assert await clock.play() == "range_end"
    assert r.sink.events == every_second(2)


async def test_step_events_delivers_exactly_that_many_at_once() -> None:
    r = rig(every_second(10), end_s=10, speed=STEP)
    async with r.clock as clock:
        assert await clock.step_event() == "step"
        assert await clock.step_events(3) == "step"
        assert (len(r.sink.events), clock.now_us()) == (4, T0 + 3 * SECOND)
        assert await clock.step_events(100) == "range_end"
    assert (r.sink.events, r.time.waits) == (every_second(10), 0)


async def test_step_ms_delivers_its_window_and_lands_the_cursor_at_the_end() -> None:
    r = rig(every_second(10), end_s=10, speed=STEP)
    async with r.clock as clock:
        assert await clock.step_ms(1_500) == "step"
        assert (len(r.sink.events), clock.now_us()) == (2, T0 + 1_500_000)
        clock.set_speed(10.0)  # not playing: only recorded, nothing is scheduled
        r.time.advance(1.0)
        assert (clock.now_us(), clock.stats().speed) == (T0 + 1_500_000, 10.0)
        assert await clock.step_ms(60_000) == "range_end"
        assert (len(r.sink.events), clock.now_us()) == (10, T0 + 10 * SECOND)


class TimeBarProbe:
    """`BarProbe` over the real `TimeBarBuilder`: every close it reports is the builder's own."""

    def __init__(self, spec: BarSpec) -> None:
        self.spec, self.builder, self.closes = spec, TimeBarBuilder(spec, SYM), 0
        self._due: int | None = None
        self.last: Bar | None = None  # the last bar it closed

    def due_us(self) -> int | None:
        return self._due

    def apply(self, event: RecordedEvent) -> bool:
        if not isinstance(event.payload, RecordedTrade):
            return False
        self._due = bucket_bounds(self.spec, event.ts_us)[1]
        return self._count(self.builder.on_trade(bar_trade(event.ts_us, event.payload.price)))

    def tick(self, now_us: int) -> bool:
        closed = self._count(self.builder.on_clock(now_us))
        self._due = None if closed else self._due
        return closed

    def _count(self, updates: Sequence[BarUpdate]) -> bool:
        closed = [u.bar for u in updates if u.kind == "close"]
        self.closes += len(closed)
        self.last = closed[-1] if closed else self.last
        return bool(closed)


async def test_step_bar_reveals_exactly_one_bar_of_the_active_spec() -> None:
    """Ticket AC 3: at speed 0 with a 1-minute BarSpec, each step_bar closes exactly one bar of
    the real builder, and the book events in that minute arrive with its trades."""
    items = sorted(
        [*(trade(i * 10 * SECOND, trade_id=f"t{i}") for i in range(30)), delta(25 * SECOND)],
        key=lambda e: e.ts_us,
    )
    r = rig(items, end_s=300, speed=STEP)
    probe = r.clock.bar_probe = TimeBarProbe(BarSpec(kind="time", interval_ms=60_000))
    async with r.clock as clock:
        for minute in (1, 2):
            assert await clock.step_bar() == "step"
            assert (probe.closes, clock.now_us()) == (minute, T0 + minute * 60 * SECOND)
            assert r.sink.events == [e for e in items if e.ts_us < T0 + minute * 60 * SECOND]


async def test_steps_refuse_while_playing_bad_sizes_and_a_missing_probe() -> None:
    r = rig(every_second(5), end_s=5, time=FakeTime(auto=False))
    async with r.clock as clock:
        with pytest.raises(ReplayClockStateError, match="bar probe"):
            await clock.step_bar()
        clock.play()
        with pytest.raises(ReplayClockStateError, match="pause playback"):
            await clock.step_events()
        await clock.pause()
        with pytest.raises(ReplayRequestInvalid, match="one event"):
            await clock.step_events(0)
        with pytest.raises(ReplayRequestInvalid, match="1 ms"):
            await clock.step_ms(0)


@pytest.mark.parametrize(("policy", "reason", "count"), [("stop", "gap", 2), ("skip", "step", 3)])
async def test_a_gap_ends_a_step_under_stop_and_is_stepped_over_under_skip(
    policy: GapPolicy, reason: StopReason, count: int
) -> None:
    two = T0 + 2 * SECOND
    marker = ReplayGap(two, SYM, StreamKind.TRADES, two, T0 + 5 * SECOND, "ws_disconnect")
    items: list[ReplayItem] = [*every_second(2), marker, trade(6 * SECOND, trade_id="after")]
    r = rig(items, end_s=10, speed=STEP, config=ClockConfig(gap_policy=policy))
    async with r.clock as clock:
        assert await clock.step_events(3) == reason
        assert await clock.step_ms(1_000) == "step"
    assert (len(r.sink.events), r.obs.gaps) == (count, [(marker, policy == "stop")])


async def test_a_loop_wraps_back_to_its_start_and_plays_the_range_again() -> None:
    """US-RPL-008: playback stops at the loop end (B12 RANGE_END); the loop-enabled session
    repositions to the loop start, which is the only way the cursor moves back."""
    loop = [trade(i * SECOND, trade_id=f"t{i}") for i in range(10, 20)]
    r = rig([], end_s=60)
    async with r.clock as clock:
        await clock.reposition(ListStream(loop), at_us=T0 + 10 * SECOND, end_us=T0 + 20 * SECOND)
        assert await clock.play() == "range_end"
        assert clock.now_us() == T0 + 20 * SECOND
        await clock.reposition(ListStream(loop), at_us=T0 + 10 * SECOND)
        assert clock.now_us() == T0 + 10 * SECOND
        assert await clock.play() == "range_end"
        with pytest.raises(ReplayRequestInvalid, match="inside the session"):
            await clock.reposition(ListStream([]), at_us=T0 + 20 * SECOND)  # the end is outside
    assert (r.sink.events, r.stream.closes) == (loop + loop, 1)


class CountProbe:
    """A count bar (a tick bar of `n` events): it closes on an event, never on time."""

    def __init__(self, n: int) -> None:
        self.n, self.seen = n, 0

    def due_us(self) -> int | None:
        return None

    def apply(self, event: RecordedEvent) -> bool:
        self.seen += 1
        return self.seen % self.n == 0

    def tick(self, now_us: int) -> bool:
        return False


async def test_step_bar_on_a_count_bar_stops_on_the_closing_event() -> None:
    r = rig(every_second(5), end_s=5, speed=STEP)
    r.clock.bar_probe = CountProbe(3)
    async with r.clock as clock:
        assert await clock.step_bar() == "step"
        assert len(r.sink.events) == 3
        assert await clock.step_bar() == "range_end"
    assert len(r.sink.events) == 5


async def test_stop_at_gap_ends_step_ms_and_step_bar_at_the_boundary() -> None:
    a, b = T0 + SECOND, T0 + 2 * SECOND
    items: list[ReplayItem] = [
        trade(0, trade_id="t0"),
        ReplayGap(a, SYM, StreamKind.TRADES, a, b, "ws_disconnect"),
        ReplayGap(b, SYM, StreamKind.TICKERS, b, T0 + 3 * SECOND, "ws_disconnect"),
        trade(4 * SECOND, trade_id="t4"),
    ]
    r = rig(items, end_s=5, speed=STEP, config=ClockConfig(gap_policy="stop"))
    r.clock.bar_probe = CountProbe(10)
    async with r.clock as clock:
        assert await clock.step_ms(5_000) == "gap"
        assert await clock.step_bar() == "gap"
        assert (len(r.sink.events), clock.now_us()) == (1, b)


@pytest.mark.parametrize("kind", ["events", "ms", "bar"])
async def test_a_long_step_yields_to_the_event_loop(kind: str) -> None:
    """Regression R3: a 5 000-event step through a CPU-bound sink held the loop for the whole
    step (151 ms for step_bar over the dense minute); it now yields every time slice."""
    ticks, time = 0, FakeTime()

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    background = asyncio.ensure_future(ticker())
    r = rig(every_second(5_000), end_s=5_000, speed=STEP, time=time, sink=BusySink(time))
    r.clock.bar_probe = CountProbe(5_000)
    async with r.clock as clock:
        if kind == "events":
            await clock.step_events(5_000)
        elif kind == "ms":
            await clock.step_ms(5_000_000)
        else:
            await clock.step_bar()
    background.cancel()
    assert len(r.sink.events) == 5_000 and ticks >= 1_000


async def test_a_destroy_during_a_step_raises_instead_of_reporting_the_range_end() -> None:
    gate = asyncio.Event()

    class ParkedStream(ListStream):
        async def __anext__(self) -> ReplayItem:
            if self._next == 1:  # the step's second read parks
                await gate.wait()
            return await super().__anext__()

    r = rig([], end_s=5, speed=STEP, stream=ParkedStream(every_second(5)))
    async with r.clock as clock:
        stepping = asyncio.ensure_future(clock.step_events(3))
        await settle()
        await clock.aclose()  # the session is destroyed while the step's read is parked
        gate.set()
        with pytest.raises(ReplayClockStateError, match="destroyed during the step"):
            await stepping


async def test_steps_refuse_after_a_source_failure_until_a_reposition() -> None:
    error = ReplaySourceUnavailable(tier="parquet", symbol=SYM, stream=None, reason="io")
    r = rig([], end_s=5, speed=STEP, stream=ListStream(every_second(5), fail_at=1, error=error))
    async with r.clock as clock:
        with pytest.raises(ReplaySourceUnavailable):
            await clock.step_events(3)
        with pytest.raises(ReplayClockStateError, match="reposition"):
            await clock.step_events()
        await clock.reposition(ListStream(every_second(5)[2:]), at_us=T0 + 2 * SECOND)
        assert await clock.step_events(3) == "step"
    assert len(r.sink.events) == 4


async def test_a_reposition_closes_the_old_source_even_if_its_caller_is_cancelled() -> None:
    gate = asyncio.Event()

    class SlowClose(ListStream):
        async def aclose(self) -> None:
            await gate.wait()
            await super().aclose()

    old = SlowClose(every_second(3))
    r = rig([], end_s=5, speed=STEP, stream=old)
    async with r.clock as clock:
        moving = asyncio.ensure_future(clock.reposition(ListStream([]), at_us=T0 + SECOND))
        await settle()
        moving.cancel()
        await settle()
        destroying = asyncio.ensure_future(clock.aclose())  # the session is destroyed meanwhile
        await settle()
        assert not destroying.done()  # fix round 2: a destroy waits for that close too
        gate.set()
        await destroying
        assert moving.cancelled() and old.closes == 1


def _sample(name: str) -> float:
    return REGISTRY.get_sample_value(name) or 0.0


class SpeedSink(RecordingSink):
    """Changes the speed in its `nth` delivery, `lag_s` of fake time in (the UI, mid-delivery)."""

    def __init__(self, time: FakeTime, *, nth: int, speed: float, lag_s: float = 0.0) -> None:
        super().__init__(time)
        self.nth, self.speed, self.lag_s = nth, speed, lag_s
        self.clock: ReplayClock | None = None

    async def deliver(self, event: RecordedEvent) -> None:
        await super().deliver(event)
        if len(self.events) == self.nth and self.clock is not None:
            self.time.advance(self.lag_s)
            self.clock.set_speed(self.speed)


async def test_playback_exports_throughput_lag_backpressure_and_the_achieved_ratio() -> None:
    """The 500th delivery switches to unbounded, which takes the clock out of the ratio gauge
    (fix round 2, #2724 NIT 3: it kept reporting its last paced ratio)."""
    names = ("replay_events_emitted_total", "replay_backpressure_seconds_total")
    before = {n: _sample(n) for n in (*names, "replay_clock_lag_ms_count")}
    items = [trade(i * 100_000, trade_id=f"t{i:04}") for i in range(600)]
    sink = SpeedSink(FakeTime(), nth=500, speed=UNBOUNDED)
    r = rig(items, end_s=60, speed=10.0, time=sink.time, sink=sink)
    sink.clock, sink.cost_s, gauges = r.clock, 0.02, []
    async with r.clock as clock:
        task = clock.play()
        while not task.done():
            await asyncio.sleep(0)
            gauges.append((len(sink.events) > 500, _sample("replay_achieved_speed_ratio")))
    after = {n: _sample(n) - before[n] for n in before}
    assert after["replay_events_emitted_total"] == 600
    assert after["replay_backpressure_seconds_total"] > 0
    assert after["replay_clock_lag_ms_count"] > 0
    assert min(ratio for unbounded, ratio in gauges if not unbounded) < 0.6
    assert {ratio for unbounded, ratio in gauges if unbounded} == {1.0}
    assert _sample("replay_achieved_speed_ratio") == 1.0  # nothing plays any more


async def test_playback_feeds_the_bar_probe_so_step_bar_closes_the_bar_play_left_open() -> None:
    """Play into the middle of a 1-minute bar, pause, then step_bar: the bar it closes holds the
    trades play delivered too (6, not just the 2 the step delivers)."""
    items = [trade(i * 10 * SECOND, trade_id=f"t{i}") for i in range(12)]
    r = rig(items, end_s=120, speed=10.0, time=FakeTime(auto=False))
    probe = r.clock.bar_probe = TimeBarProbe(BarSpec(kind="time", interval_ms=60_000))
    async with r.clock as clock:
        clock.play()
        await run_for(r.time, 3.5)  # 35 s of replay: the trades at 0..30 s
        await clock.pause()
        assert await clock.step_bar() == "step"
    assert (probe.closes, probe.last and probe.last.trade_count) == (1, 6)
    assert r.clock.now_us() == T0 + 60 * SECOND


async def test_switching_from_unbounded_back_to_paced_paces_from_the_event_in_flight() -> None:
    """The fifth delivery switches unbounded playback back to 1x: the rest is paced again, one
    second apart, from the event in flight (not one event late, from the last completed one)."""
    time = FakeTime()
    sink = SpeedSink(time, nth=5, speed=1.0)
    r = rig(every_second(20), end_s=20, speed=UNBOUNDED, time=time, sink=sink)
    sink.clock = r.clock
    async with r.clock as clock:
        assert await clock.play() == "range_end"
    assert [round(b - a, 6) for a, b in itertools.pairwise(r.sink.at)] == [0.0] * 4 + [1.0] * 15


@pytest.mark.parametrize(
    ("to", "lag_s", "booked", "edges"),
    [
        (1.0, 0.25, 0.0, []),  # carried, then caught up: under max_lag_s nothing is lost
        (1.0, 0.6, 0.5, [True, False]),  # carried, then booked past max_lag_s, less 0.1 s
        (UNBOUNDED, 0.25, 0.25, []),  # leaving the schedule books it as lost time
        (STEP, 0.25, 0.25, []),
    ],
)
async def test_a_speed_change_while_behind_carries_the_lag_and_never_rescales_it(
    to: float, lag_s: float, booked: float, edges: list[bool]
) -> None:
    """Fix round 2 (#2723 F1): 10x to 1x while 0.25 s behind re-scaled the lag to the new speed
    and booked 2.40 s (5.90 s for 0.6 s). A paced change now takes effect from the pending
    event's due time, so the lag carries over as it is."""
    time = FakeTime()
    sink = SpeedSink(time, nth=5, speed=to, lag_s=lag_s)
    items = [trade(i * 100_000, trade_id=f"t{i}") for i in range(10)]
    r = rig(items, end_s=1, speed=10.0, time=time, sink=sink)
    sink.clock = r.clock
    async with r.clock as clock:
        await clock.play()
    assert (r.clock.stats().backpressure_s, r.obs.edges) == (pytest.approx(booked, abs=1e-5), edges)


@pytest.mark.parametrize(("speed", "to"), [(1.0, 10.0), (UNBOUNDED, 10.0), (1.0, STEP)])
async def test_a_speed_change_before_playback_anchors_never_moves_now_back(
    speed: float, to: float
) -> None:
    """Fix round 2 (INV-B12-b): set_speed between play() and its first step, with an event
    pending, re-anchored at that event; play then anchored at the cursor, so now_us() went back
    (1.0 s, then 0.5 s). Until play anchors, a change is only recorded; STEP pauses it."""
    r = rig(every_second(5), end_s=5, speed=speed, time=FakeTime(auto=False))
    async with r.clock as clock:
        await clock.step_ms(500)
        task = clock.play()
        clock.set_speed(to)
        before = clock.now_us()
        await asyncio.sleep(0)
        assert clock.now_us() >= before == T0 + 500_000
        if to == STEP:
            assert (task.result(), len(r.sink.events)) == ("paused", 1)


async def test_any_source_exception_is_a_source_failure_until_a_reposition() -> None:
    """Fix round 2 (#2721 F1): `ReplaySource` hands over any exception, then ends. A
    RuntimeError read as a sink failure, so the next play() reported a false range_end."""
    boom = RuntimeError("an unwrapped tier failure")
    stream = ListStream(every_second(5), fail_at=3, error=boom)
    r = rig([], end_s=5, speed=UNBOUNDED, stream=stream)
    async with r.clock as clock:
        assert await clock.play() == "error"
        with pytest.raises(ReplayClockStateError, match="source failed"):
            clock.play()
        with pytest.raises(ReplayClockStateError, match="source failed"):
            await clock.step_events()
        await clock.reposition(ListStream(every_second(5)[3:]), at_us=T0 + 3 * SECOND)
        assert await clock.play() == "range_end"
    assert r.sink.events == every_second(5)
    assert r.obs.stops == [("error", boom), ("range_end", None)]


async def test_a_step_the_sink_failed_on_leaves_its_event_for_the_next_step() -> None:
    """The failed-event contract on the step path (a mutant clearing the event before the sink
    survived): the step raises, and the next step delivers that event first, once, in order."""
    failures = [RuntimeError("consumer down")]

    class FlakySink(RecordingSink):
        async def deliver(self, event: RecordedEvent) -> None:
            if len(self.events) == 2 and failures:  # the third event fails, once
                raise failures.pop()
            await super().deliver(event)

    time = FakeTime()
    r = rig(every_second(5), end_s=5, speed=STEP, time=time, sink=FlakySink(time))
    async with r.clock as clock:
        with pytest.raises(RuntimeError, match="consumer down"):
            await clock.step_events(5)
        assert await clock.step_events(5) == "range_end"
    assert r.sink.events == every_second(5)

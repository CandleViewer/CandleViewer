"""`ReplayClock` playback (E26-T03): faithful drift-free pacing, pause and resume, unbounded mode,
failures and per-session task ownership. Fake time only (C-13.7)."""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass

import pytest

from candleviewer.replay import (
    STEP,
    UNBOUNDED,
    ClockConfig,
    ReplayClock,
    ReplayClockStateError,
    ReplayItem,
    ReplaySourceUnavailable,
    StopReason,
)
from candleviewer.storage.repositories.recorded import RecordedEvent
from tests.unit.replay._events import SECOND, T0, trade
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
    items: list[ReplayItem],
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
        await settle()
        r.time.advance(2.5)
        await settle()
        await clock.pause()
        assert (first.result(), len(r.sink.events)) == ("paused", 3)
        assert clock.now_us() == T0 + 2_500_000
        r.time.advance(100.0)
        second = clock.play()
        await settle()
        r.time.advance(0.5)  # t3 is due 0.5 s after resuming at 2.5 s
        await settle()
        assert len(r.sink.events) == 4
        r.time.advance(7.0)
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


async def test_a_pause_during_a_parked_source_read_is_not_lost() -> None:
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
        gate.set()
        await settle()
        assert pausing.done() and task.result() == "paused"
    assert (r.time.now(), len(r.sink.events)) == (start, 1)


async def test_destroying_a_playing_session_keeps_the_cursor_it_reached() -> None:
    r = rig(every_second(5), end_s=5, time=FakeTime(auto=False))
    async with r.clock as clock:
        clock.play()
        await settle()
        r.time.advance(2.5)
        await settle()
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
    r = rig(every_second(3), end_s=3, time=FakeTime(auto=False))
    with pytest.raises(ReplayClockStateError, match="not open"):
        r.clock.play()
    async with r.clock as clock:
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

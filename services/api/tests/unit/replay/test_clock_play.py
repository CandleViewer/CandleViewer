"""`ReplayClock` playback (E26-T03): faithful drift-free pacing, pause and resume, and per-session
task ownership. Fake time only (C-13.7)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from candleviewer.replay import (
    ClockConfig,
    ReplayClock,
    ReplayItem,
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
    config: ClockConfig | None = None,
) -> Rig:
    t = time or FakeTime()
    src, sink, obs = stream or ListStream(items), RecordingSink(t), RecordingObserver()
    clock = ReplayClock(
        src, sink, obs, time=t, start_us=T0, end_us=T0 + end_s * SECOND, speed=speed, config=config
    )
    return Rig(clock, src, sink, obs, t)


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

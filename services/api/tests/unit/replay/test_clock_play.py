"""`ReplayClock` playback (E26-T03): faithful drift-free pacing, pause and resume, unbounded mode,
source failures and per-session task ownership. Fake time only (C-13.7)."""

from __future__ import annotations

import asyncio
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


async def test_a_source_failure_stops_playback_after_every_earlier_event() -> None:
    error = ReplaySourceUnavailable(tier="questdb", symbol="BTCUSDT", stream=None, reason="io")
    stream = ListStream(every_second(5), fail_at=3, error=error)
    r = rig([], end_s=5, speed=UNBOUNDED, stream=stream)
    async with r.clock as clock:
        assert await clock.play() == "error"
    assert r.sink.events == every_second(3)
    assert r.obs.stops == [("error", error)]


async def test_destroying_the_session_cancels_playback_and_closes_the_source_once() -> None:
    r = rig(every_second(5), end_s=5, time=FakeTime(auto=False))
    tasks: list[asyncio.Task[StopReason]] = []

    async def session() -> None:
        async with r.clock as clock:
            tasks.append(clock.play())
            await asyncio.Event().wait()  # lives until destroyed

    runner = asyncio.ensure_future(session())
    await settle()
    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner
    assert tasks[0].cancelled() and r.stream.closes == 1
    await r.clock.aclose()
    assert (r.stream.closes, r.obs.stops) == (1, [])


async def test_catching_up_yields_to_the_event_loop() -> None:
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0)

    background = asyncio.ensure_future(ticker())
    r = rig(every_second(1_000), end_s=1_000, speed=UNBOUNDED, config=ClockConfig(yield_every=100))
    async with r.clock as clock:
        await clock.play()
    background.cancel()
    assert ticks >= 10

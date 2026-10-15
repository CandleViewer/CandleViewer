"""`ReplayClock` playback (E26-T03): faithful drift-free pacing, speed changes, pause and resume,
unbounded mode, gaps, backpressure, source failures and per-session task ownership. Fake time
only (C-13.7)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.replay import (
    STEP,
    UNBOUNDED,
    ClockConfig,
    GapPolicy,
    ReplayClock,
    ReplayClockStateError,
    ReplayGap,
    ReplayItem,
    ReplaySourceUnavailable,
    StopReason,
)
from candleviewer.storage.models import StreamKind
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
    items: Sequence[ReplayItem],
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


async def run_for(time: FakeTime, seconds: float, *, step: float = 0.05) -> None:
    """Let `seconds` of fake time pass in steps well inside `max_lag_s`, as a punctual sleeper
    would (one big jump is a 1 s oversleep, which the clock rightly treats as falling behind)."""
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
    stats = r.clock.stats()
    assert (stats.events_emitted, stats.backpressured, r.obs.edges) == (600, True, [True])
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

"""`BarBuilderSet` forming-bar sampling (#2022; 24 §3.2, 23 §6.1 "Forming-bar cadence").

Once per 250 ms period, under the lane lock, the set routes `forming()` of every series whose
forming bar changed since it was last routed (its `open` or its last sample), and at no other
time. Opens, closes and amends are routed as built. Fake sleep and clock only: no real timer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from candleviewer.bars.activity_builders import TickBarBuilder
from candleviewer.bars.builder_set import (
    FORMING_SAMPLE_S,
    TICK_S,
    BarBuilderSet,
    BarsHealthReason,
    default_factory,
)
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.models import BarBuilder, BarSpec, BarUpdate
from candleviewer.bars.state_store import StateStore
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.exchange.base.models import TradeEvent

from ._set_harness import ENV, M1, T3, TOPIC, V5, Clock, FakeTape, RecordingSink, settle
from ._trades import SYM, trade, us

T0 = us("10:00:00")


def test_sample_period_is_the_ws_bars_throttle() -> None:
    assert FORMING_SAMPLE_S == 0.25 < TICK_S  # 23 §6.1's default `bars` throttle, 250 ms


class Periods:
    """Fake `sleep`: the ticker never wakes; the sampler wakes once per `release()`."""

    def __init__(self) -> None:
        self.gate: asyncio.Queue[None] = asyncio.Queue()
        self.entered = 0

    async def __call__(self, seconds: float) -> None:
        if seconds != FORMING_SAMPLE_S:
            await asyncio.Event().wait()  # the 1 s ticker: not driven here
        self.entered += 1
        await self.gate.get()

    async def release(self) -> None:
        """One sampling period: wake the sampler and wait until it sleeps again."""
        target = self.entered + 1
        self.gate.put_nowait(None)
        for _ in range(10_000):
            if self.entered >= target:
                return
            await asyncio.sleep(0)
        raise AssertionError("the sampler did not come back to sleep")


def _set(
    root: Path,
    bus: Bus,
    sink: RecordingSink,
    *,
    sleep: Callable[[float], object] | None = None,
    tape: FakeTape | None = None,
    factory: Callable[[BarSpec, str], BarBuilder] = default_factory,
) -> BarBuilderSet:
    kw = {} if sleep is None else {"sleep": sleep}
    return BarBuilderSet(
        bus,
        ENV,
        EmitRouter([sink]),
        StateStore(root),
        tape=tape,
        now_us=Clock(T0),
        factory=factory,
        **kw,  # type: ignore[arg-type]  # `Periods` is an async callable like `asyncio.sleep`
    )


async def _publish(bus: Bus, s: BarBuilderSet, *trades: TradeEvent) -> None:
    for t in trades:
        await bus.publish(TOPIC, t)
    await settle(bus, s)


def _kinds(sink: RecordingSink, spec: BarSpec) -> list[tuple[str, int]]:
    return [(k, i) for h, _, k, i, _ in sink.seen if h == spec.spec_hash]


def _sampled(sink: RecordingSink, spec: BarSpec) -> list[int]:
    """`trade_count` of each sample routed for `spec`, in order."""
    return [b.trade_count for h, k, b in sink.bars if h == spec.spec_hash and k == "update"]


async def test_sampler_routes_one_sample_per_period_per_changed_series(tmp_path: Path) -> None:
    bus, sink, periods = Bus(), RecordingSink(), Periods()
    s = _set(tmp_path, bus, sink, sleep=periods)
    await s.register(M1, SYM, "a")
    await s.register(V5, SYM, "b")
    await s.start()
    await periods.release()  # nothing has formed yet
    assert sink.seen == []
    await _publish(bus, s, trade(T0 + 1, seq=1), trade(T0 + 2, seq=2), trade(T0 + 3, seq=3))
    assert [k for _, _, k, _, _ in sink.seen] == ["open", "open"]  # no per-trade update
    await periods.release()
    assert (_sampled(sink, M1), _sampled(sink, V5)) == ([3], [3])  # one each, all 3 trades
    await periods.release()  # nothing changed: nothing routed
    await periods.release()
    assert (_sampled(sink, M1), _sampled(sink, V5)) == ([3], [3])
    await _publish(bus, s, *(trade(T0 + 10 + i, qty="0.1", seq=10 + i) for i in range(5)))
    await periods.release()
    assert (_sampled(sink, M1), _sampled(sink, V5)) == ([3, 8], [3, 8])  # one per period
    await s.stop()


async def test_sample_only_for_the_series_whose_forming_bar_changed(tmp_path: Path) -> None:
    bus, sink = Bus(), RecordingSink()
    s = _set(tmp_path, bus, sink)
    await s.register(M1, SYM, "a")
    await s.register(T3, SYM, "b")
    await _publish(bus, s, trade(T0 + 1, seq=1), trade(T0 + 2, seq=2), trade(T0 + 3, seq=3))
    await s.sample()  # M1 folded two trades; T3 opened and closed its bar: nothing forming
    assert _sampled(sink, M1) == [3] and _sampled(sink, T3) == []
    await s.sample()
    assert _sampled(sink, M1) == [3]
    await s.stop()


async def test_a_dropped_late_trade_does_not_route_an_unchanged_sample(tmp_path: Path) -> None:
    bus, sink = Bus(), RecordingSink()
    s = _set(tmp_path, bus, sink)
    await s.register(M1, SYM, "a")
    # bar 0, then bar 4 (10:01-10:04 empty), then a print into the empty 10:03 interval: dropped
    await _publish(bus, s, trade(us("10:00:10"), seq=1), trade(us("10:04:30"), seq=2))
    await _publish(bus, s, trade(us("10:03:30"), seq=3))
    await s.sample()
    assert _kinds(sink, M1) == [("open", 0), ("close", 0), ("open", 1)]
    await s.stop()


async def test_no_sample_of_a_bar_after_its_close(tmp_path: Path) -> None:
    bus, sink = Bus(), RecordingSink()
    s = _set(tmp_path, bus, sink)
    await s.register(T3, SYM, "a")
    await s.register(V5, SYM, "b")
    # T3: open, fold (changed), close; V5: open, fold (changed), then 2 + 2 + 2 closes it at 5
    # and the remainder opens bar 1: neither bar 0 is sampled after its close
    await _publish(bus, s, trade(T0, qty="2", seq=1), trade(T0 + 1, qty="2", seq=2))
    await _publish(bus, s, trade(T0 + 2, qty="2", seq=3))
    await s.sample()
    assert _kinds(sink, T3) == [("open", 0), ("close", 0)]
    assert _kinds(sink, V5) == [("open", 0), ("close", 0), ("open", 1)]
    await s.stop()


async def test_a_bar_that_opens_and_closes_within_one_period_is_never_sampled(
    tmp_path: Path,
) -> None:
    bus, sink, periods = Bus(), RecordingSink(), Periods()
    s = _set(tmp_path, bus, sink, sleep=periods)
    await s.register(T3, SYM, "a")
    await s.start()
    await _publish(bus, s, *(trade(T0 + i, px=str(100 + i), seq=i) for i in range(3)))
    await periods.release()
    assert _kinds(sink, T3) == [("open", 0), ("close", 0)]
    (close,) = [b for _, k, b in sink.bars if k == "close"]
    assert (close.trade_count, close.close) == (3, Decimal(102))  # every trade, none sampled
    await s.stop()


async def test_an_amend_is_routed_at_once_and_does_not_suppress_the_sample(
    tmp_path: Path,
) -> None:
    bus, sink = Bus(), RecordingSink()
    s = _set(tmp_path, bus, sink)
    await s.register(M1, SYM, "a")
    await _publish(bus, s, trade(us("10:00:10"), seq=1), trade(us("10:01:05"), seq=2))
    await _publish(bus, s, trade(us("10:01:10"), seq=3))  # extends bar 1: changed
    await _publish(bus, s, trade(us("10:00:30"), px="105", seq=4))  # late: amends bar 0
    amends = [u for u in sink.bars if u[1] == "close" and u[2].index == 0]
    assert [b.high for _, _, b in amends] == [100, 105]  # routed as built, not sampled
    await s.sample()
    assert _kinds(sink, M1) == [("open", 0), ("close", 0), ("open", 1), ("close", 0), ("update", 1)]
    assert _sampled(sink, M1) == [2]
    await s.stop()


async def test_a_held_lane_is_skipped_this_period_and_sampled_once_released(
    tmp_path: Path,
) -> None:
    other = "ETHUSDT"
    other_topic = Topic(env=ENV, domain="md", symbol=other, detail="trade")
    bus, sink = Bus(), RecordingSink()
    s = _set(tmp_path, bus, sink, factory=lambda spec, sym: default_factory(spec, sym))
    await s.register(M1, SYM, "a")
    await s.register(M1, other, "a")
    await _publish(bus, s, trade(T0 + 1, seq=1), trade(T0 + 2, seq=2))
    for i in (1, 2, 3):  # three prints: its sample counts 3, the held lane's counts 2
        await bus.publish(other_topic, trade(T0 + i, seq=i).model_copy(update={"symbol": other}))
    await settle(bus, s)
    async with s._lanes[SYM].lock:  # a restore replay or a stalled sink holds this lane
        await asyncio.wait_for(s.sample(), timeout=1)  # does not wait for it
        assert _sampled(sink, M1) == [3]  # the other symbol's sample still routed
    await s.sample()  # released: the dirty flag survived
    assert _sampled(sink, M1) == [3, 2]
    await s.sample()
    assert _sampled(sink, M1) == [3, 2]  # once
    await s.stop()


async def test_a_lane_quarantined_while_the_pass_waits_gets_no_sample(tmp_path: Path) -> None:
    bus, sink = Bus(), RecordingSink()
    s = _set(tmp_path, bus, sink)
    await s.register(M1, SYM, "a")
    await _publish(bus, s, trade(T0 + 1, seq=1), trade(T0 + 2, seq=2))
    lane = s._lanes[SYM]
    real_locked = lane.lock.locked
    lane.lock.locked = lambda: False  # type: ignore[method-assign]  # pass reaches the wait
    async with lane.lock:
        task = asyncio.ensure_future(s.sample())
        for _ in range(20):
            await asyncio.sleep(0)
        assert not task.done()
        s._on_lane_death(lane)  # the lane dies while the pass waits for the lock
    await task
    lane.lock.locked = real_locked  # type: ignore[method-assign]
    assert _sampled(sink, M1) == []
    await s.stop()


async def test_stop_routes_a_final_sample_for_a_bar_the_drain_changed(tmp_path: Path) -> None:
    bus, sink, periods = Bus(), RecordingSink(), Periods()
    s = _set(tmp_path, bus, sink, sleep=periods)
    await s.register(M1, SYM, "a")
    await s.start()
    await _publish(bus, s, trade(T0 + 1, seq=1))  # opens the bar
    await periods.release()
    lane = s._lanes[SYM]
    assert lane.task is not None
    lane.task.cancel()  # the lane loop is gone: what the bus delivers now waits for stop()
    await asyncio.gather(lane.task, return_exceptions=True)
    for i in (2, 3):
        await bus.publish(TOPIC, trade(T0 + i, seq=i))
    assert lane.sub.qsize() == 2
    assert _sampled(sink, M1) == []  # the open is routed as built; nothing sampled yet
    await s.stop()
    assert _sampled(sink, M1) == [3]  # the drain's changes are routed before the final blobs


async def test_a_restored_series_routes_no_sample_mid_catch_up_then_its_forming_bar(
    tmp_path: Path,
) -> None:
    trades = [trade(T0 + i, qty="1", seq=i) for i in range(4)]
    bus1, sink1 = Bus(), RecordingSink()
    s1 = _set(tmp_path, bus1, sink1)
    await s1.register(V5, SYM, "a")
    await _publish(bus1, s1, *trades[:2])
    await s1.stop()  # final blob: the forming bar after 2 trades, watermark at trade 1
    bus2, sink2 = Bus(), RecordingSink()
    s2 = _set(tmp_path, bus2, sink2, tape=FakeTape(trades))
    await s2.register(V5, SYM, "a")  # replays trades 2 and 3, which only extend the bar
    assert sink2.seen == []
    await s2.sample()
    assert _kinds(sink2, V5) == [("update", 0)] and _sampled(sink2, V5) == [4]
    await s2.stop()


class _Faulty(TickBarBuilder):
    def forming(self) -> BarUpdate | None:
        raise RuntimeError("forming failed")


async def test_a_builder_whose_forming_raises_is_quarantined(tmp_path: Path) -> None:
    bus, sink = Bus(), RecordingSink()
    s = _set(tmp_path, bus, sink, factory=lambda spec, sym: _Faulty(spec, sym))
    await s.register(T3, SYM, "a")
    await _publish(bus, s, trade(T0, seq=1), trade(T0 + 1, seq=2))
    await s.sample()
    assert s.quarantined(SYM, T3.spec_hash) and s.active(SYM) == ()
    assert BarsHealthReason.BUILDER_QUARANTINED in s.health_reasons()
    await s.stop()


async def test_a_failed_sampling_pass_is_reported_and_the_sampler_survives(
    tmp_path: Path,
) -> None:
    bus, sink, periods = Bus(), RecordingSink(), Periods()
    s = _set(tmp_path, bus, sink, sleep=periods)
    real, calls = s.sample, [0]

    async def flaky() -> None:
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("one bad pass")
        await real()

    s.sample = flaky  # type: ignore[method-assign]  # inject one failing pass
    await s.register(M1, SYM, "a")
    await s.start()
    await _publish(bus, s, trade(T0 + 1, seq=1), trade(T0 + 2, seq=2))
    await periods.release()
    assert BarsHealthReason.TASK_FAILED in s.health_reasons() and _sampled(sink, M1) == []
    await periods.release()
    assert _sampled(sink, M1) == [2]
    await s.stop()

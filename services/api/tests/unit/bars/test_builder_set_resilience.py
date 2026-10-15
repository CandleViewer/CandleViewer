"""Adversarial review fixes on PR #2030: builder/task failure isolation (A), bounded sink
waits (B), tape-lag BI-5 gap (C), shutdown races (9)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from candleviewer.bars import builder_set
from candleviewer.bars.builder_set import BarBuilderSet, BarsHealthReason, default_factory
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.errors import BarsError, BarServiceStopping
from candleviewer.bars.metrics import (
    bar_builder_quarantined_total,
    bar_emit_sink_errors_total,
    bars_restore_gap_total,
)
from candleviewer.bars.models import BarBuilder, BarSpec
from candleviewer.bars.service import BarsService
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.observability.health import HealthStatus

from ._set_harness import M1, T3, TOPIC, V5, Clock, FakeTape, RecordingSink, make_set, settle
from ._trades import SYM, trade, us

T0 = us("10:00:00")
BOOM = BarSpec(kind="tick", tick_count=777)


def _count(metric: Any, reason: str) -> float:
    return float(metric.labels(reason=reason)._value.get())


def _exploding_factory(spec: BarSpec, symbol: str) -> BarBuilder:
    b = default_factory(spec, symbol)
    if spec == BOOM:
        real = b.on_trade

        def on_trade(t: Any) -> Any:
            if t.seq == 3:
                raise BarsError("builder defect")
            return real(t)

        b.on_trade = on_trade  # type: ignore[method-assign]  # inject a mid-stream fault
    return b


def _set(tmp_path: Path, bus: Bus, sinks: list[Any]) -> BarBuilderSet:
    s = make_set(tmp_path, bus=bus, sinks=sinks)
    s._factory = _exploding_factory
    return s


async def test_builder_exception_quarantines_spec_others_keep_flowing(tmp_path: Path) -> None:
    bus, sink = Bus(), RecordingSink()
    s = _set(tmp_path, bus, [sink])
    before = _count(bar_builder_quarantined_total, "builder_error")
    await s.register(BOOM, SYM, "a")
    await s.register(T3, SYM, "b")
    for i in range(9):
        await bus.publish(TOPIC, trade(T0 + i, seq=i))
    await settle(bus, s)
    assert s.active(SYM) == (T3.spec_hash,)
    t3_closes = [i for h, _, k, i, _ in sink.seen if h == T3.spec_hash and k == "close"]
    assert t3_closes == [0, 1, 2]  # every trade after the fault still reached T3
    assert BarsHealthReason.BUILDER_QUARANTINED in s.health_reasons()
    assert _count(bar_builder_quarantined_total, "builder_error") == before + 1
    await s.stop()


async def test_dead_lane_task_unsubscribes_so_publisher_never_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder_set, "LANE_QUEUE", 2)
    bus = Bus()
    s = make_set(tmp_path, bus=bus)
    await s.register(T3, SYM, "a")
    lane = s._lanes[SYM]

    async def die(_: Any, __: Any) -> None:
        raise RuntimeError("lane defect outside builder isolation")

    monkeypatch.setattr(s, "_apply", die)
    await bus.publish(TOPIC, trade(T0, seq=0))
    for _ in range(50):
        await asyncio.sleep(0)
    assert lane.task is not None and lane.task.done()
    assert lane.sub not in bus._subscriptions
    # were the dead lane still subscribed, a queue of 2 would block these publishes forever
    await asyncio.wait_for(
        asyncio.gather(*(bus.publish(TOPIC, trade(T0 + i, seq=i)) for i in range(1, 50))), 5
    )
    assert BarsHealthReason.TASK_FAILED in s.health_reasons()
    await s.stop()


async def test_ticker_survives_a_failing_tick(tmp_path: Path) -> None:
    calls = 0
    ticked = asyncio.Event()

    async def fake_sleep(_: float) -> None:
        await asyncio.sleep(0)

    s = make_set(tmp_path)
    s._sleep = fake_sleep

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BarsError("bad tick")
        ticked.set()

    s.tick = flaky  # type: ignore[method-assign]  # inject a failing first tick
    await s.start()
    await asyncio.wait_for(ticked.wait(), 5)
    assert BarsHealthReason.TASK_FAILED in s.health_reasons()
    await s.stop()


async def test_on_clock_failure_quarantines_only_that_spec(tmp_path: Path) -> None:
    s = make_set(tmp_path, clock=Clock(T0))
    await s.register(M1, SYM, "a")
    await s.register(T3, SYM, "b")
    m1 = next(e for e in s._lanes[SYM].entries if e.spec == M1)

    def bad_clock(now: int) -> Any:
        raise ValueError("clock defect")

    m1.builder.on_clock = bad_clock  # type: ignore[method-assign,assignment]  # inject a fault
    await s.tick()
    assert s.active(SYM) == (T3.spec_hash,)
    await s.stop()


async def test_hung_sink_times_out_counts_and_degrades_without_stalling(tmp_path: Path) -> None:
    class Hung:
        name = "ws"

        async def emit(self, emission: Any) -> None:
            await asyncio.Event().wait()

    bus, rec = Bus(), RecordingSink("questdb")
    s = make_set(tmp_path, bus=bus)
    s._router = EmitRouter([Hung(), rec], timeout_s=0.01)
    svc = BarsService()
    svc.attach(s)
    await svc.start(None)  # type: ignore[arg-type]  # ctx unused by start()
    before = _count(bar_emit_sink_errors_total, "ws_timeout")
    await s.register(T3, SYM, "a")
    for i in range(3):
        await bus.publish(TOPIC, trade(T0 + i, seq=i))
    for _ in range(500):  # event-driven wait: real asyncio.timeout fires, no fixed sleep
        if len(rec.seen) == 3:
            break
        await asyncio.sleep(0.005)
    assert len(rec.seen) == 3  # the other sink was fed despite the hung one
    assert _count(bar_emit_sink_errors_total, "ws_timeout") == before + 3
    report = svc.health()
    assert report.status is HealthStatus.DEGRADED and "bar_emit_sink_timeout" in report.detail
    await svc.stop(1.0)


async def test_restore_with_lagging_tape_catches_up_from_lane_ring(tmp_path: Path) -> None:
    """A trade the lane applied but the async writer has not landed on the tape must still
    reach a series restored after it (BI-5 across the replay/live boundary)."""
    trades = [trade(T0 + i * 1000, px=str(100 + i), seq=i) for i in range(12)]
    ref_bus, ref_sink = Bus(), RecordingSink()
    ref = make_set(tmp_path / "ref", bus=ref_bus, sinks=[ref_sink])
    await ref.register(V5, SYM, "r")
    for t in trades:
        await ref_bus.publish(TOPIC, t)
    await settle(ref_bus, ref)
    await ref.stop()

    root = tmp_path / "live"
    b1 = Bus()
    s1 = make_set(root, bus=b1)
    await s1.register(V5, SYM, "a")
    for t in trades[:4]:
        await b1.publish(TOPIC, t)
    await settle(b1, s1)
    await s1.stop()  # blob watermark = trade 3

    bus2, sink = Bus(), RecordingSink()
    tape = FakeTape(trades[:6])  # lags: trades 6..8 applied by the lane, not on the tape
    s2 = make_set(root, bus=bus2, sinks=[sink], tape=tape)
    await s2.register(T3, SYM, "keeps-lane-alive")
    for t in trades[4:9]:
        await bus2.publish(TOPIC, t)
    await settle(bus2, s2)
    await s2.register(V5, SYM, "late")  # needs 4..8; the tape holds only 4..5
    for t in trades[9:]:
        await bus2.publish(TOPIC, t)
    await settle(bus2, s2)
    await s2.stop()
    got = [u for u in sink.seen if u[0] == V5.spec_hash]
    want = [u for u in ref_sink.seen if u[0] == V5.spec_hash]
    assert got == want[-len(got) :]  # the restored tail is exactly the uninterrupted tail
    assert got[-1] == want[-1]


async def test_register_refused_once_stopping(tmp_path: Path) -> None:
    s = make_set(tmp_path)
    await s.stop()
    with pytest.raises(BarServiceStopping, match="shutting down"):  # retryable, not invalid
        await s.register(T3, SYM, "late")
    assert s._lanes == {}


async def test_stop_applies_trades_from_publishers_blocked_on_full_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder_set, "LANE_QUEUE", 2)
    bus, sink = Bus(), RecordingSink(delay=50)
    s = make_set(tmp_path, bus=bus, sinks=[sink])
    await s.register(BarSpec(kind="tick", tick_count=1), SYM, "a")
    pubs = [asyncio.ensure_future(bus.publish(TOPIC, trade(T0 + i, seq=i))) for i in range(10)]
    await asyncio.sleep(0)
    await s.stop()
    await asyncio.wait_for(asyncio.gather(*pubs), 5)  # no publisher left blocked
    closes = [i for _, _, k, i, _ in sink.seen if k == "close"]
    # everything admitted before the unsubscribe was applied, in order, none twice
    assert closes == list(range(len(closes))) and len(closes) >= 2


async def test_lane_death_releases_publisher_already_blocked_on_full_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review re-verdict A: a publisher parked in `queue.put` before the lane dies must be
    released, or every other subscriber of the topic starves."""
    monkeypatch.setattr(builder_set, "LANE_QUEUE", 2)
    bus = Bus()
    other = bus.subscribe("other", TOPIC.key, QueuePolicy.NEVER_DROP, maxsize=100)
    s = make_set(tmp_path, bus=bus)
    await s.register(T3, SYM, "a")
    lane = s._lanes[SYM]
    gate = asyncio.Event()

    async def stuck_then_die(_: Any, __: Any) -> None:
        await gate.wait()
        raise RuntimeError("lane defect")

    monkeypatch.setattr(s, "_apply", stuck_then_die)
    for i in range(3):  # 1 taken by the stuck lane, 2 fill the queue
        await bus.publish(TOPIC, trade(T0 + i, seq=i))
    blocked = asyncio.ensure_future(bus.publish(TOPIC, trade(T0 + 9, seq=9)))
    for _ in range(20):
        await asyncio.sleep(0)
    assert not blocked.done() and lane.sub.queue.full()  # parked in put before the death
    gate.set()  # lane dies now
    await asyncio.wait_for(blocked, 1)  # released promptly by the drain
    await bus.publish(TOPIC, trade(T0 + 10, seq=10))  # the topic flows for others
    assert other.qsize() == 5
    assert BarsHealthReason.TASK_FAILED in s.health_reasons()
    assert SYM not in s._lanes
    await s.stop()


async def test_restore_gap_beyond_ring_is_counted_and_degrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review re-verdict C: tape lag larger than the ring is detected, never silent."""
    monkeypatch.setattr(builder_set, "RECENT_RING", 4)
    trades = [trade(T0 + i * 1000, seq=i) for i in range(20)]
    b1 = Bus()
    s1 = make_set(tmp_path, bus=b1)
    await s1.register(V5, SYM, "a")
    for t in trades[:3]:
        await b1.publish(TOPIC, t)
    await settle(b1, s1)
    await s1.stop()  # watermark = trade 2

    bus2 = Bus()
    s2 = make_set(tmp_path, bus=bus2, tape=FakeTape(trades[:5]))  # tape ends at trade 4
    await s2.register(T3, SYM, "lane")
    for t in trades[3:15]:  # lane applies 3..14; ring (4) keeps only 11..14
        await bus2.publish(TOPIC, t)
    await settle(bus2, s2)
    before = bars_restore_gap_total._value.get()
    await s2.register(V5, SYM, "late")  # trades 5..10 are on neither tape nor ring
    assert bars_restore_gap_total._value.get() == before + 1
    assert BarsHealthReason.RESTORE_GAP in s2.health_reasons()
    await s2.stop()


async def test_restore_without_gap_does_not_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder_set, "RECENT_RING", 4)
    trades = [trade(T0 + i * 1000, seq=i) for i in range(12)]
    b1 = Bus()
    s1 = make_set(tmp_path, bus=b1)
    await s1.register(V5, SYM, "a")
    for t in trades[:3]:
        await b1.publish(TOPIC, t)
    await settle(b1, s1)
    await s1.stop()
    bus2 = Bus()
    s2 = make_set(tmp_path, bus=bus2, tape=FakeTape(trades[:9]))  # tape covers up to the ring
    await s2.register(T3, SYM, "lane")
    for t in trades[3:12]:
        await bus2.publish(TOPIC, t)
    await settle(bus2, s2)
    await s2.register(V5, SYM, "late")
    assert BarsHealthReason.RESTORE_GAP not in s2.health_reasons()
    await s2.stop()

"""`BarBuilderSet` fan-out, leases, caps, emit path, backpressure, stop (E12-T03)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from candleviewer.bars import builder_set, emit
from candleviewer.bars.builder_set import BarBuilderSet, default_factory
from candleviewer.bars.emit import EmitRouter, WriterSink
from candleviewer.bars.errors import BarSpecError, SpecCapExceeded
from candleviewer.bars.leases import SpecCaps
from candleviewer.bars.models import BarSpec, BuilderState
from candleviewer.bus.bus import Bus

from ._set_harness import H1, M1, T3, TOPIC, V5, Clock, FakeWriter, RecordingSink, make_set, settle
from ._trades import SYM, trade, us

T0 = us("10:00:00")


def _specs(n: int) -> list[BarSpec]:
    return [BarSpec(kind="tick", tick_count=100 + i) for i in range(n)]


async def test_set_eight_specs_one_subscription_every_builder_advanced(tmp_path: Path) -> None:
    bus, sink = Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[sink])
    for i, spec in enumerate(_specs(8)):
        await s.register(spec, SYM, f"c{i}")
    assert len(bus._subscriptions) == 1  # one bus read per trade, no per-builder subscription
    await bus.publish(TOPIC, trade(T0, seq=1))
    await settle(bus, s)
    assert sorted(h for h, *_ in sink.seen) == sorted(sp.spec_hash for sp in _specs(8))
    await s.stop()


async def test_set_delivers_every_trade_once_in_order(tmp_path: Path) -> None:
    bus, sink = Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[sink])
    await s.register(T3, SYM, "a")
    for i in range(9):
        await bus.publish(TOPIC, trade(T0 + i, px=str(100 + i), seq=i))
    await settle(bus, s)
    closes = [(idx, px) for _, _, k, idx, px in sink.seen if k == "close"]
    assert closes == [(0, "102"), (1, "105"), (2, "108")]
    await s.stop()


async def test_set_register_mid_stream_sees_only_later_trades(tmp_path: Path) -> None:
    bus, sink = Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[sink])
    await s.register(T3, SYM, "a")
    for i in range(3):
        await bus.publish(TOPIC, trade(T0 + i, seq=i))
    await settle(bus, s)
    await s.register(V5, SYM, "b")
    for i in range(3, 5):
        await bus.publish(TOPIC, trade(T0 + i, qty="2", seq=i))
    await settle(bus, s)
    vol = [u for u in sink.seen if u[0] == V5.spec_hash]
    assert [k for _, _, k, _, _ in vol] == ["open", "update"]  # 2 trades, 4 < 5 qty
    t3 = [u for u in sink.seen if u[0] == T3.spec_hash and u[2] == "close"]
    assert len(t3) == 1  # nothing dropped for the existing spec while registering
    await s.stop()


async def test_set_release_tears_down_after_grace_with_final_blob(tmp_path: Path) -> None:
    clock, bus = Clock(T0), Bus()
    s = make_set(tmp_path, bus=bus, clock=clock)
    await s.register(V5, SYM, "chart-1", user="u1")
    await bus.publish(TOPIC, trade(T0, seq=1))
    await settle(bus, s)
    s.release(V5.spec_hash, SYM, "chart-1")
    clock.t = T0 + 29_999_999
    await s.tick()
    assert s.active(SYM) == (V5.spec_hash,)
    clock.t = T0 + 30_000_000
    await s.tick()
    assert s.active(SYM) == ()
    assert bus._subscriptions == []
    assert (tmp_path / SYM / f"{V5.spec_hash}.state.json").exists()
    await s.stop()


async def test_set_reacquire_within_grace_keeps_series(tmp_path: Path) -> None:
    clock = Clock(T0)
    s = make_set(tmp_path, clock=clock)
    await s.register(V5, SYM, "a")
    s.release(V5.spec_hash, SYM, "a")
    clock.t += 10_000_000
    await s.register(V5, SYM, "b")
    clock.t += 60_000_000
    await s.tick()
    assert s.active(SYM) == (V5.spec_hash,)
    await s.stop()


async def test_set_liveness_sweep_releases_vanished_consumer(tmp_path: Path) -> None:
    clock = Clock(T0)
    s = make_set(tmp_path, clock=clock)
    await s.register(V5, SYM, "ghost")
    await s.register(T3, SYM, "ghost")
    s.release_consumer("ghost")
    clock.t += 30_000_000
    await s.tick()
    assert s.active(SYM) == ()
    await s.stop()


async def test_set_per_symbol_cap_refuses_naming_cap_and_active(tmp_path: Path) -> None:
    bus, sink = Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[sink], caps=SpecCaps(per_symbol=2))
    await s.register(M1, SYM, "a")
    await s.register(H1, SYM, "b")
    with pytest.raises(SpecCapExceeded) as ei:
        await s.register(T3, SYM, "c")
    assert ei.value.code == "spec_cap_exceeded" and ei.value.cap == "per-symbol"
    assert "limit of 2" in str(ei.value) and "(2 active)" in str(ei.value)
    assert M1.spec_hash not in str(ei.value) and H1.spec_hash not in str(ei.value)
    await s.register(M1, SYM, "d")  # joining an existing series is not a new one
    await bus.publish(TOPIC, trade(T0, seq=1))
    await settle(bus, s)
    assert {h for h, *_ in sink.seen} == {M1.spec_hash, H1.spec_hash}
    await s.stop()


async def test_set_per_user_and_global_caps(tmp_path: Path) -> None:
    s = make_set(tmp_path, caps=SpecCaps(per_user=1, global_=2))
    await s.register(M1, SYM, "a", user="u1")
    await s.register(M1, SYM, "a2", user="u1")  # same series twice: still one
    with pytest.raises(SpecCapExceeded, match="per-user"):
        await s.register(H1, SYM, "b", user="u1")
    await s.register(H1, SYM, "rec", user=None)  # system consumer: no user cap
    with pytest.raises(SpecCapExceeded, match="process-wide"):
        await s.register(T3, "ETHUSDT", "c", user="u2")
    assert "ETHUSDT" not in s._lanes
    await s.stop()


def test_cap_error_message_truncates_long_own_list() -> None:
    err = SpecCapExceeded("per-user", 32, 20, tuple(f"h{i}" for i in range(20)))
    assert "and more" in str(err) and "h8" not in str(err)
    assert "try again later" in str(SpecCapExceeded("process-wide", 512, 512))


async def test_set_unbuildable_kind_refused_and_lease_rolled_back(tmp_path: Path) -> None:
    s = make_set(tmp_path)
    rng = BarSpec(kind="range", range_ticks=10)
    with pytest.raises(BarSpecError):
        await s.register(rng, SYM, "a")
    assert s._leases.keys() == ()
    assert s._lanes == {}
    with pytest.raises(BarSpecError):
        default_factory(BarSpec(kind="renko", range_ticks=4), SYM)
    await s.stop()


async def test_set_writer_and_ws_sinks_get_one_sequence(tmp_path: Path) -> None:
    bus, ws, writer = Bus(), RecordingSink(), FakeWriter()
    s = make_set(tmp_path, bus=bus, sinks=[WriterSink(writer), ws], clock=Clock(T0))
    await s.register(T3, SYM, "a")
    for i in range(7):
        await bus.publish(TOPIC, trade(T0 + i, seq=i))
    await settle(bus, s)
    assert {g for _, g, *_ in ws.seen} == {T0 // 1000}  # the cold-start time in ms is stamped
    ws_closes = [(h, idx) for h, _, k, idx, _ in ws.seen if k == "close"]
    assert (
        [(h, i) for h, i, _ in writer.rows] == ws_closes == [(T3.spec_hash, 0), (T3.spec_hash, 1)]
    )
    assert writer.generations == [g for _, g, k, *_ in ws.seen if k == "close"]  # same epoch
    await s.stop()


async def test_set_failing_sink_counted_others_still_fed(tmp_path: Path) -> None:
    class Boom:
        name = "boom"

        async def emit(self, emission: object) -> None:
            raise RuntimeError("down")

    bus, ws = Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[Boom(), ws])
    await s.register(T3, SYM, "a")
    await bus.publish(TOPIC, trade(T0, seq=1))
    await settle(bus, s)
    assert len(ws.seen) == 1
    await s.stop()


async def test_set_slow_sink_backpressures_without_drop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder_set, "LANE_QUEUE", 2)  # tiny queue: publish must await
    bus, slow = Bus(), RecordingSink(delay=20)
    s = make_set(tmp_path, bus=bus, sinks=[slow])
    await s.register(BarSpec(kind="tick", tick_count=1), SYM, "a")
    assert s._lanes[SYM].sub.maxsize == 2
    await asyncio.gather(*(bus.publish(TOPIC, trade(T0 + i, seq=i)) for i in range(30)))
    await settle(bus, s)
    assert [idx for _, _, k, idx, _ in slow.seen if k == "close"] == list(range(30))
    await s.stop()


async def test_set_stop_applies_queued_trades_and_leaves_no_tasks(tmp_path: Path) -> None:
    before = asyncio.all_tasks()
    bus, sink = Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[sink])
    await s.start()
    await s.start()  # idempotent
    await s.register(BarSpec(kind="tick", tick_count=1), SYM, "a")
    for i in range(5):
        await bus.publish(TOPIC, trade(T0 + i, seq=i))
    await s.stop()  # no settle: stop must drain what the bus already queued
    assert len([u for u in sink.seen if u[2] == "close"]) == 5
    assert asyncio.all_tasks() - before == set()
    assert bus._subscriptions == []


async def test_set_ticker_drives_clock_closes(tmp_path: Path) -> None:
    clock, bus, sink = Clock(T0), Bus(), RecordingSink()
    ticks = asyncio.Event()

    async def fake_sleep(_: float) -> None:
        ticks.set()
        await asyncio.sleep(0)

    s = BarBuilderSet(
        bus, "demo", EmitRouter([sink]), make_set(tmp_path)._store, now_us=clock, sleep=fake_sleep
    )
    await s.register(M1, SYM, "a")
    await bus.publish(TOPIC, trade(T0 + 1, seq=1))
    await settle(bus, s)
    clock.t = T0 + 60_000_000
    await s.start()
    await ticks.wait()
    await settle(bus, s)
    await s.stop()
    assert ("close", 0) in [(k, i) for _, _, k, i, _ in sink.seen]


async def test_set_fanout_loop_allocates_nothing_per_spec(tmp_path: Path) -> None:
    """§3.5 scope (narrowed per review): the set's fan-out loop itself (builder_set + emit)
    retains nothing per trade x spec once its bounded catch-up ring is full. Builders and
    each *emitted* update still allocate (a `BarEmission`, the `Bar`); that cost is per
    emission, not per spec, and is measured by the E12-T04 bench."""
    import tracemalloc

    class Quiet:
        def __init__(self, spec: BarSpec, symbol: str) -> None:
            self.spec = spec

        def on_trade(self, t: object) -> tuple[()]:
            return ()

        def on_clock(self, now_us: int) -> tuple[()]:
            return ()

        def snapshot(self) -> BuilderState:
            return BuilderState(
                spec_hash=self.spec.spec_hash, symbol=SYM, state_version=1, blob=b"{}"
            )

        def restore(self, state: object) -> None:
            raise AssertionError("no blob in this test")

    s = BarBuilderSet(
        Bus(),
        "demo",
        EmitRouter([]),
        make_set(tmp_path)._store,
        now_us=Clock(),
        factory=Quiet,  # Quiet satisfies BarBuilder structurally
    )
    for spec in _specs(8):
        await s.register(spec, SYM, "a")
    lane = s._lanes[SYM]
    warm = builder_set.RECENT_RING + 10  # fill the bounded catch-up ring first
    trades = [trade(T0 + i, seq=i) for i in range(warm + 2_000)]
    for t in trades[:warm]:
        await s._apply(lane, t)  # warm-up (metric children, ring at capacity)
    tracemalloc.start()
    snap0 = tracemalloc.take_snapshot()
    for t in trades[warm:]:
        await s._apply(lane, t)
    snap1 = tracemalloc.take_snapshot()
    tracemalloc.stop()
    flt = [tracemalloc.Filter(True, builder_set.__file__), tracemalloc.Filter(True, emit.__file__)]
    grown = sum(
        d.size_diff for d in snap1.filter_traces(flt).compare_to(snap0.filter_traces(flt), "lineno")
    )
    assert grown < 1_024  # bounded: no per-trade growth across 2 000 trades x 8 specs
    await s.stop()

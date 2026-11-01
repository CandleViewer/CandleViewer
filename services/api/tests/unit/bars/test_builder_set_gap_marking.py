"""An unrecovered tape gap marks the next bar of every builder `gap_before` (#529, E12-Q06).

`TradeStream` publishes a `GapEvent` on `{env}.md.{sym}.gap` before the window's merged prints.
Recovered: the backfill is merged in order, so the tape is complete and nothing is flagged.
Unrecovered: the one bar that follows the hole carries `gap_before=True` on every update, once.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.bars.builder_set import BarBuilderSet, TapeGap, production_factory
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.metrics import bars_gap_detected_total
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.state_store import StateStore
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.domain.events import uuid7
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.ingestion.trade_stream import GapEvent

from ._set_harness import ENV, TOPIC, V5, Clock, FakeTape, RecordingSink, make_set, settle
from ._trades import SYM, trade, us

T0 = us("10:00:00")
GAP_TOPIC = Topic(env=ENV, domain="md", symbol=SYM, detail="gap")
SPECS = {
    "time": BarSpec(kind="time", interval_ms=60_000),
    "tick": BarSpec(kind="tick", tick_count=3),
    "volume": V5,
    "range": BarSpec(kind="range", range_ticks=2),
    "delta": BarSpec(kind="delta", delta_threshold=Decimal(3)),
    "renko": BarSpec(kind="renko", range_ticks=2),
}
PRE = 3  # prints before the hole
POST = 14  # prints after it, enough to close several bars of every kind


def _tape() -> list[TradeEvent]:
    """Rising by one tick per print, 8 s apart, so every kind closes bars across the hole."""
    return [
        trade(T0 + 8_000_000 * i, px=str(Decimal("100") + Decimal("0.01") * i), qty="2", seq=i)
        for i in range(PRE + POST)
    ]


def _gap(recovered: bool, symbol: str = SYM, start_us: int = T0 + 16_000_000) -> GapEvent:
    return GapEvent(
        event_id=EventId(uuid7(T0 // 1000)),
        ts_event=T0 + 20_000_000,
        ts_ingest=T0 + 20_000_000,
        source="live",
        symbol=symbol,
        start_us=start_us,
        end_us=T0 + 20_000_000,
        recovered=recovered,
        reason="reconnect",
    )


def _count(recovered: bool) -> float:
    return float(
        bars_gap_detected_total.labels(
            reason="recovered" if recovered else "unrecovered"
        )._value.get()
    )


def _make(tmp_path: Path, bus: Bus, sink: RecordingSink, **kw: object) -> BarBuilderSet:
    s = make_set(tmp_path, bus=bus, sinks=[sink], **kw)  # type: ignore[arg-type]  # test kwargs
    s._factory = production_factory(lambda _s: Decimal("0.01"), renko_enabled=True)
    return s


def _by_spec(sink: RecordingSink) -> dict[str, list[tuple[str, Bar]]]:
    out: dict[str, list[tuple[str, Bar]]] = {}
    for h, kind, bar in sink.bars:
        out.setdefault(h, []).append((kind, bar))
    return out


async def _run(
    tmp_path: Path, gap: GapEvent | None, *, specs: Sequence[BarSpec] = tuple(SPECS.values())
) -> tuple[RecordingSink, dict[str, int]]:
    """Pre-hole prints, the gap (if any), then post-hole prints. Returns the sink and, per spec,
    how many updates it had seen when the hole opened."""
    bus, sink = Bus(), RecordingSink()
    s = _make(tmp_path, bus, sink)
    for i, spec in enumerate(specs):
        await s.register(spec, SYM, f"c{i}")
    tape = _tape()
    for t in tape[:PRE]:
        await bus.publish(TOPIC, t)
    await settle(bus, s)
    before = {h: len(v) for h, v in _by_spec(sink).items()}
    if gap is not None:
        await bus.publish(GAP_TOPIC, gap)
    for t in tape[PRE:]:
        await bus.publish(TOPIC, t)
    await settle(bus, s)
    await s.stop()
    return sink, before


def test_gap_event_satisfies_the_structural_protocol() -> None:
    assert isinstance(_gap(False), TapeGap)


@pytest.mark.parametrize("name", list(SPECS))
async def test_unrecovered_gap_flags_the_first_bar_after_the_hole_once(
    name: str, tmp_path: Path
) -> None:
    spec = SPECS[name]
    sink, before = await _run(tmp_path, _gap(False), specs=[spec])
    updates = _by_spec(sink)[spec.spec_hash]
    n_before = before.get(spec.spec_hash, 0)
    first_after = updates[n_before][1].index
    flagged = [b.index for _, b in updates if b.gap_before]
    assert flagged, f"{name}: no bar carries gap_before"
    assert set(flagged) == {first_after}  # exactly one bar...
    assert {b.index for _, b in updates} - {first_after}  # ...among several
    # every update of it after the hole (a bar open across the hole was emitted unflagged before)
    assert all(b.gap_before for _, b in updates[n_before:] if b.index == first_after)
    assert all(not b.gap_before for _, b in updates[:n_before])  # none before the hole


@pytest.mark.parametrize("name", list(SPECS))
async def test_no_gap_flags_nothing(name: str, tmp_path: Path) -> None:
    sink, _ = await _run(tmp_path, None, specs=[SPECS[name]])
    assert sink.bars and not any(b.gap_before for _, _, b in sink.bars)


async def test_unrecovered_gap_flags_every_builder_type_in_one_set(tmp_path: Path) -> None:
    sink, _ = await _run(tmp_path, _gap(False))
    per_spec = _by_spec(sink)
    assert set(per_spec) == {s.spec_hash for s in SPECS.values()}
    for spec_hash, updates in per_spec.items():
        assert len({b.index for _, b in updates if b.gap_before}) == 1, spec_hash


async def test_recovered_gap_flags_nothing_and_is_counted(tmp_path: Path) -> None:
    n = _count(True)
    sink, _ = await _run(tmp_path, _gap(True))
    assert sink.bars and not any(b.gap_before for _, _, b in sink.bars)
    assert _count(True) == n + 1


async def test_another_symbols_gap_flags_nothing(tmp_path: Path) -> None:
    n = _count(False)
    other = Topic(env=ENV, domain="md", symbol="ETHUSDT", detail="gap")
    bus, sink = Bus(), RecordingSink()
    s = _make(tmp_path, bus, sink)
    await s.register(V5, SYM, "a")
    tape = _tape()
    for t in tape[:PRE]:
        await bus.publish(TOPIC, t)
    await bus.publish(other, _gap(False, "ETHUSDT"))
    for t in tape[PRE:]:
        await bus.publish(TOPIC, t)
    await settle(bus, s)
    await s.stop()
    assert sink.bars and not any(b.gap_before for _, _, b in sink.bars)
    assert _count(False) == n


async def test_unrecovered_gap_increments_the_counter_without_a_trade(tmp_path: Path) -> None:
    n = _count(False)
    bus = Bus()
    s = _make(tmp_path, bus, RecordingSink())
    await s.register(V5, SYM, "a")
    await bus.publish(GAP_TOPIC, _gap(False))
    await settle(bus, s)
    assert _count(False) == n + 1  # by the gap task, not only at the next print
    await s.stop()


async def test_a_gap_queued_before_a_trade_flags_that_trade_even_if_the_gap_task_lags(
    tmp_path: Path,
) -> None:
    bus, sink = Bus(), RecordingSink()
    s = _make(tmp_path, bus, sink)
    await s.register(SPECS["tick"], SYM, "a")
    tape = _tape()
    await bus.publish(TOPIC, tape[0])
    await settle(bus, s)
    lane = s._lanes[SYM]
    lane.gap_task.cancel()  # type: ignore[union-attr]  # the lane has its gap task
    # queued; only `_apply`'s drain can consume it
    await bus.publish(GAP_TOPIC, _gap(False, start_us=tape[0].ts_event))
    await bus.publish(TOPIC, tape[1])
    await settle(bus, s)
    assert [b.gap_before for _, _, b in sink.bars] == [False, True]
    await s.stop()


async def test_restart_and_restore_do_not_reflag(tmp_path: Path) -> None:
    tape = _tape()
    bus1, sink1 = Bus(), RecordingSink()
    s1 = _make(tmp_path, bus1, sink1)
    await s1.register(V5, SYM, "a")
    for t in tape[:PRE]:
        await bus1.publish(TOPIC, t)
    await bus1.publish(GAP_TOPIC, _gap(False))
    await bus1.publish(TOPIC, tape[PRE])
    await settle(bus1, s1)
    assert any(b.gap_before for _, _, b in sink1.bars)  # flagged once, before the stop
    await s1.stop()
    bus2, sink2 = Bus(), RecordingSink()
    s2 = BarBuilderSet(
        bus2,
        ENV,
        EmitRouter([sink2]),
        StateStore(tmp_path),
        tape=FakeTape(tape[: PRE + 1]),
        now_us=Clock(T0),
    )
    await s2.register(V5, SYM, "a")  # restores the blob, replays the tape after the watermark
    for t in tape[PRE + 1 :]:
        await bus2.publish(TOPIC, t)
    await settle(bus2, s2)
    await s2.stop()
    # only the bar that was flagged before the stop (still open, restored with its flag) may be
    flagged_before = {b.index for _, _, b in sink1.bars if b.gap_before}
    assert sink2.bars and {b.index for _, _, b in sink2.bars if b.gap_before} <= flagged_before


async def test_unsubscribing_a_lane_drops_both_of_its_subscriptions(
    tmp_path: Path,
) -> None:
    bus = Bus()
    s = _make(tmp_path, bus, RecordingSink())
    await s.register(V5, SYM, "a")
    lane = s._lanes[SYM]
    s._unsubscribe(lane)
    assert lane.sub not in bus._subscriptions and lane.gap_sub not in bus._subscriptions
    await s.stop()


async def test_the_clock_close_of_the_flagged_time_bar_keeps_the_flag(tmp_path: Path) -> None:
    clock, bus, sink = Clock(T0), Bus(), RecordingSink()
    s = _make(tmp_path, bus, sink, clock=clock)
    spec = SPECS["time"]
    await s.register(spec, SYM, "a")
    await bus.publish(TOPIC, trade(T0 + 1_000_000, seq=1))
    await settle(bus, s)
    await bus.publish(GAP_TOPIC, _gap(False))
    await bus.publish(TOPIC, trade(T0 + 20_000_000, seq=2))  # first print after the hole
    await settle(bus, s)
    clock.t = T0 + 61_000_000
    await s.tick()  # the sparse tape: the clock closes the bar
    closes = [b for _, k, b in sink.bars if k == "close"]
    assert [(b.index, b.gap_before) for b in closes] == [(0, True)]
    await s.stop()


async def test_a_clock_close_before_any_post_hole_trade_leaves_the_next_bar_flagged(
    tmp_path: Path,
) -> None:
    clock, bus, sink = Clock(T0), Bus(), RecordingSink()
    s = _make(tmp_path, bus, sink, clock=clock)
    await s.register(SPECS["time"], SYM, "a")
    await bus.publish(TOPIC, trade(T0 + 1_000_000, seq=1))
    await settle(bus, s)
    await bus.publish(GAP_TOPIC, _gap(False))
    await settle(bus, s)
    clock.t = T0 + 61_000_000
    await s.tick()  # closes the pre-hole bar: it holds no post-hole trade
    await bus.publish(TOPIC, trade(T0 + 62_000_000, seq=2))
    await settle(bus, s)
    assert [(b.index, k, b.gap_before) for _, k, b in sink.bars] == [
        (0, "open", False),
        (0, "close", False),
        (1, "open", True),
    ]
    await s.stop()


async def test_stop_counts_a_gap_still_queued(tmp_path: Path) -> None:
    n = _count(False)
    bus = Bus()
    s = _make(tmp_path, bus, RecordingSink())
    await s.register(V5, SYM, "a")
    lane = s._lanes[SYM]
    lane.gap_task.cancel()  # type: ignore[union-attr]  # the lane has its gap task
    await bus.publish(GAP_TOPIC, _gap(False))
    await s.stop()
    assert _count(False) == n + 1


async def test_a_gap_whose_recovered_is_not_a_bool_is_ignored(tmp_path: Path) -> None:
    class Odd:
        symbol, recovered, start_us = SYM, "no", 0

    n = _count(False)
    s = _make(tmp_path, Bus(), RecordingSink())
    await s.register(V5, SYM, "a")
    s._on_gap(s._lanes[SYM], Odd())
    assert _count(False) == n
    await s.stop()


async def test_a_post_hole_print_amending_a_clock_closed_bar_flags_that_bar(tmp_path: Path) -> None:
    """The backfill outlasts the bar: the clock closes it, then the first live print amends it."""
    clock, bus, sink = Clock(T0), Bus(), RecordingSink()
    s = _make(tmp_path, bus, sink, clock=clock)
    await s.register(SPECS["time"], SYM, "a")
    await bus.publish(TOPIC, trade(T0 + 1_000_000, seq=1))
    await settle(bus, s)
    clock.t = T0 + 61_000_000
    await s.tick()  # closes bar 0 while the hole is still being backfilled
    await bus.publish(GAP_TOPIC, _gap(False))
    await bus.publish(TOPIC, trade(T0 + 50_000_000, seq=2))  # in bar 0, arrives late
    await settle(bus, s)
    assert [(b.index, k, b.gap_before) for _, k, b in sink.bars] == [
        (0, "open", False),
        (0, "close", False),
        (0, "close", True),  # the amended close
    ]
    await s.stop()


async def test_a_pre_hole_straggler_does_not_take_the_flag_the_post_hole_bar_does(
    tmp_path: Path,
) -> None:
    clock, bus, sink = Clock(T0), Bus(), RecordingSink()
    s = _make(tmp_path, bus, sink, clock=clock)
    await s.register(SPECS["time"], SYM, "a")
    await bus.publish(TOPIC, trade(T0 + 40_000_000, seq=1))  # the newest print before the hole
    await settle(bus, s)
    clock.t = T0 + 61_000_000
    await s.tick()  # bar 0 closed by the clock
    await bus.publish(GAP_TOPIC, _gap(False, start_us=T0 + 40_000_000))
    await bus.publish(TOPIC, trade(T0 + 10_000_000, seq=2))  # at or before start_us: amends bar 0
    await bus.publish(TOPIC, trade(T0 + 130_000_000, seq=3))  # the first post-hole print: bar 1
    await settle(bus, s)
    flags = [(b.index, k, b.gap_before) for _, k, b in sink.bars]
    assert flags == [
        (0, "open", False),
        (0, "close", False),
        (0, "close", False),  # the straggler's amendment: unflagged
        (1, "open", True),  # the post-hole bar, flagged once
    ]
    await s.stop()


async def test_a_gap_whose_start_us_is_not_an_int_is_ignored(tmp_path: Path) -> None:
    class Odd:
        symbol, recovered, start_us = SYM, False, "soon"

    n = _count(False)
    s = _make(tmp_path, Bus(), RecordingSink())
    await s.register(V5, SYM, "a")
    s._on_gap(s._lanes[SYM], Odd())
    assert _count(False) == n
    await s.stop()

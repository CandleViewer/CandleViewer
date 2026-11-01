"""Scenario 3 - out-of-order and duplicate prints. C-13.6 #3 (sequence gap / out-of-order / dup).

Declared (E12-Q06 AC; BQ-10): duplicates are suppressed upstream (`TradeStream`'s trade-id
ring), never by the builders, so a duplicated wire frame leaves the bars equal to the golden.
A reordered pair of frames reaches the builders swapped: a late print amends the time bar that
closed less than 60 s ago (`amended`), is folded into the open bar of a volume series, and is
dropped, counted and logged once it is older than the 60 s window. Volume is conserved in every
case, except the prints the builder reports as dropped.

Negative control: with `TradeStream`'s ring replaced by one that remembers nothing, a duplicated
frame reaches the builders and is counted twice by the volume, tick, range and renko folds, and
the conservation helper fails on each.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from structlog.testing import capture_logs

from bench.bar_conformance import runner
from bench.bar_determinism import tapes
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.time_builder import bars_amended_total, bars_late_trade_dropped_total
from candleviewer.bus.models import Topic
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.ingestion import trade_stream
from candleviewer.ingestion.metrics import trade_duplicates_suppressed_total
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._rig import SPECS, SYMBOL, TIME_5S, VOLUME_1, BarsRig
from tests.chaos.ingestion._clock import EPOCH_S
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

TOPIC = f"publicTrade.{SYMBOL}"
CONTROL_SPECS = {
    "vol:1": VOLUME_1,
    "tick:20": BarSpec(kind="tick", tick_count=20),
    "range:20": BarSpec(kind="range", range_ticks=20),
    "renko:30": BarSpec(kind="renko", range_ticks=30),
}
#: Frames land at 2.05 s + k * 0.5 s of each 5 s time bar: the pair at 4.55 s and 5.05 s
#: straddles a bar boundary (a frame's prints are stamped 5 ms before its envelope time).
PHASE_S = 2.05
FRAMES_BEFORE_PAIR_S = 2.5
BASE_US = round(EPOCH_S * 1_000_000)


@pytest.fixture
async def bars(rig: Rig) -> BarsRig:
    b = BarsRig(rig)
    await b.start()
    return b


async def _start_on_phase(rig: Rig, bars: BarsRig) -> Feeder:
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await rig.clock.advance((PHASE_S - rig.clock.wall_s() % 5.0) % 5.0)
    return Feeder(rig.ex)


def _print(offset_s: float, qty: str, trade_id: str) -> TradeEvent:
    ts = BASE_US + round(offset_s * 1_000_000)
    return tapes.event(0, ts, Decimal(100), Decimal(qty), "buy", SYMBOL, trade_id)


async def _publish(rig: Rig, *events: TradeEvent) -> None:
    topic = Topic(env=rig.env, domain="md", symbol=SYMBOL, detail="trade")
    for ev in events:
        await rig.bus.publish(topic, ev)
    await rig.clock.settle()


async def _expected(rig: Rig) -> dict[str, list[Bar]]:
    return await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)


async def test_s03_duplicated_frames_never_reach_the_bars(rig: Rig, bars: BarsRig) -> None:
    feed = await _start_on_phase(rig, bars)
    before = metric(trade_duplicates_suppressed_total, symbol=SYMBOL)
    await bars.run(feed, 3.0)
    rig.ex.inject(Fault(FaultKind.DUPLICATE, topic=TOPIC, count=4))
    await bars.run(feed, 12.0)
    await bars.finish()
    assert metric(trade_duplicates_suppressed_total, symbol=SYMBOL) >= before + 4
    expected = await _expected(rig)
    for label in SPECS:
        golden.assert_matches_golden(
            expected[label], bars.bars(label), label, kind=SPECS[label].kind
        )


async def test_s03_reordered_frames_amend_the_closed_time_bar(rig: Rig, bars: BarsRig) -> None:
    feed = await _start_on_phase(rig, bars)
    before = metric(bars_amended_total, symbol=SYMBOL)
    await bars.run(feed, FRAMES_BEFORE_PAIR_S)
    rig.ex.inject(Fault(FaultKind.REORDER, topic=TOPIC))
    await bars.run(feed, 12.0)
    await bars.finish()
    assert bars.amended("time:5s") >= 1, "the late frame did not amend the closed bar"
    assert metric(bars_amended_total, symbol=SYMBOL) >= before + 1
    expected = await _expected(rig)
    # The late prints are the last of their bar either way, so the amended bar is the golden's.
    golden.assert_matches_golden(expected["time:5s"], bars.bars("time:5s"), "time:5s", kind="time")
    golden.assert_monotonic(bars.bars("time:5s"), "time:5s")


async def test_s03_reordered_frames_conserve_volume_in_every_series(
    rig: Rig, bars: BarsRig
) -> None:
    feed = await _start_on_phase(rig, bars)
    await bars.run(feed, FRAMES_BEFORE_PAIR_S)
    rig.ex.inject(Fault(FaultKind.REORDER, topic=TOPIC))
    await bars.run(feed, 12.0)
    await bars.finish()
    expected = await _expected(rig)
    for label in SPECS:
        golden.assert_conserved(expected[label], bars.bars(label), label)
        golden.assert_monotonic(bars.bars(label), label)


async def test_s03_a_print_older_than_the_window_is_dropped_counted_and_logged(
    rig: Rig,
) -> None:
    bars = BarsRig(rig, {"time:5s": TIME_5S})
    await bars.start()
    first, mid, later, late = (
        _print(1.0, "1", "a"),
        _print(7.0, "2", "b"),
        _print(130.0, "4", "c"),
        _print(2.0, "8", "d"),  # bar [0 s, 5 s) closed 125 s before the watermark
    )
    before = metric(bars_late_trade_dropped_total, symbol=SYMBOL, reason="late_window")
    with capture_logs() as logs:
        await _publish(rig, first, mid, later, late)
        await bars.finish()
    assert metric(bars_late_trade_dropped_total, symbol=SYMBOL, reason="late_window") == before + 1
    warned = [e for e in logs if e["event"] == "bars_late_trade_dropped"]
    assert [(e["reason"], e["log_level"]) for e in warned] == [("late_window", "warning")]
    # conservation: every print is in a bar, except the one reported as dropped
    assert golden.total_volume(bars.bars("time:5s")) == Decimal(1 + 2 + 4)
    assert bars.amended("time:5s") == 0


class _NoDedupe:
    """The naive collaborator: a trade-id ring that remembers nothing, so nothing is a duplicate."""

    def __init__(self, capacity: int = 0) -> None:
        self.capacity = capacity

    def __len__(self) -> int:
        return 0

    def add(self, trade_id: str) -> bool:
        return True


async def test_s03_negative_control_without_the_dedupe_ring_every_fold_double_counts(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The builders never dedupe (BQ-10): remove `TradeStream`'s ring and a duplicated frame is
    counted twice by the volume, tick, range and renko folds, and conservation fails on each."""
    monkeypatch.setattr(trade_stream, "DedupeRing", _NoDedupe)
    bars = BarsRig(rig, CONTROL_SPECS, factory=runner.factory)
    await bars.start()
    feed = await _start_on_phase(rig, bars)
    suppressed = metric(trade_duplicates_suppressed_total, symbol=SYMBOL)
    await bars.run(feed, 3.0)
    rig.ex.inject(Fault(FaultKind.DUPLICATE, topic=TOPIC, count=4))
    await bars.run(feed, 12.0)
    await bars.finish()
    assert metric(trade_duplicates_suppressed_total, symbol=SYMBOL) == suppressed
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), CONTROL_SPECS, SYMBOL)
    for label in CONTROL_SPECS:
        with pytest.raises(AssertionError, match="not conserved"):
            golden.assert_conserved(expected[label], bars.bars(label), label)

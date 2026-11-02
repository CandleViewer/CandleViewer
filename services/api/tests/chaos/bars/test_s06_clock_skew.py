"""Scenario 6 - host clock jumps of +-2 s and +-2 min. C-13.6 #6 (clock drift).

Declared (E12-Q06 AC3; US-MKT-009): bar boundaries follow the exchange clock. The venue stamps
every print, and the bar set's "now" is the host clock corrected by `ClockGuard`'s offset
(`app.exchange_corrected_clock`, the #529 fix), so a host clock step changes nothing a client
sees: the bars equal the golden, no print is dropped as late, no closed bar is re-emitted as
amended, and no bar opens before its predecessor. `ClockGuard` raises the drift alarm
(`clock_resync_triggered_total{reason="host_step"}`, `exchange_clock_drift_ms`, severity warn
above 500 ms and critical above 2 s).

Negative controls: the pre-#529 wiring, the raw host clock, fed the same jumps. A +2 min jump
closes the open bar early and drops the venue-correct prints that follow (`late_window`); a
+2 s jump re-emits bars as amended. A backward jump is harmless either way (the watermark never
moves back), which is pinned too.
"""

from __future__ import annotations

import pytest

from candleviewer.bars.time_builder import bars_late_trade_dropped_total
from candleviewer.ingestion.metrics import clock_resync_triggered_total, exchange_clock_drift_ms
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._rig import SPECS, SYMBOL, BarsRig, ClockSource
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

#: Host jump -> the drift severity ClockGuard reports once it has re-measured it.
SEVERITY = {2.0: "warn", -2.0: "warn", 120.0: "critical", -120.0: "critical"}
BEFORE_S, AFTER_S = 6.0, 14.0


def _dropped() -> float:
    return sum(
        metric(bars_late_trade_dropped_total, symbol=SYMBOL, reason=r)
        for r in ("late_window", "empty_interval")
    )


async def _jump(rig: Rig, bars: BarsRig, skew_s: float, *, after_s: float = AFTER_S) -> None:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await bars.run(feed, BEFORE_S)
    rig.ex.inject(Fault(FaultKind.CLOCK_JUMP, seconds=skew_s))
    await bars.run(feed, after_s)
    await bars.finish()


async def _setup(rig: Rig, clock: ClockSource) -> BarsRig:
    bars = BarsRig(rig, clock=clock)
    await bars.start()
    return bars


@pytest.mark.parametrize("skew", sorted(SEVERITY))
async def test_s06_bars_follow_the_exchange_clock_through_a_host_jump(
    rig: Rig, skew: float
) -> None:
    bars = await _setup(rig, "corrected")
    dropped, resyncs = _dropped(), metric(clock_resync_triggered_total, reason="host_step")
    await _jump(rig, bars, skew)
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
    for label in SPECS:
        golden.assert_matches_golden(
            expected[label], bars.bars(label), label, kind=SPECS[label].kind
        )
        golden.assert_monotonic(bars.bars(label), label)
    assert _dropped() == dropped, "venue-correct prints dropped as late"
    assert bars.amended("time:5s") == 0, "a host jump re-emitted closed bars"
    # the alarm: the step is detected, re-measured and reported with its severity
    assert metric(clock_resync_triggered_total, reason="host_step") == resyncs + 1
    assert abs(metric(exchange_clock_drift_ms) + skew * 1000) < 250  # offset = venue - host
    assert rig.clock_guard.health_severity() == SEVERITY[skew]


@pytest.mark.harness
async def test_s06_dense_jump_forward_and_back_leaves_the_bars_equal_to_the_golden(
    rig: Rig,
) -> None:
    bars = await _setup(rig, "corrected")
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    for skew in (120.0, -240.0, 120.0, 2.0, -2.0):  # WSL sleep, resume, NTP fix-ups
        await bars.run(feed, 10.0)
        rig.ex.inject(Fault(FaultKind.CLOCK_JUMP, seconds=skew))
    await bars.run(feed, 10.0)
    await bars.finish()
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
    for label in SPECS:
        golden.assert_matches_golden(
            expected[label], bars.bars(label), label, kind=SPECS[label].kind
        )
    assert bars.amended("time:5s") == 0


async def test_s06_negative_control_raw_host_clock_plus_two_minutes_drops_correct_prints(
    rig: Rig,
) -> None:
    bars = await _setup(rig, "raw")
    dropped = _dropped()
    await _jump(rig, bars, 120.0)
    assert _dropped() > dropped, "the raw host clock no longer loses prints: control is stale"
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
    with pytest.raises(AssertionError, match="differs from the golden"):
        golden.assert_matches_golden(
            expected["time:5s"], bars.bars("time:5s"), "time:5s", kind="time"
        )
    with pytest.raises(AssertionError, match="volume not conserved"):
        golden.assert_conserved(expected["time:5s"], bars.bars("time:5s"), "time:5s")


async def test_s06_negative_control_raw_host_clock_plus_two_seconds_reemits_amended_bars(
    rig: Rig,
) -> None:
    bars = await _setup(rig, "raw")
    await _jump(rig, bars, 2.0)
    assert bars.amended("time:5s") > 0, "the raw host clock no longer closes bars early"


@pytest.mark.parametrize("clock", ["corrected", "raw"])
async def test_s06_backward_jump_never_opens_a_bar_before_its_predecessor(
    rig: Rig, clock: ClockSource
) -> None:
    """The watermark never moves back, so a backward jump is harmless on either clock."""
    bars = await _setup(rig, clock)
    dropped = _dropped()
    await _jump(rig, bars, -120.0)
    for label in SPECS:
        golden.assert_monotonic(bars.bars(label), label)
    assert _dropped() == dropped
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
    golden.assert_matches_golden(expected["time:5s"], bars.bars("time:5s"), "time:5s", kind="time")

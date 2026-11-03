"""Scenario 2 - a tape gap is never silent in the bars. C-13.6 #1 (WS reconnect) + #3 (gap).

Declared (E12-Q06 AC1): a hole in the trade tape is either healed before the bars see it, or
it is visible. Two halves, because the bars have no input of their own for a hole:

* **Recovered** (REST backfill works): `TradeStream` merges the missing prints in order before
  any later one, so the bars equal the venue's golden, and the `GapEvent` says "Backfilled".
* **Unrecovered** (REST down): the hole is reported by ingestion (`GapEvent(recovered=False)`,
  `trade_gaps_total{recovered="false"}`, health `trade_gap_unrecovered`) and the bars visibly
  lack the lost prints. `BarBuilderSet` consumes the `GapEvent` and flags the first bar each
  builder emits after the hole (`gap_before`), which the last test below asserts.

Negative control: the unrecovered run is what a pipeline without backfill produces, and it
fails the same golden comparison the recovered run passes.
"""

from __future__ import annotations

import pytest

from candleviewer.ingestion.metrics import trade_gaps_total
from candleviewer.ingestion.service import HealthReason
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._rig import SPECS, SYMBOL, BarsRig
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

TOPIC = f"publicTrade.{SYMBOL}"
BACKFILL_PATH = "/v5/market/recent-trade"
LOST_FRAMES = 2
#: 3 REST retries x full-jitter backoff capped at 2/4/8 s: the backfill has failed after this.
BACKFILL_RETRY_BUDGET_S = 16.0


def _gaps(recovered: str) -> float:
    return metric(trade_gaps_total, symbol=SYMBOL, recovered=recovered)


async def _tape_with_hole(rig: Rig, bars: BarsRig, *, tail_s: float = 6.0) -> Feeder:
    """Run, lose `LOST_FRAMES` trade frames on the wire, reset the socket, keep trading."""
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await bars.run(feed, 8.0)
    rig.ex.inject(Fault(FaultKind.DROP, topic=TOPIC, count=LOST_FRAMES))
    await bars.run(feed, 1.0)  # the venue prints; the wire loses it
    rig.ex.inject(Fault(FaultKind.RESET))
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="reopen")
    await bars.run(feed, tail_s)
    return feed


@pytest.fixture
async def bars(rig: Rig) -> BarsRig:
    b = BarsRig(rig)
    await b.start()
    return b


async def test_s02_recovered_gap_leaves_the_bars_equal_to_the_golden(
    rig: Rig, bars: BarsRig
) -> None:
    before = _gaps("true")
    await _tape_with_hole(rig, bars)
    await bars.finish()
    seen = rig.observe()
    assert [g.recovered for g in seen.gaps] == [True]
    assert seen.gaps[0].label().startswith("Backfilled")  # words, not a colour band
    assert _gaps("true") == before + 1
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
    for label in SPECS:
        golden.assert_matches_golden(
            expected[label], bars.bars(label), label, kind=SPECS[label].kind
        )
        golden.assert_monotonic(bars.bars(label), label)


async def test_s02_unrecovered_gap_is_reported_and_the_bars_lack_the_lost_prints(
    rig: Rig, bars: BarsRig
) -> None:
    before = _gaps("false")
    rig.ex.inject(Fault(FaultKind.HTTP_STATUS, status=503, count=50, path=BACKFILL_PATH))
    await _tape_with_hole(rig, bars, tail_s=BACKFILL_RETRY_BUDGET_S)
    await bars.finish()
    seen = rig.observe()
    assert [g.recovered for g in seen.gaps] == [False]
    assert seen.gaps[0].label().startswith("No data")
    assert _gaps("false") == before + 1  # IngestionTradeGapUnrecovered keys on this
    assert rig.svc.health().detail == HealthReason.TRADE_GAP_UNRECOVERED
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
    assert golden.total_volume(bars.bars("vol:1")) < golden.total_volume(expected["vol:1"])


async def test_s02_unrecovered_gap_leaves_the_bars_health_unchanged(
    rig: Rig, bars: BarsRig
) -> None:
    """BQ-8: the bars have no tape-gap health reason; ingestion's is the only one (SCENARIOS.md)."""
    rig.ex.inject(Fault(FaultKind.HTTP_STATUS, status=503, count=50, path=BACKFILL_PATH))
    await _tape_with_hole(rig, bars, tail_s=BACKFILL_RETRY_BUDGET_S)
    await bars.finish()
    assert rig.observe().gaps[0].recovered is False
    assert bars.set.health_reasons() == ()


async def test_s02_negative_control_a_pipeline_without_backfill_fails_the_golden(
    rig: Rig, bars: BarsRig
) -> None:
    rig.ex.inject(Fault(FaultKind.HTTP_STATUS, status=503, count=50, path=BACKFILL_PATH))
    await _tape_with_hole(rig, bars, tail_s=BACKFILL_RETRY_BUDGET_S)
    await bars.finish()
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
    with pytest.raises(AssertionError, match="differs from the golden"):
        golden.assert_matches_golden(
            expected["time:5s"], bars.bars("time:5s"), "time:5s", kind="time"
        )
    with pytest.raises(AssertionError, match="volume not conserved"):
        golden.assert_conserved(expected["vol:1"], bars.bars("vol:1"), "vol:1")


async def test_s02_gap_marker_helper_demands_a_flag_on_the_first_bar_after_the_hole(
    rig: Rig, bars: BarsRig
) -> None:
    """The invariant helper is not vacuous: it passes a flagged bar and fails an unflagged one."""
    rig.ex.inject(Fault(FaultKind.HTTP_STATUS, status=503, count=50, path=BACKFILL_PATH))
    await _tape_with_hole(rig, bars, tail_s=BACKFILL_RETRY_BUDGET_S)
    await bars.finish()
    gap = rig.observe().gaps[0]
    unflagged = [
        b.model_copy(update={"gap_before": False, "partial": False}) for b in bars.bars("vol:1")
    ]
    with pytest.raises(golden.GapNotMarkedError, match="hides the gap"):
        golden.assert_gap_marked(unflagged, gap, "vol:1")
    first = next(i for i, b in enumerate(unflagged) if b.close_time >= gap.end_us)
    flagged = [*unflagged]
    flagged[first] = unflagged[first].model_copy(update={"gap_before": True})
    golden.assert_gap_marked(flagged, gap, "vol:1")


async def test_s02_first_bar_after_an_unrecovered_hole_is_flagged(rig: Rig, bars: BarsRig) -> None:
    rig.ex.inject(Fault(FaultKind.HTTP_STATUS, status=503, count=50, path=BACKFILL_PATH))
    await _tape_with_hole(rig, bars, tail_s=BACKFILL_RETRY_BUDGET_S)
    await bars.finish()
    gap = rig.observe().gaps[0]
    for label in SPECS:
        golden.assert_gap_marked(bars.bars(label), gap, label)


@pytest.mark.harness
async def test_s02_dense_repeated_gaps_across_the_corpus_equal_the_golden(
    rig: Rig, bars: BarsRig
) -> None:
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    for _ in range(4):
        await bars.run(feed, 12.0)
        rig.ex.inject(Fault(FaultKind.DROP, topic=TOPIC, count=LOST_FRAMES))
        await bars.run(feed, 1.0)
        rig.ex.inject(Fault(FaultKind.RESET))
        await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="reopen")
    await bars.run(feed, 8.0)
    await bars.finish()
    assert [g.recovered for g in rig.observe().gaps] == [True] * 4
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
    for label in SPECS:
        golden.assert_matches_golden(
            expected[label], bars.bars(label), label, kind=SPECS[label].kind
        )

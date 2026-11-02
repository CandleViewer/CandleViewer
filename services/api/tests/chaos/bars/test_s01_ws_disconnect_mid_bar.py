"""Scenario 1 - the public socket drops in the middle of a bar. C-13.6 #1 (WS disconnect).

Declared (E12-Q06 scenario 1, BQ-9 a): a reconnect mid-bar is healed before the bars see it.
`TradeStream` backfills the prints the dead socket missed from REST and publishes them in order
ahead of the live ones, so a bar that was open across the drop closes exactly as the golden says,
volume and print count are conserved, and no bar index is emitted twice. The drop is visible
where it should be: `ingest_ws_up` 1 -> 0 -> 1, `trade_gaps_total{recovered="true"}` +1.
The other half of the scenario, a process restart mid-bar, is `test_s01b_restart_mid_bar.py`.

The test proves the drop really fell inside a bar: when the socket dies the volume series holds
a forming bar (its last emission is not a close) and the time series sits off a bucket edge.

Negative control: with the REST backfill down the same drop loses prints, and the golden and the
conservation helpers fail on it.
"""

from __future__ import annotations

import pytest

from candleviewer.ingestion.connection import PHASE_OPEN
from candleviewer.ingestion.metrics import ingest_ws_up, trade_gaps_total
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._rig import SPECS, SYMBOL, BarsRig
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

BACKFILL_PATH = "/v5/market/recent-trade"
#: 3 REST retries x full-jitter backoff capped at 2/4/8 s: the backfill has failed after this.
BACKFILL_RETRY_BUDGET_S = 16.0
OUTAGE_STEPS_S = 2.0  # the venue keeps printing while the socket is down


def _up() -> float:
    return metric(ingest_ws_up, socket="public")


def _gaps(recovered: str) -> float:
    return metric(trade_gaps_total, symbol=SYMBOL, recovered=recovered)


def _forming(bars: BarsRig, label: str) -> bool:
    """The series' newest emission is not a close: a bar is open."""
    updates = bars.sink.updates[bars.specs[label].spec_hash]
    return bool(updates) and updates[-1].kind != "close"


async def _drop_mid_bar(rig: Rig, bars: BarsRig, *, tail_s: float) -> list[bool]:
    """Run, kill the socket while a volume bar is open, keep the venue printing through the
    outage, reconnect, run on. Returns `[volume bar open, time bar off its edge]` at the drop."""
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == PHASE_OPEN, within_s=5, what="open")
    await bars.run(feed, 9.0)
    # advance to the first moment a volume bar is open off a 5 s edge, then cut the socket
    while not _forming(bars, "vol:1") or rig.clock.wall_s() % 5.0 < 0.3:
        await bars.run(feed, 0.1)
    mid_bar = [_forming(bars, "vol:1"), rig.clock.wall_s() % 5.0 >= 0.3]
    assert _up() == 1.0
    rig.ex.inject(Fault(FaultKind.RESET))
    await bars.run(feed, OUTAGE_STEPS_S)  # frames the dead socket never delivered
    await rig.clock.run_until(lambda: rig.ws.state() == PHASE_OPEN, within_s=15, what="reopen")
    await bars.run(feed, tail_s)
    return mid_bar


@pytest.fixture
async def bars(rig: Rig) -> BarsRig:
    b = BarsRig(rig)
    await b.start()
    return b


async def test_s01_a_drop_mid_bar_is_healed_and_the_bars_equal_the_golden(
    rig: Rig, bars: BarsRig
) -> None:
    before = _gaps("true")
    mid_bar = await _drop_mid_bar(rig, bars, tail_s=10.0)
    await bars.finish()
    assert mid_bar == [True, True], "the drop did not fall inside a bar"
    seen = rig.observe()
    assert [g.recovered for g in seen.gaps] == [True]
    assert seen.gaps[0].label().startswith("Backfilled")
    assert _gaps("true") == before + 1
    assert _up() == 1.0  # 1 -> 0 -> 1: the socket is back
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
    for label in SPECS:
        golden.assert_matches_golden(
            expected[label], bars.bars(label), label, kind=SPECS[label].kind
        )
        golden.assert_conserved(expected[label], bars.bars(label), label)


async def test_s01_no_bar_index_is_emitted_closed_twice_across_the_reconnect(
    rig: Rig, bars: BarsRig
) -> None:
    await _drop_mid_bar(rig, bars, tail_s=10.0)
    await bars.finish()
    for label, spec in SPECS.items():
        closes = [s.bar.index for s in bars.sink.updates[spec.spec_hash] if s.kind == "close"]
        assert len(closes) == len(set(closes)), f"{label}: a bar closed twice"
        assert closes == sorted(closes), f"{label}: bars closed out of order"
        golden.assert_monotonic(bars.bars(label), label)
    assert bars.amended("time:5s") == 0 and bars.amended("vol:1") == 0, "a healed gap amends"


async def test_s01_the_socket_state_goes_down_and_comes_back() -> None:
    """`ingest_ws_up` reads 0 while the socket is down: the drop is observable, not just healed."""
    rig = Rig(seed=11)
    await rig.start()
    try:
        feed = Feeder(rig.ex)
        await rig.clock.run_until(lambda: rig.ws.state() == PHASE_OPEN, within_s=5, what="open")
        await feed.run(2.0)
        assert _up() == 1.0
        rig.ex.inject(Fault(FaultKind.RESET))
        await rig.clock.settle()
        assert _up() == 0.0
        await rig.clock.run_until(lambda: rig.ws.state() == PHASE_OPEN, within_s=15, what="reopen")
        assert _up() == 1.0
    finally:
        await rig.stop()


async def test_s01_negative_control_without_the_backfill_the_drop_loses_prints(
    rig: Rig, bars: BarsRig
) -> None:
    rig.ex.inject(Fault(FaultKind.HTTP_STATUS, status=503, count=50, path=BACKFILL_PATH))
    await _drop_mid_bar(rig, bars, tail_s=BACKFILL_RETRY_BUDGET_S)
    await bars.finish()
    assert [g.recovered for g in rig.observe().gaps] == [False]
    expected = await golden.golden_bars(golden.venue_tape(rig, SYMBOL), SPECS, SYMBOL)
    with pytest.raises(AssertionError, match="differs from the golden"):
        golden.assert_matches_golden(
            expected["time:5s"], bars.bars("time:5s"), "time:5s", kind="time"
        )
    with pytest.raises(AssertionError, match="not conserved"):
        golden.assert_conserved(expected["vol:1"], bars.bars("vol:1"), "vol:1")

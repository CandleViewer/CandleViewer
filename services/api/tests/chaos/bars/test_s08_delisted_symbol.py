"""Scenario 8 - a symbol is delisted or halted mid-session. Extension of C-13.6 #1 (topic teardown).

Declared (E12-Q06 scenario 8): when the venue stops a contract, its bars stop with it. The
builders have no symbol-status input and synthesise nothing, so after the last print the series
emits at most the clock close of the bar that was open, never an empty bar and never a bar that
opens after the last print. The delist itself is the feed's to announce, not the bars': ingestion
publishes `FeedHealthEvent(state="delisted")` for the topic, refuses new demand for the symbol
(`UnknownSymbolError`) and unsubscribes it; the bars stay healthy and the live symbol is
untouched. Everything printed before the delist equals the golden.

There is no bars-specific "delisted" banner (BQ-7): the banner reads the feed-health event.

Negative control: a builder that filled the quiet interval with empty bars (a naive "keep the
chart moving") fails the no-empty-bars helper.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import pytest

from candleviewer.bars.models import Bar
from candleviewer.ingestion.connection import PHASE_OPEN
from candleviewer.ingestion.ticker_stream import UnknownSymbolError
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._rig import SPECS, BarsRig
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig

pytestmark = pytest.mark.chaos

DEAD, ALIVE = "LUNAUSDT", "BTCUSDT"
DEAD_TOPIC = f"publicTrade.{DEAD}"
QUIET_S = 90.0  # past the 60 s late window and the 10 s trade staleness limit


@dataclass
class _Delisted:
    rig: Rig
    bars: BarsRig
    feed: Feeder
    updates_at_delist: dict[str, int]


def assert_no_empty_bars(bars: Sequence[Bar], last_print_us: int, what: str) -> None:
    """Every bar holds a print, and none opens after the last print the venue made."""
    for bar in bars:
        assert bar.trade_count > 0 and bar.volume > 0, f"{what}: bar {bar.index} is empty"
        assert bar.open_time <= last_print_us, f"{what}: bar {bar.index} opens after the delist"


@pytest.fixture
async def delisted() -> AsyncIterator[_Delisted]:
    rig = Rig(seed=8, symbols=(ALIVE, DEAD))
    await rig.start()
    try:
        bars = BarsRig(rig, symbol=DEAD)
        await bars.start()
        feed = Feeder(rig.ex, books=(ALIVE,), trades={ALIVE: ALIVE, DEAD: "SOLUSDT"})
        await rig.clock.run_until(lambda: rig.ws.state() == PHASE_OPEN, within_s=5, what="open")
        await bars.run(feed, 12.0)
        rig.observe()
        at_delist = {label: len(bars.sink.updates[spec.spec_hash]) for label, spec in SPECS.items()}
        rig.ex.inject(Fault(FaultKind.DELIST, symbol=DEAD))
        await rig.call(rig.instruments.refresh_now())
        await bars.run(feed, QUIET_S)
        await bars.finish()
        yield _Delisted(rig, bars, feed, at_delist)
    finally:
        await rig.stop()


async def test_s08_a_delisted_symbol_stops_its_bars_and_never_synthesises_empty_ones(
    delisted: _Delisted,
) -> None:
    rig, bars = delisted.rig, delisted.bars
    tape = golden.venue_tape(rig, DEAD)
    assert tape, "the dead symbol never printed"
    expected = await golden.golden_bars(tape, SPECS, DEAD)
    for label, spec in SPECS.items():
        golden.assert_matches_golden(
            expected[label], bars.bars(label), label, kind=SPECS[label].kind
        )
        assert_no_empty_bars(bars.bars(label), tape[-1].ts_event, label)
        after = bars.sink.updates[spec.spec_hash][delisted.updates_at_delist[label] :]
        assert all(s.kind == "close" for s in after), f"{label}: a bar kept forming after delist"
        assert len(after) <= 1, f"{label}: {len(after)} emissions after the delist"
    assert bars.set.health_reasons() == (), "a delist is not a bars fault"


async def test_s08_the_feed_announces_the_delist_and_refuses_new_demand(
    delisted: _Delisted,
) -> None:
    rig = delisted.rig
    states = {(e.topic, e.state) for e in rig.observe().feed}
    assert (DEAD_TOPIC, "delisted") in states
    with pytest.raises(UnknownSymbolError):
        rig.trades.acquire("chart-2", DEAD)
    live = rig.ex.live_sockets()[0].topics
    assert DEAD_TOPIC not in live and f"publicTrade.{ALIVE}" in live, "the delist leaked"


async def test_s08_negative_control_filling_the_quiet_interval_with_empty_bars_fails(
    delisted: _Delisted,
) -> None:
    final = delisted.bars.bars("time:5s")
    last_print_us = golden.venue_tape(delisted.rig, DEAD)[-1].ts_event
    assert_no_empty_bars(final, last_print_us, "time:5s")
    last = final[-1]
    filler = last.model_copy(
        update={
            "index": last.index + 1,
            "open_time": last.open_time + 5_000_000,
            "close_time": last.close_time + 5_000_000,
            "trade_count": 0,
            "volume": last.volume * 0,
        }
    )
    with pytest.raises(AssertionError, match="is empty"):
        assert_no_empty_bars([*final, filler], last_print_us, "time:5s")
    late = filler.model_copy(update={"trade_count": 1, "volume": last.volume})
    with pytest.raises(AssertionError, match="opens after the delist"):
        assert_no_empty_bars([*final, late], last_print_us, "time:5s")

"""SR-040 - a malformed or hostile print never reaches a bar. C-13.6 #3 (the boundary half).

Declared (E12-Q06, BQ-14): the REST backfill of a gap can be fed an attacker-shaped row (a NaN
price). The ingestion boundary rejects the whole page (ingestion `test_s06` proves that half), so
the gap is reported unrecovered, and the bars never see the row: no hostile trade id and no
non-finite price on the bus, every bar finite and built only from prints the venue made.

Negative control: the invariant helper fails on a trade that carries the hostile row's id or a
NaN price, i.e. on a boundary that let it through.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

import pytest

from bench.bar_determinism import tapes
from candleviewer.bars.models import Bar
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.ingestion.metrics import trade_gaps_total
from tests.chaos.bars import _golden as golden
from tests.chaos.bars._rig import SPECS, SYMBOL, BarsRig
from tests.chaos.ingestion._faults import Fault, FaultKind
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._rig import Rig, metric

pytestmark = pytest.mark.chaos

BACKFILL_PATH = "/v5/market/recent-trade"
HOSTILE_ID = "x"  # the id the stub's hostile row carries
BACKFILL_RETRY_BUDGET_S = 16.0


def assert_only_venue_prints(
    trades: Iterable[object], bars: Iterable[Bar], venue_ids: set[str], what: str
) -> None:
    for t in trades:
        if not isinstance(t, TradeEvent):
            continue
        assert t.trade_id in venue_ids, f"{what}: trade {t.trade_id!r} was never printed"
        assert t.price.is_finite(), f"{what}: trade {t.trade_id!r} has a bad price"
    for bar in bars:
        assert all(p.is_finite() for p in (bar.open, bar.high, bar.low, bar.close, bar.volume)), (
            f"{what}: bar {bar.index} is not finite"
        )


@pytest.fixture
async def bars(rig: Rig) -> BarsRig:
    b = BarsRig(rig)
    await b.start()
    return b


async def test_sr040_a_hostile_backfill_row_never_reaches_the_bars(rig: Rig, bars: BarsRig) -> None:
    rig.ex.inject(Fault(FaultKind.HOSTILE_JSON, path=BACKFILL_PATH, count=50))
    feed = Feeder(rig.ex)
    before = metric(trade_gaps_total, symbol=SYMBOL, recovered="false")
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await bars.run(feed, 8.0)
    rig.ex.inject(Fault(FaultKind.DROP, topic=f"publicTrade.{SYMBOL}", count=2))
    await bars.run(feed, 1.0)
    rig.ex.inject(Fault(FaultKind.RESET))
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="reopen")
    await bars.run(feed, BACKFILL_RETRY_BUDGET_S)
    await bars.finish()
    assert metric(trade_gaps_total, symbol=SYMBOL, recovered="false") == before + 1
    venue_ids = {t.trade_id for t in golden.venue_tape(rig, SYMBOL)}
    assert HOSTILE_ID not in venue_ids
    for label in SPECS:
        assert_only_venue_prints(rig.observe().trades, bars.bars(label), venue_ids, label)


async def test_sr040_negative_control_the_helper_rejects_a_hostile_print() -> None:
    venue = {"a"}
    hostile = tapes.event(0, 1, Decimal(100), Decimal(1), "buy", SYMBOL, HOSTILE_ID)
    with pytest.raises(AssertionError, match="never printed"):
        assert_only_venue_prints([hostile], [], venue, "leaked row")
    nan = tapes.event(0, 1, Decimal("NaN"), Decimal(1), "buy", SYMBOL, "a")
    with pytest.raises(AssertionError, match="bad price"):
        assert_only_venue_prints([nan], [], venue, "NaN price")

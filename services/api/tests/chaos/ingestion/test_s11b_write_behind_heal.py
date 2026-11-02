"""Scenario 11b - hot-tier outage heals its lost trade runs (#1944). C-13.6 #10.

Declared: a slow store evicts write-behind rows (counted, recorded as lost runs, never
hidden). Once the writer has stayed recovered for `HEAL_SETTLE_S`, the healer refills each
closed run from one REST recent-trade page that spans it, through the same writer, reads the
rows back and clears the run. A run older than the page can never be refilled: it is counted
`unrecoverable` once and stays in `lost_ranges()`. Live publication is never touched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.metrics import (
    write_behind_heal_ranges_total,
    write_behind_heal_rows_total,
)
from candleviewer.ingestion.write_behind import BACKOFF_CAP_S
from candleviewer.ingestion.write_behind_heal import HEAL_SETTLE_S
from tests.chaos.ingestion._feed import Feeder
from tests.chaos.ingestion._oracle import RECENT_TRADE_LIMIT
from tests.chaos.ingestion._rig import Rig, metric
from tests.chaos.ingestion.conftest import SEED

pytestmark = pytest.mark.chaos

SYM = "BTCUSDT"
BUFFER = 4  # rows: a 6 s outage at ~3 prints/s overflows it
OUTAGE_S = 6.0
SMALL_PAGE = 10  # prints (~3 s of tape): far younger than a run 30 s old


def _heal(result: str) -> float:
    return metric(write_behind_heal_ranges_total, table="trades", result=result)


async def _build(page: int) -> Rig:
    rig = Rig(seed=SEED, trades_buffer=BUFFER, heal=True, recent_page=page)
    await rig.start()
    return rig


@pytest.fixture
async def healing() -> AsyncIterator[Rig]:
    rig = await _build(RECENT_TRADE_LIMIT)
    try:
        yield rig
    finally:
        await rig.stop()


@pytest.fixture
async def short_page() -> AsyncIterator[Rig]:
    rig = await _build(SMALL_PAGE)
    try:
        yield rig
    finally:
        await rig.stop()


async def _outage_then_recovery(rig: Rig) -> tuple[Feeder, list[Range]]:
    """Outage with evictions, then recovery until the write-behind closed the run."""
    feed = Feeder(rig.ex)
    await rig.clock.run_until(lambda: rig.ws.state() == "open", within_s=5, what="open")
    await feed.run(2.0)
    rig.writer.down = True
    await feed.run(OUTAGE_S)
    assert rig.trades.write_behind.evicted > 0, "the slow store evicted nothing"
    rig.writer.down = False
    await feed.run(BACKOFF_CAP_S + 2.0)  # the retry may be parked on its capped backoff
    runs = rig.trades.write_behind.closed_ranges(SYM)
    assert runs, "no closed lost run recorded"
    assert not rig.trades.write_behind.degraded
    return feed, runs


def _oracle_ids(rig: Rig, runs: list[Range]) -> set[str]:
    return {
        str(p["i"])
        for p in rig.ex.trades.prints[SYM]
        if any(r.start_us <= int(p["T"]) * 1000 < r.end_us for r in runs)
    }


async def test_s11b_lost_runs_are_refilled_verified_and_cleared(healing: Rig) -> None:
    rig = healing
    feed, runs = await _outage_then_recovery(rig)
    wanted = _oracle_ids(rig, runs)
    lost = wanted - {t.trade_id for t in rig.writer.persisted_trades}
    assert lost, "nothing was lost"
    healed = _heal("healed")
    unrecoverable = _heal("unrecoverable")
    rows = metric(write_behind_heal_rows_total, table="trades")
    reads = rig.hot_ids.reads

    await feed.run(HEAL_SETTLE_S + 5.0)  # settle debounce, then a pass per second

    persisted = {t.trade_id: t for t in rig.writer.persisted_trades}
    assert lost <= persisted.keys(), "run not refilled"
    assert {persisted[i].source for i in lost} == {"backfill"}  # the heal's own rows
    assert rig.hot_ids.reads > reads, "healed without reading the rows back"
    assert _heal("healed") >= healed + len(runs)
    assert _heal("unrecoverable") == unrecoverable
    assert metric(write_behind_heal_rows_total, table="trades") >= rows + len(lost)
    assert rig.trades.write_behind.closed_ranges(SYM) == []  # runs cleared


async def test_s11b_run_older_than_the_page_stays_lost_and_counts_once(short_page: Rig) -> None:
    rig = short_page
    feed, runs = await _outage_then_recovery(rig)
    before_unrec, before_healed = _heal("unrecoverable"), _heal("healed")

    await feed.run(HEAL_SETTLE_S + 40.0)  # many passes: still counted once per run

    assert rig.trades.write_behind.closed_ranges(SYM) == runs  # never hidden, never cleared
    assert rig.trades.write_behind.lost_ranges(SYM)[: len(runs)] == runs
    assert _heal("unrecoverable") == before_unrec + len(runs)
    assert _heal("healed") == before_healed

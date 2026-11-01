"""E12-X02 abuse beside ingestion (#452 AC3; BQ-4 as ruled in 6554826610; budgets #5 and #13): the
in-process `perf` leg, the PR-lane evidence for "abuse does not touch ingestion".

Abusive sessions loop maximal `/market/bars` pages (`limit=5000`, the whole recorded tape) over
stale rows, so every page is also a rebuild trigger, while E08-X02's `Rig` feeds the recorded
BTCUSDT tape through the production `TradeStream` onto a real `Bus` into a real `BarBuilderSet`
(`test_integrity._run`), and one well-behaved session times its own small reads. All of it shares
one event loop and one in-process app (no socket, C-13.5). Asserted:

- the bars built beside the abuse equal the bars built alone (golden: the same tape, no abuse);
- the ingestion loss counters do not move: `ingest_dispatch_overflow_total`,
  `ingest_queue_full_total`, `trade_writes_dropped_total`, `trade_prints_rejected_total`;
- the rebuild-trigger storm schedules one rebuild per series;
- the well-behaved session's p95 is under budget #13's 150 ms, in process.

Not here, and **not built**: real QuestDB, where the REST reads serialise on the `bars` pgwire lock
(#452 findings row F3), and the 10-minute k6 battery; both are carried to #528 (E12-Q05), whose
real-QuestDB leg is F3's escalation trigger. Both are NOT RUN rows of the report.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path
from typing import Final

import httpx
import pytest
from prometheus_client import Counter as PromCounter

from candleviewer.bars import rows
from candleviewer.bus import metrics as bus_metrics
from candleviewer.ingestion import metrics as im
from tests.contract import _market_world as mw
from tests.contract._market_world import NOW, READER, T0, operation
from tests.contract.test_market_bars_contract import _iso
from tests.security.bars import test_integrity as integrity
from tests.security.bars.conftest import Stores

SESSIONS: Final = 4
ROUNDS: Final = 200
P95_BUDGET_S: Final = 0.150  # budget #13: API read p95 < 150 ms
_LOSS: Final[tuple[PromCounter, ...]] = (
    im.ingest_dispatch_overflow_total,
    bus_metrics.ingest_queue_full_total,
    im.trade_writes_dropped_total,
    im.trade_prints_rejected_total,
)


def _lost() -> dict[str, float]:
    """Each loss counter, summed over its labels."""
    return {
        family.name: sum(s.value for s in family.samples if s.name.endswith("_total"))
        for counter in _LOSS
        for family in counter.collect()
    }


@pytest.mark.perf
async def test_exhaustion_perf_abuse_beside_ingestion_loses_nothing_and_keeps_the_p95(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    golden = await integrity._run(tmp_path / "alone", hostile=False)
    mw.stored_rows()  # built at the current version, then every time row is made stale
    monkeypatch.setitem(rows.BUILD_VERSIONS, "time", rows.BUILD_VERSIONS["time"] + 1)
    scheduled: list[str] = []

    async def schedule(symbol: str, spec_hash: str, lo: int, hi: int) -> None:
        scheduled.append(spec_hash)

    monkeypatch.setattr(mw, "_no_rebuild", schedule)
    lost, path, stop = _lost(), operation("getBars")[0], asyncio.Event()
    window = {"symbol": "BTCUSDT", "bar_type": "time", "from": _iso(T0), "to": _iso(NOW)}
    served: list[int] = []

    async def abuse(client: httpx.AsyncClient, n: int) -> None:
        params = {**window, "param": ("1", "5")[n % 2], "limit": "5000"}
        while not stop.is_set():
            served.append((await client.get(path, params=params, headers=dict(READER))).status_code)
            # In process nothing in a request suspends (no socket, no store I/O), so a loop that
            # never yields would starve every other task; a socket delivers the next request on
            # a later turn of the loop, and so does this.
            await asyncio.sleep(0)

    async with stores.asgi() as client:
        abusers = [asyncio.ensure_future(abuse(client, n)) for n in range(SESSIONS)]
        ingest = asyncio.ensure_future(integrity._run(tmp_path / "beside", hostile=False))
        took: list[float] = []
        for _ in range(ROUNDS):
            began = time.perf_counter()
            resp = await client.get(path, params={**window, "param": "1", "limit": "100"},
                                    headers=dict(READER))  # fmt: skip
            took.append(time.perf_counter() - began)
            assert resp.status_code == 200
        beside = await ingest
        stop.set()
        await asyncio.gather(*abusers)
    assert len(served) >= SESSIONS * 10 and set(served) == {200}  # the abuse really ran
    assert beside == golden
    assert _lost() == lost
    assert len(set(scheduled)) == len(scheduled) == 2  # one rebuild per series, the storm aside
    p95 = statistics.quantiles(took, n=20)[18]
    assert p95 < P95_BUDGET_S, (p95, statistics.median(took))

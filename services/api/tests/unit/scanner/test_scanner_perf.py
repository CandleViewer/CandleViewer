"""E08-T09 (#4708) PR 2b: `GET /scanner`'s own cost (C-13.9). Over 500 symbols with a ticker
source whose `refresh()` answers at once, 200 scans each: cache-cold (every scan evaluates: the
recorded-set read, the evaluation off the loop and the body) p95 under 200 ms, and cached p95
under 20 ms. The venue round trip a cold scan may wait for in production (`refresh()` when the
snapshot is over 5 s old) is not ours and not measured. Deselected by default (`-m perf`)."""

from __future__ import annotations

import statistics
import time
from decimal import Decimal

import pytest

from candleviewer.api.scanner_criteria import CRITERIA_BY_ID
from candleviewer.api.scanner_eval import scan_query
from tests.scanner._scan_env import FakeRecording, FakeUniverse, entry, service, ticker, universe

pytestmark = pytest.mark.perf

SYMBOLS = 500
RUNS = 200
COLD_P95_MS = 200.0
CACHED_P95_MS = 20.0


def _p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[-1]


async def test_scan_cold_and_cached_p95_stay_inside_their_budgets() -> None:
    rows = [
        ticker(
            f"S{i:03d}USDT",
            turnover_24h=Decimal(i * 1000),
            volume_24h=Decimal(i),
            funding_rate=Decimal(i % 40 - 20) / 10000,
        )
        for i in range(SYMBOLS)
    ]
    svc = service(
        FakeUniverse(universe(rows)),
        FakeRecording([entry(f"S{i:03d}USDT") for i in range(0, SYMBOLS, 10)]),
    )
    flt = {"turnover_24h": {"min": "10000"}, "funding_rate": {"max": "0.0015"}}
    query = scan_query(flt, "turnover_24h", 200, CRITERIA_BY_ID)
    cold: list[float] = []
    for _ in range(RUNS):
        svc.invalidate()
        started = time.perf_counter()
        await svc.scan(query, restricted=True)
        cold.append((time.perf_counter() - started) * 1000)
    cached: list[float] = []
    for _ in range(RUNS):
        started = time.perf_counter()
        await svc.scan(query, restricted=True)
        cached.append((time.perf_counter() - started) * 1000)
    print(
        f"[perf][E08-T09] scan of {SYMBOLS} symbols: cold p95 {_p95(cold):.2f} ms "
        f"(budget {COLD_P95_MS:.0f} ms), cached p95 {_p95(cached):.4f} ms "
        f"(budget {CACHED_P95_MS:.0f} ms)"
    )
    assert _p95(cold) < COLD_P95_MS
    assert _p95(cached) < CACHED_P95_MS

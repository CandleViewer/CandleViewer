"""Perf lane (C-13.9) for the cold 5 000-bar kline read behind Budget #13 (#2523).

A lake shaped like the pack's (as `bench/ingestion/fixture_app.write_cold_lake` writes it: one
month partition, one `part-0000.parquet`, 30 days of 1-minute bars), built here in `tmp_path`,
is read through `ParquetKlineReader.__call__`.
The bound is a ratio, not milliseconds: the reader's fastest call over a bare DuckDB
`execute` + `to_arrow_table` of the same window in the same process, so runner speed cancels
out. It fails on the pre-#2523 row build (tz-aware datetimes, per-row dicts, Decimal text).

The concurrent rig (#2523 lever 3) is the pack's own shape: five simultaneous cold 5 000-bar
reads through the in-process ASGI app (`fixture_app.build_app`, driven as
`rest_load.drive_inprocess` drives it), round after round, its p95 read against Budget #13 in
milliseconds. Sequential timings hide the GIL-held per-row work that concurrency multiplies.
It is reported, not gated, as the pack's smoke rows are (`rest_load.py`, #399): the gate flips
to an assertion in the follow-up gc.freeze PR under #2523. The budget itself never moves.
"""

from __future__ import annotations

import asyncio
import gc
import random
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import httpx
import pyarrow as pa
import pytest

from bench.ingestion.budgets import B13_READ_P95_MS
from bench.ingestion.fixture_app import (
    assert_loopback_target,
    build_app,
    requests_plan,
    write_cold_lake,
)
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.storage.cold.kline_reader import ParquetKlineReader
from candleviewer.storage.cold.layout import DatasetRegistry
from tests.unit.storage.cold.test_kline_reader import _write_table

MIN = 60_000_000
ROWS = 30 * 1440  # 43 200 bars: one month partition, as the pack writes it
WINDOW = 5_000
RUNS = 7
# Reader time / bare DuckDB execute + to_arrow_table time, fastest of 7 each. Set at 1.5x the
# post-fix median ratio (3.42 -> 5.1) and below every pre-fix ratio measured (5.84-6.27).
MAX_RATIO = 5.1


def _lake(root: Path) -> tuple[list[str], int]:
    rng = random.Random(2523)  # noqa: S311 - seeded, reproducible test data
    t0 = int(datetime(2026, 8, 1, tzinfo=UTC).timestamp() * 1_000_000)
    price, opens, highs, lows, closes, volumes, turnovers = 60_000.0, [], [], [], [], [], []
    for _ in range(ROWS):
        o = price
        c = round(o + rng.uniform(-40, 40), 1)
        v = round(rng.uniform(0, 50), 3)
        opens.append(o)
        highs.append(round(max(o, c) + rng.uniform(0, 20), 1))
        lows.append(round(min(o, c) - rng.uniform(0, 20), 1))
        closes.append(c)
        volumes.append(v)
        turnovers.append(v * (o + c) / 2)
        price = c
    table = pa.table(
        {
            "ts": pa.array([t0 + i * MIN for i in range(ROWS)], type=pa.timestamp("us", tz="UTC")),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "turnover": turnovers,
            "confirmed": [True] * ROWS,
            "source": ["tape"] * ROWS,
        }
    )
    f = _write_table(root, "2026-08", table, iv="1")
    return [f.as_posix()], t0 + (ROWS - 1440) * MIN  # the window ends a day before the edge


def _bare(files: list[str], lo: int, hi: int) -> float:
    con = duckdb.connect(":memory:", config={"memory_limit": "256MiB", "threads": "2"})
    try:
        con.execute("SET TimeZone = 'UTC'")
        t0 = time.perf_counter()
        table = con.execute(
            "SELECT * FROM read_parquet($files, hive_partitioning = false, union_by_name = true) "
            "WHERE ts >= make_timestamptz($lo::BIGINT) AND ts < make_timestamptz($hi::BIGINT) "
            "QUALIFY row_number() OVER (PARTITION BY ts ORDER BY ts) = 1 "
            "ORDER BY ts DESC LIMIT $n",
            {"files": files, "lo": lo, "hi": hi, "n": WINDOW + 100},
        ).to_arrow_table()
        ms = (time.perf_counter() - t0) * 1000
    finally:
        con.close()
    assert table.num_rows == WINDOW
    return ms


@pytest.mark.perf
async def test_cold_5000_bar_read_cost_over_a_bare_duckdb_scan_is_bounded(tmp_path: Path) -> None:
    files, end = _lake(tmp_path)
    lo = end - WINDOW * MIN
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    assert len(await reader("BTCUSDT", "1", Range(lo, end))) == WINDOW  # warm-up + verify
    _bare(files, lo, end)
    read_ms: list[float] = []
    bare_ms: list[float] = []
    gc.disable()
    try:
        for _ in range(RUNS):
            t0 = time.perf_counter()
            rows = await reader("BTCUSDT", "1", Range(lo, end))
            read_ms.append((time.perf_counter() - t0) * 1000)
            assert len(rows) == WINDOW
            bare_ms.append(_bare(files, lo, end))
    finally:
        gc.enable()
    ratio = min(read_ms) / min(bare_ms)
    print(
        f"\n#2523 cold {WINDOW}-bar read: reader min {min(read_ms):.1f} ms "
        f"(all {[round(x, 1) for x in read_ms]}), bare DuckDB min {min(bare_ms):.1f} ms "
        f"(all {[round(x, 1) for x in bare_ms]}), ratio {ratio:.2f} (bound {MAX_RATIO})"
    )
    assert ratio <= MAX_RATIO


CONCURRENCY = 5  # the pack's REST profile (`scenarios/rest_k6.json`, k6 VUs)
ROUNDS = 20


def _p95(samples: list[float]) -> float:
    """Nearest-rank p95, as the pack reads it."""
    ordered = sorted(samples)
    return ordered[max(0, -(-95 * len(ordered) // 100) - 1)]


@pytest.mark.perf
async def test_five_concurrent_cold_5000_bar_reads_report_their_p95_against_budget_13(
    tmp_path: Path,
) -> None:
    write_cold_lake(tmp_path)
    app = await build_app(tmp_path)
    base = "http://127.0.0.1"
    assert_loopback_target(base)
    spec = requests_plan()["klines_cold"]
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    samples: list[float] = []
    async with httpx.AsyncClient(transport=transport, base_url=base) as client:

        async def one() -> float:
            t0 = time.perf_counter()
            r = await client.get(spec["path"], params=spec["params"])
            ms = (time.perf_counter() - t0) * 1000
            assert r.status_code == 200
            assert len(r.json()["bars"]) == WINDOW
            return ms

        await one()  # untimed warm-up: verifies the month once, opens the shared instance
        for _ in range(ROUNDS):
            samples += await asyncio.gather(*(one() for _ in range(CONCURRENCY)))
    p95 = _p95(samples)
    verdict = "pass" if p95 <= B13_READ_P95_MS else f"{p95:.1f} > {B13_READ_P95_MS:g}"
    # Reported, not gated (#399's smoke pattern): this becomes `assert p95 <= B13_READ_P95_MS`
    # in the follow-up gc.freeze PR under #2523.
    print(
        f"\n#2523 {CONCURRENCY} concurrent cold {WINDOW}-bar reads x {ROUNDS} rounds: "
        f"p50 {sorted(samples)[len(samples) // 2]:.1f} ms, p95 {p95:.1f} ms, "
        f"max {max(samples):.1f} ms (Budget #13 {B13_READ_P95_MS} ms): {verdict}, "
        "reported, not gated"
    )
    assert len(samples) == ROUNDS * CONCURRENCY

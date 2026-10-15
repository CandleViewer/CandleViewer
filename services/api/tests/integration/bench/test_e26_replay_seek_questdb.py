"""E26-K01 hot-tier bench against a REAL QuestDB (CI `integration` job).

Writes a SYNTHETIC 200-depth span (dense profile, 120 s, ~260 k delta level-rows) through the
production `IlpWriter`, waits for WAL apply, then times the replay-seek read shapes (#7 of
`21-database-schema.md` Sec.13.2 via `QuestDbReader`) and a full sequential delta scan. Numbers are
printed as one JSON line (`E26K01_HOT=`) for the spike note; the only assertions are correctness
(row counts) so a slow runner never fails the job.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from bench.replay_seek import synth
from candleviewer.storage.models import TimeRange
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.reader import (
    QuestDbReader,
    build_read_book_deltas,
    build_read_book_snapshot_at,
)
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS

pytestmark = pytest.mark.integration

DDL_DIR = Path(__file__).resolve().parents[5] / "backend" / "db" / "questdb"
_USER, _PASSWORD = "admin", "quest"
SPAN_S = 120


class _Exec:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._c = conn

    async def execute(self, sql: str, *args: object) -> None:
        await self._c.execute(sql, *args)

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        return [dict(r) for r in await self._c.fetch(sql, *args)]


class _Tcp:
    def __init__(self, host: str, port: int) -> None:
        self._host, self._port = host, port
        self._w: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        _, self._w = await asyncio.open_connection(self._host, self._port)

    async def write(self, data: bytes) -> None:
        assert self._w is not None
        self._w.write(data)
        await self._w.drain()

    async def close(self) -> None:
        if self._w is not None:
            self._w.close()
            with contextlib.suppress(Exception):
                await self._w.wait_closed()


async def _connect(host: str, port: int) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=host, port=port, user=_USER, password=_PASSWORD, database="qdb"
    )


@pytest_asyncio.fixture
async def questdb() -> AsyncIterator[tuple[str, int, int]]:
    from testcontainers.core.container import DockerContainer

    with DockerContainer("questdb/questdb:8.1.1").with_exposed_ports(8812, 9009) as c:
        host, pg, ilp = (
            c.get_container_host_ip(),
            int(c.get_exposed_port(8812)),
            int(c.get_exposed_port(9009)),
        )
        for _ in range(60):
            try:
                await (await _connect(host, pg)).close()
                break
            except OSError:
                await asyncio.sleep(1.0)
        yield host, pg, ilp


async def _wait_count(
    conn: asyncpg.Connection, table: str, n: int, timeout_s: float = 180.0
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    sql = f"SELECT count() FROM {table}"  # noqa: S608  # nosec B608 - test-owned literal table
    while int(await conn.fetchval(sql)) != n:
        assert asyncio.get_running_loop().time() < deadline, f"{table} never reached {n} rows"
        await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_e26_k01_hot_tier_seek_and_scan(questdb: tuple[str, int, int]) -> None:
    host, pg, ilp = questdb
    s = synth.generate(synth.DENSE, 200, SPAN_S, 26_001)
    conn = await _connect(host, pg)
    try:
        await run_migrations(_Exec(conn), DDL_DIR)
        writer = IlpWriter(_Tcp(host, ilp), ALL_SCHEMAS)
        await writer.start()
        deltas = s.deltas.drop_columns(["recv_ts"]).to_pylist()
        snaps = s.snapshots.drop_columns(["recv_ts"]).to_pylist()
        t0 = time.perf_counter()
        for off in range(0, len(deltas), 50_000):
            await writer.write_rows("orderbook_deltas", deltas[off : off + 50_000], "ts")
        await writer.write_rows("orderbook_snapshots", snaps, "ts")
        await writer.stop()
        await _wait_count(conn, "orderbook_deltas", len(deltas))
        await _wait_count(conn, "orderbook_snapshots", len(snaps))
        ingest_s = time.perf_counter() - t0

        reader = QuestDbReader(conn)
        end = synth.SPAN0_US + SPAN_S * 1_000_000
        out: dict[str, object] = {
            "label": "SYNTHETIC dense 200-depth, 120 s span, CI runner",
            "delta_rows": len(deltas),
            "ingest_plus_wal_s": round(ingest_s, 2),
        }
        for interval in (30, 60):
            target = synth.SPAN0_US + interval * 1_000_000 - 1
            anchor = synth.SPAN0_US
            runs = []
            for _ in range(5):
                a = time.perf_counter()
                await reader.run(build_read_book_snapshot_at(synth.SYMBOL, target))
                b = time.perf_counter()
                rows = await reader.run(
                    build_read_book_deltas(
                        synth.SYMBOL, TimeRange(start_us=anchor, end_us=target + 1)
                    )
                )
                runs.append(
                    {
                        "anchor_ms": (b - a) * 1e3,
                        "deltas_ms": (time.perf_counter() - b) * 1e3,
                        "rows": len(rows),
                    }
                )
            out[f"seek_read_{interval}s"] = runs
        a = time.perf_counter()
        rows = await reader.run(
            build_read_book_deltas(synth.SYMBOL, TimeRange(start_us=synth.SPAN0_US, end_us=end))
        )
        dt = time.perf_counter() - a
        out["scan_events_per_s"] = round(len(rows) / dt)
        assert len(rows) == len(deltas)
        print("E26K01_HOT=" + json.dumps(out))
    finally:
        await conn.close()

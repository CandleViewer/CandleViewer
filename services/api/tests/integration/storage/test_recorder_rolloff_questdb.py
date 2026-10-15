"""Integration: real QuestDB + real Parquet roll-off round-trip for one partition
(E16-T05). Needs Docker (testcontainers QuestDB 8.x); runs in CI's
`integration` job and only collects locally without Docker.

Seeds two days of BTCUSDT trades, runs `RollOffJob` with an injected clock so
only the older day is outside the 7-day hot window, then asserts: the old
partition is in Parquet (count + checksum verified), dropped from QuestDB
(`table_partitions()`), the watermark advanced, the newer day stays hot, and
a DuckDB view over the cold tier returns the archived rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from candleviewer.recorder.rolloff import RollOffConfig, RollOffJob
from candleviewer.storage.cold.duckdb_views import build_views, query_symbol_day_count
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.questdb_source import QuestDbHotTierSource
from candleviewer.storage.cold.rolloff_ops import ColdArchiver, QuestDbHotPartitions
from candleviewer.storage.cold.watermarks import FileWatermarkStore
from candleviewer.storage.models import StreamKind
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.reader import QuestDbReader
from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from candleviewer.storage.repositories.rows import TradeRow
from tests.integration.storage.test_questdb_hot_tier import (
    DDL_DIR,
    _AsyncpgExecutor,
    _AsyncpgTcpIlpTransport,
    _connect,
    questdb_container,  # noqa: F401 -- pytest fixture re-export
    wait_for_row_count,
)

pytestmark = pytest.mark.integration

_OLD = datetime(2026, 10, 1, tzinfo=UTC)
_NEW = datetime(2026, 10, 9, tzinfo=UTC)
_NOW = datetime(2026, 10, 10, 2, 15, tzinfo=UTC)


def _us(d: datetime) -> int:
    return int(d.timestamp() * 1_000_000)


class _Audit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, str | int]]] = []

    async def write(self, action: str, detail: dict[str, str | int]) -> None:
        self.rows.append((action, detail))


class _Events:
    async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
        return None


class _Lock:
    @asynccontextmanager
    async def hold(self, volume: str) -> AsyncIterator[bool]:
        yield True


@pytest.mark.asyncio
async def test_rolloff_real_questdb_partition_export_verify_drop(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
    tmp_path: Path,
) -> None:
    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        writer = IlpWriter(_AsyncpgTcpIlpTransport(host, ilp_port), ALL_SCHEMAS)
        await writer.start()
        repo = QuestDbMarketDataRepository(writer, QuestDbReader(conn))
        rows = [
            TradeRow(
                ts_us=_us(base) + i * 1000,
                symbol="BTCUSDT",
                price=f"{65000 + i % 5}.5",
                qty="0.01",
                side="buy" if i % 2 else "sell",
                trade_id=f"{base.day}-{i}",
            )
            for base in (_OLD, _NEW)
            for i in range(1200)
        ]
        await repo.write_trades(rows)
        await writer.flush("trades")
        await writer.stop()
        await wait_for_row_count(conn, "trades", 2400)

        pg = _AsyncpgExecutor(conn)
        reg = DatasetRegistry(tmp_path)
        source = QuestDbHotTierSource(pg)
        marks = FileWatermarkStore(reg)
        audit = _Audit()

        async def hot_days(symbol: str, stream: StreamKind) -> int | None:
            return 7

        job = RollOffJob(
            hot=QuestDbHotPartitions(pg),
            archiver=ColdArchiver(reg, source),
            watermarks=marks,
            hot_days=hot_days,
            audit=audit,
            events=_Events(),
            lock=_Lock(),
            config=RollOffConfig(streams=(StreamKind.TRADES,)),
            clock=lambda: _NOW,
        )
        report = await job.run()

        assert report.dropped == [(StreamKind.TRADES, _us(_OLD))]
        # Applied = absent, or listed but emptied: QuestDB can keep a dropped WAL partition listed
        # with numRows 0 / NULL minTimestamp until the purge job runs (the #2522 race), and
        # `drop_day` returns on exactly that signal, so the assertion mirrors it.
        parts = await pg.fetch("SELECT name, numRows, minTimestamp FROM table_partitions('trades')")
        live = {
            str(r["name"])
            for r in parts
            if int(r["numRows"] or 0) > 0 and r["minTimestamp"] is not None
        }
        assert "2026-10-01" not in live and "2026-10-09" in live
        assert await conn.fetchval("SELECT count() FROM trades") == 1200
        mark = await marks.get("BTCUSDT", StreamKind.TRADES)
        assert mark.archived_through_us == _us(_OLD + timedelta(days=1))
        assert audit.rows[0][0] == "retention.purge" and audit.rows[0][1]["rows"] == 1200

        db = tmp_path / "analytics.duckdb"
        build_views(db, reg)
        assert query_symbol_day_count(db, "trades", "BTCUSDT", "2026-10-01") == 1200
    finally:
        await conn.close()

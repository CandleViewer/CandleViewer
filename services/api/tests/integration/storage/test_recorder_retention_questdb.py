"""Integration (E16-T06): one real reaper pass over real QuestDB + real Parquet.

Seeds two BTCUSDT days, rolls the old one off with the real `RollOffJob` (archive + verify),
re-seeds it hot (so a hot day exists that the watermark proves archived), then runs one
`RetentionManager.run_nightly` with an injected clock and a 1-day total horizon:
the archived hot day is dropped (`table_partitions`), the expired Parquet partition directory
and its manifest are gone, the newer day stays hot, every deletion has exactly one
`data.deleted` written before it, and the audit records outlive the data they describe.
Needs Docker (testcontainers QuestDB 8.x); only collects locally without Docker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from candleviewer.recorder.retention import (
    MemoryCheckpoint,
    PolicyRow,
    RetentionConfig,
    RetentionManager,
)
from candleviewer.recorder.rolloff import RollOffConfig, RollOffJob
from candleviewer.retention_wiring import _Cold, _Hot
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.questdb_source import QuestDbHotTierSource
from candleviewer.storage.cold.retention_ops import ColdRetentionStore, QuestDbRetentionHotStore
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

T = StreamKind.TRADES
_OLD = datetime(2026, 10, 1, tzinfo=UTC)
_NEW = datetime(2026, 10, 9, tzinfo=UTC)
_NOW = datetime(2026, 10, 10, 2, 15, tzinfo=UTC)


def _us(d: datetime) -> int:
    return int(d.timestamp() * 1_000_000)


class _Audit:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, str | int]]] = []

    async def write(self, action: str, detail: dict[str, str | int]) -> None:
        self.rows.append((action, dict(detail)))


class _Events:
    async def emit(self, severity: str, code: str, detail: dict[str, str | int]) -> None:
        return None


class _Lock:
    @asynccontextmanager
    async def hold(self, volume: str) -> AsyncIterator[bool]:
        yield True


class _Facts:
    async def symbols(self) -> list[str]:
        return ["BTCUSDT"]

    async def pinned(self) -> set[str]:
        return set()

    async def policies(self) -> Mapping[tuple[str | None, str], PolicyRow]:
        return {(None, "trades"): PolicyRow(None, "trades", 7, 1)}


async def _seed(conn: object, host: str, ilp_port: int, base: datetime, n: int) -> None:
    writer = IlpWriter(_AsyncpgTcpIlpTransport(host, ilp_port), ALL_SCHEMAS)
    await writer.start()
    repo = QuestDbMarketDataRepository(writer, QuestDbReader(conn))  # type: ignore[arg-type]  # asyncpg conn
    await repo.write_trades(
        [
            TradeRow(
                ts_us=_us(base) + i * 1000,
                symbol="BTCUSDT",
                price=f"{65000 + i % 5}.5",
                qty="0.01",
                side="buy" if i % 2 else "sell",
                trade_id=f"{base.day}-{i}",
            )
            for i in range(n)
        ]
    )
    await writer.flush("trades")
    await writer.stop()


async def test_retention_real_pass_drops_archived_hot_day_and_expired_parquet(
    questdb_container: tuple[str, int, int],  # noqa: F811 -- fixture injection
    tmp_path: Path,
) -> None:
    host, pg_port, ilp_port = questdb_container
    conn = await _connect(host, pg_port)
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        await _seed(conn, host, ilp_port, _OLD, 1200)
        await _seed(conn, host, ilp_port, _NEW, 1200)
        await wait_for_row_count(conn, "trades", 2400)
        pg = _AsyncpgExecutor(conn)
        reg = DatasetRegistry(tmp_path)
        marks = FileWatermarkStore(reg)

        async def hot_days(symbol: str, stream: StreamKind) -> int | None:
            return 7

        await RollOffJob(
            hot=QuestDbHotPartitions(pg),
            archiver=ColdArchiver(reg, QuestDbHotTierSource(pg)),
            watermarks=marks,
            hot_days=hot_days,
            audit=_Audit(),
            events=_Events(),
            lock=_Lock(),
            config=RollOffConfig(streams=(T,)),
            clock=lambda: _NOW,
        ).run()
        await _seed(conn, host, ilp_port, _OLD, 10)  # a late hot copy of the archived day
        await wait_for_row_count(conn, "trades", 1210)
        cold = ColdRetentionStore(reg)
        assert [p.rows for p in await cold.partitions("BTCUSDT", T)] == [1200]

        audit = _Audit()
        mgr = RetentionManager(
            hot=_Hot(QuestDbRetentionHotStore(pg)),
            cold=_Cold(cold),
            facts=_Facts(),
            watermarks=marks,
            audit=audit,
            events=_Events(),
            lock=_Lock(),
            checkpoint=MemoryCheckpoint(),
            config=RetentionConfig(hot_streams=(T,), cold_streams=(T,)),
            clock=lambda: _NOW,
        )
        report = await mgr.run_nightly()

        held = [(i.tier, i.key, why) for i, why in report.failed] + [
            (p.item.tier, p.item.key, f"{p.reason}:{p.info}") for p in report.skipped
        ]
        wal = await pg.fetch("SELECT * FROM wal_tables() WHERE name = 'trades'")
        parts = await pg.fetch("SELECT * FROM table_partitions('trades')")
        assert sorted(i.tier for i in report.deleted) == ["cold", "hot"], (held, wal, parts)
        # A dropped partition may stay listed empty (numRows 0, null minTimestamp): not data.
        names = {
            str(r["name"])
            for r in await pg.fetch(
                "SELECT name, numRows, minTimestamp FROM table_partitions('trades')"
            )
            if int(str(r["numRows"] or 0)) > 0 and r["minTimestamp"] is not None
        }
        assert "2026-10-01" not in names and "2026-10-09" in names, parts
        assert await cold.partitions("BTCUSDT", T) == []
        assert not (tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-01").exists()
        deleted = [d for a, d in audit.rows if a == "data.deleted"]
        assert len(deleted) == 2 and {d["rows"] for d in deleted} == {10, 1200}
        assert [a for a, _ in audit.rows][-1] == "retention.run"  # outlives the data
    finally:
        await conn.close()

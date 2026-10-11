"""Integration (E16-T10): one public-archive day (the committed synthetic fixture) through the real
adapter parse + integrity check, the importer, and the real Parquet cold writer, then read back
through `TierRouter` + `ParquetColdTierRepository` (DuckDB) with `meta.sources == ['parquet']`.

No network: the adapter's `fetch` is the only HTTP step and is served by respx at the transport.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from candleviewer.exchange.bybit.archive import BybitTradeArchive
from candleviewer.recorder.importer import BulkImporter, ImportRequest
from candleviewer.storage.cold.archive_import import ColdArchiveDayWriter, FileImportLedger
from candleviewer.storage.cold.exporter import HotTierSource
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.parquet_repository import ParquetColdTierRepository
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.router import TierRouter

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[2] / "fixtures" / "archive" / "BTCUSDT2026-06-05.csv.gz"
DAY = date(2026, 6, 5)
LO = int(datetime(2026, 6, 5, tzinfo=UTC).timestamp()) * 1_000_000


async def _no_recorded(symbol: str, lo: int, hi: int) -> list[tuple[int, int]]:
    return []


@respx.mock
async def test_archive_day_round_trip_parquet_router_meta_sources(tmp_path: Path) -> None:
    respx.get(url__regex=r".*BTCUSDT2026-06-05\.csv\.gz$").mock(
        return_value=httpx.Response(200, content=FIXTURE.read_bytes())
    )
    reg = DatasetRegistry(tmp_path)
    async with httpx.AsyncClient() as client:
        summary = await BulkImporter(
            source=BybitTradeArchive(client=client),
            writer=ColdArchiveDayWriter(reg),
            ledger=FileImportLedger(reg),
            backlog_rows=lambda: 0,
            disk_usage=None,
            recorded=_no_recorded,
        ).run(ImportRequest("BTCUSDT", DAY, DAY))
    assert (summary.files_processed, summary.rows_written, summary.skipped) == (1, 6, [])

    repo = ParquetColdTierRepository(reg, source=_unused_hot())
    rng = TimeRange(start_us=LO, end_us=LO + 86_400_000_000)

    async def cold(sym: str, r: TimeRange) -> list[dict[str, object]]:
        return await repo.query(sym, StreamKind.TRADES, r)

    async def hot(sym: str, r: TimeRange) -> list[dict[str, object]]:
        raise AssertionError("hot tier must not be read for an archived window")

    router = TierRouter(
        {StreamKind.TRADES: hot},
        {StreamKind.TRADES: cold},
        lambda _s: 30,
        clock_us=lambda: LO + 120 * 86_400_000_000,
    )
    got = await router.read(StreamKind.TRADES, "BTCUSDT", rng)
    assert got.sources == ["parquet"]
    assert len(got.rows) == 6
    first = got.rows[0]
    assert first["_source"] == "archive" and first["side"] == "buy"
    assert Decimal(repr(first["price"])) == Decimal("67012.5")
    assert first["trade_id"] == "00000000-0000-4000-8000-000000000000"


def _unused_hot() -> HotTierSource:
    class _Hot:
        def iter_partition(self, *a: object, **k: object) -> object:
            raise AssertionError("export path unused")

        async def count_partition(self, *a: object) -> int:
            raise AssertionError("export path unused")

    return _Hot()  # type: ignore[return-value]  # test stub: never called

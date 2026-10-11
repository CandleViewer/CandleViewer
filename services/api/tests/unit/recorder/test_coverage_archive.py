"""E16-T10 Scenario "Imported windows are labelled archive-derived": coverage over an imported-only
window reports `trades` with source `archive` (cold tier) and `orderbook_delta` as absent; a
recorded window always wins over an archive window (no double counting)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from candleviewer.recorder.coverage import CoverageService
from candleviewer.recorder.importer import BulkImporter, ImportRequest
from candleviewer.recorder.sessions import to_dt
from candleviewer.storage.cold.archive_import import ColdArchiveDayWriter, FileImportLedger
from candleviewer.storage.cold.layout import DatasetRegistry
from tests.unit.recorder._session_fakes import MemRecorderStore
from tests.unit.recorder.test_importer import FakeArchive, day_lo

D = 86_400_000_000


def _session(store: MemRecorderStore, lo: int, hi: int, streams: list[str]) -> None:
    store.sessions["s1"] = {
        "id": "s1", "symbol": "BTCUSDT", "state": "stopped", "streams": streams,
        "started_at": to_dt(lo), "ended_at": to_dt(hi), "first_event_ts": to_dt(lo),
        "last_event_ts": to_dt(hi), "end_reason": "stopped",
    }  # fmt: skip


async def _import(root: Path, store: MemRecorderStore, svc: CoverageService) -> None:
    reg = DatasetRegistry(root)
    await BulkImporter(
        source=FakeArchive(),
        writer=ColdArchiveDayWriter(reg),
        ledger=FileImportLedger(reg),
        recorded=svc.recorded_windows,
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
    ).run(ImportRequest("BTCUSDT", date(2026, 6, 1), date(2026, 6, 3)))


async def test_coverage_imported_only_window_trades_archive_orderbook_absent(
    tmp_path: Path,
) -> None:
    store = MemRecorderStore()
    lo = day_lo(date(2026, 6, 1))
    svc = CoverageService(
        store, now_us=lambda: lo + 120 * D, archive=FileImportLedger(DatasetRegistry(tmp_path))
    )
    await _import(tmp_path, store, svc)
    trades, book = await svc.coverage("BTCUSDT", ["trades", "orderbook_delta"], lo, lo + 3 * D)
    assert [(i.lo, i.hi, i.tier, i.source) for i in trades.intervals] == [
        (lo, lo + 3 * D, "parquet", "archive")  # adjacent imported days merge
    ]
    assert book.intervals == ()


async def test_coverage_recorded_window_wins_over_archive(tmp_path: Path) -> None:
    store = MemRecorderStore()
    lo = day_lo(date(2026, 6, 1))
    _session(store, lo + D + 3_600_000_000, lo + 4 * D, ["trades", "orderbook_delta"])
    svc = CoverageService(
        store, now_us=lambda: lo + 120 * D, archive=FileImportLedger(DatasetRegistry(tmp_path))
    )
    await _import(tmp_path, store, svc)
    (trades,) = await svc.coverage("BTCUSDT", ["trades"], lo, lo + 3 * D)
    got: list[tuple[Any, ...]] = [(i.lo, i.hi, i.source) for i in trades.intervals]
    assert got == [
        (lo, lo + D + 3_600_000_000, "archive"),
        (lo + D + 3_600_000_000, lo + 3 * D, "recorded"),
    ]


async def test_recorded_windows_only_sessions_carrying_the_stream(tmp_path: Path) -> None:
    store = MemRecorderStore()
    _session(store, 10, 50, ["orderbook_delta"])
    svc = CoverageService(store, now_us=lambda: 100)
    assert await svc.recorded_windows("BTCUSDT", 0, 100) == []
    _session(store, 10, 50, ["trades"])
    assert await svc.recorded_windows("BTCUSDT", 20, 100) == [(20, 50)]

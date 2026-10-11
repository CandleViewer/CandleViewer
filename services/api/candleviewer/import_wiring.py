"""Composition of the public trade-archive import (E16-T10).

Builds the `ImportRunner` the admin router calls: the venue archive source (from the exchange
adapter service), the storage-side cold day writer + import ledger under `CV_PARQUET_ROOT`, and
the recorded-window query from `CoverageService`. Only on the `real` storage backend with a
coverage service; otherwise the route answers 503 (fails closed).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

from candleviewer.api.recorder_admin import ImportRunner
from candleviewer.recorder.coverage import CoverageService
from candleviewer.recorder.importer import ArchiveSource, BulkImporter, DiskUsage, ImportRequest
from candleviewer.storage.cold.archive_import import ColdArchiveDayWriter, FileImportLedger
from candleviewer.storage.cold.layout import DatasetRegistry


def build_import_runner(
    source: ArchiveSource,
    parquet_root: str,
    coverage: CoverageService | None,
    backlog_rows: Callable[[], int],
    disk_usage: DiskUsage | None = None,
) -> ImportRunner | None:
    """`backlog_rows` is required: production passes the recorder's published write backlog
    (`recorder.metrics.current_write_backlog_rows`) so live capture always wins."""
    if coverage is None:
        return None
    registry = DatasetRegistry(parquet_root)

    def cold_volume_usage() -> tuple[int, int]:
        root = registry.root
        root.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(Path(root))
        return usage.total, usage.used

    importer = BulkImporter(
        source=source,
        writer=ColdArchiveDayWriter(registry),
        ledger=FileImportLedger(registry),
        recorded=coverage.recorded_windows,
        backlog_rows=backlog_rows,
        disk_usage=disk_usage or cold_volume_usage,  # always guarded in production
    )

    async def run(
        symbol: str, start: date, end: date, progress: Callable[[float], None]
    ) -> dict[str, object]:
        summary = await importer.run(ImportRequest(symbol, start, end), progress)
        return summary.as_result()

    return run

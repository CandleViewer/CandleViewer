"""Composition of the public trade-archive import (E16-T10).

Builds the `ImportRunner` the admin router calls: the venue archive source (from the exchange
adapter service), the storage-side cold day writer + import ledger under `CV_PARQUET_ROOT`, and
the recorded-window query from `CoverageService`. Only on the `real` storage backend with a
coverage service and the recorder's running `DiskBudget`; otherwise the route answers 503 (fails
closed). The import honours that budget: it refuses at the budget's AUTOSTOP level or on a
refused volume, fits each day within `min(cap - used, free)` as well as the cold volume's own
ratio, and never creates a missing cold root.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path

from candleviewer.api.recorder_admin import ImportRunner
from candleviewer.recorder.budget import RECORDED_TIERS, DiskBudget
from candleviewer.recorder.coverage import CoverageService
from candleviewer.recorder.importer import (
    ArchiveSource,
    BulkImporter,
    DiskUsage,
    ImportDiskBudgetExceeded,
    ImportDiskPressure,
    ImportRequest,
    ImportRootMissing,
    import_refused_total,
)
from candleviewer.storage.cold.archive_import import ColdArchiveDayWriter, FileImportLedger
from candleviewer.storage.cold.layout import DatasetRegistry


def _budget_room(budget: DiskBudget) -> int:
    """Bytes the recorder's disk budget still admits: `min(cap - used, free)` from its last
    sample, `used` being the recorded tiers it measured. Refuses at AUTOSTOP or above or on a
    refused volume, and fails closed until a sample has measured those tiers."""
    if budget.refuses_auto_record:
        import_refused_total.labels(reason="disk_pressure").inc()
        raise ImportDiskPressure("the recorder's disk budget refuses new data")
    report = budget.report()
    tiers = [] if report is None else [t for t in report.tiers if t.tier in RECORDED_TIERS]
    if report is None or not tiers:
        import_refused_total.labels(reason="disk_budget").inc()
        raise ImportDiskBudgetExceeded("the recorder's disk use is not measured yet")
    used = sum(t.used_bytes for t in tiers)
    return min(budget.config.cap_bytes - used, report.disk_free_bytes)


def build_import_runner(
    source: ArchiveSource,
    parquet_root: str,
    coverage: CoverageService | None,
    backlog_rows: Callable[[], int],
    disk_usage: DiskUsage | None = None,
    *,
    budget: DiskBudget | None,
) -> ImportRunner | None:
    """`backlog_rows` is required: production passes the recorder's published write backlog
    (`recorder.metrics.current_write_backlog_rows`) so live capture always wins. So is `budget`:
    production passes the recorder's running `DiskBudget`, and without one nothing is composed."""
    if coverage is None or budget is None:
        return None
    registry = DatasetRegistry(parquet_root)

    def cold_volume_usage() -> tuple[int, int]:
        root = registry.root
        if not root.is_dir():  # refused, never created
            import_refused_total.labels(reason="root_missing").inc()
            raise ImportRootMissing("the cold root is missing")
        usage = shutil.disk_usage(Path(root))
        return usage.total, usage.used

    importer = BulkImporter(
        source=source,
        writer=ColdArchiveDayWriter(registry),
        ledger=FileImportLedger(registry),
        recorded=coverage.recorded_windows,
        backlog_rows=backlog_rows,
        disk_usage=disk_usage or cold_volume_usage,  # always guarded in production
        room=partial(_budget_room, budget),
    )

    async def run(
        symbol: str, start: date, end: date, progress: Callable[[float], None]
    ) -> dict[str, object]:
        summary = await importer.run(ImportRequest(symbol, start, end), progress)
        return summary.as_result()

    return run

"""E16-T10 composition: `build_import_runner` fails closed without coverage and, when composed,
runs an import end to end into the cold root (fake archive source, no network)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from candleviewer.import_wiring import build_import_runner
from candleviewer.recorder.coverage import CoverageService
from tests.unit.recorder._session_fakes import MemRecorderStore
from tests.unit.recorder.test_importer import FakeArchive


def test_build_import_runner_none_without_coverage(tmp_path: Path) -> None:
    assert build_import_runner(FakeArchive(), str(tmp_path), None) is None


async def test_build_import_runner_imports_into_cold_root(tmp_path: Path) -> None:
    svc = CoverageService(MemRecorderStore(), now_us=lambda: 0)
    run = build_import_runner(FakeArchive(), str(tmp_path), svc, backlog_rows=lambda: 0)
    assert run is not None
    seen: list[float] = []
    result = await run("BTCUSDT", date(2026, 6, 1), date(2026, 6, 2), seen.append)
    assert result["rows_written"] == 48 and result["source"] == "archive"
    assert seen[-1] == 100.0
    assert _dirs(tmp_path) == [
        "dt=2026-06-01", "dt=2026-06-02"
    ]  # fmt: skip


def _dirs(root: Path) -> list[str]:
    return sorted(p.parent.name for p in (root / "trades").rglob("*.parquet"))

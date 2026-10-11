"""E16-T10 composition: `build_import_runner` fails closed without coverage and, when composed,
runs an import end to end into the cold root (fake archive source, no network)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from candleviewer.import_wiring import build_import_runner
from candleviewer.recorder.coverage import CoverageService
from tests.unit.recorder._session_fakes import MemRecorderStore
from tests.unit.recorder.test_importer import FakeArchive


def _ROOMY() -> tuple[int, int]:
    return 1_000_000, 0


def test_build_import_runner_none_without_coverage(tmp_path: Path) -> None:
    assert build_import_runner(FakeArchive(), str(tmp_path), None, backlog_rows=lambda: 0) is None


async def test_build_import_runner_imports_into_cold_root(tmp_path: Path) -> None:
    svc = CoverageService(MemRecorderStore(), now_us=lambda: 0)
    run = build_import_runner(
        FakeArchive(), str(tmp_path), svc, backlog_rows=lambda: 0, disk_usage=_ROOMY
    )
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


def test_build_import_runner_requires_backlog_provider() -> None:
    import inspect

    param = inspect.signature(build_import_runner).parameters["backlog_rows"]
    assert param.default is inspect.Parameter.empty


def test_app_wires_recorder_backlog_gauge_into_import_runner() -> None:
    """Production composition passes the live backlog source, never None (review #1)."""
    import ast
    from pathlib import Path as _P

    import candleviewer.app as app_mod

    tree = ast.parse(_P(app_mod.__file__).read_text(encoding="utf-8"))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "build_import_runner"
    ]  # fmt: skip
    assert len(calls) == 1
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert isinstance(kw["backlog_rows"], ast.Name)
    assert kw["backlog_rows"].id == "current_write_backlog_rows"


async def test_composed_runner_pauses_while_recorder_backlog_nonzero(tmp_path: Path) -> None:
    """The composed runner polls the recorder's published backlog and waits until it drains
    before fetching (one 0.25 s poll here; the live writer drains on the second read)."""
    from candleviewer.recorder.metrics import (
        current_write_backlog_rows,
        recorder_write_backlog_rows,
    )

    polls: list[int] = []
    src = FakeArchive()

    def backlog() -> int:
        value = current_write_backlog_rows()
        polls.append(value)
        if value:
            assert src.fetches == [], "fetched while the live backlog was non-zero"
            recorder_write_backlog_rows.set(0)  # live writer drains during the pause
        return value

    recorder_write_backlog_rows.set(500)
    try:
        svc = CoverageService(MemRecorderStore(), now_us=lambda: 0)
        run = build_import_runner(src, str(tmp_path), svc, backlog_rows=backlog, disk_usage=_ROOMY)
        assert run is not None
        await run("BTCUSDT", date(2026, 6, 1), date(2026, 6, 1), lambda _p: None)
    finally:
        recorder_write_backlog_rows.set(0)
    assert polls[:2] == [500, 0] and src.fetches == [date(2026, 6, 1)]


async def test_composed_runner_disk_guard_defaults_on_and_refuses(tmp_path: Path) -> None:
    from candleviewer.recorder.importer import ImportDiskBudgetExceeded

    svc = CoverageService(MemRecorderStore(), now_us=lambda: 0)
    full = build_import_runner(
        FakeArchive(), str(tmp_path), svc, backlog_rows=lambda: 0, disk_usage=lambda: (100, 95)
    )
    assert full is not None
    with pytest.raises(ImportDiskBudgetExceeded):
        await full("BTCUSDT", date(2026, 6, 1), date(2026, 6, 1), lambda _p: None)
    assert not _dirs(tmp_path)

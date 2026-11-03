"""#5396: the write-hole ledger is composed with a real row sink only, loaded before the writer
starts and flushed after it stops."""

from __future__ import annotations

from pathlib import Path

import pytest

from candleviewer.app import build_app_context, create_app
from candleviewer.bars.rows import bar_row
from candleviewer.bars.write_holes import WriteHoleLedger, hole_key_for_row
from candleviewer.bars_wiring import wire_bars
from tests.unit.bars.test_bars_persistence import SPEC, _bar
from tests.unit.test_bars_wiring import _settings

T0 = 1_700_000_000_000_000


class _Refusing:
    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        raise ValueError("not stored")  # a permanent outcome


def test_no_ledger_without_a_real_row_sink(tmp_path: Path) -> None:
    ctx = build_app_context(_settings(tmp_path))
    assert wire_bars(ctx, now_us=lambda: T0).holes is None
    assert create_app(_settings(tmp_path)).state.bars_runtime.holes is None


@pytest.mark.asyncio
async def test_ledger_loads_before_the_writer_and_flushes_after_it(tmp_path: Path) -> None:
    root = tmp_path / "bars"
    earlier = WriteHoleLedger(root)
    row = bar_row(_bar(index=9, open_time=T0 + 9), SPEC, generation=3)
    earlier.lost([hole_key_for_row(row, SPEC.spec_hash, SPEC.kind)], "shutdown")
    await earlier.flush()
    ctx = build_app_context(_settings(tmp_path))
    runtime = wire_bars(ctx, now_us=lambda: T0, inner_sink=_Refusing())
    assert runtime.holes is not None
    await runtime.start()
    assert [r.reason for r in runtime.holes.pending()] == ["shutdown"]  # read before any write
    await runtime.writer.submit([_bar(index=1, open_time=T0 + 1)], SPEC, generation=3)
    await runtime.stop()
    reread = WriteHoleLedger(root)
    assert await reread.load() == "ok"
    assert sorted(r.reason for r in reread.pending()) == ["permanent", "shutdown"]


def test_a_dropped_series_degrades_the_bars_writer(tmp_path: Path) -> None:
    """Past the ledger's hard series cap a dropped series is an under-report: `bars_writer`
    reports DEGRADED with `bars_write_holes_dropped` (24 §19.81)."""
    ctx = build_app_context(_settings(tmp_path))
    runtime = wire_bars(ctx, now_us=lambda: T0, inner_sink=_Refusing())
    assert runtime.holes is not None and runtime.writer_state() == (False, "")
    runtime.holes.dropped = True
    assert runtime.writer_state() == (True, "bars_write_holes_dropped")


@pytest.mark.asyncio
async def test_a_discarded_journal_degrades_the_bars_writer(tmp_path: Path) -> None:
    """A journal `load` discards loses the holes it held: `bars_writer` reports DEGRADED."""
    root = tmp_path / "bars"
    root.mkdir()
    (root / "write_holes.json").write_bytes(b"{not json")
    ctx = build_app_context(_settings(tmp_path))
    runtime = wire_bars(ctx, now_us=lambda: T0, inner_sink=_Refusing())
    await runtime.start()
    try:
        assert runtime.writer_state() == (True, "bars_write_holes_dropped")
    finally:
        await runtime.stop()

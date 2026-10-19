"""Chaos scenarios 4-7 (E07-Q04): export crash points, verify mismatch, corruption.

Invariant under test (21-database-schema.md Sec.5.3): duplicate is harmless,
missing is not. The exporter never mutates the hot source.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from candleviewer.storage.cold import exporter as exporter_mod
from candleviewer.storage.cold.parquet_repository import ParquetColdTierRepository
from candleviewer.storage.errors import StorageExportVerifyFailed
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.router import TierRouter
from tests.chaos.storage._harness import PART, Crash, Rig
from tests.unit.storage.cold._helpers import FakeHotSource, day_range

pytestmark = pytest.mark.chaos
N = 40
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_US = timedelta(microseconds=1)


async def test_s4_crash_before_manifest_reconciles_to_single_entry(
    rig: Rig, arm_crash: Callable[[str], None]
) -> None:
    arm_crash("AFTER_CHECKSUM")  # file committed + checksummed, manifest not yet written
    with pytest.raises(Crash):
        await rig.exporter().export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    assert rig.entries() == [], "INVARIANT: no manifest entry before the manifest step"
    assert rig.source.table.num_rows == N, "INVARIANT: hot partition untouched"

    exporter_mod._TEST_HOOKS.clear()
    run = await rig.exporter().export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    entries = rig.entries()
    assert len(entries) == 1, "INVARIANT: re-run reconciles to a single manifest entry"
    assert run.row_count == N and entries[0].row_count == N, "INVARIANT: zero rows lost"
    parts = sorted(p.name for p in (rig.root / PART).glob("part-*.parquet"))
    assert parts == [entries[0].file], "INVARIANT: orphan part file removed"


async def _straddling_read(rig: Rig) -> list[dict[str, Any]]:
    cold = ParquetColdTierRepository(rig.registry, rig.source, events=rig.sink)
    hot_rows = rig.source.table.to_pylist()

    async def hot(_s: str, _r: TimeRange) -> list[dict[str, Any]]:
        return hot_rows

    async def cold_reader(s: str, r: TimeRange) -> list[dict[str, Any]]:
        rows = await cold.query(s, StreamKind.TRADES, r)
        # cold reads surface `ts` as tz-aware datetime; normalise to epoch-us like the hot reader
        return [{**x, "ts": (x["ts"] - _EPOCH) // _US} for x in rows]

    boundary = day_range().start_us + 1  # hot window starts mid-range => straddle
    router = TierRouter(
        {StreamKind.TRADES: hot},
        {StreamKind.TRADES: cold_reader},
        lambda _s: 1,
        clock_us=lambda: boundary + 86_400_000_000,
    )
    routed = await router.read(StreamKind.TRADES, "BTCUSDT", day_range(), "auto")
    assert routed.tier == "both"
    return routed.rows


async def test_s5_crash_after_manifest_before_drop_duplicates_are_harmless(
    rig: Rig, arm_crash: Callable[[str], None]
) -> None:
    arm_crash("AFTER_MANIFEST")
    with pytest.raises(Crash):
        await rig.exporter().export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    assert len(rig.entries()) == 1, "rows exist in the cold tier"
    assert rig.source.table.num_rows == N, "INVARIANT: hot rows still present (drop never ran)"
    rows = await _straddling_read(rig)
    keys = [(r["ts"], r["symbol"], r["trade_id"]) for r in rows]
    assert len(keys) == len(set(keys)) == N, "INVARIANT: straddling read returns each row once"


async def test_s6_verify_mismatch_aborts_critical_and_retains_hot(rig: Rig) -> None:
    rig.source = FakeHotSource(rig.source.table, count_override=N + 3)
    with pytest.raises(StorageExportVerifyFailed):
        await rig.exporter().export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    assert (
        "CRITICAL",
        "STORAGE_EXPORT_VERIFY_FAILED",
    ) in rig.codes(), "INVARIANT: CRITICAL system_events on verify mismatch"
    assert rig.entries() == [], "INVARIANT: nothing manifested, so nothing is droppable"
    assert not list((rig.root / PART).glob("part-*.parquet")), "no partial cold file kept"
    assert rig.source.table.num_rows == N, "INVARIANT: hot data fully retained"


async def test_s7_corrupted_parquet_is_quarantined_and_read_fails_loudly(rig: Rig) -> None:
    await rig.exporter().export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    file = next((rig.root / PART).glob("part-*.parquet"))
    raw = bytearray(file.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    file.write_bytes(bytes(raw))

    cold = ParquetColdTierRepository(rig.registry, rig.source, events=rig.sink)
    with pytest.raises(StorageExportVerifyFailed):
        await cold.query("BTCUSDT", StreamKind.TRADES, day_range())
    assert ("CRITICAL", "STORAGE_COLD_FILE_QUARANTINED") in rig.codes()
    assert not file.exists(), "INVARIANT: corrupt file moved out of the dataset tree"
    assert (rig.root / "_quarantine").exists()
    # INVARIANT: nothing served from the quarantined file, and the day never reads as empty
    # while its quarantine stands (#3477).
    with pytest.raises(StorageExportVerifyFailed, match="quarantined part"):
        await cold.query("BTCUSDT", StreamKind.TRADES, day_range())


def test_hooks_cannot_be_armed_outside_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.delitem(sys.modules, "pytest")
    with pytest.raises(RuntimeError):
        exporter_mod.arm_test_hook("AFTER_CHECKSUM", lambda: None)
    assert exporter_mod._TEST_HOOKS == {}


def test_unknown_hook_point_rejected() -> None:
    with pytest.raises(ValueError):
        exporter_mod.arm_test_hook("NOPE", lambda: None)

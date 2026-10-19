"""Unit tests: `ParquetColdTierRepository` — Protocol conformance, query
round-trip, verify-on-read quarantine (AC 3), dataset-id registry (AC 9)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from candleviewer.storage.cold.layout import DatasetNotRegistered, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore
from candleviewer.storage.cold.parquet_repository import (
    DownsampleNotImplemented,
    ParquetColdTierRepository,
    downsample,
)
from candleviewer.storage.cold.scrub import scrub_all
from candleviewer.storage.errors import StorageExportVerifyFailed
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.cold import ColdTierRepository
from tests.unit.storage.cold._helpers import (
    DAY_START_US,
    FakeHotSource,
    RecordingSink,
    day_range,
    quarantine_before_next_read,
    trades_table,
)

PART = Path("trades") / "symbol=BTCUSDT" / "dt=2026-10-17"


def _repo(root: Path, n: int = 5, sink: RecordingSink | None = None) -> ParquetColdTierRepository:
    return ParquetColdTierRepository(
        DatasetRegistry(root), FakeHotSource(trades_table(n)), events=sink
    )


def test_repository_is_protocol_conformant(tmp_path: Path) -> None:
    assert isinstance(_repo(tmp_path), ColdTierRepository)


async def test_export_then_query_round_trips_rows_in_ts_order(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 5)
    await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    sub = TimeRange(start_us=DAY_START_US + 1, end_us=DAY_START_US + 4)
    rows = await repo.query("BTCUSDT", StreamKind.TRADES, sub)
    assert [int(r["ts"].timestamp() * 1_000_000) for r in rows] == [
        DAY_START_US + 1,
        DAY_START_US + 2,
        DAY_START_US + 3,
    ]
    assert all(r["ts"].utcoffset().total_seconds() == 0 for r in rows)
    assert await repo.query("ETHUSDT", StreamKind.TRADES, day_range()) == []


async def test_list_manifest_and_verify_checksums(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 4)
    run = await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    [listed] = await repo.list_manifest("BTCUSDT", StreamKind.TRADES)
    assert (listed.run_id, listed.row_count, listed.partition_range) == (
        run.run_id,
        4,
        day_range(),
    )
    assert await repo.verify_checksums(run) is True
    assert await repo.list_manifest("ETHUSDT", StreamKind.TRADES) == []


async def test_corrupted_byte_is_quarantined_alerted_and_never_served(tmp_path: Path) -> None:
    sink = RecordingSink()
    repo = _repo(tmp_path, 5, sink)
    await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    f = tmp_path / PART / "part-0000.parquet"
    data = bytearray(f.read_bytes())
    data[len(data) // 2] ^= 0x01
    f.write_bytes(bytes(data))
    with pytest.raises(StorageExportVerifyFailed):
        await repo.query("BTCUSDT", StreamKind.TRADES, day_range())
    assert sink.events[-1][:2] == ("CRITICAL", "STORAGE_COLD_FILE_QUARANTINED")
    assert (tmp_path / "_quarantine" / PART / "part-0000.parquet").exists()
    with pytest.raises(StorageExportVerifyFailed, match="quarantined part"):  # never an empty day
        await repo.query("BTCUSDT", StreamKind.TRADES, day_range())


FIRST = TimeRange(start_us=DAY_START_US, end_us=DAY_START_US + 3)
SECOND = TimeRange(start_us=DAY_START_US + 3, end_us=DAY_START_US + 5)


def _second_source(root: Path) -> ParquetColdTierRepository:
    """Exports the day's last two trades, `SECOND`, as a part of their own."""
    late = trades_table(2, start_us=SECOND.start_us)
    return ParquetColdTierRepository(DatasetRegistry(root), FakeHotSource(late))


async def _day_that_lost_its_second_part(root: Path) -> ParquetColdTierRepository:
    """#3477: two disjoint parts in one day; the second goes bad, and the query that finds it
    quarantines it."""
    await _repo(root, 3).export_partition("BTCUSDT", StreamKind.TRADES, FIRST)
    await _second_source(root).export_partition("BTCUSDT", StreamKind.TRADES, SECOND)
    bad = root / PART / "part-0001.parquet"
    bad.write_bytes(bad.read_bytes() + b"x")
    repo = _repo(root)
    with pytest.raises(StorageExportVerifyFailed, match="sha256 mismatch"):
        await repo.query("BTCUSDT", StreamKind.TRADES, day_range())
    return repo


async def test_a_day_that_lost_a_part_is_refused_never_served_partly(tmp_path: Path) -> None:
    """C-2.14: the manifest no longer names the quarantined part, so the first part alone would
    pass for the whole day. The refusal names no path."""
    repo = await _day_that_lost_its_second_part(tmp_path)

    for _ in range(2):
        with pytest.raises(StorageExportVerifyFailed, match="quarantined part") as err:
            await repo.query("BTCUSDT", StreamKind.TRADES, day_range())
        assert "/" not in str(err.value)


async def test_a_repository_that_verified_the_day_refuses_it_once_the_scrub_quarantines_a_part(
    tmp_path: Path,
) -> None:
    """The weekly scrub quarantines without any query: the part that stays verified in the
    repository's cache must not be served as the whole day."""
    await _repo(tmp_path, 3).export_partition("BTCUSDT", StreamKind.TRADES, FIRST)
    await _second_source(tmp_path).export_partition("BTCUSDT", StreamKind.TRADES, SECOND)
    repo = _repo(tmp_path)
    assert len(await repo.query("BTCUSDT", StreamKind.TRADES, day_range())) == 5
    bad = tmp_path / PART / "part-0001.parquet"
    bad.write_bytes(bad.read_bytes() + b"x")
    assert await scrub_all(DatasetRegistry(tmp_path), RecordingSink()) == 1

    with pytest.raises(StorageExportVerifyFailed, match="quarantined part"):
        await repo.query("BTCUSDT", StreamKind.TRADES, day_range())


async def test_clearing_the_quarantine_after_a_re_export_restores_the_day(tmp_path: Path) -> None:
    repo = await _day_that_lost_its_second_part(tmp_path)
    rerun = await _second_source(tmp_path).export_partition("BTCUSDT", StreamKind.TRADES, SECOND)
    assert await repo.verify_checksums(rerun) is True  # the re-export verifies before the clear
    with pytest.raises(StorageExportVerifyFailed, match="quarantined part"):  # until cleared
        await repo.query("BTCUSDT", StreamKind.TRADES, day_range())

    shutil.rmtree(tmp_path / "_quarantine" / PART)  # the runbook's last step

    rows = await repo.query("BTCUSDT", StreamKind.TRADES, day_range())
    assert [int(r["ts"].timestamp() * 1_000_000) - DAY_START_US for r in rows] == [0, 1, 2, 3, 4]


async def test_a_quarantine_landing_just_before_the_manifest_read_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _repo(tmp_path, 3).export_partition("BTCUSDT", StreamKind.TRADES, FIRST)
    await _second_source(tmp_path).export_partition("BTCUSDT", StreamKind.TRADES, SECOND)
    quarantine_before_next_read(monkeypatch, "part-0001.parquet")

    with pytest.raises(StorageExportVerifyFailed, match="quarantined part"):
        await _repo(tmp_path).query("BTCUSDT", StreamKind.TRADES, day_range())


async def test_a_day_whose_part_went_missing_is_refused_rather_than_read_empty(
    tmp_path: Path,
) -> None:
    """The scrub quarantines a part found missing by its manifest entry alone."""
    repo = _repo(tmp_path, 2)
    await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    (tmp_path / PART / "part-0000.parquet").unlink()
    assert await scrub_all(DatasetRegistry(tmp_path), RecordingSink()) == 1

    with pytest.raises(StorageExportVerifyFailed, match="quarantined part"):
        await repo.query("BTCUSDT", StreamKind.TRADES, day_range())


async def test_a_day_that_cannot_be_listed_is_refused_typed_naming_no_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path, 2)
    await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())

    def denied(self: ManifestStore, partition_dir: Path, cold_root: Path) -> object:
        raise PermissionError(13, "Permission denied", str(partition_dir))

    monkeypatch.setattr(ManifestStore, "read_with_quarantine", denied)

    with pytest.raises(StorageExportVerifyFailed, match="could not be listed") as err:
        await repo.query("BTCUSDT", StreamKind.TRADES, day_range())
    assert str(tmp_path) not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__


async def test_a_quarantine_on_one_day_leaves_the_next_day_served(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 2)
    await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    store = ManifestStore(tmp_path / "_manifests")
    store.quarantine(tmp_path / PART, tmp_path, "part-0000.parquet")  # as verification does
    day = 86_400_000_000
    next_day = TimeRange(start_us=DAY_START_US + day, end_us=DAY_START_US + 2 * day)
    later = trades_table(2, start_us=next_day.start_us)
    await ParquetColdTierRepository(
        DatasetRegistry(tmp_path), FakeHotSource(later)
    ).export_partition("BTCUSDT", StreamKind.TRADES, next_day)

    rows = await repo.query("BTCUSDT", StreamKind.TRADES, next_day)

    assert len(rows) == 2


async def test_missing_file_is_flagged(tmp_path: Path) -> None:
    repo = _repo(tmp_path, 2, RecordingSink())
    run = await repo.export_partition("BTCUSDT", StreamKind.TRADES, day_range())
    (tmp_path / PART / "part-0000.parquet").unlink()
    with pytest.raises(StorageExportVerifyFailed, match="missing"):
        await repo.verify_checksums(run)


@pytest.mark.parametrize("symbol", ["../../etc/passwd", "..", "/etc", "C:\\x", "a/b", ""])
async def test_query_rejects_traversal_symbols_without_reading(tmp_path: Path, symbol: str) -> None:
    with pytest.raises(DatasetNotRegistered):
        await _repo(tmp_path).query(symbol, StreamKind.TRADES, day_range())
    with pytest.raises(DatasetNotRegistered):
        await _repo(tmp_path).list_manifest(symbol, StreamKind.TRADES)


async def test_query_rejects_stream_not_addressable_by_day(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not addressable"):
        await _repo(tmp_path).query("BTCUSDT", StreamKind.KLINES, day_range())


def test_downsample_raises_not_implemented_referencing_e16() -> None:
    with pytest.raises(DownsampleNotImplemented, match="E16"):
        downsample(StreamKind.ORDERBOOK_DELTA, day_range())

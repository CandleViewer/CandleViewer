"""E16-T10 `BulkImporter`: every Gherkin scenario, against a fake archive source (counts
fetches) and the real storage-side cold writer + ledger under `tmp_path` (no network).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.domain.archive import (
    ArchiveChecksumFailed,
    ArchiveFile,
    ArchiveParseFailed,
    ArchiveRangeInvalid,
    ArchiveTrade,
)
from candleviewer.recorder.importer import (
    BulkImporter,
    ImportRequest,
    merge_windows,
    split_overlap,
)
from candleviewer.storage.cold.archive_import import ColdArchiveDayWriter, FileImportLedger
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore, sha256_of

DAY_US = 86_400_000_000
H = 3_600_000_000
SYM = "BTCUSDT"


def day_lo(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()) * 1_000_000


class FakeArchive:
    """`TradeArchiveSource` fake: 24 rows/day (one per hour), deterministic ids."""

    def __init__(self, *, corrupt: set[date] | None = None, bad_parse: set[date] | None = None):
        self.fetches: list[date] = []
        self.corrupt = corrupt or set()
        self.bad_parse = bad_parse or set()
        self.cancel_after: int | None = None
        self.in_flight = 0
        self.peak = 0

    @property
    def max_concurrency(self) -> int:
        return 2

    def list_files(self, symbol: str, start: date, end: date) -> list[ArchiveFile]:
        if end < start:
            raise ArchiveRangeInvalid("invalid date range")
        n = (end - start).days + 1
        days = [start + timedelta(days=i) for i in range(n)]
        return [ArchiveFile(symbol, d, f"{symbol}{d.isoformat()}.csv.gz") for d in days]

    async def fetch(self, file: ArchiveFile) -> bytes:
        if self.cancel_after is not None and len(self.fetches) >= self.cancel_after:
            raise asyncio.CancelledError
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        self.fetches.append(file.day)
        return file.day.isoformat().encode()

    def verify_checksum(self, file: ArchiveFile, raw: bytes) -> str:
        if file.day in self.corrupt:
            raise ArchiveChecksumFailed("gzip integrity check failed")
        return hashlib.sha256(raw).hexdigest()

    def parse(
        self, file: ArchiveFile, raw: bytes, batch_rows: int
    ) -> Iterator[Sequence[ArchiveTrade]]:
        if file.day in self.bad_parse:
            raise ArchiveParseFailed("unexpected column set")
        lo = day_lo(file.day)
        rows = [
            ArchiveTrade(
                ts_us=lo + h * H + 500,
                symbol=file.symbol,
                side="buy" if h % 2 else "sell",
                price=Decimal("67000.1") + h,
                size=Decimal("0.001"),
                trade_id=f"{file.day.isoformat()}-{h}",
            )
            for h in range(24)
        ]
        for i in range(0, len(rows), batch_rows):
            yield rows[i : i + batch_rows]


class Recorded:
    def __init__(self, windows: list[tuple[int, int]] | None = None) -> None:
        self.windows = windows or []

    async def __call__(self, symbol: str, lo: int, hi: int) -> list[tuple[int, int]]:
        return [(max(a, lo), min(b, hi)) for a, b in self.windows if a < hi and b > lo]


def _importer(root: Path, src: FakeArchive, rec: Recorded | None = None) -> BulkImporter:
    reg = DatasetRegistry(root)
    return BulkImporter(
        source=src,
        writer=ColdArchiveDayWriter(reg),
        ledger=FileImportLedger(reg),
        recorded=rec or Recorded(),
        clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        batch_rows=10,
    )


def _rows_on_disk(root: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for f in sorted((root / "trades").rglob("part-*.parquet")):
        t = pq.read_table(f, columns=["ts", "trade_id"])
        ts = pc.cast(t.column("ts"), "int64").to_pylist()
        out.extend(zip(ts, t.column("trade_id").to_pylist(), strict=True))
    return out


JUNE = (date(2026, 6, 1), date(2026, 6, 30))


async def test_import_date_range_summary_reports_files_rows_overlap_skipped(
    tmp_path: Path,
) -> None:
    """Scenario: Import a date range."""
    s = await _importer(tmp_path, FakeArchive()).run(ImportRequest(SYM, *JUNE))
    res = s.as_result()
    assert (res["files_total"], res["files_processed"], res["rows_written"]) == (30, 30, 720)
    assert (res["rows_discarded_overlap"], res["files_skipped"]) == (0, [])
    assert res["source"] == "archive" and res["streams"] == ["trades"]
    assert len(_rows_on_disk(tmp_path)) == 720
    part = tmp_path / "trades" / f"symbol={SYM}" / "dt=2026-06-01"
    entries = ManifestStore(tmp_path / "_manifests").read(part, tmp_path)
    assert len(entries) == 1 and entries[0].row_count == 24
    assert entries[0].sha256 == sha256_of(part / entries[0].file)
    assert entries[0].export_run_id.startswith("archive-import-")


async def test_import_recorded_window_wins_exact_bounds_and_no_duplicates(tmp_path: Path) -> None:
    """Scenario: Recorded data wins on overlap."""
    lo, hi = day_lo(date(2026, 6, 20)), day_lo(date(2026, 7, 1))
    s = await _importer(tmp_path, FakeArchive(), Recorded([(lo, hi)])).run(
        ImportRequest(SYM, *JUNE)
    )
    rows = _rows_on_disk(tmp_path)
    assert not [ts for ts, _ in rows if lo <= ts < hi]
    assert s.rows_discarded_overlap == 11 * 24 and s.rows_written == 19 * 24
    assert s.as_result()["overlap"] == [
        {"from": "2026-06-20T00:00:00Z", "to": "2026-07-01T00:00:00Z"}
    ]
    assert len(rows) == len(set(rows))  # natural key (ts, symbol, trade_id) unique


async def test_import_partial_day_overlap_reports_exact_sub_day_bounds(tmp_path: Path) -> None:
    d = date(2026, 6, 10)
    # rows sit at h*H + 500; half-open [lo, hi): h3 is just before lo, h5 is exactly hi
    lo, hi = day_lo(d) + 3 * H + 501, day_lo(d) + 5 * H + 500
    s = await _importer(tmp_path, FakeArchive(), Recorded([(lo, hi)])).run(ImportRequest(SYM, d, d))
    assert s.rows_discarded_overlap == 1 and s.rows_written == 23
    assert s.overlap == [(lo, hi)]


async def test_import_corrupt_file_skipped_named_and_rest_imported(tmp_path: Path) -> None:
    """Scenario: Corrupt file does not abort the import."""
    src = FakeArchive(corrupt={date(2026, 6, 7)}, bad_parse={date(2026, 6, 9)})
    s = await _importer(tmp_path, src).run(ImportRequest(SYM, *JUNE))
    assert s.as_result()["files_skipped"] == [
        {"file": "BTCUSDT2026-06-07.csv.gz", "reason": "import_checksum_failed"},
        {"file": "BTCUSDT2026-06-09.csv.gz", "reason": "import_parse_failed"},
    ]
    assert s.files_processed == 28 and s.rows_written == 28 * 24
    assert not list((tmp_path / "trades").rglob("dt=2026-06-09/*.parquet"))
    # a skipped day was never checkpointed, so the next run retries exactly those two
    src2 = FakeArchive()
    s2 = await _importer(tmp_path, src2).run(ImportRequest(SYM, *JUNE))
    assert sorted(src2.fetches) == [date(2026, 6, 7), date(2026, 6, 9)]
    assert s2.files_already_imported == 28


class _BlockingArchive(FakeArchive):
    """Every fetch after the first `n` blocks until cancelled (a cancel at 12/30)."""

    def __init__(self, n: int) -> None:
        super().__init__()
        self.n = n
        self.blocked = 0
        self.all_blocked = asyncio.Event()

    async def fetch(self, file: ArchiveFile) -> bytes:
        if len(self.fetches) >= self.n:
            self.blocked += 1
            if self.blocked == self.max_concurrency:
                self.all_blocked.set()
            await asyncio.Event().wait()
        return await super().fetch(file)


async def test_import_cancelled_after_12_resumes_at_13_without_redownload(tmp_path: Path) -> None:
    """Scenario: Import is resumable."""
    src = _BlockingArchive(12)
    task = asyncio.ensure_future(_importer(tmp_path, src).run(ImportRequest(SYM, *JUNE)))
    await asyncio.wait_for(src.all_blocked.wait(), timeout=30)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sorted(src.fetches) == [date(2026, 6, d) for d in range(1, 13)]
    src2 = FakeArchive()
    s = await _importer(tmp_path, src2).run(ImportRequest(SYM, *JUNE))
    assert min(src2.fetches) == date(2026, 6, 13) and len(src2.fetches) == 18
    assert s.files_already_imported == 12
    rows = _rows_on_disk(tmp_path)
    assert len(rows) == 720 == len(set(rows))


async def test_import_rerun_of_completed_import_is_noop(tmp_path: Path) -> None:
    await _importer(tmp_path, FakeArchive()).run(ImportRequest(SYM, *JUNE))
    before = _parquet_files(tmp_path)
    src = FakeArchive()
    s = await _importer(tmp_path, src).run(ImportRequest(SYM, *JUNE))
    assert src.fetches == [] and s.rows_written == 0 and s.files_already_imported == 30
    assert _parquet_files(tmp_path) == before


def _parquet_files(root: Path) -> list[str]:
    return sorted(str(p) for p in root.rglob("*.parquet"))


def _drop_ledger(root: Path) -> None:
    (root / "_manifests" / "_imports" / "trades" / f"symbol={SYM}.json").unlink()


async def test_import_crash_after_manifest_before_checkpoint_adopts_not_rewrites(
    tmp_path: Path,
) -> None:
    d = date(2026, 6, 3)
    await _importer(tmp_path, FakeArchive()).run(ImportRequest(SYM, d, d))
    _drop_ledger(tmp_path)
    s = await _importer(tmp_path, FakeArchive()).run(ImportRequest(SYM, d, d))
    assert s.rows_written == 24 and len(_rows_on_disk(tmp_path)) == 24


async def test_import_rows_already_in_cold_by_natural_key_are_not_duplicated(
    tmp_path: Path,
) -> None:
    d = date(2026, 6, 3)
    await _importer(tmp_path, FakeArchive()).run(ImportRequest(SYM, d, d))
    # Ledger lost AND the manifest entry no longer matches the day range: the import is
    # re-attempted, yet every row is already present by natural key, so nothing is written.
    _drop_ledger(tmp_path)
    part = tmp_path / "trades" / f"symbol={SYM}" / f"dt={d.isoformat()}"
    store = ManifestStore(tmp_path / "_manifests")
    [e] = store.read(part, tmp_path)
    store.write(part, tmp_path, [replace(e, range_end_us=e.range_end_us - 1)])
    s = await _importer(tmp_path, FakeArchive()).run(ImportRequest(SYM, d, d))
    assert s.rows_written == 0 and s.rows_discarded_duplicate == 24
    rows = _rows_on_disk(tmp_path)
    assert len(rows) == 24 == len(set(rows))


async def test_import_concurrency_never_exceeds_source_cap(tmp_path: Path) -> None:
    src = FakeArchive()
    await _importer(tmp_path, src).run(ImportRequest(SYM, *JUNE))
    assert 1 <= src.peak <= 2


async def test_import_invalid_range_raises_before_any_fetch(tmp_path: Path) -> None:
    src = FakeArchive()
    with pytest.raises(ArchiveRangeInvalid):
        await _importer(tmp_path, src).run(ImportRequest(SYM, date(2026, 6, 2), date(2026, 6, 1)))
    assert src.fetches == []


async def test_import_progress_monotonic_to_100(tmp_path: Path) -> None:
    seen: list[float] = []
    await _importer(tmp_path, FakeArchive()).run(
        ImportRequest(SYM, date(2026, 6, 1), date(2026, 6, 4)), seen.append
    )
    assert seen == sorted(seen) and seen[-1] == 100.0


async def test_import_yields_while_live_backlog_nonzero(tmp_path: Path) -> None:
    backlog = [5, 3, 0]
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    reg = DatasetRegistry(tmp_path)
    imp = BulkImporter(
        source=FakeArchive(),
        writer=ColdArchiveDayWriter(reg),
        ledger=FileImportLedger(reg),
        recorded=Recorded(),
        backlog_rows=lambda: backlog.pop(0) if len(backlog) > 1 else 0,
        sleep=fake_sleep,
    )
    d = date(2026, 6, 1)
    await imp.run(ImportRequest(SYM, d, d))
    assert len(slept) == 2


# -- pure overlap arithmetic + property -------------------------------------------------------


def test_merge_windows_merges_touching_and_drops_empty() -> None:
    assert merge_windows([(5, 9), (0, 3), (3, 4), (7, 7)]) == [(0, 4), (5, 9)]


def _trade(ts: int, i: int) -> ArchiveTrade:
    return ArchiveTrade(ts, SYM, "buy", Decimal("1"), Decimal("1"), f"t{i}")


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    ts=st.lists(st.integers(0, 10_000), max_size=200),
    raw=st.lists(st.tuples(st.integers(0, 10_000), st.integers(1, 2_000)), max_size=8),
)
def test_split_overlap_written_disjoint_from_recorded_and_partition_complete(
    ts: list[int], raw: list[tuple[int, int]]
) -> None:
    """For any recorded windows and archive rows: written rows intersect no recorded window,
    and written + discarded == parsed (exactly the rows inside a window are discarded)."""
    windows = merge_windows([(a, a + w) for a, w in raw])
    rows = [_trade(t, i) for i, t in enumerate(sorted(ts))]
    kept, discarded = split_overlap(rows, windows)
    assert not [r for r in kept if any(a <= r.ts_us < b for a, b in windows)]
    inside = [r for r in rows if any(a <= r.ts_us < b for a, b in windows)]
    assert len(kept) + discarded == len(rows) and discarded == len(inside)

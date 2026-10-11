"""Resumable bulk import of public trade archives into the cold tier (E16-T10, US-REC-007).

Pipeline per daily file: download -> integrity check -> parse (normalised `ArchiveTrade`) ->
overlap filter against recorded coverage (recorded wins: rows inside a recorded window are
discarded, counted and the exact window bounds reported) -> Parquet via the storage-side day
writer (E16-T05 layout + manifest, natural-key dedup) -> checkpoint in the import ledger, which
is also what `CoverageService` reads to label the window `source='archive'` for `trades` only.

Exchange-neutral: the venue adapter is injected through `ArchiveSource` (structurally the
`exchange.base` `TradeArchiveSource` port; recorder may not import exchange modules, §3 M11),
and storage through `DayWriter` / `ImportLedger` (ADR-0003: no storage driver here).

Resumable: a day is checkpointed only after its file + manifest are durable, so a cancelled
import re-run skips every finished day without downloading it, and a completed import re-run
is a no-op. A corrupt file (integrity, parse, size) is skipped and named with its reason.
Bounded: the adapter caps concurrency and bandwidth; this module runs at most
`max_concurrency` workers and yields while live capture has a write backlog.
"""

from __future__ import annotations

import asyncio
import bisect
import time
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Final, Protocol, cast

import structlog

from candleviewer.domain.archive import (
    ArchiveError,
    ArchiveFile,
    ArchiveRangeInvalid,
    ArchiveTrade,
)
from candleviewer.observability.metrics import Counter, Histogram

_DAY_US: Final = 86_400_000_000
BATCH_ROWS: Final = 50_000
#: Longest the importer waits for a live-capture backlog to drain before proceeding anyway.
BACKLOG_YIELD_MAX_S: Final = 30.0
_BACKLOG_POLL_S: Final = 0.25
MAX_SKIPPED_REPORTED: Final = 400

import_files_total = Counter("import_files_total", "Archive import files, by result.", ["result"])
import_rows_written_total = Counter("import_rows_written_total", "Archive rows written to cold.")
import_rows_discarded_total = Counter(
    "import_rows_discarded_total", "Archive rows discarded, by reason.", ["reason"]
)
import_bytes_downloaded_total = Counter(
    "import_bytes_downloaded_total", "Archive bytes downloaded."
)
import_duration_seconds = Histogram("import_duration_seconds", "Wall time of one archive import.")


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class ArchiveSource(Protocol):
    @property
    def max_concurrency(self) -> int: ...

    def list_files(self, symbol: str, start: date, end: date) -> list[ArchiveFile]: ...

    async def fetch(self, file: ArchiveFile) -> bytes: ...

    def verify_checksum(self, file: ArchiveFile, raw: bytes) -> str: ...

    def parse(
        self, file: ArchiveFile, raw: bytes, batch_rows: int
    ) -> Iterator[Sequence[ArchiveTrade]]: ...


class DayResult(Protocol):
    @property
    def rows_written(self) -> int: ...

    @property
    def rows_duplicate(self) -> int: ...

    @property
    def file(self) -> str | None: ...


class DaySink(Protocol):
    @property
    def already_done(self) -> DayResult | None: ...

    async def write(self, rows: Sequence[ArchiveTrade], now_us: int) -> None: ...

    async def commit(self, now_us: int) -> DayResult: ...

    async def abort(self) -> None: ...


class DayWriter(Protocol):
    async def open_day(self, symbol: str, day: date, lo: int, hi: int) -> DaySink: ...


class ImportLedger(Protocol):
    async def done_days(self, symbol: str) -> set[date]: ...

    async def mark_done(
        self, symbol: str, day: date, lo: int, hi: int, rows: int, sha256: str, file: str | None
    ) -> None: ...


#: `(symbol, lo_us, hi_us) -> sorted recorded [lo, hi) windows` (CoverageService, trades).
RecordedWindows = Callable[[str, int, int], Awaitable[list[tuple[int, int]]]]


def _day_bounds(day: date) -> tuple[int, int]:
    lo = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * 1_000_000
    return lo, lo + _DAY_US


def _iso(us: int) -> str:
    return (
        (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=us))
        .isoformat()
        .replace("+00:00", "Z")
    )


def split_overlap(
    rows: Sequence[ArchiveTrade], windows: Sequence[tuple[int, int]]
) -> tuple[list[ArchiveTrade], int]:
    """`(kept, discarded)`: rows with `ts` inside any sorted, disjoint `[lo, hi)` window are
    discarded (recorded wins). Pure; O(n log w)."""
    if not windows:
        return list(rows), 0
    starts = [w[0] for w in windows]
    kept: list[ArchiveTrade] = []
    for r in rows:
        i = bisect.bisect_right(starts, r.ts_us) - 1
        if i >= 0 and r.ts_us < windows[i][1]:
            continue
        kept.append(r)
    return kept, len(rows) - len(kept)


def merge_windows(windows: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for lo, hi in sorted(w for w in windows if w[1] > w[0]):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


@dataclass(slots=True)
class ImportSummary:
    symbol: str
    start: date
    end: date
    files_total: int = 0
    files_processed: int = 0
    files_already_imported: int = 0
    rows_written: int = 0
    rows_discarded_overlap: int = 0
    rows_discarded_duplicate: int = 0
    bytes_downloaded: int = 0
    overlap: list[tuple[int, int]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def as_result(self) -> dict[str, object]:
        """The `Job.result` document rendered on SCR-142 (logical names only, no paths)."""
        return {
            "symbol": self.symbol,
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "files_total": self.files_total,
            "files_processed": self.files_processed,
            "files_already_imported": self.files_already_imported,
            "files_skipped": [
                {"file": f, "reason": r} for f, r in self.skipped[:MAX_SKIPPED_REPORTED]
            ],
            "rows_written": self.rows_written,
            "rows_discarded_overlap": self.rows_discarded_overlap,
            "rows_discarded_duplicate": self.rows_discarded_duplicate,
            "overlap": [{"from": _iso(a), "to": _iso(b)} for a, b in self.overlap],
            "bytes_downloaded": self.bytes_downloaded,
            "streams": ["trades"],
            "source": "archive",
        }


@dataclass(frozen=True, slots=True)
class ImportRequest:
    symbol: str
    start: date
    end: date


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BulkImporter:
    """One import run (`run`); the admin job wraps it. Safe to re-run with the same request."""

    def __init__(
        self,
        *,
        source: ArchiveSource,
        writer: DayWriter,
        ledger: ImportLedger,
        recorded: RecordedWindows,
        clock: Callable[[], datetime] = _utc_now,
        backlog_rows: Callable[[], int] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        batch_rows: int = BATCH_ROWS,
        day_timeout_s: float = 3600.0,
    ) -> None:
        self._src = source
        self._writer = writer
        self._ledger = ledger
        self._recorded = recorded
        self._clock = clock
        self._backlog = backlog_rows
        self._sleep = sleep
        self._batch_rows = batch_rows
        self._day_timeout_s = day_timeout_s

    def _now_us(self) -> int:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("importer clock must be tz-aware UTC")
        return int(now.timestamp() * 1_000_000)

    async def _yield_to_live(self) -> None:
        """Live capture always wins: pause while the recorder has a write backlog."""
        if self._backlog is None:
            return
        waited = 0.0
        while self._backlog() > 0 and waited < BACKLOG_YIELD_MAX_S:
            await self._sleep(_BACKLOG_POLL_S)
            waited += _BACKLOG_POLL_S

    async def run(
        self, req: ImportRequest, progress: Callable[[float], None] = lambda _p: None
    ) -> ImportSummary:
        files = self._src.list_files(req.symbol, req.start, req.end)  # validates the range
        summary = ImportSummary(req.symbol, req.start, req.end, files_total=len(files))
        started = time.perf_counter()
        done = await self._ledger.done_days(req.symbol)
        todo = [f for f in files if f.day not in done]
        summary.files_already_imported = len(files) - len(todo)
        finished = summary.files_already_imported
        progress(100.0 * finished / max(1, len(files)))
        overlap: list[tuple[int, int]] = []
        queue: asyncio.Queue[ArchiveFile] = asyncio.Queue(maxsize=max(1, len(todo)))
        for f in todo:
            queue.put_nowait(f)

        async def worker() -> None:
            nonlocal finished
            while True:
                try:
                    f = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                await self._yield_to_live()
                await self._one(f, summary, overlap)
                finished += 1
                progress(100.0 * finished / max(1, len(files)))

        workers = max(1, min(self._src.max_concurrency, len(todo)))
        async with asyncio.TaskGroup() as tg:
            for i in range(workers):
                tg.create_task(worker(), name=f"archive-import-{i}")
        summary.overlap = merge_windows(overlap)
        summary.skipped.sort()
        import_duration_seconds.observe(time.perf_counter() - started)
        logger().info(
            "archive_import_done",
            symbol=req.symbol,
            files=summary.files_processed,
            skipped=len(summary.skipped),
            rows=summary.rows_written,
            overlap_rows=summary.rows_discarded_overlap,
        )
        return summary

    async def _one(
        self, f: ArchiveFile, summary: ImportSummary, overlap: list[tuple[int, int]]
    ) -> None:
        lo, hi = _day_bounds(f.day)
        try:
            async with asyncio.timeout(self._day_timeout_s):
                raw = await self._src.fetch(f)
                summary.bytes_downloaded += len(raw)
                import_bytes_downloaded_total.inc(len(raw))
                sha = await asyncio.to_thread(self._src.verify_checksum, f, raw)
                windows = merge_windows(
                    [(max(a, lo), min(b, hi)) for a, b in await self._recorded(f.symbol, lo, hi)]
                )
                written, dup, out_file, discarded = await self._write_day(f, raw, lo, hi, windows)
        except ArchiveError as exc:
            summary.skipped.append((f.name, exc.code))
            import_files_total.labels(result="skipped").inc()
            logger().warning("archive_import_file_skipped", file=f.name, reason=exc.code)
            return
        await self._ledger.mark_done(f.symbol, f.day, lo, hi, written, sha, out_file)
        overlap.extend(windows)
        summary.files_processed += 1
        summary.rows_written += written
        summary.rows_discarded_overlap += discarded
        summary.rows_discarded_duplicate += dup
        import_files_total.labels(result="imported").inc()
        import_rows_written_total.inc(written)
        import_rows_discarded_total.labels(reason="overlap").inc(discarded)
        import_rows_discarded_total.labels(reason="duplicate").inc(dup)

    async def _write_day(
        self, f: ArchiveFile, raw: bytes, lo: int, hi: int, windows: list[tuple[int, int]]
    ) -> tuple[int, int, str | None, int]:
        sink = await self._writer.open_day(f.symbol, f.day, lo, hi)
        prior = sink.already_done
        if prior is not None:  # crash after manifest, before ledger: adopt, never rewrite
            return prior.rows_written, 0, prior.file, 0
        now_us = self._now_us()
        discarded = 0
        batches = self._src.parse(f, raw, self._batch_rows)
        try:
            while True:
                batch = await asyncio.to_thread(next, batches, None)
                if batch is None:
                    break
                kept, n = split_overlap(batch, windows)
                discarded += n
                if kept:
                    await sink.write(kept, now_us)
            result = await sink.commit(now_us)
        except BaseException:
            await asyncio.shield(sink.abort())
            raise
        return result.rows_written, result.rows_duplicate, result.file, discarded


__all__ = [
    "ArchiveRangeInvalid",
    "BulkImporter",
    "ImportRequest",
    "ImportSummary",
    "merge_windows",
    "split_overlap",
]

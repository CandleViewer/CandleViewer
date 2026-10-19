"""Compactor — `21-database-schema.md` Sec.5.4 as code.

Merges small-file partitions into a single `part-0000.parquet`, recording
row count and SHA-256 of the merged output *before* deleting originals
(same atomicity discipline as the exporter). Skips any partition referenced
by an active `replay_sessions` row (the idle guard) — until E07-T02's table
exists, `active_replay_partitions` reads an empty set (a test covers that
path per this ticket's own "Dependencies" note).
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import structlog

from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore, sha256_of
from candleviewer.storage.cold.observability import (
    LoggingSystemEventSink,
    SystemEventSink,
    storage_compaction_files_merged_total,
)
from candleviewer.storage.cold.partition_lock import partition_write_lock
from candleviewer.storage.cold.writer import (
    MARKET_DATA_PROFILE,
    sweep_stale_temps,
    write_parquet_file,
)
from candleviewer.storage.errors import StorageExportVerifyFailed

_PART_RE = re.compile(r"^part-(\d{4})\.parquet$")

#: Sec.5.4 trigger thresholds.
MERGE_TRIGGER_FILE_COUNT = 4
SMALL_FILE_THRESHOLD_BYTES = 16 * 1024 * 1024
MERGE_TARGET_MAX_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """One partition's compaction outcome — `skipped=True` covers both the
    idle-guard skip and the below-threshold no-op case."""

    partition_dir: Path
    skipped: bool
    reason: str = ""
    merged_file: str | None = None
    row_count: int = 0
    sha256: str = ""


def should_compact(file_sizes_bytes: list[int]) -> bool:
    """Sec.5.4 trigger: ">4 files in a partition, or any file <16 MiB with
    siblings"."""
    if len(file_sizes_bytes) <= 1:
        return False
    if len(file_sizes_bytes) > MERGE_TRIGGER_FILE_COUNT:
        return True
    return any(size < SMALL_FILE_THRESHOLD_BYTES for size in file_sizes_bytes)


#: Async predicate: given a partition directory, returns the active
#: `replay_sessions.id` referencing it, or `None`. Default (no DB wired yet)
#: always returns `None` — a test asserts this "empty set" path explicitly
#: (ticket "Dependencies": "until then the guard reads an empty set").
IdleGuard = Callable[[Path], Awaitable[str | None]]


async def _default_idle_guard(_partition_dir: Path) -> str | None:
    return None


class Compactor:
    """Merges one partition directory's Parquet files into `part-0000`,
    honouring the idle guard and the 512 MiB merge-target cap.

    Crash-safe ordering (Sec.5.4 "Safety"): the merged output is written to a
    fresh part name via `.tmp` -> fsync -> rename, its row count and SHA-256
    are verified and recorded in the manifest, and only then are the
    originals deleted; finally it is linked to `part-0000`. A crash at any
    point leaves either the originals (manifest unchanged) or the merged file
    (manifest updated) as manifested truth, never neither. Unmanifested part
    files left by an earlier crash are removed at the start of a run.
    """

    def __init__(
        self,
        idle_guard: IdleGuard = _default_idle_guard,
        *,
        events: SystemEventSink | None = None,
        max_merge_bytes: int = MERGE_TARGET_MAX_BYTES,
    ) -> None:
        self._idle_guard = idle_guard
        self._events: SystemEventSink = events or LoggingSystemEventSink()
        self._max_merge_bytes = max_merge_bytes

    async def compact_partition(
        self, partition_dir: Path, cold_root: Path, manifests_dir: Path
    ) -> CompactionResult:
        rel_dir = partition_dir.relative_to(cold_root).as_posix()
        session_id = await self._idle_guard(partition_dir)
        if session_id is not None:
            structlog.get_logger(__name__).info(
                "cold_compaction_skip_active_replay", partition=rel_dir, session_id=session_id
            )
            return CompactionResult(
                partition_dir=partition_dir,
                skipped=True,
                reason=f"active replay_sessions id={session_id}",
            )
        store = ManifestStore(manifests_dir)
        async with partition_write_lock(partition_dir):
            plan = await asyncio.to_thread(self._plan, store, partition_dir, cold_root)
            if plan is None:
                return CompactionResult(
                    partition_dir=partition_dir, skipped=True, reason="below threshold"
                )
            # Shielded: once originals may be deleted the step must finish.
            result = await asyncio.shield(
                asyncio.to_thread(self._merge, store, partition_dir, cold_root, plan)
            )
        storage_compaction_files_merged_total.inc(len(plan))
        await self._events.emit(
            "INFO",
            "STORAGE_COMPACTION_DELETED_ORIGINALS",
            {
                "partition": rel_dir,
                "files": ",".join(e.file for e in plan),
                "merged_rows": result.row_count,
                "merged_sha256": result.sha256,
            },
        )
        return result

    def _plan(
        self, store: ManifestStore, partition_dir: Path, cold_root: Path
    ) -> list[ManifestEntry] | None:
        """Blocking: recover crash leftovers, then pick the manifested files
        to merge (by name, capped at `max_merge_bytes`)."""
        entries = store.read(partition_dir, cold_root)
        _reconcile_orphans(partition_dir, {e.file for e in entries})
        sized = sorted(
            ((e, (partition_dir / e.file).stat().st_size) for e in entries),
            key=lambda pair: pair[0].file,
        )
        if not should_compact([s for _, s in sized]):
            return None
        chosen: list[ManifestEntry] = []
        total = 0
        for entry, size in sized:
            if chosen and total + size > self._max_merge_bytes:
                break
            chosen.append(entry)
            total += size
        return chosen if len(chosen) > 1 else None

    def _merge(
        self,
        store: ManifestStore,
        partition_dir: Path,
        cold_root: Path,
        plan: list[ManifestEntry],
    ) -> CompactionResult:
        entries = store.read(partition_dir, cold_root)
        used = [int(m.group(1)) for e in entries if (m := _PART_RE.fullmatch(e.file))]
        staged = partition_dir / f"part-{max(used, default=0) + 1:04d}.parquet"

        tables = [pq.read_table(partition_dir / e.file) for e in plan]
        expected_rows = sum(e.row_count for e in plan)
        merged = pa.concat_tables(tables, promote_options="none")
        keys = [("ts", "ascending")]
        if "price" in merged.column_names:
            keys.append(("price", "ascending"))
        merged = merged.take(pc.sort_indices(merged, sort_keys=keys))
        write_parquet_file(merged, staged, profile=MARKET_DATA_PROFILE)
        del tables, merged

        merged_rows = pq.ParquetFile(staged).metadata.num_rows
        if merged_rows != expected_rows:
            staged.unlink(missing_ok=True)
            raise StorageExportVerifyFailed(
                f"compaction row-count mismatch: expected {expected_rows}, wrote {merged_rows}"
            )
        merged_sha = sha256_of(staged)
        merged_entry = ManifestEntry(
            file=staged.name,
            sha256=merged_sha,
            row_count=merged_rows,
            source_table=plan[0].source_table,
            export_run_id="compaction",
            exported_at_us=max(e.exported_at_us for e in plan),
            range_start_us=min(e.range_start_us for e in plan),
            range_end_us=max(e.range_end_us for e in plan),
        )
        merged_names = {e.file for e in plan}
        keep = [e for e in entries if e.file not in merged_names]
        store.write(partition_dir, cold_root, [*keep, merged_entry])
        for entry in plan:
            (partition_dir / entry.file).unlink(missing_ok=True)

        final_name = staged.name
        if not any(e.file == "part-0000.parquet" for e in keep):
            final_name = "part-0000.parquet"
            # Link the final name, switch the manifest, then drop the staged
            # name: a crash in between leaves an unmanifested duplicate that
            # the next run's orphan sweep removes.
            os.link(staged, partition_dir / final_name)
            store.write(
                partition_dir,
                cold_root,
                [*keep, dataclasses.replace(merged_entry, file=final_name)],
            )
            staged.unlink()
        return CompactionResult(
            partition_dir=partition_dir,
            skipped=False,
            merged_file=final_name,
            row_count=merged_rows,
            sha256=merged_sha,
        )


def _reconcile_orphans(partition_dir: Path, known: set[str]) -> None:
    """Remove `.tmp` leftovers and part files no manifest entry references
    (a compaction or export killed before its manifest step). Their rows are
    still in the manifested originals or still in the hot tier."""
    sweep_stale_temps(partition_dir)
    if partition_dir.is_dir():
        for part in partition_dir.glob("part-*.parquet"):
            if part.name not in known:
                part.unlink(missing_ok=True)

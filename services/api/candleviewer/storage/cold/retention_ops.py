"""Storage-side adapters for the recorder `RetentionManager` (E16-T06).

The recorder module never touches a driver or a path (ADR-0003, SR-097); these adapters do:

- `ColdRetentionStore`: lists manifested Parquet partitions per `(symbol, stream)` and deletes
  one partition directory under `partition_write_lock` (bounded by `asyncio.timeout`). The
  partition is re-resolved through `DatasetRegistry` at the delete site (containment check
  again, symlink escape refused). Order: directory first, then manifest — a crash between the
  two leaves a manifest whose files are gone, which the next pass lists and finishes (the
  DuckDB views are globs over the tree, so nothing stays registered for a deleted directory).
- `QuestDbRetentionHotStore`: DAY partitions with per-symbol row counts and on-disk bytes;
  the drop re-reads `table_partitions` first so a repeated drop is an idempotent no-op.
- `FileRetentionCheckpoint`: the reaper's atomic progress document (tmp + fsync + rename,
  the #2213/#2217 pattern) with a read-modify-write lock (the #2217 lost-update fix).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from candleviewer.storage.cold.layout import (
    DatasetNotRegistered,
    DatasetRegistry,
    partition_template,
    stream_dir_name,
)
from candleviewer.storage.cold.manifest import ManifestCorrupt, ManifestStore
from candleviewer.storage.cold.partition_lock import partition_write_lock
from candleviewer.storage.cold.rolloff_ops import QuestDbHotPartitions, day_name
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.natural_keys import TABLE_BY_STREAM
from candleviewer.storage.questdb.reader import PgWireConnection
from candleviewer.storage.sql_identifiers import checked_identifier, sql_string_literal

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YM_RE = re.compile(r"^\d{4}-\d{2}$")
_Y_RE = re.compile(r"^\d{4}$")
_HOUR_RE = re.compile(r"^\d{2}$")
_US_PER_HOUR = 3_600_000_000
US_PER_DAY = 86_400_000_000


class RetentionCheckpointCorrupt(ValueError):
    """The reaper checkpoint is unreadable: fail closed (the pass deletes nothing)."""

    code = "retention_checkpoint_corrupt"


@dataclass(frozen=True, slots=True)
class ColdPartitionInfo:
    key: str  # partition dir relative to the cold root
    start_us: int
    end_us: int
    rows: int
    bytes: int


@dataclass(frozen=True, slots=True)
class HotDayInfo:
    start_us: int
    rows_by_symbol: dict[str, int]
    bytes: int


def _epoch_us(dt: datetime) -> int:
    return int(dt.replace(tzinfo=UTC).timestamp()) * 1_000_000


def partition_range(values: dict[str, str]) -> tuple[int, int] | None:
    """`[start, end)` in UTC µs from the time keys of a partition (`dt`/`hour`/`ym`/`y`)."""
    if (dt := values.get("dt")) is not None:
        if not _DATE_RE.fullmatch(dt):
            return None
        start = _epoch_us(datetime.strptime(dt, "%Y-%m-%d"))
        hour = values.get("hour")
        if hour is not None:
            if not _HOUR_RE.fullmatch(hour) or int(hour) > 23:
                return None
            start += int(hour) * _US_PER_HOUR
            return start, start + _US_PER_HOUR
        return start, start + US_PER_DAY
    if (ym := values.get("ym")) is not None:
        if not _YM_RE.fullmatch(ym):
            return None
        y, m = int(ym[:4]), int(ym[5:])
        if not 1 <= m <= 12:
            return None
        nxt = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1)
        return _epoch_us(datetime(y, m, 1)), _epoch_us(nxt)
    if (yr := values.get("y")) is not None and _Y_RE.fullmatch(yr):
        return _epoch_us(datetime(int(yr), 1, 1)), _epoch_us(datetime(int(yr) + 1, 1, 1))
    return None


class ColdRetentionStore:
    def __init__(self, registry: DatasetRegistry, *, lock_timeout_s: float = 120.0) -> None:
        self._registry = registry
        self._manifests = ManifestStore(registry.root / "_manifests")
        self._lock_timeout_s = lock_timeout_s

    def _key(self, partition_dir: Path) -> str:
        return partition_dir.relative_to(self._registry.root).as_posix()

    def _list_sync(self, symbol: str, stream: StreamKind) -> list[ColdPartitionInfo]:
        out: list[ColdPartitionInfo] = []
        for paths in self._registry.manifested_partitions(stream, symbol):
            values = dict(p.split("=", 1) for p in paths.partition_dir.parts if "=" in p)
            rng = partition_range(values)
            if rng is None:
                continue
            try:
                entries = self._manifests.read(paths.partition_dir, paths.root)
            except ManifestCorrupt:
                continue  # never delete what we cannot account for
            size = 0
            if paths.partition_dir.is_dir():
                size = sum(f.stat().st_size for f in paths.partition_dir.rglob("*") if f.is_file())
            rows = sum(e.row_count for e in entries)
            out.append(
                ColdPartitionInfo(self._key(paths.partition_dir), rng[0], rng[1], rows, size)
            )
        return out

    async def partitions(self, symbol: str, stream: StreamKind) -> list[ColdPartitionInfo]:
        return await asyncio.to_thread(self._list_sync, symbol, stream)

    def _resolve(self, symbol: str, stream: StreamKind, key: str) -> Path:
        """Re-derive the directory from the key through the registry (SR-097 at the delete
        site): the key must be `<stream dir>/<k=v>...` with this stream's template and symbol."""
        parts = key.split("/")
        if not parts or parts[0] != stream_dir_name(stream):
            raise DatasetNotRegistered("partition key does not match the stream")
        pairs = [p.split("=", 1) for p in parts[1:]]
        if any(len(p) != 2 for p in pairs):
            raise DatasetNotRegistered("malformed partition key")
        values = {k: v for k, v in pairs}
        if tuple(values) != partition_template(stream) or values.get("symbol") != symbol:
            raise DatasetNotRegistered("partition key does not match the template/symbol")
        paths = self._registry.resolve_partition(stream, partition_values=values)
        if paths.partition_dir.is_symlink():
            raise DatasetNotRegistered("refusing to delete a symlinked partition")
        return paths.partition_dir

    def _delete_sync(self, partition_dir: Path) -> bool:
        manifest = self._manifests._manifest_path(partition_dir, self._registry.root)
        existed = partition_dir.exists() or manifest.exists()
        if partition_dir.exists():
            shutil.rmtree(partition_dir)
        manifest.unlink(missing_ok=True)
        return existed

    async def delete(self, symbol: str, stream: StreamKind, key: str) -> bool:
        partition_dir = self._resolve(symbol, stream, key)
        async with asyncio.timeout(self._lock_timeout_s):
            async with partition_write_lock(partition_dir):
                # Shielded: a cancelled pass never leaves a half-deleted tree behind a live
                # manifest without the thread finishing (the checkpoint keeps it `pending`).
                return await asyncio.shield(asyncio.to_thread(self._delete_sync, partition_dir))


class QuestDbRetentionHotStore:
    """QuestDB DAY partitions with per-symbol counts; every await bounded (C-2.18)."""

    def __init__(
        self,
        connection: PgWireConnection,
        *,
        timeout_s: float = 60.0,
        apply_timeout_s: float = 120.0,
        poll_s: float = 0.2,
    ) -> None:
        self._conn = connection
        self._timeout_s = timeout_s
        self._apply_timeout_s = apply_timeout_s
        self._poll_s = poll_s
        self._parts = QuestDbHotPartitions(connection, timeout_s=timeout_s)

    async def _fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        async with asyncio.timeout(self._timeout_s):
            return await self._conn.fetch(sql, *params)

    @staticmethod
    def _table(stream: StreamKind) -> str:
        try:
            return checked_identifier(TABLE_BY_STREAM[stream])
        except KeyError as exc:
            raise DatasetNotRegistered(f"no hot-tier table for {stream!r}") from exc

    async def _sizes(self, stream: StreamKind) -> dict[str, int]:
        literal = sql_string_literal(self._table(stream))
        sql = f"SELECT name, diskSize FROM table_partitions({literal})"  # noqa: S608  # nosec B608 - allowlisted table as escaped literal
        out: dict[str, int] = {}
        for row in await self._fetch(sql):
            name = str(row.get("name", ""))
            if _DATE_RE.fullmatch(name):
                out[name] = int(str(row.get("diskSize") or 0))
        return out

    async def days(self, stream: StreamKind, before_us: int) -> list[HotDayInfo]:
        sizes = await self._sizes(stream)
        out: list[HotDayInfo] = []
        for start in await self._parts.closed_days(stream, before_us):
            rng = TimeRange(start_us=start, end_us=start + US_PER_DAY)
            counts = await self._parts.row_counts(stream, rng)
            out.append(HotDayInfo(start, counts, sizes.get(day_name(start), 0)))
        return out

    async def _applied(self, stream: StreamKind) -> bool:
        """WAL tables apply DDL asynchronously: the DROP is only visible once the table writer
        has caught up with its sequencer (`wal_tables()`; a non-WAL table has no row)."""
        rows = await self._fetch(
            "SELECT writerTxn, sequencerTxn, suspended FROM wal_tables() WHERE name = $1",
            self._table(stream),
        )
        if not rows:
            return True
        row = rows[0]
        if str(row.get("suspended")).lower() in ("true", "t", "1"):
            raise RuntimeError("questdb WAL apply suspended for the table")
        return int(str(row.get("writerTxn"))) >= int(str(row.get("sequencerTxn")))

    async def drop_day(self, stream: StreamKind, day_start_us: int) -> bool:
        """Issue the DROP, then wait (bounded) until it is applied AND the partition is gone.
        Raises `TimeoutError` otherwise, so the reaper keeps the item `pending` and retries."""
        name = day_name(day_start_us)
        if name not in await self._sizes(stream):
            return False  # already dropped (resumed pass): idempotent
        await self._parts.drop_day(stream, day_start_us)
        async with asyncio.timeout(self._apply_timeout_s):
            for _ in range(max(1, int(self._apply_timeout_s / self._poll_s))):
                if await self._applied(stream) and name not in await self._sizes(stream):
                    return True
                await asyncio.sleep(self._poll_s)
        raise TimeoutError("partition drop not applied")


class FileRetentionCheckpoint:
    """`<cold root>/_manifests/_retention/checkpoint-<name>.json`; atomic + locked RMW."""

    _NAME = re.compile(r"^[a-z0-9_-]{1,40}$")

    def __init__(self, registry: DatasetRegistry, name: str = "reaper") -> None:
        if not self._NAME.fullmatch(name):
            raise DatasetNotRegistered("unsafe checkpoint name")
        self._path = registry.root / "_manifests" / "_retention" / f"checkpoint-{name}.json"
        self._lock = asyncio.Lock()

    def _load_sync(self) -> dict[str, object] | None:
        if not self._path.is_file():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise RetentionCheckpointCorrupt("checkpoint is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise RetentionCheckpointCorrupt("checkpoint is not an object")
        return {str(k): v for k, v in raw.items()}

    def _save_sync(self, doc: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def load(self) -> dict[str, object] | None:
        async with self._lock:
            return await asyncio.to_thread(self._load_sync)

    async def save(self, doc: dict[str, object]) -> None:
        async with self._lock:
            await asyncio.shield(asyncio.to_thread(self._save_sync, dict(doc)))

    async def clear(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._path.unlink, True)

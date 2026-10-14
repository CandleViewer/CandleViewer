"""Composition of the E16-T07 `DiskBudget` on the real storage backend (#491 decisions).

There is no recorder flag (none exists; a safety monitor is never default-off, C-4.14): the
budget runs whenever `storage_backend == "real"`. Free space is the `statvfs` of the volume
under `CV_PARQUET_ROOT` (the api cannot see QuestDB's volume; that tier counts against the cap
through `table_partitions` sizes). Parquet bytes per symbol are exact, from the `symbol=`
partition path; hot bytes per symbol are apportioned by `recorder_bytes_written_total` share.
No shell-out anywhere (SR-096). Deviations: 24-internal-schemas §13.4.1.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import cast

import structlog

from candleviewer.recorder.budget import (
    US_PER_S,
    Breakdown,
    BudgetConfig,
    DiskBudget,
    Point,
    PressurePublisher,
)
from candleviewer.recorder.metrics import recorder_bytes_written_total
from candleviewer.recorder.models import TierName
from candleviewer.recorder.writer import STREAM_KIND
from candleviewer.settings import Settings
from candleviewer.storage.cold.observability import LoggingSystemEventSink
from candleviewer.storage.cold.rolloff_ops import QuestDbHotPartitions
from candleviewer.storage.models import StreamKind
from candleviewer.storage.questdb.wiring import LazyPgWire
from candleviewer.storage.repositories.recorder_sqlalchemy import SqlAlchemyRecorderRepository

#: The recorder's hot tables: one per `StreamWriter` lane.
HOT_STREAMS = tuple(StreamKind(kind) for kind in STREAM_KIND.values())


def logger() -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


def parquet_usage(root: Path) -> tuple[int, dict[str, int]]:
    """Bytes under the cold root, and per `symbol=` partition (exact). Blocking: run off-loop.
    Symlinks are never followed (`os.walk` default, `lstat`)."""
    total = 0
    per: dict[str, int] = {}
    for dirpath, _dirs, files in os.walk(root):
        parts = Path(dirpath).relative_to(root).parts
        symbol = next((p[7:] for p in parts if p.startswith("symbol=")), None)
        size = 0
        for name in files:
            try:
                size += os.lstat(os.path.join(dirpath, name)).st_size
            except FileNotFoundError:  # removed by retention mid-walk
                continue
        total += size
        if symbol:
            per[symbol] = per.get(symbol, 0) + size
    return total, per


def written_by_symbol() -> dict[str, int]:
    """ILP bytes written per symbol since start (the StreamWriter counter, all streams)."""
    out: dict[str, int] = {}
    for family in recorder_bytes_written_total.collect():
        for sample in family.samples:
            if sample.name.endswith("_total"):
                symbol = sample.labels.get("symbol", "")
                out[symbol] = out.get(symbol, 0) + int(sample.value)
    return out


class _OneThread[T]:
    """One dedicated worker thread. A call still running is awaited again, never stacked, so a
    slow walk or a hung `statvfs` cannot pile into the default pool (audit write-ahead)."""

    def __init__(self, name: str) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self._pending: Future[T] | None = None

    async def run(self, fn: Callable[[], T]) -> T:
        if self._pending is None or self._pending.done():
            self._pending = self._pool.submit(fn)
        return await asyncio.wrap_future(self._pending)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _existing(path: Path) -> Path:
    """`path` or its nearest existing parent (where a not-yet-created path will land)."""
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _volume(root: Path) -> tuple[int, int]:
    usage = shutil.disk_usage(_existing(root))  # statvfs on POSIX
    return usage.total, usage.free


class VolumeMeter:
    """`StorageMeter`: `statvfs` of the volume under `CV_PARQUET_ROOT`, then the best-effort
    breakdown (QuestDB `table_partitions` sizes, the Parquet walk), each on its own thread."""

    def __init__(
        self,
        root: Path,
        pg: LazyPgWire | None,
        written: Callable[[], Mapping[str, int]] = written_by_symbol,
    ) -> None:
        self._root, self._pg, self._written, self._questdb = root, pg, written, 0
        self._hot = None if pg is None else QuestDbHotPartitions(pg, timeout_s=4.0)
        self._statvfs = _OneThread[tuple[int, int]]("disk-budget-statvfs")
        self._walk = _OneThread[tuple[int, dict[str, int]]]("disk-budget-walk")

    async def volume(self) -> tuple[int, int]:
        return await self._statvfs.run(partial(_volume, self._root))

    async def breakdown(self) -> Breakdown:
        if self._hot is not None:
            try:
                self._questdb = await self._hot.disk_bytes(HOT_STREAMS)
            except Exception as exc:  # any QuestDB failure: the cap path keeps the last size
                logger().warning("disk_budget_questdb_unavailable", error=type(exc).__name__)
        parquet, symbols = await self._walk.run(partial(parquet_usage, self._root))
        written = self._written()
        total_written = sum(written.values())
        for symbol, n in written.items():
            if total_written and symbol:
                symbols[symbol] = symbols.get(symbol, 0) + self._questdb * n // total_written
        tiers: dict[TierName, int] = {"questdb": self._questdb, "parquet": parquet}
        return Breakdown(tiers, symbols)

    async def close(self) -> None:
        self._statvfs.close()
        self._walk.close()
        if self._pg is not None:
            await self._pg.close()


class FileSeriesStore:
    """`SeriesStore`: one NDJSON file per UTC day, the newest `keep_days` kept (bounded)."""

    def __init__(self, directory: Path, *, keep_days: int = 8) -> None:
        self._dir, self._keep = directory, keep_days

    async def load(self, since_us: int) -> list[Point]:
        return await asyncio.to_thread(self._load, since_us)

    def _load(self, since_us: int) -> list[Point]:
        points: list[Point] = []
        for path in sorted(self._dir.glob("*.ndjson")):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    raw = json.loads(line)
                    point = Point(
                        int(raw["t"]), int(raw["b"]), tuple((str(s), int(b)) for s, b in raw["s"])
                    )
                except (ValueError, KeyError, TypeError):  # a torn last line after a crash
                    continue
                if point.ts_us >= since_us:
                    points.append(point)
        return points

    async def append(self, point: Point) -> None:
        await asyncio.to_thread(self._append, point)

    def _append(self, point: Point) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        day = datetime.fromtimestamp(point.ts_us / US_PER_S, tz=UTC).strftime("%Y%m%d")
        line = json.dumps({"t": point.ts_us, "b": point.recorded_bytes, "s": point.symbols})
        with (self._dir / f"{day}.ndjson").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        for old in sorted(self._dir.glob("*.ndjson"))[: -self._keep]:
            old.unlink(missing_ok=True)


def _us(at: datetime) -> int:
    return int(at.timestamp() * US_PER_S)


async def recorded_gaps(
    repo: SqlAlchemyRecorderRepository, lo_us: int, hi_us: int
) -> list[tuple[int, int]]:
    """`recording_gaps` windows (all recorded symbols) overlapping `[lo_us, hi_us)`."""
    lo, hi = (datetime.fromtimestamp(t / US_PER_S, tz=UTC) for t in (lo_us, hi_us))
    symbols = [str(r["symbol"]) for r in await repo.list_recorded()]
    rows = [g for s in symbols for g in await repo.gaps_in(s, lo, hi)]
    return [(_us(g["gap_start"]), _us(g["gap_end"])) for g in rows]


async def pinned_symbols(repo: SqlAlchemyRecorderRepository) -> frozenset[str]:
    return frozenset(str(r["symbol"]) for r in await repo.list_recorded() if r.get("pinned"))


def shared_volume(recording: Path, protected: Sequence[Path]) -> list[str]:
    """Names (never full paths) of `protected` paths on the recording volume (SR-096). A path
    not created yet is judged by its nearest existing parent, so every boot agrees."""
    dev = os.stat(recording).st_dev
    return [p.name for p in protected if os.stat(_existing(p)).st_dev == dev]


def recording_refusal(root: Path, protected: Sequence[Path], allow_shared: bool) -> str | None:
    """Why recording must stay refused (SR-096), else `None`. Never raises at boot: a missing
    root or any filesystem error refuses recording instead of failing the app."""
    try:
        if not root.is_dir():
            return "recording_root_missing"
        shared = shared_volume(root, protected)
    except OSError:
        return "recording_volume_unreadable"
    if shared:
        logger().critical("recording_volume_shared", shared=shared, allowed=allow_shared)
    return "recording_volume_shared" if shared and not allow_shared else None


def build_disk_budget(
    settings: Settings,
    *,
    bus: PressurePublisher,
    recorder_repo: SqlAlchemyRecorderRepository | None,
) -> DiskBudget | None:
    """The real-backend `DiskBudget`, or `None` (fake backend). A recording volume shared with
    the backend's own paths is logged critical and, unless `CV_ALLOW_SHARED_VOLUME` (testnet
    only, E16-FR-11), keeps recording refused: the write gate stays closed (SR-096)."""
    if settings.storage_backend != "real" or recorder_repo is None:
        return None
    root = Path(settings.parquet_root)
    protected = [Path(settings.audit_wal_path).resolve().parent, Path(settings.bars_state_root)]
    refusal = recording_refusal(root, protected, settings.allow_shared_volume)
    if refusal is not None:
        logger().critical("recording_refused", reason=refusal)
    host, _, port = settings.questdb_pg.partition(":")
    pg = LazyPgWire(
        host,
        int(port or 8812),
        settings.questdb_pg_user,
        settings.questdb_pg_password.get_secret_value(),
    )
    config = BudgetConfig(
        cap_bytes=settings.disk_cap_gb * 10**9,
        warn_pct=settings.disk_warn_pct,
        autostop_pct=settings.disk_autostop_pct,
        halt_pct=settings.disk_halt_pct,
        sample_interval_s=settings.disk_sample_interval_s,
        hot_days=settings.recorder_hot_days,
        retention_days=settings.recorder_retention_days,
    )
    return DiskBudget(
        meter=VolumeMeter(root, pg),
        events=LoggingSystemEventSink(),
        bus=bus,
        env=settings.environment.value,
        config=config,
        now_us=lambda: time.time_ns() // 1_000,
        gaps=partial(recorded_gaps, recorder_repo),
        pinned=partial(pinned_symbols, recorder_repo),
        store=FileSeriesStore(root / "_disk_budget" / settings.environment.value),
        recording_refused=refusal is not None,
    )

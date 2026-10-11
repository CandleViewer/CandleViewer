"""Unit (E16-T06): storage-side retention adapters.

Cold delete: SR-097 containment re-checked at the delete site (wrong stream / symbol / template
/ traversal / symlink refused), directory + manifest removed under `partition_write_lock`,
idempotent second delete. Listing: ranges from dt/hour/ym/y keys, unreadable manifests never
listed. Hot store: per-symbol counts + sizes, drop idempotent. Checkpoint: atomic round trip,
corrupt document fails closed, unsafe name refused.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from candleviewer.storage.cold.layout import DatasetNotRegistered, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore
from candleviewer.storage.cold.partition_lock import is_locked
from candleviewer.storage.cold.retention_ops import (
    ColdRetentionStore,
    FileRetentionCheckpoint,
    QuestDbRetentionHotStore,
    RetentionCheckpointCorrupt,
    partition_range,
)
from candleviewer.storage.models import StreamKind

T = StreamKind.TRADES
KEY = "trades/symbol=BTCUSDT/dt=2026-08-01"
DAY_US = int(datetime(2026, 8, 1, tzinfo=UTC).timestamp()) * 1_000_000


def _seed(reg: DatasetRegistry, rows: int = 5) -> Path:
    paths = reg.resolve_partition(T, partition_values={"symbol": "BTCUSDT", "dt": "2026-08-01"})
    paths.partition_dir.mkdir(parents=True)
    (paths.partition_dir / "part-0000.parquet").write_bytes(b"x" * 64)
    entry = ManifestEntry("part-0000.parquet", "0" * 64, rows, "trades", "r", 0)
    ManifestStore(paths.manifests_dir).write(paths.partition_dir, paths.root, [entry])
    return paths.partition_dir


async def test_cold_lists_manifested_partition_with_range_rows_bytes(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path)
    _seed(reg)
    (part,) = await ColdRetentionStore(reg).partitions("BTCUSDT", T)
    assert (part.key, part.rows, part.bytes) == (KEY, 5, 64)
    assert (part.start_us, part.end_us) == (DAY_US, DAY_US + 86_400_000_000)


async def test_cold_skips_corrupt_manifest(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path)
    _seed(reg)
    doc = tmp_path / "_manifests" / "trades" / "symbol=BTCUSDT" / "dt=2026-08-01.json"
    doc.write_text("{not json", encoding="utf-8")
    assert await ColdRetentionStore(reg).partitions("BTCUSDT", T) == []


async def test_cold_delete_removes_dir_and_manifest_under_lock_idempotently(
    tmp_path: Path,
) -> None:
    reg = DatasetRegistry(tmp_path)
    part_dir = _seed(reg)
    store = ColdRetentionStore(reg)
    seen: list[bool] = []
    real = store._delete_sync

    def spy(p: Path) -> bool:
        seen.append(is_locked(p))
        return real(p)

    store._delete_sync = spy  # type: ignore[method-assign]  # observe the lock from the thread
    assert await store.delete("BTCUSDT", T, KEY) is True
    assert seen == [True] and not part_dir.exists()
    assert await store.partitions("BTCUSDT", T) == []
    assert await store.delete("BTCUSDT", T, KEY) is False


@pytest.mark.parametrize(
    ("symbol", "stream", "key"),
    [
        ("ETHUSDT", T, KEY),  # another symbol's key
        ("BTCUSDT", StreamKind.TICKERS, KEY),  # another stream
        ("BTCUSDT", T, "trades/symbol=BTCUSDT"),  # template incomplete
        ("BTCUSDT", T, "trades/symbol=BTCUSDT/dt=.."),  # traversal
        ("BTCUSDT", T, "trades/symbol=BTCUSDT/dt"),  # malformed pair
        ("BTCUSDT", T, "../trades/symbol=BTCUSDT/dt=2026-08-01"),
    ],
)
async def test_cold_delete_refuses_keys_outside_containment(
    tmp_path: Path, symbol: str, stream: StreamKind, key: str
) -> None:
    reg = DatasetRegistry(tmp_path)
    part_dir = _seed(reg)
    with pytest.raises(DatasetNotRegistered):
        await ColdRetentionStore(reg).delete(symbol, stream, key)
    assert part_dir.exists()


async def test_cold_delete_refuses_symlinked_partition(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path / "root")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.parquet").write_bytes(b"k")
    link = tmp_path / "root" / "trades" / "symbol=BTCUSDT" / "dt=2026-08-01"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted on this host")
    with pytest.raises(DatasetNotRegistered):
        await ColdRetentionStore(reg).delete("BTCUSDT", T, KEY)
    assert (outside / "keep.parquet").exists()


def test_partition_range_keys() -> None:
    assert partition_range({"dt": "2026-08-01", "hour": "05"}) == (
        DAY_US + 5 * 3_600_000_000,
        DAY_US + 6 * 3_600_000_000,
    )
    ym = partition_range({"ym": "2026-12"})
    assert ym is not None and ym[1] == int(datetime(2027, 1, 1, tzinfo=UTC).timestamp()) * 10**6
    assert partition_range({"y": "2026"}) is not None
    for bad in ({"dt": "x"}, {"dt": "2026-08-01", "hour": "24"}, {"ym": "2026-13"}, {}):
        assert partition_range(bad) is None


class _Pg:
    def __init__(self) -> None:
        self.parts = {"2026-08-01": 4096}
        self.calls: list[str] = []

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls.append(sql)
        if "table_partitions" in sql:
            return [{"name": n, "diskSize": s} for n, s in self.parts.items()]
        if sql.startswith("ALTER TABLE"):
            self.parts.clear()
            return []
        assert all(isinstance(p, datetime) and p.tzinfo is None for p in params)  # ts_param
        return [{"symbol": "BTCUSDT", "n": 7}, {"symbol": "ETHUSDT", "n": 2}]


async def test_hot_store_days_counts_sizes_and_idempotent_drop() -> None:
    pg = _Pg()
    store = QuestDbRetentionHotStore(pg)
    (d,) = await store.days(T, DAY_US + 2 * 86_400_000_000)
    assert (d.start_us, d.rows_by_symbol, d.bytes) == (
        DAY_US,
        {"BTCUSDT": 7, "ETHUSDT": 2},
        4096,
    )
    assert await store.drop_day(T, DAY_US) is True
    assert any("DROP PARTITION LIST '2026-08-01'" in c for c in pg.calls)
    assert await store.drop_day(T, DAY_US) is False
    with pytest.raises(DatasetNotRegistered):
        await store.days(StreamKind.BARS, DAY_US)


async def test_checkpoint_round_trip_clear_and_corrupt(tmp_path: Path) -> None:
    reg = DatasetRegistry(tmp_path)
    ck = FileRetentionCheckpoint(reg)
    assert await ck.load() is None
    await asyncio.gather(ck.save({"a": 1}), ck.save({"a": 2}))
    assert (await ck.load()) in ({"a": 1}, {"a": 2})
    await ck.clear()
    assert await ck.load() is None
    path = tmp_path / "_manifests" / "_retention" / "checkpoint-reaper.json"
    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(RetentionCheckpointCorrupt):
        await ck.load()
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(RetentionCheckpointCorrupt):
        await ck.load()
    assert not list(path.parent.glob("*.tmp"))
    with pytest.raises(DatasetNotRegistered):
        FileRetentionCheckpoint(reg, "../x")

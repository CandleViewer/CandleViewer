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

from candleviewer.storage.cold import rolloff_ops
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
from candleviewer.storage.errors import StoragePartitionDropNotApplied
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
    """QuestDB fake with WAL semantics: the DROP bumps `sequencerTxn`; the partition only
    disappears after `apply_after` more `wal_tables()` polls (async WAL apply), whichever wait
    polls it: the shared drop (`SELECT suspended ...`, which since #2566 waits for the apply
    itself) or the store's own `SELECT writerTxn ...` check.

    `lag`: the partition applies but the table writer never catches up with its sequencer (other
    pending transactions). `suspended`: the WAL is suspended from the start. `suspend_after_apply`:
    it suspends right after the drop applied (the shared wait has already returned by then)."""

    def __init__(
        self,
        *,
        apply_after: int = 0,
        wal: bool = True,
        lag: bool = False,
        suspended: bool = False,
        suspend_after_apply: bool = False,
    ) -> None:
        self.parts = {"2026-08-01": 4096, "2026-08-02": 10}
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.writer, self.seq, self.apply_after, self.wal = 1, 1, apply_after, wal
        self.lag, self.suspended, self.suspend_after_apply = lag, suspended, suspend_after_apply
        self.pending: str | None = None
        self.ghosts: list[str] = []  # dropped but still listed, empty (real QuestDB behaviour)

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls.append((sql, params))
        if "wal_tables" in sql:
            assert params == ("trades",)
            if not self.wal:
                return []
            suspended = self.suspended  # what THIS poll reports (before a later suspension)
            if self.pending and self.apply_after <= 0:
                self.parts.pop(self.pending)
                self.ghosts.append(self.pending)
                self.pending = None
                self.writer = self.writer if self.lag else self.seq
                self.suspended = self.suspended or self.suspend_after_apply
            self.apply_after -= 1
            if sql.startswith("SELECT suspended"):  # the shared drop reads only the flag
                return [{"suspended": suspended}]
            return [{"writerTxn": self.writer, "sequencerTxn": self.seq, "suspended": suspended}]
        if "table_partitions" in sql:
            live = [
                {"name": n, "diskSize": s, "numRows": 5, "minTimestamp": "x"}
                for n, s in self.parts.items()
            ]
            return live + [
                {"name": n, "diskSize": 0, "numRows": 0, "minTimestamp": None} for n in self.ghosts
            ]
        if sql.startswith("ALTER TABLE"):
            self.pending = sql.rsplit("'", 2)[1]
            self.seq += 1
            if not self.wal:
                self.parts.pop(self.pending)
            return []
        assert all(isinstance(p, datetime) and p.tzinfo is None for p in params)  # ts_param
        return [{"symbol": "BTCUSDT", "n": 7}, {"symbol": "ETHUSDT", "n": 2}]


@pytest.fixture(autouse=True)
def _fast_drop_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    """#2566: the shared `QuestDbHotPartitions.drop_day` now waits for the apply itself with a
    20 -> 200 ms backoff; shrink it so the unit tests stay fast (the module constants are read
    on every wait)."""
    monkeypatch.setattr(rolloff_ops, "DROP_POLL_MIN_S", 0.001)
    monkeypatch.setattr(rolloff_ops, "DROP_POLL_MAX_S", 0.002)


def _store(pg: _Pg, *, apply_timeout_s: float = 1.0) -> QuestDbRetentionHotStore:
    return QuestDbRetentionHotStore(pg, apply_timeout_s=apply_timeout_s, poll_s=0.001)


async def test_hot_store_days_counts_sizes() -> None:
    d, _ = await _store(_Pg()).days(T, DAY_US + 3 * 86_400_000_000)
    assert (d.start_us, d.rows_by_symbol, d.bytes) == (
        DAY_US,
        {"BTCUSDT": 7, "ETHUSDT": 2},
        4096,
    )
    with pytest.raises(DatasetNotRegistered):
        await _store(_Pg()).days(StreamKind.BARS, DAY_US)


async def test_hot_drop_statement_targets_exact_utc_day_partition_name() -> None:
    pg = _Pg()
    assert await _store(pg).drop_day(T, DAY_US) is True
    (stmt,) = [c for c, _ in pg.calls if c.startswith("ALTER")]
    assert stmt == "ALTER TABLE trades DROP PARTITION LIST '2026-08-01'"
    assert "2026-08-01" not in pg.parts and "2026-08-02" in pg.parts


async def test_hot_drop_waits_for_wal_apply_before_reporting_success() -> None:
    """Regression (#2229 integration): on a WAL table the DROP returns before it is applied;
    reporting success then left the partition visible. The store only reports success once the
    partition is gone: the shared drop (#2566) polls `wal_tables()` / `table_partitions()` until
    then, and the store's own writerTxn == sequencerTxn check follows."""
    pg = _Pg(apply_after=3)
    assert await _store(pg).drop_day(T, DAY_US) is True
    assert "2026-08-01" not in pg.parts
    assert sum(1 for c, _ in pg.calls if "wal_tables" in c) >= 4


async def test_hot_drop_lagging_writer_raises_timeout_keeps_item_retryable() -> None:
    """The partition is gone but the table writer never catches up with its sequencer (other
    pending transactions): the store's own check refuses to report success, so the reaper keeps
    the item `pending` and retries."""
    pg = _Pg(lag=True)
    with pytest.raises(TimeoutError):
        await _store(pg, apply_timeout_s=0.05).drop_day(T, DAY_US)
    assert "2026-08-01" not in pg.parts


async def test_hot_drop_suspended_wal_raises_the_typed_drop_error() -> None:
    """A suspended WAL can never apply the drop: the shared wait (#2566) fails fast with the typed
    error the reaper handles like a timeout, and nothing is reported dropped."""
    pg = _Pg(apply_after=10**9, suspended=True)
    with pytest.raises(StoragePartitionDropNotApplied) as exc:
        await _store(pg).drop_day(T, DAY_US)
    assert exc.value.reason == "suspended" and "2026-08-01" in pg.parts


async def test_hot_drop_wal_suspended_after_the_apply_raises() -> None:
    """The WAL suspends right after the drop applied (the shared wait has returned): the store's
    own check still refuses to report success."""
    pg = _Pg(suspend_after_apply=True)
    with pytest.raises(RuntimeError, match="suspended"):
        await _store(pg).drop_day(T, DAY_US)


async def test_hot_drop_non_wal_table_and_idempotent_second_drop() -> None:
    pg = _Pg(wal=False)
    store = _store(pg)
    assert await store.drop_day(T, DAY_US) is True
    assert await store.drop_day(T, DAY_US) is False


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


async def test_hot_drop_treats_empty_listed_partition_as_dropped() -> None:
    """Regression (#2229 integration): after the DROP is applied QuestDB may still list the
    partition with numRows=0 / null minTimestamp; waiting for the name to vanish timed out."""
    pg = _Pg(apply_after=1)
    store = _store(pg)
    assert await store.drop_day(T, DAY_US) is True
    assert pg.ghosts == ["2026-08-01"]
    assert [d.start_us for d in await store.days(T, DAY_US + 3 * 86_400_000_000)] == [
        DAY_US + 86_400_000_000
    ]
    assert await store.drop_day(T, DAY_US) is False


async def test_cold_delete_timeout_bounds_only_lock_acquisition(tmp_path: Path) -> None:
    """Review M2: a held lock -> TimeoutError and nothing deleted; once the delete starts,
    the lock is held until the thread finishes even if the caller is cancelled."""
    from candleviewer.storage.cold.partition_lock import partition_write_lock

    reg = DatasetRegistry(tmp_path)
    part_dir = _seed(reg)
    store = ColdRetentionStore(reg, lock_timeout_s=0.05)
    async with partition_write_lock(part_dir):
        with pytest.raises(TimeoutError):
            await store.delete("BTCUSDT", T, KEY)
    assert part_dir.exists()

    started, release = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    real = store._delete_sync

    def slow(p: Path) -> bool:
        loop.call_soon_threadsafe(started.set)
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result()
        return real(p)

    store._delete_sync = slow  # type: ignore[method-assign]  # gate the thread
    task = asyncio.ensure_future(store.delete("BTCUSDT", T, KEY))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert is_locked(part_dir)  # cancelled caller, but the delete is still running: locked
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Event-driven (no sleep loop, C-13.7): the lock is acquirable only once the delete thread
    # has FINISHED, so taking it proves the delete completed before the release.
    async with asyncio.timeout(30), partition_write_lock(part_dir):
        pass
    assert not is_locked(part_dir) and not part_dir.exists()


async def test_archive_verifier_reads_manifest_rows_for_the_day(tmp_path: Path) -> None:
    from candleviewer.storage.cold.retention_ops import ArchiveRowVerifier

    reg = DatasetRegistry(tmp_path)
    _seed(reg, rows=5)
    v = ArchiveRowVerifier(_Pg(), reg)
    assert await v.cold_rows("BTCUSDT", T, DAY_US) == 5
    assert await v.cold_rows("BTCUSDT", T, DAY_US + 86_400_000_000) is None
    assert await v.hot_rows(T, DAY_US) == {"BTCUSDT": 7, "ETHUSDT": 2}
    doc = tmp_path / "_manifests" / "trades" / "symbol=BTCUSDT" / "dt=2026-08-01.json"
    doc.write_text("{bad", encoding="utf-8")
    assert await v.cold_rows("BTCUSDT", T, DAY_US) is None

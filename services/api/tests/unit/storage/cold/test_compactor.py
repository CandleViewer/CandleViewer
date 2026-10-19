"""Unit tests: `Compactor` — Sec.5.4 trigger rules, merge, idle guard,
crash safety and the row-multiset-preservation property (AC 6, 7)."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import structlog
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from structlog.testing import capture_logs

from candleviewer.observability.logging import configure_logging
from candleviewer.storage.cold import compactor as compactor_mod
from candleviewer.storage.cold.compactor import Compactor, should_compact
from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore, sha256_of
from candleviewer.storage.cold.writer import normalise_ts, write_parquet_file
from candleviewer.storage.errors import StorageExportVerifyFailed
from tests.unit.storage.cold._helpers import RecordingSink, SimulatedKill

MIB = 1024 * 1024
PART = Path("trades") / "symbol=BTCUSDT" / "dt=2026-10-17"


def test_should_compact_false_for_single_file() -> None:
    assert should_compact([1]) is False


def test_should_compact_true_when_more_than_four_files() -> None:
    assert should_compact([100 * MIB] * 5) is True


def test_should_compact_true_when_small_file_has_siblings() -> None:
    assert should_compact([100 * MIB, 1 * MIB]) is True


def test_should_compact_false_when_few_large_files() -> None:
    assert should_compact([100 * MIB] * 4) is False


def _seed(
    root: Path, files: list[list[tuple[int, float]]], names: list[str] | None = None
) -> ManifestStore:
    """Write manifested part files (each a list of `(ts, price)` rows)."""
    part = root / PART
    store = ManifestStore(root / "_manifests")
    entries: list[ManifestEntry] = []
    for i, rows in enumerate(files):
        table = normalise_ts(
            pa.table(
                {
                    "ts": pa.array([r[0] for r in sorted(rows)], type=pa.int64()),
                    "symbol": ["BTCUSDT"] * len(rows),
                    "price": [r[1] for r in sorted(rows)],
                }
            )
        )
        dest = part / (names[i] if names else f"part-{i:04d}.parquet")
        write_parquet_file(table, dest)
        entries.append(
            ManifestEntry(
                file=dest.name,
                sha256=sha256_of(dest),
                row_count=len(rows),
                source_table="trades",
                export_run_id=f"r{i}",
                exported_at_us=i,
                range_start_us=i,
                range_end_us=i + 1,
            )
        )
    store.write(part, root, entries)
    return store


def _rows(root: Path) -> Counter[tuple[int, float]]:
    out: Counter[tuple[int, float]] = Counter()
    for f in (root / PART).glob("part-*.parquet"):
        t = pq.read_table(f)
        out.update(
            zip(
                t.column("ts").cast(pa.int64()).to_pylist(),
                t.column("price").to_pylist(),
                strict=True,
            )
        )
    return out


async def _compact(root: Path, **kw: object) -> compactor_mod.CompactionResult:
    return await Compactor(**kw).compact_partition(root / PART, root, root / "_manifests")  # type: ignore[arg-type]  # test kwargs passthrough


async def test_six_small_files_merge_to_part_0000_with_manifest_before_delete(
    tmp_path: Path,
) -> None:
    sink = RecordingSink()
    _seed(tmp_path, [[(i * 10 + j, 1.0) for j in range(10)] for i in range(6)])
    result = await _compact(tmp_path, events=sink)
    assert result.skipped is False and result.merged_file == "part-0000.parquet"
    assert result.row_count == 60
    assert [p.name for p in (tmp_path / PART).iterdir()] == ["part-0000.parquet"]
    [entry] = ManifestStore(tmp_path / "_manifests").read(tmp_path / PART, tmp_path)
    assert entry.row_count == 60 and entry.sha256 == sha256_of(tmp_path / PART / entry.file)
    assert sink.events[-1][1] == "STORAGE_COMPACTION_DELETED_ORIGINALS"


async def test_active_replay_session_skips_partition_and_logs_session_id(
    tmp_path: Path,
) -> None:
    _seed(tmp_path, [[(1, 1.0)], [(2, 1.0)]])

    async def guard(_p: Path) -> str | None:
        return "sess-42"

    configure_logging(env="demo")
    try:
        await _compact(tmp_path, idle_guard=guard)  # first emit OUTSIDE capture pins the chain
        with capture_logs() as logs:
            result = await _compact(tmp_path, idle_guard=guard)
        assert result.skipped and "sess-42" in result.reason
        assert len(list((tmp_path / PART).iterdir())) == 2
        assert [e["session_id"] for e in logs] == ["sess-42"]
    finally:
        structlog.reset_defaults()


async def test_default_idle_guard_reads_empty_set_and_compacts(tmp_path: Path) -> None:
    _seed(tmp_path, [[(1, 1.0)], [(2, 1.0)]])
    assert (await _compact(tmp_path)).skipped is False


@pytest.mark.parametrize(
    ("name", "staged"),
    [
        ("part-0007.parquet", "part-0008.parquet"),
        ("part-0007.parquet\n", "part-0002.parquet"),
        ("part-0007.parquet\r\n", "part-0002.parquet"),
    ],
    ids=["legal", "lf", "crlf"],
)
async def test_a_manifest_name_ending_in_a_newline_is_no_part_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, staged: str
) -> None:
    """#3555: `$` also matches before a final newline, so `match` counted `part-0007.parquet\\n`
    as part 7 and staged the merge at 8. Outside the pattern it is not a part name: it is still
    merged and removed like any original, and the staged name is free, never an existing one."""
    dests: list[Path] = []

    def spy(table: pa.Table, dest: Path, **kw: Any) -> int:
        assert not dest.exists()
        dests.append(dest)
        return write_parquet_file(table, dest, **kw)

    monkeypatch.setattr(compactor_mod, "write_parquet_file", spy)
    names = ["part-0000.parquet", "part-0001.parquet", name]
    _seed(tmp_path, [[(1, 1.0)], [(2, 1.0)], [(3, 1.0)]], names)
    result = await _compact(tmp_path)
    assert [d.name for d in dests] == [staged]
    assert result.merged_file == "part-0000.parquet" and result.row_count == 3
    assert sorted(p.name for p in (tmp_path / PART).iterdir()) == ["part-0000.parquet"]
    assert sum(_rows(tmp_path).values()) == 3


async def test_below_threshold_is_noop(tmp_path: Path) -> None:
    _seed(tmp_path, [[(1, 1.0)]])
    assert (await _compact(tmp_path)).reason == "below threshold"


async def test_merge_cap_limits_files_per_merge(tmp_path: Path) -> None:
    _seed(tmp_path, [[(i, 1.0)] for i in range(5)])
    size = (tmp_path / PART / "part-0000.parquet").stat().st_size
    result = await _compact(tmp_path, max_merge_bytes=size * 2)
    assert result.row_count == 2
    assert sum(_rows(tmp_path).values()) == 5


async def test_crash_after_staged_write_is_recovered_without_row_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path, [[(1, 1.0)], [(2, 2.0)], [(3, 3.0)]])
    real = ManifestStore.write
    calls = {"n": 0}

    def boom(self: ManifestStore, *a: object) -> None:
        calls["n"] += 1
        raise SimulatedKill("kill before manifest")

    monkeypatch.setattr(ManifestStore, "write", boom)
    with pytest.raises(SimulatedKill):
        await _compact(tmp_path)
    monkeypatch.setattr(ManifestStore, "write", real)
    assert calls["n"] == 1
    assert len(list((tmp_path / PART).glob("part-*.parquet"))) == 4  # staged orphan
    assert sum(_rows(tmp_path).values()) >= 3  # originals intact (+ orphan)
    result = await _compact(tmp_path)
    assert result.row_count == 3 and sum(_rows(tmp_path).values()) == 3


async def test_row_count_mismatch_aborts_and_keeps_originals(tmp_path: Path) -> None:
    store = _seed(tmp_path, [[(1, 1.0)], [(2, 2.0)]])
    entries = store.read(tmp_path / PART, tmp_path)
    store.write(tmp_path / PART, tmp_path, [entries[0], _bump(entries[1])])
    with pytest.raises(StorageExportVerifyFailed):
        await _compact(tmp_path)
    assert sorted(p.name for p in (tmp_path / PART).iterdir()) == [
        "part-0000.parquet",
        "part-0001.parquet",
    ]


def _bump(e: ManifestEntry) -> ManifestEntry:
    import dataclasses

    return dataclasses.replace(e, row_count=e.row_count + 1)


@settings(
    max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    files=st.lists(
        st.lists(
            st.tuples(st.integers(0, 10_000), st.sampled_from([1.0, 2.5, 65000.0])),
            min_size=1,
            max_size=20,
        ),
        min_size=2,
        max_size=7,
    )
)
def test_property_compaction_preserves_row_multiset(
    tmp_path_factory: pytest.TempPathFactory, files: list[list[tuple[int, float]]]
) -> None:
    root = tmp_path_factory.mktemp("cmp")
    _seed(root, files)
    before = _rows(root)
    result = asyncio.run(_compact(root))
    assert result.skipped is False
    assert _rows(root) == before
    t = pq.read_table(root / PART / "part-0000.parquet")
    keys = list(
        zip(t.column("ts").cast(pa.int64()).to_pylist(), t.column("price").to_pylist(), strict=True)
    )
    assert keys == sorted(keys)


def test_cold_modules_have_no_module_level_logger() -> None:
    """Structural guard (#2009 pattern): a cached module-level logger escapes capture_logs()."""
    from candleviewer.storage.cold import exporter, scrub

    for mod in (compactor_mod, exporter, scrub):
        assert not hasattr(mod, "logger"), mod.__name__

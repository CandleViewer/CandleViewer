"""Unit tests: manifest store, checksum verification, schema registry
(SR-094). See ticket AC: corrupted-byte verify quarantine, and the
crash-point resume reconciliation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pyarrow as pa
import pytest

from candleviewer.storage.cold.manifest import (
    ChecksumMismatch,
    ManifestEntry,
    ManifestStore,
    SchemaRegistry,
    sha256_of,
)
from candleviewer.storage.cold.writer import write_parquet_file


def _write_sample(dest: Path, ts_values: list[int]) -> int:
    table = pa.table({"ts": pa.array(ts_values, type=pa.int64()), "price": [1.0] * len(ts_values)})
    write_parquet_file(table, dest)
    return int(table.num_rows)


def test_append_reconciled_replaces_same_file_entry(tmp_path: Path) -> None:
    cold_root = tmp_path
    partition_dir = cold_root / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17"
    manifests_dir = cold_root / "_manifests"
    store = ManifestStore(manifests_dir)

    entry_v1 = ManifestEntry(
        file="part-0000.parquet",
        sha256="a" * 64,
        row_count=10,
        source_table="trades",
        export_run_id="run-1",
        exported_at_us=1,
    )
    store.append_reconciled(partition_dir, cold_root, entry_v1)
    assert store.read(partition_dir, cold_root) == [entry_v1]

    entry_v2 = ManifestEntry(
        file="part-0000.parquet",
        sha256="b" * 64,
        row_count=10,
        source_table="trades",
        export_run_id="run-2",
        exported_at_us=2,
    )
    store.append_reconciled(partition_dir, cold_root, entry_v2)
    entries = store.read(partition_dir, cold_root)
    assert entries == [entry_v2]


def test_verify_checksums_passes_for_untouched_file(tmp_path: Path) -> None:
    cold_root = tmp_path
    partition_dir = cold_root / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17"
    manifests_dir = cold_root / "_manifests"
    dest = partition_dir / "part-0000.parquet"
    row_count = _write_sample(dest, [1, 2, 3])

    store = ManifestStore(manifests_dir)
    store.append_reconciled(
        partition_dir,
        cold_root,
        ManifestEntry(
            file="part-0000.parquet",
            sha256=sha256_of(dest),
            row_count=row_count,
            source_table="trades",
            export_run_id="run-1",
            exported_at_us=1,
        ),
    )

    assert store.verify_checksums(partition_dir, cold_root) is True


def test_verify_checksums_raises_on_corrupted_byte(tmp_path: Path) -> None:
    cold_root = tmp_path
    partition_dir = cold_root / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17"
    manifests_dir = cold_root / "_manifests"
    dest = partition_dir / "part-0000.parquet"
    row_count = _write_sample(dest, [1, 2, 3])

    store = ManifestStore(manifests_dir)
    store.append_reconciled(
        partition_dir,
        cold_root,
        ManifestEntry(
            file="part-0000.parquet",
            sha256=sha256_of(dest),
            row_count=row_count,
            source_table="trades",
            export_run_id="run-1",
            exported_at_us=1,
        ),
    )

    # Corrupt one byte in the middle of the file, mid-file so Parquet's
    # footer (row count) can usually still be parsed but the checksum
    # necessarily changes.
    data = bytearray(dest.read_bytes())
    data[len(data) // 2] ^= 0xFF
    dest.write_bytes(bytes(data))

    with pytest.raises(ChecksumMismatch):
        store.verify_checksums(partition_dir, cold_root)


def test_schema_registry_register_then_read_roundtrip(tmp_path: Path) -> None:
    registry = SchemaRegistry(tmp_path / "schema-registry.json")
    assert registry.columns_for("trades") is None
    registry.register("trades", frozenset({"ts", "price", "symbol"}))
    assert registry.columns_for("trades") == frozenset({"ts", "price", "symbol"})
    # A second dataset key does not clobber the first.
    registry.register("bars", frozenset({"ts", "open"}))
    assert registry.columns_for("trades") == frozenset({"ts", "price", "symbol"})


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        "[]",
        '{"layout_version": 99, "entries": []}',
        '{"layout_version": 1, "entries": [{"bogus": 1}]}',
    ],
)
def test_manifest_read_rejects_corrupt_or_unknown_documents(tmp_path: Path, payload: str) -> None:
    from candleviewer.storage.cold.manifest import ManifestCorrupt, ManifestStore

    part = tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17"
    doc = (tmp_path / "_manifests" / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17").with_suffix(
        ".json"
    )
    doc.parent.mkdir(parents=True)
    doc.write_text(payload, encoding="utf-8")
    with pytest.raises(ManifestCorrupt):
        ManifestStore(tmp_path / "_manifests").read(part, tmp_path)


def test_row_count_mismatch_is_detected(tmp_path: Path) -> None:
    import dataclasses

    from candleviewer.storage.cold.manifest import (
        ManifestEntry,
        ManifestStore,
        RowCountMismatch,
        sha256_of,
    )

    part = tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17"
    dest = part / "part-0000.parquet"
    rows = _write_sample(dest, [1, 2])
    store = ManifestStore(tmp_path / "_manifests")
    entry = ManifestEntry("part-0000.parquet", sha256_of(dest), rows, "trades", "r", 1)
    store.write(part, tmp_path, [dataclasses.replace(entry, row_count=rows + 1)])
    with pytest.raises(RowCountMismatch):
        store.verify_checksums(part, tmp_path)


def test_quarantine_moves_file_and_drops_manifest_entry(tmp_path: Path) -> None:
    from candleviewer.storage.cold.manifest import ManifestEntry, ManifestStore, sha256_of

    part = tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17"
    dest = part / "part-0000.parquet"
    rows = _write_sample(dest, [1])
    store = ManifestStore(tmp_path / "_manifests")
    store.write(part, tmp_path, [ManifestEntry(dest.name, sha256_of(dest), rows, "trades", "r", 1)])
    rel = store.quarantine(part, tmp_path, dest.name)
    assert (tmp_path / rel).exists() and not dest.exists()
    assert rel.parts[0] == "_quarantine"
    assert store.read(part, tmp_path) == []
    store.quarantine(part, tmp_path, dest.name)  # idempotent when already moved


def test_a_quarantine_marks_its_partition_until_its_mirror_is_removed(tmp_path: Path) -> None:
    """#3477: `_quarantine/<partition>/` is the mark its readers refuse on; the runbook's last
    step, removing it after a verified re-export, clears it."""
    part = tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17"
    other = tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-18"
    dest = part / "part-0000.parquet"
    rows = _write_sample(dest, [1])
    store = ManifestStore(tmp_path / "_manifests")
    store.write(part, tmp_path, [ManifestEntry(dest.name, sha256_of(dest), rows, "trades", "r", 1)])
    assert not store.has_quarantined_part(part, tmp_path)

    rel = store.quarantine(part, tmp_path, dest.name)

    assert store.has_quarantined_part(part, tmp_path)
    assert not store.has_quarantined_part(other, tmp_path)
    shutil.rmtree((tmp_path / rel).parent)
    assert not store.has_quarantined_part(part, tmp_path)


def test_a_part_found_missing_marks_its_partition_too(tmp_path: Path) -> None:
    """An entry whose file is gone is quarantined by its entry alone: nothing moves, and the
    mirror is an empty directory, which marks the partition all the same."""
    part = tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17"
    store = ManifestStore(tmp_path / "_manifests")
    store.write(part, tmp_path, [ManifestEntry("part-0000.parquet", "0" * 64, 1, "trades", "r", 1)])

    rel = store.quarantine(part, tmp_path, "part-0000.parquet")

    assert not any((tmp_path / rel).parent.iterdir())
    assert store.has_quarantined_part(part, tmp_path)


def test_a_mirror_that_cannot_be_looked_up_is_never_taken_for_none(tmp_path: Path) -> None:
    """Fail closed: only a mirror that does not exist clears the partition."""
    part = tmp_path / "trades" / "symbol=BTCUSDT" / "dt=2026-10-17"
    (tmp_path / "_quarantine").write_text("not a directory", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        ManifestStore(tmp_path / "_manifests").has_quarantined_part(part, tmp_path)

"""Cold-tier export manifest — per-file SHA-256, row counts, schema registry.

`docs/plan/21-database-schema.md` Sec.5.1: `_manifests/<dt>.json`. This
module owns manifest read/write and `verify_checksums()` (used by the
weekly scrub, SR-094, and by `verify_checksums` on the `ColdTierRepository`
Protocol) plus the schema-drift registry the exporter fails closed against.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


class ManifestCorrupt(ValueError):
    """The on-disk manifest file is not valid JSON / not the expected shape."""


class ChecksumMismatch(ValueError):
    """`verify_checksums` found a file whose SHA-256 no longer matches the
    manifest — SR-094: the file must be quarantined and a CRITICAL
    `system_events` row raised by the caller (this module only detects)."""

    def __init__(self, path: Path, expected: str, actual: str) -> None:
        super().__init__(f"checksum mismatch for {path}: expected {expected}, got {actual}")
        self.path = path
        self.expected = expected
        self.actual = actual


class RowCountMismatch(ValueError):
    """`verify_checksums` found a file whose row count no longer matches the
    manifest entry (a truncated or otherwise silently-modified file)."""

    def __init__(self, path: Path, expected: int, actual: int) -> None:
        super().__init__(f"row count mismatch for {path}: expected {expected}, got {actual}")
        self.path = path
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One recorded Parquet file: its checksum, row count and provenance."""

    file: str
    sha256: str
    row_count: int
    source_table: str
    export_run_id: str
    exported_at_us: int
    range_start_us: int = 0
    range_end_us: int = 0


def sha256_of(path: Path) -> str:
    """Streamed SHA-256 — never loads the whole file into memory (files can
    be up to the 512 MiB compaction target)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: object) -> None:
    """Write `payload` to `path` via `.tmp` + fsync + `os.rename` — same
    atomicity discipline as Parquet file writes (ticket "Technical notes /
    design": "Atomicity")."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


#: Cold-lake layout version recorded in every manifest document
#: (`21-database-schema.md` Sec.5.1). Bump only with a reader for the old
#: layout (C-2.15, `.claude/rules/60-database-migrations.md`).
LAYOUT_VERSION = 1

QUARANTINE_DIR = "_quarantine"


class ManifestStore:
    """Reads/writes one partition's manifest file:
    `_manifests/<stream>/<symbol>/<partition-key>.json`, keyed by the
    partition directory relative to `CV_COLD_ROOT` so re-running an export
    for the same partition reconciles to one entry set rather than growing
    unboundedly (ticket AC: "the duplicate file is reconciled to a single
    manifest entry")."""

    def __init__(self, manifests_dir: Path) -> None:
        self._manifests_dir = manifests_dir

    def _manifest_path(self, partition_dir: Path, cold_root: Path) -> Path:
        rel = partition_dir.relative_to(cold_root)
        return self._manifests_dir / rel.with_suffix(".json")

    def read(self, partition_dir: Path, cold_root: Path) -> list[ManifestEntry]:
        path = self._manifest_path(partition_dir, cold_root)
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
                raise ManifestCorrupt(f"manifest {path.name} has an unexpected shape")
            if raw.get("layout_version") != LAYOUT_VERSION:
                raise ManifestCorrupt(f"manifest {path.name} has unknown layout_version")
            return [ManifestEntry(**entry) for entry in raw["entries"]]
        except (json.JSONDecodeError, TypeError) as exc:
            raise ManifestCorrupt(f"manifest {path.name} is not valid") from exc

    def write(self, partition_dir: Path, cold_root: Path, entries: list[ManifestEntry]) -> None:
        """Overwrite the manifest for `partition_dir` with exactly
        `entries` — the caller (exporter/compactor) is responsible for
        reconciling duplicates into this final list before calling."""
        path = self._manifest_path(partition_dir, cold_root)
        doc = {
            "layout_version": LAYOUT_VERSION,
            "entries": [asdict(e) for e in sorted(entries, key=lambda e: e.file)],
        }
        _atomic_write_json(path, doc)

    def append_reconciled(self, partition_dir: Path, cold_root: Path, entry: ManifestEntry) -> None:
        """Append `entry`, replacing any existing entry for the same
        `file` name (the reconciliation the crash-resume AC requires)."""
        existing = self.read(partition_dir, cold_root)
        merged = [e for e in existing if e.file != entry.file]
        merged.append(entry)
        self.write(partition_dir, cold_root, merged)

    def verify_checksums(self, partition_dir: Path, cold_root: Path) -> bool:
        """Recompute SHA-256 and row count (via `pyarrow.parquet` metadata)
        for every manifest entry in `partition_dir`. Raises on the first
        mismatch (SR-094) rather than returning `False` — see
        `ChecksumMismatch`/`RowCountMismatch`."""
        import pyarrow.parquet as pq

        for entry in self.read(partition_dir, cold_root):
            file_path = partition_dir / entry.file
            actual_sha = sha256_of(file_path)
            if actual_sha != entry.sha256:
                raise ChecksumMismatch(file_path, entry.sha256, actual_sha)
            actual_rows = pq.ParquetFile(file_path).metadata.num_rows
            if actual_rows != entry.row_count:
                raise RowCountMismatch(file_path, entry.row_count, actual_rows)
        return True

    def quarantine(self, partition_dir: Path, cold_root: Path, file_name: str) -> Path:
        """SR-094: move `file_name` to `_quarantine/<same relative path>` and
        drop it from the manifest so no reader is ever served its data.
        Returns the quarantine path relative to `cold_root`."""
        src = partition_dir / file_name
        rel = src.relative_to(cold_root)
        dest = cold_root / QUARANTINE_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            os.replace(src, dest)
        remaining = [e for e in self.read(partition_dir, cold_root) if e.file != file_name]
        self.write(partition_dir, cold_root, remaining)
        return dest.relative_to(cold_root)

    def has_quarantined_part(self, partition_dir: Path, cold_root: Path) -> bool:
        """#3477: whether `quarantine` took a part of this partition out and its mark, the
        partition's directory under `_quarantine/`, is still there. The manifest no longer names
        that part, so serving the rest would serve the partition partly (C-2.14): the cold
        readers refuse it until an operator removes the directory after a verified re-export.
        An empty directory counts (a part found missing is quarantined by its entry alone), and
        any failure to look it up other than its absence is raised, never read as "none"."""
        try:
            os.lstat(cold_root / QUARANTINE_DIR / partition_dir.relative_to(cold_root))
        except FileNotFoundError:
            return False
        return True


class SchemaRegistry:
    """`cold/_manifests/schema-registry.json` — the exporter's fail-closed
    drift check (`21-database-schema.md` Sec.5.2 last paragraph)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def columns_for(self, dataset_key: str) -> frozenset[str] | None:
        if not self._path.exists():
            return None
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        cols = raw.get(dataset_key)
        return frozenset(cols) if cols is not None else None

    def register(self, dataset_key: str, columns: frozenset[str]) -> None:
        raw: dict[str, list[str]] = {}
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        raw[dataset_key] = sorted(columns)
        _atomic_write_json(self._path, raw)

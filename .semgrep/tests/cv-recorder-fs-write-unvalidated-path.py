"""Fixtures for cv-recorder-fs-write-unvalidated-path (E16-X02, SR-097)."""
from pathlib import Path

import pyarrow.parquet as pq

from candleviewer.storage.cold.writer import AtomicParquetWriter


def planted(table, symbol, user_dir):
    pq.write_table(table, f"/data/{symbol}.parquet")  # ruleid: cv-recorder-fs-write-unvalidated-path
    AtomicParquetWriter(Path(user_dir) / "part.parquet", table.schema)  # ruleid: cv-recorder-fs-write-unvalidated-path
    pq.ParquetWriter(user_dir, table.schema)  # ruleid: cv-recorder-fs-write-unvalidated-path
    Path(user_dir).write_bytes(b"x")  # ruleid: cv-recorder-fs-write-unvalidated-path
    with open(user_dir, "wb") as fh:  # ruleid: cv-recorder-fs-write-unvalidated-path
        fh.write(b"x")


async def export_symbol(table, symbol: str, archive_path: str) -> None:
    """The planted defect: a Parquet write through a caller-supplied directory."""
    target = Path(archive_path) / f"{symbol}.parquet"
    pq.write_table(table, target)  # ruleid: cv-recorder-fs-write-unvalidated-path


def good(paths, table, wal_dir, runs_dir):
    AtomicParquetWriter(paths.partition_dir / "part-0001.parquet", table.schema)  # ok: cv-recorder-fs-write-unvalidated-path
    pq.write_table(table, paths.partition_dir / "part-0002.parquet")  # ok: cv-recorder-fs-write-unvalidated-path
    (wal_dir / "spill.wal").write_bytes(b"x")  # ok: cv-recorder-fs-write-unvalidated-path
    with open(runs_dir / "meta.json", "w") as fh:  # ok: cv-recorder-fs-write-unvalidated-path
        fh.write("{}")
    with open(paths.partition_dir / "f.parquet", "rb") as fh:  # ok: cv-recorder-fs-write-unvalidated-path
        fh.read()

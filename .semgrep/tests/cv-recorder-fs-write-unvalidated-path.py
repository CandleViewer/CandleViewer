"""Fixtures for cv-recorder-fs-write-unvalidated-path (E16-X02, SR-097)."""
import os
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


async def export_symbol_renamed(table, symbol: str, archive_path: str) -> None:
    """The same defect with the unchecked path held in a local named like a registry target."""
    dest = Path(archive_path) / f"{symbol}.parquet"
    pq.write_table(table, dest)  # ruleid: cv-recorder-fs-write-unvalidated-path
    tmp = Path(archive_path) / "part.tmp"
    tmp.write_bytes(b"x")  # ruleid: cv-recorder-fs-write-unvalidated-path


def planted_open_forms(user_dir):
    fd = os.open(user_dir, os.O_WRONLY | os.O_CREAT, 0o600)  # ruleid: cv-recorder-fs-write-unvalidated-path
    os.open(user_dir, os.O_APPEND)  # ruleid: cv-recorder-fs-write-unvalidated-path
    with open(user_dir, mode="w") as fh:  # ruleid: cv-recorder-fs-write-unvalidated-path
        fh.write("x")
    with Path(user_dir).open(mode="wb") as fh:  # ruleid: cv-recorder-fs-write-unvalidated-path
        fh.write(b"x")
    return fd


def good(paths, table, wal_dir, runs_dir):
    AtomicParquetWriter(paths.partition_dir / "part-0001.parquet", table.schema)  # ok: cv-recorder-fs-write-unvalidated-path
    pq.write_table(table, paths.partition_dir / "part-0002.parquet")  # ok: cv-recorder-fs-write-unvalidated-path
    (wal_dir / "spill.wal").write_bytes(b"x")  # ok: cv-recorder-fs-write-unvalidated-path
    with open(runs_dir / "meta.json", "w") as fh:  # ok: cv-recorder-fs-write-unvalidated-path
        fh.write("{}")
    with open(paths.partition_dir / "f.parquet", "rb") as fh:  # ok: cv-recorder-fs-write-unvalidated-path
        fh.read()


def good_open_forms(user_dir):
    os.open(user_dir, os.O_RDONLY)  # ok: cv-recorder-fs-write-unvalidated-path
    os.open(user_dir, os.O_RDWR)  # ok: cv-recorder-fs-write-unvalidated-path
    with open(user_dir, mode="rb") as fh:  # ok: cv-recorder-fs-write-unvalidated-path
        fh.read()

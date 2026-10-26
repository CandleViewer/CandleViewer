"""Fixture tree for cv-recorder-destructive-outside-retention: a destructive op in the recorder."""
import os
import shutil


async def planted(conn, table, day, partition_dir):
    shutil.rmtree(partition_dir)  # ruleid: cv-recorder-destructive-outside-retention
    os.rmdir(partition_dir)  # ruleid: cv-recorder-destructive-outside-retention
    await conn.fetch(f"ALTER TABLE {table} DROP PARTITION LIST '{day}'")  # ruleid: cv-recorder-destructive-outside-retention
    await conn.fetch(f"TRUNCATE TABLE {table}")  # ruleid: cv-recorder-destructive-outside-retention


def good(partition_dir, tmp):
    # The hot roll-off issues DROP PARTITION only in its own audited site.  # ok: cv-recorder-destructive-outside-retention
    partition_dir.mkdir(parents=True, exist_ok=True)  # ok: cv-recorder-destructive-outside-retention
    os.replace(tmp, partition_dir / "part-0000.parquet")  # ok: cv-recorder-destructive-outside-retention

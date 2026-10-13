"""SR-090..093 restore drill, executed in CI (E07-X02, #276).

Against a real Postgres 16 (testcontainers, CI `integration` job): seed via
`alembic upgrade head` + audit rows through the real `AuditWriter`; back up
with `pg_dump -Fc` (inside the container) plus one Parquet partition written
by the real cold-tier writer; encrypt both with a throwaway backup key that is
distinct from every runtime key (SR-092); destroy both; decrypt + restore;
start the app (`create_app`, storage_backend=real) and require `/readyz` 200;
verify the audit hash chain on the restored rows and the partition's sha256.

Emits `build/reports/restore-drill.json` (gitignored, uploaded by CI) — the
test never writes into the repo's tracked tree.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pyarrow as pa
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr
from testcontainers.postgres import PostgresContainer

from candleviewer.app import create_app
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.settings import Environment, Settings
from candleviewer.storage.cold.writer import write_parquet_file
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_REPORT = _ROOT / "build" / "reports" / "restore-drill.json"
_AUDIT_ROWS = 25
_PARQUET_ROWS = 1000
_PARTITION = Path("trades") / "symbol=BTCUSDT" / "dt=2026-10-17"
_DUMP_IN_CONTAINER = "/tmp/cv-drill.dump"  # noqa: S108 -- path inside the throwaway container


@pytest.fixture(scope="module")
def pg() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


def _dsn(c: PostgresContainer, driver: str) -> str:
    return c.get_connection_url().replace("postgresql+psycopg2", f"postgresql+{driver}")


def _sync(c: PostgresContainer) -> str:
    return c.get_connection_url().replace("postgresql+psycopg2", "postgresql")


def _alembic_head(c: PostgresContainer) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": _dsn(c, "psycopg")},
        check=True,
    )


def _exec(c: PostgresContainer, *argv: str) -> bytes:
    code, out = c.exec(list(argv))
    assert code == 0, f"{argv[0]} failed ({code}): {out.decode(errors='replace')[-2000:]}"
    return bytes(out)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _encrypt(key: bytes, plain: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plain, b"cv-backup-v1")


def _decrypt(key: bytes, blob: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], b"cv-backup-v1")


def _get_file(c: PostgresContainer, path: str) -> bytes:
    stream, _ = c.get_wrapped_container().get_archive(path)
    with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as tar:
        member = tar.extractfile(Path(path).name)
        assert member is not None
        return member.read()


def _put_file(c: PostgresContainer, path: str, data: bytes) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(Path(path).name)
        info.size = len(data)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(data))
    assert c.get_wrapped_container().put_archive(str(Path(path).parent), buf.getvalue())


async def _seed_audit(dsn: str, wal: Path) -> None:
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        writer = AuditWriter(SqlAlchemyAuditRepository(relational), str(wal))
        await writer.start()
        for i in range(_AUDIT_ROWS):
            await writer.emit("orders.submit", actor_label="drill", object_id=str(i))
        await writer.flush(60)
        await writer.stop(5)
    finally:
        await relational.dispose()


def _write_partition(cold_root: Path) -> Path:
    base = int(datetime(2026, 10, 17, tzinfo=UTC).timestamp() * 1_000_000)
    table = pa.table(
        {
            "ts": pa.array(
                [base + i * 1000 for i in range(_PARQUET_ROWS)], pa.timestamp("us", "UTC")
            ),
            "symbol": pa.array(["BTCUSDT"] * _PARQUET_ROWS, pa.string()),
            "price": pa.array([f"{65000 + i % 7}.5" for i in range(_PARQUET_ROWS)], pa.string()),
            "qty": pa.array(["0.01"] * _PARQUET_ROWS, pa.string()),
        }
    )
    dest = cold_root / _PARTITION / "part-0000.parquet"
    assert write_parquet_file(table, dest) == _PARQUET_ROWS
    return dest


def _settings(dsn: str, tmp: Path) -> Settings:
    return Settings(
        environment=Environment.TESTNET,
        storage_backend="real",
        pg_dsn=SecretStr(dsn),
        auth_totp_key_hex=SecretStr("33" * 32),
        auth_recovery_hmac_key_hex=SecretStr("44" * 32),
        auth_csrf_key_hex=SecretStr("55" * 32),
        auth_pepper=SecretStr("drill-pepper"),
        audit_wal_path=str(tmp / "restored-audit.wal"),
    )


async def _start_app_and_verify(dsn: str, tmp: Path) -> tuple[float, int, bool, int]:
    """Start the app on the restored DB; return (ready_s, readyz status,
    chain verified, entries checked) — verification via the app's own
    audit module (`AuditQueryService.verify`)."""
    t0 = time.perf_counter()
    app = create_app(_settings(dsn, tmp))
    ctx = app.state.app_context
    await ctx.audit.start(ctx)
    try:
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
            status = (await c.get("/readyz")).status_code
        ready_s = time.perf_counter() - t0
        result = await ctx.audit.query.verify()
        return ready_s, status, result.verified, result.entries_checked
    finally:
        await ctx.audit.stop(1.0)


async def _verify_only(dsn: str) -> tuple[bool, int]:
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        r = await AuditQueryService(SqlAlchemyAuditRepository(relational)).verify()
        return r.verified, r.entries_checked
    finally:
        await relational.dispose()


@pytest.mark.asyncio
async def test_sr093_restore_drill_pg_and_parquet_restored_app_ready(
    pg: PostgresContainer, tmp_path: Path
) -> None:
    started = datetime.now(UTC)
    dsn = _dsn(pg, "asyncpg")
    user, db = pg.username, pg.dbname

    # 1. Seed: schema at head + audit rows via the real writer (trigger-chained).
    _alembic_head(pg)
    await _seed_audit(dsn, tmp_path / "seed.wal")
    pre_verified, pre_rows = await _verify_only(dsn)
    assert pre_verified and pre_rows == _AUDIT_ROWS
    cold = tmp_path / "cold"
    part = _write_partition(cold)
    part_sha = _sha256(part)

    # 2. Back up (SR-090/091): pg_dump custom format + the partition, each
    #    encrypted with a throwaway backup key distinct from runtime keys (SR-092).
    _exec(pg, "pg_dump", "-U", user, "-d", db, "-Fc", "-f", _DUMP_IN_CONTAINER)
    dump = _get_file(pg, _DUMP_IN_CONTAINER)
    backup_key = AESGCM.generate_key(bit_length=256)
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "postgres.dump.enc").write_bytes(_encrypt(backup_key, dump))
    (backup / "partition.parquet.enc").write_bytes(_encrypt(backup_key, part.read_bytes()))

    # 3. Destroy both.
    _exec(pg, "rm", "-f", _DUMP_IN_CONTAINER)
    with psycopg.connect(_sync(pg), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        gone = conn.execute("SELECT to_regclass('public.audit_log')").fetchone()
        assert gone == (None,)
    shutil.rmtree(cold / _PARTITION)
    assert not part.exists()

    # 4. Backup is useless without its key (runtime-style key must fail; SR-092).
    with pytest.raises(InvalidTag):
        _decrypt(bytes.fromhex("33" * 32), (backup / "postgres.dump.enc").read_bytes())

    # 5. Restore.
    t_restore = time.perf_counter()
    _put_file(
        pg, _DUMP_IN_CONTAINER, _decrypt(backup_key, (backup / "postgres.dump.enc").read_bytes())
    )
    _exec(
        pg, "pg_restore", "-U", user, "-d", db, "--no-owner", "--exit-on-error", _DUMP_IN_CONTAINER
    )
    part.parent.mkdir(parents=True)
    part.write_bytes(_decrypt(backup_key, (backup / "partition.parquet.enc").read_bytes()))
    restore_s = time.perf_counter() - t_restore
    with psycopg.connect(_sync(pg)) as conn:
        row = conn.execute("SELECT count(*) FROM audit_log").fetchone()
    pg_rows = int(row[0]) if row else -1
    restored_sha = _sha256(part)

    # 6. App starts on the restored data; chain verifies through the app.
    ready_s, readyz, verified, checked = await _start_app_and_verify(dsn, tmp_path)

    report = {
        "drill": "E07-X02 SR-090..093 restore drill",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "github_run": os.environ.get("GITHUB_RUN_ID"),
        "postgres": {
            "dump_bytes": len(dump),
            "audit_rows_seeded": _AUDIT_ROWS,
            "audit_rows_restored": pg_rows,
            "chain_verified": verified,
            "chain_entries_checked": checked,
        },
        "parquet": {
            "partition": _PARTITION.as_posix(),
            "rows": _PARQUET_ROWS,
            "sha256_before": part_sha,
            "sha256_after": restored_sha,
            "match": part_sha == restored_sha,
        },
        "decrypt_with_wrong_key": "InvalidTag (refused)",
        "restore_seconds": round(restore_s, 3),
        "app": {"readyz_status": readyz, "ready_seconds": round(ready_s, 3)},
    }
    _REPORT.parent.mkdir(parents=True, exist_ok=True)
    _REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    assert pg_rows == _AUDIT_ROWS
    assert restored_sha == part_sha
    assert readyz == 200
    assert verified and checked == _AUDIT_ROWS

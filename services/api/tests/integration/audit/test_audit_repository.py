"""Integration: `0003_audit_log` + `SqlAlchemyAuditRepository` against real
Postgres 16 (testcontainers). Covers the DB-side AC: trigger-computed chain
with 64-zero genesis, Python verifier agreeing byte-for-byte with the
trigger, out-of-band tamper located, cv_app refused UPDATE/DELETE,
round-trip upgrade/downgrade/upgrade, checkpoint idempotency. #2266: in-transaction inserts
through `insert_audit_row_locked` interleave with the WAL path in one verified chain, and the
negative control (an insert without the explicit lock) shows why the lock comes first.

Not run locally (no docker); exercised by the `migrations`/integration CI jobs.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
import sqlalchemy as sa
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.models import VerifyResult
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.storage.repositories.audit_sqlalchemy import (
    SqlAlchemyAuditRepository,
    insert_audit_row_locked,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        _alembic(dsn, "upgrade", "head")
        yield dsn


def _alembic(dsn: str, *args: str) -> None:
    subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        check=True,
    )


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


async def _emit_n(dsn: str, n: int, wal: Path) -> None:
    """Engine is built inside the running loop and disposed before it closes
    (never shared across `asyncio.run` calls — asyncpg futures are
    loop-bound; that was the `different loop` CI failure)."""
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        writer = AuditWriter(SqlAlchemyAuditRepository(relational), str(wal))
        await writer.start()
        for i in range(n):
            await writer.emit(
                "orders.submit",
                actor_label="bot",
                actor_ip="10.0.0.7",
                object_id=str(i),
                before_state={"qty": "0.01", "password_hash": "x"} if i % 2 else None,
            )
        await writer.flush(60)
        await writer.stop(5)
    finally:
        await relational.dispose()


async def _verify(dsn: str) -> VerifyResult:
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        return await AuditQueryService(SqlAlchemyAuditRepository(relational)).verify()
    finally:
        await relational.dispose()


def test_trigger_chain_genesis_and_python_verifier_agree(pg_dsn: str, tmp_path: Path) -> None:
    asyncio.run(_emit_n(pg_dsn, 1000, tmp_path / "a.wal"))
    with psycopg.connect(_sync(pg_dsn)) as conn:
        first = conn.execute("SELECT prev_hash FROM audit_log ORDER BY id LIMIT 1").fetchone()
        assert first is not None and first[0] == "0" * 64
        leak = conn.execute(
            "SELECT count(*) FROM audit_log WHERE before_state::text LIKE '%\"x\"%'"
        )
        assert leak.fetchone() == (0,)
    result = asyncio.run(_verify(pg_dsn))
    assert result.verified and result.entries_checked >= 1000


def test_superuser_tamper_is_located(pg_dsn: str, tmp_path: Path) -> None:
    asyncio.run(_emit_n(pg_dsn, 5, tmp_path / "b.wal"))
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        victim = conn.execute("SELECT max(id) - 2 FROM audit_log").fetchone()
        assert victim is not None
        conn.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_append")
        conn.execute("UPDATE audit_log SET reason = 'forged' WHERE id = %s", (victim[0],))
        conn.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_append")
    result = asyncio.run(_verify(pg_dsn))
    assert not result.verified and result.first_bad_id == victim[0]


def test_truncate_refused_even_for_owner(pg_dsn: str) -> None:
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute("TRUNCATE audit_log")


def test_app_role_cannot_update_or_delete(pg_dsn: str) -> None:
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        conn.execute("CREATE ROLE cv_app_t LOGIN PASSWORD 'test-only'")
        conn.execute("GRANT SELECT, INSERT ON audit_log TO cv_app_t")
        conn.execute("SET ROLE cv_app_t")
        for stmt in ("UPDATE audit_log SET reason = 'x'", "DELETE FROM audit_log"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(stmt)


def test_migration_downgrade_refused_while_audit_history_exists(
    pg_dsn: str, tmp_path: Path
) -> None:
    asyncio.run(_emit_n(pg_dsn, 1, tmp_path / "c.wal"))
    with pytest.raises(subprocess.CalledProcessError):
        _alembic(pg_dsn, "downgrade", "0002_rbac_seed")


def test_migration_round_trip_on_empty_db() -> None:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        _alembic(dsn, "upgrade", "head")
        _alembic(dsn, "downgrade", "0002_rbac_seed")
        _alembic(dsn, "upgrade", "head")


_T0 = datetime(2026, 10, 18, tzinfo=UTC)
Insert = Callable[[SqlAlchemyRelationalRepository, dict[str, Any]], Awaitable[None]]
_WAITING = "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
_HOLDER_ROW = (
    "INSERT INTO audit_log (record_id, actor_label, action) VALUES (%s, 'h', 'auth.login')"
)


def _record(label: str) -> dict[str, Any]:
    return {
        "record_id": str(uuid.uuid4()), "actor_label": label, "action": "auth.login",
        "outcome": "success", "severity": "info", "event_ts": _T0.isoformat(),
    }  # fmt: skip


async def _locked(relational: SqlAlchemyRelationalRepository, record: dict[str, Any]) -> None:
    """An in-transaction insert through the lock-first helper (#2266)."""
    async with relational.unit_of_work() as uow:
        assert await insert_audit_row_locked(uow.session, record)
        await uow.commit()


async def _unlocked(relational: SqlAlchemyRelationalRepository, record: dict[str, Any]) -> None:
    """The negative control: an INSERT whose only chain lock is the trigger's, which it takes
    after the bigserial default has drawn its id."""
    insert = "INSERT INTO audit_log (record_id, actor_label, action) VALUES (:r, 'w', 'auth.login')"
    async with relational.unit_of_work() as uow:
        await uow.session.execute(sa.text(insert), {"r": uuid.UUID(record["record_id"])})
        await uow.commit()


async def _race(dsn: str, insert: Insert) -> tuple[int, int, VerifyResult]:
    """`insert` starts while another connection holds the chain lock, and waits; the holder then
    commits a row of its own, which releases the lock. Returns the waiter's id, the holder's id
    and the verify result over the two."""
    relational = SqlAlchemyRelationalRepository(dsn)
    query = AuditQueryService(SqlAlchemyAuditRepository(relational))
    waiter, holder = _record("waiter"), _record("holder")
    try:
        async with await psycopg.AsyncConnection.connect(_sync(dsn)) as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext('audit_log'))")
            task = asyncio.ensure_future(insert(relational, waiter))
            async with asyncio.timeout(30):  # fails a missed wait fast
                while not await (await conn.execute(_WAITING)).fetchall():
                    pass
            await conn.execute(_HOLDER_ROW, (holder["record_id"],))
            await conn.commit()  # releases the chain lock
            await task
            ids = "SELECT id FROM audit_log WHERE record_id = %s"
            [(w,)] = await (await conn.execute(ids, (waiter["record_id"],))).fetchall()
            [(h,)] = await (await conn.execute(ids, (holder["record_id"],))).fetchall()
        return w, h, await query.verify(from_id=min(w, h), to_id=max(w, h))
    finally:
        query.close()
        await relational.dispose()


async def test_an_insert_without_the_explicit_lock_breaks_the_chain(pg_dsn: str) -> None:
    """The waiter drew its id first but hashed after the holder's later row, so verify, which
    walks by id, names it."""
    waiter, holder, result = await _race(pg_dsn, _unlocked)
    assert waiter < holder and not result.verified and result.first_bad_id == waiter


async def test_the_lock_first_helper_keeps_the_chain_under_the_same_schedule(pg_dsn: str) -> None:
    waiter, holder, result = await _race(pg_dsn, _locked)
    assert holder < waiter and result.verified and result.entries_checked == 2


async def test_wal_path_and_in_transaction_inserts_interleave_into_one_verified_chain(
    pg_dsn: str,
) -> None:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    repo = SqlAlchemyAuditRepository(relational)
    query = AuditQueryService(repo)
    try:
        head = await repo.read_head()
        records = [_record(f"r{i}") for i in range(40)]
        await asyncio.gather(
            *(repo.insert(r) for r in records[::2]),  # the WAL flusher's path
            *(_locked(relational, r) for r in records[1::2]),
        )
        result = await query.verify(from_id=1 if head is None else head[0] + 1)
        assert result.verified and result.entries_checked == 40
    finally:
        query.close()
        await relational.dispose()

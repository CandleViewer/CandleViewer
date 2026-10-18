"""Integration: `SqlAlchemyBackups`' reads on real Postgres 16 at head (E42-T05 #966 BK-3a), what
the fake cannot show. testcontainers, CI-only; run before the PR on a scratch Postgres 16.4."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from structlog.testing import capture_logs
from testcontainers.postgres import PostgresContainer

from candleviewer.api._generated.openapi_models import Backup
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories import backups as port
from candleviewer.storage.repositories import backups_sqlalchemy as repo
from candleviewer.storage.repositories.backups_sqlalchemy import SqlAlchemyBackups
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

pytestmark = pytest.mark.integration

T0, MIN, H = datetime(2026, 10, 18, 9, 0, tzinfo=UTC), timedelta(minutes=1), timedelta(hours=1)
USER, _DIGEST, _ALIAS = UUID(int=77), "a" * 64, "age:" + "offsite-2026"  # the alias: class S
_CONTRACT = {"location": "target_path", "error": "error_message"}  # `Backup` name: column
_WAITING = (  # this store's statements waiting on a lock in this database
    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
    " AND wait_event_type = 'Lock' AND application_name = 'candleviewer:api'"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(  # bounded, so a stuck migration fails the module instead of hanging it
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[3], env=env, check=True, timeout=120,
        )  # fmt: skip
        plain = url.replace("postgresql+psycopg2", "postgresql")
        _q(plain, "INSERT INTO users (id, email, username, password_hash, status) VALUES"
           " (%s, 'ops@x.test', 'ops', '$argon2id$x', 'active') RETURNING id", USER)  # fmt: skip
        yield plain


@pytest.fixture
async def store(pg_dsn: str) -> AsyncIterator[SqlAlchemyBackups]:
    rel = SqlAlchemyRelationalRepository(pg_dsn.replace("postgresql", "postgresql+asyncpg", 1))
    try:
        yield SqlAlchemyBackups(rel)
    finally:
        await rel.dispose()


def _q(dsn: str, query: Any, *args: Any) -> tuple[Any, ...]:
    with psycopg.connect(dsn, autocommit=True) as c:
        return c.execute(query, args).fetchone() or ()


def _seed(dsn: str, *rows: dict[str, Any]) -> list[UUID]:
    """Empty the table, then insert these rows (`pg_dump`s unless they say)."""
    ids: list[UUID] = []
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("TRUNCATE backups")
        for cols in rows:
            row: dict[str, Any] = {"id": uuid4(), "kind": "pg_dump", "target_path": "/b/x"}
            row |= {"started_at": T0} | cols
            names = sql.SQL(", ").join(map(sql.Identifier, row))
            values = sql.SQL(", ").join([sql.Placeholder()] * len(row))
            insert = sql.SQL("INSERT INTO backups ({}) VALUES ({})").format(names, values)
            c.execute(insert, [*row.values()])
            ids.append(row["id"])
    return ids


async def test_keyset_order_with_id_tie_break(pg_dsn: str, store: SqlAlchemyBackups) -> None:
    starts = ((1, 0), (2, 1), (3, 1), (4, 3), (5, 4))  # 2 and 3 share their start
    _seed(pg_dsn, *({"id": UUID(int=n), "started_at": T0 - ago * MIN} for n, ago in starts))
    seen: list[int] = []
    after: port.Position | None = None  # the loop is bounded: a loose keyset would page forever
    while len(seen) < 9 and (page := await store.page(None, None, after, 2)):
        seen, after = seen + [r.id.int for r in page], (page[-1].started_at, page[-1].id)
    assert seen == [1, 3, 2, 4, 5]  # 3 before 2: the same start, the larger id first
    rest = await store.page("pg_dump", "running", (T0 - MIN, UUID(int=3)), 9)
    assert [r.id.int for r in rest] == [2, 4, 5]  # strictly after the position, filters kept


async def test_each_kind_and_status_filter(pg_dsn: str, store: SqlAlchemyBackups) -> None:
    pairs = [(k, s) for k in get_args(port.BackupKind) for s in get_args(port.BackupStatus)]
    rows = _seed(pg_dsn, *({"kind": k, "status": s} for k, s in pairs))
    seeded = dict(zip(rows, pairs, strict=True))
    filters = [(k, None) for k in get_args(port.BackupKind)] + [("config_bundle", "failed")]
    for kind, status in filters + [(None, s) for s in get_args(port.BackupStatus)]:
        got = {r.id for r in await store.page(kind, status, None, 50)}
        assert got == {b for b, pair in seeded.items() if {kind, status} - {None} <= set(pair)}


async def test_a_value_the_database_refuses_is_a_bug_without_its_text(
    store: SqlAlchemyBackups,
) -> None:
    bad: Any = _ALIAS  # not a `backup_kind`: the server's 22P02 message quotes it
    with capture_logs() as logs, pytest.raises(StorageQueryFailed) as refused:
        await store.page(bad, None, None, 1)
    assert refused.value.sqlstate == "22P02" and logs[0]["sqlstate"] == "22P02"
    assert _ALIAS not in str(refused.value) + repr(refused.value) + repr(logs)
    assert refused.value.__cause__ is None and refused.value.__context__ is None


async def test_row_types_match_the_backup_contract(pg_dsn: str, store: SqlAlchemyBackups) -> None:
    [bid] = _seed(pg_dsn, {
        "status": "verified", "target_path": "/b/p", "size_bytes": 2**40, "encrypted": False,
        "checksum_sha256": _DIGEST, "encryption_ref": _ALIAS, "covers_from": T0 - H,
        "covers_to": T0, "verified_at": T0 + MIN, "error_message": "verify_failed",
        "triggered_by": "pre_release", "triggered_by_user": USER, "finished_at": T0,
        "retention_until": T0 + 720 * H, "deleted_at": T0 + 2 * MIN, "deleted_by": USER,
    })  # fmt: skip
    row = await store.get(bid)
    assert row is not None and await store.page(None, None, None, 1) == [row]
    assert await store.get(uuid4()) is None  # an unknown id: no row, never an error
    names = {n: _CONTRACT.get(n, n) for n in Backup.model_fields}
    Backup.model_validate({n: getattr(row, c) for n, c in names.items()}, strict=True)
    assert {f.name for f in fields(port.BackupRow)} - set(names.values()) == {
        "covers_to", "triggered_by",
    }  # fmt: skip
    assert (row.status, row.target_path, row.size_bytes, row.encrypted, row.error_message) == (
        "verified", "/b/p", 2**40, False, "verify_failed",
    )  # fmt: skip
    assert (row.covers_to, row.verified_at, row.finished_at, row.retention_until) == (
        T0, T0 + MIN, T0, T0 + 720 * H,
    )  # fmt: skip
    assert (row.triggered_by, row.started_at, row.deleted_at) == ("pre_release", T0, T0 + 2 * MIN)
    assert _ALIAS not in repr(row) and row.checksum_sha256 == _DIGEST


async def test_statement_timeout_is_an_outage_57014(pg_dsn: str, store: SqlAlchemyBackups) -> None:
    with psycopg.connect(pg_dsn) as holder, capture_logs() as logs:
        holder.execute("LOCK TABLE backups IN ACCESS EXCLUSIVE MODE")
        task = asyncio.ensure_future(store.page("pg_dump", None, None, 1))
        for _ in range(500):  # one connection per poll: its own transaction, a fresh snapshot
            async with await psycopg.AsyncConnection.connect(
                pg_dsn, autocommit=True, connect_timeout=5
            ) as poll:
                waiting = await (await poll.execute(_WAITING)).fetchone()
            if waiting == (1,):
                break
        else:
            pytest.fail("the store's statement never waited on the lock")
        with pytest.raises(StorageTierUnavailable):
            await asyncio.wait_for(task, 10)  # cut by the 1 s cap, not the 30 s session default
    assert [(log["op"], log["sqlstate"]) for log in logs] == [("page", "57014")]


async def test_the_cap_ends_with_its_transaction(store: SqlAlchemyBackups) -> None:
    await store.page(None, None, None, 1)
    async with store._rel.unit_of_work() as uow:  # the cap's statement in a committed unit (X10)
        await uow.session.execute(repo._TIMEOUT, {"timeout": repo.STATEMENT_TIMEOUT})
        await uow.commit()
    async with store._rel.engine.connect() as pooled:  # the one connection both used
        timeout = (await pooled.exec_driver_sql("SHOW statement_timeout")).scalar()
    assert timeout == "0"  # the server's default: `set_config(..., true)` is transaction-local


async def test_last_success_by_kind_ignores_failed_running_and_deleted(
    pg_dsn: str, store: SqlAlchemyBackups
) -> None:
    _seed(
        pg_dsn,
        {"status": "ok", "finished_at": T0 - 2 * H},  # pg_dump's latest success
        {"status": "verified", "finished_at": T0 - 3 * H},
        {"status": "failed", "finished_at": T0 - H}, {"status": "running", "finished_at": T0},
        {"status": "ok", "finished_at": T0 - MIN, "deleted_at": T0},
        {"kind": "pg_basebackup", "status": "restored", "finished_at": T0 - 5 * H},
        {"kind": "parquet_sync", "status": "verified", "finished_at": T0 - 4 * H},
        {"kind": "config_bundle", "status": "failed", "finished_at": T0},
        {"kind": "config_bundle", "status": "verified", "finished_at": T0, "deleted_at": T0},
        {"kind": "questdb_snapshot", "status": "ok"},  # no finish recorded: no sample
    )  # fmt: skip
    assert await store.last_success_by_kind() == {
        "pg_dump": T0 - 2 * H, "pg_basebackup": T0 - 5 * H, "parquet_sync": T0 - 4 * H,
    }  # fmt: skip


async def test_usable_count_needs_a_verified_status_a_verified_at_and_no_deleted_at(
    pg_dsn: str, store: SqlAlchemyBackups
) -> None:
    ids = _seed(
        pg_dsn,
        {"status": "verified", "verified_at": T0}, {"status": "restored", "verified_at": T0},
        {"status": "verified"}, {"status": "ok", "verified_at": T0},
        {"status": "failed", "verified_at": T0},
        {"status": "verified", "verified_at": T0, "deleted_at": T0},
        {"kind": "pg_basebackup", "status": "verified", "verified_at": T0},
    )  # fmt: skip
    counts = [await store.usable_count(k) for k in ("pg_dump", "pg_basebackup", "config_bundle")]
    usable = [port.counts_as_usable(row) for row in [await store.get(b) for b in ids] if row]
    assert counts == [2, 1, 0] and usable == [True, True, False, False, False, False, True]

"""Integration: a backup run's lifecycle on Postgres 16 at head (E42-T05 #966 BK-8), through
`BackupRuns` and `RunRows` over the real `SqlAlchemyBackups`, with the engine, audit and job
runner faked.
testcontainers, CI-only; run before the PR on a scratch Postgres 16.4 (stand-in)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.rows import RunRows
from candleviewer.admin.backups.runs import BackupRuns
from candleviewer.storage.repositories.backups import BackupKind, RunFinished
from candleviewer.storage.repositories.backups_sqlalchemy import SqlAlchemyBackups
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.unit.admin._run_fakes import (
    ALIAS,
    DIGEST,
    OWNER,
    Audit,
    Engine,
    Faults,
    Jobs,
    Limit,
    Lost,
)

pytestmark = pytest.mark.integration

T0, USER = datetime(2026, 10, 18, 21, 0, tzinfo=UTC), UUID(int=77)


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
    with psycopg.connect(pg_dsn, autocommit=True) as c:
        c.execute("TRUNCATE backups")
    rel = SqlAlchemyRelationalRepository(pg_dsn.replace("postgresql", "postgresql+asyncpg", 1))
    try:
        yield SqlAlchemyBackups(rel)
    finally:
        await rel.dispose()


def _q(dsn: str, query: Any, *args: Any) -> tuple[Any, ...]:
    with psycopg.connect(dsn, autocommit=True) as c:
        return c.execute(query, args).fetchone() or ()


def _runs(
    store: SqlAlchemyBackups, trail: list[tuple[str, str]]
) -> tuple[BackupRuns, RunRows, Jobs, Lost]:
    faults, jobs, lost = Faults(), Jobs(), Lost()
    audit = Audit(trail, faults)
    rows = RunRows(store, audit, lost=lost, now=lambda: T0)
    runs = BackupRuns(rows, Engine(faults), gate=BackupJobGate(), jobs=jobs, audit=audit,
                      limit=Limit(), now=lambda: T0)  # fmt: skip
    return runs, rows, jobs, lost


async def test_run_lifecycle_running_to_ok_with_checksum_set_once(
    pg_dsn: str, store: SqlAlchemyBackups
) -> None:
    trail: list[tuple[str, str]] = []
    runs, _, jobs, _ = _runs(store, trail)
    who = replace(OWNER, user_id=USER)  # a user the row's `triggered_by_user` can reference

    async def write_ahead(backup_id: UUID, kind: BackupKind) -> None:
        await runs.audit_requested(who, backup_id, kind=kind, verify=True, note=None)

    started = await runs.start(who, kind="pg_dump", write_ahead=write_ahead)
    assert started.status == "running" and trail == [("record", "requested")]
    async with asyncio.timeout(5):
        await jobs.settled.wait()
    ended = await store.get(started.id)
    assert ended is not None and trail == [("record", "requested"), ("record", "finished")]
    assert (ended.status, ended.size_bytes, ended.checksum_sha256) == ("ok", 1234, DIGEST)
    again = RunFinished(T0 + timedelta(hours=1), None, size_bytes=1, checksum_sha256="c" * 64)
    assert await store.record_run_finished(started.id, again) is None  # it ends once
    assert await store.get(started.id) == ended
    stored = "SELECT triggered_by, triggered_by_user, encryption_ref FROM backups WHERE id = %s"
    assert _q(pg_dsn, stored, started.id) == ("manual", USER, ALIAS)


async def test_a_lost_run_is_ended_failed_once_on_postgres(
    pg_dsn: str, store: SqlAlchemyBackups
) -> None:
    lost = uuid4()
    _q(pg_dsn, "INSERT INTO backups (id, kind, target_path, started_at) VALUES (%s, 'pg_dump',"
       " '/srv/cv/backups/lost.age', %s) RETURNING id", lost, T0 - timedelta(hours=2))  # fmt: skip
    trail: list[tuple[str, str]] = []
    _, rows, _, count = _runs(store, trail)
    assert (await rows.close_lost(), await rows.close_lost()) == (1, 0)  # a second boot: none
    ended = await store.get(lost)
    assert ended is not None and (trail, count.added) == ([("record", "finished")], [1])
    assert (ended.status, ended.error_message, ended.finished_at) == (
        "failed",
        "internal_error",
        T0,
    )

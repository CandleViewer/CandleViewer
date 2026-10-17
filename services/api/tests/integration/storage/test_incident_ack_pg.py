"""Integration: acknowledging an incident on real Postgres 16 (E42-T05, `21-database-schema.md`
3.10.2a), through the composition root's own service. What a fake unit of work cannot show: the row
lock held while the write-ahead record is written, and concurrent acknowledges making one
transition and one record. Each test seeds its own incident. Not run locally (no docker); the same
file was run on a scratch Postgres 16.4 first. CI integration lane."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.ops.incidents import AdminIncidentsService
from candleviewer.admin_wiring import build_admin_incidents
from candleviewer.settings import Settings
from candleviewer.storage.repositories.incidents import AckWriteAhead, IncidentRow
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_USER = UUID(int=77)
_NOWAIT = "SELECT 1 FROM incidents WHERE id = %s FOR UPDATE NOWAIT"
_WAITING = (  # statements waiting on a row lock in this database
    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
    " AND wait_event_type = 'Lock' AND query LIKE %s"
)
_INSERT = (  # an open incident
    "INSERT INTO incidents (id, component, signature, severity, title, first_seen_at, last_seen_at)"
    " VALUES (%s, 'recorder', %s, 'error', 'probe failed', now(), now())"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(  # bounded, so a stuck migration fails the module instead of hanging it
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env=env,
            check=True,
            timeout=120,
        )
        plain = url.replace("postgresql+psycopg2", "postgresql")
        with psycopg.connect(plain, autocommit=True) as c:
            c.execute(
                "INSERT INTO users (id, email, username, password_hash, status)"
                " VALUES (%s, 'ops@example.test', 'ops', '$argon2id$fixed-test-vector', 'active')",
                (_USER,),
            )
        yield plain


@pytest.fixture
async def service(pg_dsn: str) -> AsyncIterator[AdminIncidentsService]:
    rel = SqlAlchemyRelationalRepository(pg_dsn.replace("postgresql", "postgresql+asyncpg", 1))
    settings = Settings(storage_backend="real")  # its own engine is not used: `rel` is shared
    try:
        yield build_admin_incidents(settings, system_settings=SqlAlchemySystemSettings(rel))
    finally:
        await rel.dispose()


def _hook(on_call: Callable[[], Awaitable[object]]) -> tuple[list[str], AckWriteAhead]:
    """The write-ahead hook (the record): it runs inside the transaction, row locked."""
    calls: list[str] = []

    async def hook(before: IncidentRow, after: IncidentRow) -> None:
        calls.append(after.status)
        await on_call()

    return calls, hook


def _seed(dsn: str, n: int) -> UUID:
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(_INSERT, (UUID(int=n), f"{n:016x}"))
    return UUID(int=n)


def _state(dsn: str, incident: UUID) -> tuple[Any, ...]:
    select = "SELECT status, acknowledged_by, acknowledged_at FROM incidents WHERE id = %s"
    with psycopg.connect(dsn, autocommit=True) as c:
        return c.execute(select, (incident,)).fetchone() or ()


async def test_the_record_is_written_with_the_row_locked_and_nothing_committed(
    pg_dsn: str, service: AdminIncidentsService
) -> None:
    incident, seen = _seed(pg_dsn, 1), []

    async def probe() -> None:
        seen.append(_state(pg_dsn, incident)[0])  # another session still sees the old row
        with psycopg.connect(pg_dsn, autocommit=True) as other:
            try:
                other.execute(_NOWAIT, (incident,))
                seen.append("free")
            except psycopg.errors.LockNotAvailable:
                seen.append("locked")

    shown = await service.acknowledge(incident, by=_USER, write_ahead=_hook(probe)[1])
    status, by, at = _state(pg_dsn, incident)
    assert seen == ["open", "locked"] and (status, by) == ("acknowledged", _USER)
    assert shown.acknowledged_at == at  # the row's own, stamped by the database


async def test_concurrent_acknowledges_make_one_transition_and_one_record(
    pg_dsn: str, service: AdminIncidentsService
) -> None:
    incident, release = _seed(pg_dsn, 3), asyncio.Event()
    calls, hook = _hook(release.wait)  # the first record is held until the others queue behind
    running = [
        asyncio.create_task(service.acknowledge(incident, by=_USER, write_ahead=hook))
        for _ in range(5)
    ]
    for _ in range(500):  # no event to wait on: poll (10 ms steps, at most 5 s) for the queue
        with psycopg.connect(pg_dsn, autocommit=True) as c:
            queued = c.execute(_WAITING, ("SELECT incidents.id%FOR UPDATE",)).fetchone()
        if queued == (4,):
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("four acknowledges never queued behind the first")
    release.set()
    shown = await asyncio.gather(*running)
    assert calls == ["acknowledged"] and len({r.acknowledged_at for r in shown}) == 1

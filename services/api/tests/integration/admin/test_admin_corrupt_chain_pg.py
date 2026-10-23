"""Integration (E42-Q01, #962): the corrupted-chain fixture on a migrated Postgres 16.

#962's AC: the fixture reproducibly makes `POST /admin/audit/verify` report the expected
`first_bad_id`, through the route over the real audit service; a second seed changes nothing; a
database not named for tests is refused before any read. Needs Docker (testcontainers); not run
locally while the bench runner holds the VPS. CI `integration` runs it.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from fastapi import FastAPI, Request
from testcontainers.postgres import PostgresContainer

from candleviewer.api.audit import make_audit_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.service import AuditService
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.fixtures.admin.corrupt_chain import ACTOR, FORGED, seed_corrupted_chain
from tests.fixtures.admin.seed import FixtureRefused

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_OWNER = AuditPrincipal(uuid.uuid4(), "fx-owner", frozenset({"*"}), is_owner=True)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:  # its database is named `test`
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


@pytest.fixture
async def audit(pg_dsn: str, tmp_path: Path) -> AsyncIterator[AuditService]:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    service = AuditService(SqlAlchemyAuditRepository(relational))
    settings = SimpleNamespace(
        audit_wal_path=str(tmp_path / "a.wal"), audit_page_structure_budget=50_000
    )
    await service.start(SimpleNamespace(settings=settings))  # type: ignore[arg-type]  # the settings it reads
    try:
        yield service
    finally:
        await service.stop(5)
        await relational.dispose()


class _Owner:
    async def resolve(self, _request: Request) -> AuditPrincipal:
        return _OWNER


async def _verify(service: AuditService) -> Any:
    app = FastAPI()
    app.include_router(make_audit_router(service, _Owner()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fixture") as client:
        response = await client.post("/admin/audit/verify", json={})
    return response


def _forged_ids(dsn: str) -> list[int]:
    with psycopg.connect(_sync(dsn)) as conn:
        rows = conn.execute(
            "SELECT id FROM audit_log WHERE actor_label = %s AND reason = %s", (ACTOR, FORGED)
        )
        return [int(r[0]) for r in rows.fetchall()]


async def test_the_verify_route_reports_the_fixtures_victim(
    pg_dsn: str, audit: AuditService
) -> None:
    victim = await seed_corrupted_chain(audit.writer, _sync(pg_dsn))
    response = await _verify(audit)
    assert response.status_code == 200, response.text
    assert (response.json()["verified"], response.json()["first_bad_id"]) == (False, victim)


async def test_a_second_seed_writes_and_alters_nothing(pg_dsn: str, audit: AuditService) -> None:
    first = await seed_corrupted_chain(audit.writer, _sync(pg_dsn))
    second = await seed_corrupted_chain(audit.writer, _sync(pg_dsn))
    assert second == first
    assert await asyncio.to_thread(_forged_ids, pg_dsn) == [first]


async def test_a_database_not_named_for_tests_is_refused(pg_dsn: str, audit: AuditService) -> None:
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS candleviewer")
        conn.execute("CREATE DATABASE candleviewer")
    other = _sync(pg_dsn).rsplit("/", 1)[0] + "/candleviewer"
    with pytest.raises(FixtureRefused):
        await seed_corrupted_chain(audit.writer, other)

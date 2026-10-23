"""Integration (E42-Q01, #962): the corrupted-chain fixture on a migrated Postgres 16.

#962's AC: the fixture reproducibly makes `POST /admin/audit/verify` report the expected
`first_bad_id`, through the route over the real audit service; a second seed changes nothing; a
database not named for tests is refused before anything is written. Needs Docker (testcontainers);
CI `integration` runs it.
"""

from __future__ import annotations

import asyncio
import math
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from fastapi import FastAPI, Request
from prometheus_client import REGISTRY

from candleviewer.api.audit import make_audit_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.service import AuditService
from candleviewer.observability.audit_query_metrics import cv_audit_chain_verified_state
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.fixtures.admin.corrupt_chain import ACTOR, FORGED, seed_corrupted_chain
from tests.fixtures.admin.seed import FixtureRefused
from tests.integration import _refused

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; its database is named `test`

#: The fixture's entries as the chain holds them, each with the chain's length. `xmin` is the
#: version of the row: an UPDATE, even to an equal value, gives it a new one.
_SNAPSHOT = (
    "SELECT id, xmin::text, entry_hash, reason, (SELECT count(*) FROM audit_log) FROM audit_log"
    " WHERE actor_label = %s ORDER BY id"
)
_LENGTH = "SELECT count(*) FROM audit_log"
_VERIFY_RECORDS = (
    "SELECT reason FROM audit_log WHERE action = 'admin.audit_verify' AND actor_user_id = %s"
    " ORDER BY id"
)


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


def _rows(dsn: str, query: str, *params: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_sync(dsn)) as conn:
        return conn.execute(query, params).fetchall()


def _names(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir())


@pytest.fixture(scope="module")
def owner(pg_dsn: str) -> AuditPrincipal:
    """An Owner who is a `users` row: the verify route's own records name its id, and
    `audit_log.actor_user_id` references `users`."""
    user_id = _refused.seed_user(pg_dsn, username="fx-owner")
    return AuditPrincipal(uuid.UUID(user_id), "fx-owner", frozenset({"*"}), is_owner=True)


@pytest.fixture(scope="module")
def other_dsn(pg_dsn: str) -> str:
    """A migrated database beside `test` whose name does not mark it for tests: a seed that wrote
    here would add entries to a chain that can never be cleaned."""
    with psycopg.connect(_sync(pg_dsn), autocommit=True) as conn:
        conn.execute("CREATE DATABASE candleviewer")
    dsn = pg_dsn.rsplit("/", 1)[0] + "/candleviewer"
    subprocess.run(  # fixed argv, literal alembic subcommand, no shell
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        check=True,
        timeout=120,
    )
    return dsn


@pytest.fixture
async def audit(pg_dsn: str, tmp_path: Path) -> AsyncIterator[AuditService]:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    service = AuditService(SqlAlchemyAuditRepository(relational))
    settings = SimpleNamespace(
        audit_wal_path=str(tmp_path / "a.wal"), audit_page_structure_budget=50_000
    )
    ctx: Any = SimpleNamespace(settings=settings)
    chain_state = REGISTRY.get_sample_value("cv_audit_chain_verified_state")
    try:
        await service.start(ctx)
        yield service
    finally:
        await service.stop(5)
        await relational.dispose()
        # A verify sets this process-wide gauge: leave it as found, as the scheduled-run test does.
        cv_audit_chain_verified_state.set(math.nan if chain_state is None else chain_state)


class _Owner:
    def __init__(self, principal: AuditPrincipal) -> None:
        self._principal = principal

    async def resolve(self, _request: Request) -> AuditPrincipal:
        return self._principal


async def _verify(service: AuditService, principal: AuditPrincipal) -> httpx.Response:
    app = FastAPI()
    app.include_router(make_audit_router(service, _Owner(principal)))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fixture") as client:
        return await client.post("/admin/audit/verify", json={})


async def test_the_verify_route_reports_the_fixtures_victim(
    pg_dsn: str, tmp_path: Path, audit: AuditService, owner: AuditPrincipal
) -> None:
    victim = await seed_corrupted_chain(pg_dsn, tmp_path)
    response = await _verify(audit, owner)
    assert response.status_code == 200, response.text
    assert (response.json()["verified"], response.json()["first_bad_id"]) == (False, victim)


async def test_the_verify_routes_own_records_land_under_the_principal(
    pg_dsn: str, tmp_path: Path, audit: AuditService, owner: AuditPrincipal
) -> None:
    victim = await seed_corrupted_chain(pg_dsn, tmp_path)
    before = await asyncio.to_thread(_rows, pg_dsn, _VERIFY_RECORDS, owner.user_id)
    await _verify(audit, owner)
    await audit.writer.flush(60)
    after = await asyncio.to_thread(_rows, pg_dsn, _VERIFY_RECORDS, owner.user_id)
    assert [reason for (reason,) in after[len(before) :]] == [
        "started",
        f"entry_hash_mismatch@{victim}",
    ]


async def test_the_altered_entry_is_the_fourth_and_the_only_one(
    pg_dsn: str, tmp_path: Path
) -> None:
    await seed_corrupted_chain(pg_dsn, tmp_path)
    query = "SELECT object_id FROM audit_log WHERE actor_label = %s AND reason = %s ORDER BY id"
    assert await asyncio.to_thread(_rows, pg_dsn, query, ACTOR, FORGED) == [("fixture-3",)]


async def test_a_second_seed_answers_the_same_victim(pg_dsn: str, tmp_path: Path) -> None:
    first = await seed_corrupted_chain(pg_dsn, tmp_path)
    assert await seed_corrupted_chain(pg_dsn, tmp_path) == first


async def test_a_second_seed_changes_no_row(pg_dsn: str, tmp_path: Path) -> None:
    await seed_corrupted_chain(pg_dsn, tmp_path)
    before = await asyncio.to_thread(_rows, pg_dsn, _SNAPSHOT, ACTOR)
    await seed_corrupted_chain(pg_dsn, tmp_path)
    assert await asyncio.to_thread(_rows, pg_dsn, _SNAPSHOT, ACTOR) == before


async def test_the_append_only_trigger_is_enabled_after_the_seed(
    pg_dsn: str, tmp_path: Path
) -> None:
    await seed_corrupted_chain(pg_dsn, tmp_path)
    guard = (
        "SELECT tgenabled::text FROM pg_trigger"
        " WHERE tgrelid = 'audit_log'::regclass AND tgname = 'trg_audit_append'"
    )
    assert await asyncio.to_thread(_rows, pg_dsn, guard) == [("O",)]


async def test_a_database_not_named_for_tests_is_refused(other_dsn: str, tmp_path: Path) -> None:
    with pytest.raises(FixtureRefused):
        await seed_corrupted_chain(other_dsn, tmp_path)


async def test_a_refused_seed_writes_nothing(other_dsn: str, tmp_path: Path) -> None:
    before = await asyncio.to_thread(_rows, other_dsn, _LENGTH)
    with pytest.raises(FixtureRefused):
        await seed_corrupted_chain(other_dsn, tmp_path)
    after = await asyncio.to_thread(_rows, other_dsn, _LENGTH)
    wal = await asyncio.to_thread(_names, tmp_path)
    assert (after, wal) == (before, [])  # no entry, and no WAL file to hold one

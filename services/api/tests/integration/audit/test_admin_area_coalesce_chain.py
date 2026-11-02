"""Integration, #5331: a span of coalesced admin-area reads, a refusal, a write and a summary
leaves ONE verified hash chain (`AuditQueryService.verify`), exactly the rows the policy writes
and no gap. Coalescing only decides whether `emit` is called; no row is ever updated (the table's
`forbid_mutation` trigger would refuse it). Real Postgres 16 via testcontainers (needs Docker)."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from fastapi import Request
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.area_coalescer import AreaEntryCoalescer
from candleviewer.admin.http import AdminAreaRefused, admin_area
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import VerifyResult
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.generated_permissions import Permission
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

pytestmark = pytest.mark.integration
_API = Path(__file__).resolve().parents[3]
_T0 = datetime(2026, 10, 16, 9, 30, tzinfo=UTC)
_WHO = AuditPrincipal(
    UUID(int=1), "owner", frozenset({"admin:read"}), UUID(int=2), "10.0.0.1", UUID(int=3), True
)


@pytest.fixture
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_API,
            env={**os.environ, "CV_PG_DSN": dsn.replace("+asyncpg", "+psycopg")},
            check=True,
        )
        with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
            c.execute(  # audit_log.actor_user_id references users(id)
                "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, %s)",
                [str(_WHO.user_id), "owner@example.test", "owner", "$argon2id$x"],
            )
        yield dsn


class _Resolver:
    def __init__(self) -> None:
        self.who = _WHO

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        return self.who


def _request(method: str, path: str = "/admin/overview") -> Request:
    return Request({"type": "http", "method": method, "path": path, "headers": []})


async def _run(dsn: str, tmp: Path) -> VerifyResult:
    relational = SqlAlchemyRelationalRepository(dsn)
    repo = SqlAlchemyAuditRepository(relational)
    writer = AuditWriter(repo, str(tmp / "a.wal"), flush_batch_size=7)
    await writer.start()
    now = [1000.0]
    coalescer = AreaEntryCoalescer(
        300,
        writer,
        ready=lambda: True,
        monotonic=lambda: now[0],
        wall=lambda: _T0 + timedelta(seconds=now[0] - 1000.0),
    )
    resolver = _Resolver()
    enter = admin_area(Permission.ADMIN_READ, resolver, writer, coalescer=coalescer)
    try:
        for _ in range(12):  # polling: 1 row, then the window ends: a 2nd row carrying the count
            await enter(_request("GET"))
            now[0] += 30
        await enter(_request("POST"))  # a write: its own row
        resolver.who = dataclasses.replace(_WHO, permissions=frozenset())
        with pytest.raises(AdminAreaRefused):  # a refusal: its own row, closes the window
            await enter(_request("GET"))
        resolver.who = _WHO
        await enter(_request("GET"))  # a fresh row after the denial
        await enter(_request("GET"))  # coalesced
        now[0] += 400
        await coalescer.flush_due()  # the window's summary
        await writer.flush(60)
        service = AuditQueryService(repo)
        try:
            return await service.verify(batch_size=7)
        finally:
            service.close()
    finally:
        await writer.stop(5)
        await relational.dispose()


def test_a_coalesced_span_keeps_one_verified_chain_with_exactly_the_policy_rows(
    pg_dsn: str, tmp_path: Path
) -> None:
    result = asyncio.run(_run(pg_dsn, tmp_path))
    with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql")) as conn:
        rows = conn.execute(
            "SELECT outcome, reason FROM audit_log WHERE action = 'admin.area_entered' ORDER BY id"
        ).fetchall()
    assert (result.verified, result.first_bad_id) == (True, None)
    assert [(o, r) for o, r in rows] == [
        ("success", None),  # first poll
        ("success", None),  # the window after it (carries prior_window.reads = 10)
        ("success", None),  # the POST
        ("denied", "missing_permission:admin:read"),
        ("success", None),  # the read after the denial
        ("success", "coalesced_summary"),  # its window's summary (2 reads)
    ]
    assert result.entries_checked == len(rows)

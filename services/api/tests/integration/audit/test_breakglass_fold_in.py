"""Integration, chaos #10 (C-13.6): break-glass records journaled while Postgres was down fold
into `audit_log` exactly once at the next boots and the chain verifies (E09-S11 #2119, S7).
Real Postgres 16 via testcontainers (the CI integration lane; needs Docker)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.journal import journal_dir
from candleviewer.audit.service import AuditService
from candleviewer.audit.wal import AuditWal
from candleviewer.settings import Settings
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration
#: What the CLI journals while Postgres is down: its intent and refusal records.
_ACTIONS = ("auth.break_glass_attempt", "auth.break_glass_refused")
_CLI = {"actor_label": "system:breakglass", "outcome": "denied", "event_ts": "2026-10-15T12:00:00Z"}


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[3],
            env={**os.environ, "CV_PG_DSN": dsn.replace("+asyncpg", "+psycopg")},
            check=True,
        )
        yield dsn


async def _boot(dsn: str, wal: Path) -> bool:
    """One audit-module boot and stop; returns the chain verdict."""
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        svc = AuditService(SqlAlchemyAuditRepository(relational))
        ctx: Any = SimpleNamespace(settings=Settings(audit_wal_path=str(wal)))
        await svc.start(ctx)
        await svc.writer.flush(60)
        verdict = (await svc.query.verify()).verified
        await svc.stop(5)
        return verdict
    finally:
        await relational.dispose()


def test_folded_chain_verifies(pg_dsn: str, tmp_path: Path) -> None:
    wal = tmp_path / "audit.wal"
    journal = AuditWal(journal_dir(str(wal)) / "journal.wal")
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    for record_id, action in zip(ids, _ACTIONS, strict=True):
        journal.append({"record_id": record_id, "action": action, "severity": "critical"} | _CLI)
    assert asyncio.run(_boot(pg_dsn, wal))
    assert asyncio.run(_boot(pg_dsn, wal))  # a second boot folds nothing again
    with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql")) as conn:
        rows = conn.execute(
            "SELECT record_id::text FROM audit_log WHERE action LIKE 'auth.break%' ORDER BY id"
        ).fetchall()
    assert [row[0] for row in rows] == ids

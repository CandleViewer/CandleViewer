"""Integration: text Postgres cannot store (U+0000, a lone surrogate) in an audit record lands
replaced in real Postgres 16 (testcontainers), and the trigger-computed chain verifies.

Not run locally without docker; exercised by the integration CI job."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.models import AuditOutcome, VerifyResult
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_FFFD = "\N{REPLACEMENT CHARACTER}"


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


async def _emit_and_verify(dsn: str, wal: Path) -> VerifyResult:
    relational = SqlAlchemyRelationalRepository(dsn)
    try:
        repo = SqlAlchemyAuditRepository(relational)
        writer = AuditWriter(repo, str(wal))
        await writer.start()
        await writer.emit(
            "auth.login_failed",
            actor_label="\x00ab***(len=3)",
            outcome=AuditOutcome.FAILURE,
            reason="bad\x00reason",
            before_state={"old\x00": "Ctrl+Shift"},
            after_state={"binding\x00": "Ctrl+\x00", "list": ["a\ud800"]},
        )
        await writer.emit("auth.login", actor_label="owner")
        await writer.flush(60)
        await writer.stop(5)
        return await AuditQueryService(repo).verify()
    finally:
        await relational.dispose()


def test_unstorable_text_lands_replaced_and_chain_verifies(pg_dsn: str, tmp_path: Path) -> None:
    result = asyncio.run(_emit_and_verify(pg_dsn, tmp_path / "a.wal"))
    assert result.verified and result.entries_checked == 2
    with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql")) as conn:
        row = conn.execute(
            "SELECT actor_label, reason, before_state, after_state FROM audit_log "
            "WHERE action = 'auth.login_failed'"
        ).fetchone()
    assert row == (
        f"{_FFFD}ab***(len=3)",
        f"bad{_FFFD}reason",
        {f"old{_FFFD}": "Ctrl+Shift"},
        {f"binding{_FFFD}": f"Ctrl+{_FFFD}", "list": ["a?"]},
    )

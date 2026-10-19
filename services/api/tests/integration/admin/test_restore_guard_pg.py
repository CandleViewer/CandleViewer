"""Integration (E42-T05 #966 BK-13): the restore precondition matrix on Postgres 16 at head, with
`maintenance.mode` read fresh from `feature_flags` through `FlagStoreMaintenance` and each
`backup.restore` record written into `audit_log` by the real `AuditWriter`; the catalogue row, its
evidence, the positions, #3084's check and the executor are faked. testcontainers, CI-only; run
before the PR on a scratch Postgres 16.4 (stand-in)."""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.restore import RestoreAccepted, RestoreGuard
from candleviewer.admin.errors import OpsUnavailable
from candleviewer.audit.writer import AuditWriter
from candleviewer.backups_wiring import FlagStoreMaintenance
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.flags_sqlalchemy import FlagSeed, SqlAlchemyFlagRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.unit.admin._restore_fakes import (
    GRANT,
    OWNER,
    POSITIONS,
    REASON,
    Executor,
    Jobs,
    Ports,
    expected,
    request,
)

pytestmark = pytest.mark.integration

STORED = {"on": "true", "off": "false", "unknown": '"on"'}  # jsonb: a string is not a boolean
USER = UUID(int=77)
_OWNER = (
    "INSERT INTO users (id, email, username, password_hash, status)"
    " VALUES (%s, 'owner@x.test', 'owner', '$argon2id$x', 'active')"
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
        with psycopg.connect(plain, autocommit=True) as c:  # the actor `audit_log` references
            c.execute(_OWNER, (USER,))
        yield plain


def _set_maintenance(dsn: str, stored: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("UPDATE feature_flags SET default_value = CAST(%s AS jsonb) WHERE key ="
                  " 'maintenance.mode'", (stored,))  # fmt: skip


async def test_precondition_matrix_against_postgres_flags_and_audit(
    pg_dsn: str, tmp_path: Path
) -> None:
    rel = SqlAlchemyRelationalRepository(pg_dsn.replace("postgresql", "postgresql+asyncpg", 1))
    flags = SqlAlchemyFlagRepository(rel, read_budget_ms=500)
    writer = AuditWriter(SqlAlchemyAuditRepository(rel), str(tmp_path / "audit.wal"))
    maintenance, who, want = FlagStoreMaintenance(flags), replace(OWNER, user_id=USER), []
    await flags.ensure([FlagSeed("maintenance.mode", "boolean", "Maintenance", False, True)])
    await writer.start()
    try:
        for mode, held, ack_open, ack_unknown in itertools.product(
            STORED, POSITIONS, (False, True), (False, True)
        ):
            _set_maintenance(pg_dsn, STORED[mode])
            trail: list[str] = []
            ports, jobs = Ports(trail, positions=POSITIONS[held]), Jobs(trail)
            guard = RestoreGuard(
                Executor(trail), revocations=ports, gate=BackupJobGate(), jobs=jobs, audit=writer,
                rows=ports, evidence=ports, maintenance=maintenance, positions=ports,
            )  # fmt: skip
            acks = {"acknowledge_open_positions": ack_open}
            acks["acknowledge_unknown_positions"] = ack_unknown
            rule = expected(mode, held, ack_open, ack_unknown)
            try:
                answer: Any = await guard.admit(request(**acks), who, GRANT)
            except OpsUnavailable:
                answer = "503"  # raised, never a returned refusal of that name
            accepted = isinstance(answer, RestoreAccepted)
            assert ("accepted" if accepted else getattr(answer, "rule", answer)) == rule
            assert len(jobs.jobs) == int(accepted)
            reason = REASON if accepted else "store_unavailable" if rule == "503" else rule
            want.append(("success" if accepted else "failure", reason, acks))
        await writer.flush(60)
    finally:
        await writer.stop(5)
        await rel.dispose()
    with psycopg.connect(pg_dsn) as c:
        rows = c.execute(
            "SELECT outcome::text, severity::text, reason, after_state FROM audit_log"
            " WHERE action = 'backup.restore' ORDER BY id"
        ).fetchall()
    assert {severity for _, severity, _, _ in rows} == {"error"}
    got = [(o, r, {k: state[k] for k in acks}) for o, _, r, state in rows]
    assert got == want and len(want) == 36

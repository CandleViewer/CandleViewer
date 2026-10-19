"""Integration: the scenario "Backup verification fails" on Postgres 16 at head (E42-T05 #966 BK-9),
through `BackupVerifications` over the real `SqlAlchemyBackups` and the real admin job store, with
the trail's evidence, the artefact reader, the engine's verifier and the audit writer faked.
testcontainers, CI-only; run before the PR on a scratch Postgres 16.4 (stand-in)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.backups.catalogue import BackupCatalogue
from candleviewer.admin.backups.gate import BackupJobGate
from candleviewer.admin.backups.ports import RunRecord
from candleviewer.admin.backups.verify import BackupVerifications
from candleviewer.api._generated import openapi_models as api
from candleviewer.storage.repositories.backups_sqlalchemy import SqlAlchemyBackups
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.unit.admin._run_fakes import OWNER, Audit, Faults, Jobs, Limit

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
BOUND, ON_DISK = "ab" * 32, "cd" * 32  # what the run bound; what the file hashes to now


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        env = {**os.environ, "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg")}
        subprocess.run(  # bounded, so a stuck migration fails the module instead of hanging it
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=Path(__file__).resolve().parents[3], env=env, check=True, timeout=120,
        )  # fmt: skip
        yield url.replace("postgresql+psycopg2", "postgresql")


@pytest.fixture
async def store(pg_dsn: str) -> AsyncIterator[SqlAlchemyBackups]:
    rel = SqlAlchemyRelationalRepository(pg_dsn.replace("postgresql", "postgresql+asyncpg", 1))
    try:
        yield SqlAlchemyBackups(rel)
    finally:
        await rel.dispose()


class Engine:
    """The trail's evidence, the reader of a file that changed since its run, the verifier."""

    size = 1001

    def __init__(self) -> None:
        self.closes, self.verified = 0, list[object]()

    async def run_record(self, backup_id: UUID) -> RunRecord:
        return RunRecord(BOUND)

    async def resolve(self, location: str) -> Engine:
        return self

    async def digest(self) -> str:
        return ON_DISK

    async def stream(self) -> Any:
        yield b""

    def close(self) -> None:
        self.closes += 1

    async def verify(self, *call: Any) -> Any:
        self.verified.append(call)
        return "restore_smoke"


async def test_failed_verification_is_recorded_on_the_row(
    pg_dsn: str, store: SqlAlchemyBackups
) -> None:
    backup, verified_at = uuid4(), T0 - timedelta(days=1)
    with psycopg.connect(pg_dsn, autocommit=True) as c:
        c.execute(
            "INSERT INTO backups (id, kind, status, target_path, checksum_sha256, encrypted,"
            " started_at, finished_at, verified_at, verify_method) VALUES (%s, 'pg_dump',"
            " 'verified', '/srv/cv/backups/pg.dump.age', %s, true, %s, %s, %s, 'restore_smoke')",
            (backup, BOUND, T0 - timedelta(days=2), T0 - timedelta(days=2), verified_at),
        )
    trail: list[tuple[str, str]] = []
    faults, jobs, engine = Faults(), Jobs(), Engine()
    audit = Audit(trail, faults)
    service = BackupVerifications(
        BackupCatalogue(store), store, engine, engine, evidence=engine, gate=BackupJobGate(),
        jobs=jobs, audit=audit, limit=Limit(), now=lambda: T0,
    )  # fmt: skip

    async def write_ahead(backup_id: UUID, job_id: UUID) -> None:
        await service.audit_requested(OWNER, backup_id, job_id)

    job_id = await service.start(OWNER, backup, write_ahead=write_ahead)
    async with asyncio.timeout(5):
        await jobs.settled.wait()
    row = await store.get(backup)
    assert row is not None and (row.status, row.error_message) == ("failed", "checksum_mismatch")
    assert row.verified_at == verified_at  # the last successful verification stands
    job = jobs.store.get(str(job_id))
    assert job is not None
    view = api.Job.model_validate(job.view())
    assert (view.kind, view.status, view.error) == ("backup_verify", "failed", "checksum_mismatch")
    finished = audit.records[-1]
    assert (finished["action"], finished["after_state"]["error"]) == (
        "backup.verified",
        "checksum_mismatch",
    )
    assert (trail, engine.verified, engine.closes) == (
        [("record", "requested"), ("record", "finished")],
        [],
        1,
    )

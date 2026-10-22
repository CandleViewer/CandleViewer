"""Integration: the scheduled audit chain verify run on real Postgres 16 (#2966). The real job runs
the real `ChainVerifyRunner` over `SqlAlchemyAuditRepository` (the trigger-computed chain) and
the real `PgSystemEventWriter`. A row altered behind the chain, as a superuser can, is found by a
scheduled run: its critical `admin.audit_verify` record names the first bad entry, the failure
counter, the gauge and one `audit_chain_break` event follow, and the next run still happens.

Not run locally (no docker); exercised by the CI integration job (testcontainers).
"""

from __future__ import annotations

import asyncio
import math
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from prometheus_client import REGISTRY
from testcontainers.postgres import PostgresContainer

from candleviewer.api.audit_verify_runner import ChainVerifyRunner
from candleviewer.audit.redact import redact
from candleviewer.audit.service import AuditService
from candleviewer.audit.verify_job import AuditVerifyJob
from candleviewer.audit.verify_runner import (
    VerifyOutcome,
    VerifyOutcomeKind,
    VerifyRunRequest,
    VerifyTrigger,
)
from candleviewer.health_wiring import PgSystemEventWriter
from candleviewer.observability.audit_query_metrics import cv_audit_chain_verified_state
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_T0 = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
_MISMATCH = VerifyOutcomeKind.MISMATCH


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        migrate_dsn = url.replace("postgresql+psycopg2", "postgresql+psycopg")
        subprocess.run(  # fixed argv, literal alembic subcommand, no shell
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": migrate_dsn},
            check=True,
            timeout=120,
        )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


def _tamper(dsn: str) -> int:
    """Alter the third of five entries behind the chain, as a superuser can; its id."""
    with psycopg.connect(_sync(dsn), autocommit=True) as conn:
        # The third of the five by position: ids are not consecutive (0045).
        third = conn.execute("SELECT id FROM audit_log ORDER BY id DESC OFFSET 2 LIMIT 1")
        victim = third.fetchone()
        assert victim is not None
        conn.execute("ALTER TABLE audit_log DISABLE TRIGGER trg_audit_append")
        conn.execute("UPDATE audit_log SET reason = 'forged' WHERE id = %s", (victim[0],))
        conn.execute("ALTER TABLE audit_log ENABLE TRIGGER trg_audit_append")
        return int(victim[0])


def _verify_records(dsn: str) -> list[tuple[str, str, str, dict[str, Any]]]:
    sql = (
        "SELECT outcome::text, severity::text, reason, after_state FROM audit_log"
        " WHERE action = 'admin.audit_verify' ORDER BY id"
    )
    with psycopg.connect(_sync(dsn)) as conn:
        return [(str(a), str(b), str(c), d) for a, b, c, d in conn.execute(sql).fetchall()]


def _break_events(dsn: str) -> list[dict[str, Any]]:
    sql = "SELECT details FROM system_events WHERE kind = 'audit_chain_break' ORDER BY id"
    with psycopg.connect(_sync(dsn)) as conn:
        return [row[0] for row in conn.execute(sql).fetchall()]


def _failures() -> float:
    return REGISTRY.get_sample_value("audit_chain_verification_failures_total") or 0.0


def _gauge() -> float | None:
    return REGISTRY.get_sample_value("cv_audit_chain_verified_state")


class _Halt(BaseException):
    """Ends the job loop from its sleep. Not an `Exception`, so the job cannot absorb it."""


class _Time:
    """The job clock and sleep: a sleep adds what it asked for, and halts the loop once `done()`."""

    def __init__(self, done: Callable[[], bool]) -> None:
        self.now, self._done = _T0, done

    def clock(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        if self._done():
            raise _Halt
        self.now += timedelta(seconds=seconds)
        await asyncio.sleep(0)  # one scheduler turn, no wall-clock time


async def test_scheduled_run_finds_a_row_altered_behind_the_chain_and_the_next_run_still_happens(
    pg_dsn: str, tmp_path: Path
) -> None:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    audit = AuditService(SqlAlchemyAuditRepository(relational))
    settings = SimpleNamespace(
        audit_wal_path=str(tmp_path / "a.wal"), audit_page_structure_budget=50_000
    )
    ctx: Any = SimpleNamespace(settings=settings)
    events = PgSystemEventWriter(relational, redact_details=redact)
    real = ChainVerifyRunner(audit, events)
    ended: list[VerifyOutcomeKind] = []

    class _Counting:
        async def run(self, request: VerifyRunRequest) -> VerifyOutcome:
            outcome = await real.run(request)
            ended.append(outcome.outcome)
            return outcome

    metrics = Metrics("demo")
    register_r0(metrics)
    time = _Time(lambda: len(ended) >= 2)
    failures = _failures()
    try:
        await audit.start(ctx)
        for i in range(5):
            await audit.writer.emit("orders.submit", actor_label="bot", object_id=str(i))
        await audit.writer.flush(60)
        victim = await asyncio.to_thread(_tamper, pg_dsn)
        job = AuditVerifyJob(
            _Counting(),
            lambda: audit.query.verify_slot,
            metrics,
            hour_utc=4,
            deadline_s=120,
            clock=time.clock,
            sleep=time.sleep,
        )

        assert await job.run_once(VerifyTrigger.SCHEDULED) is _MISMATCH
        await audit.writer.flush(60)
        started, found = (await asyncio.to_thread(_verify_records, pg_dsn))[-2:]
        assert started[:3] == ("success", "info", "started")
        assert found[:3] == ("failure", "critical", f"entry_hash_mismatch@{victim}")
        assert found[3]["first_bad_id"] == victim and found[3]["verified"] is False
        assert _failures() == failures + 1 and _gauge() == 0
        [event] = await asyncio.to_thread(_break_events, pg_dsn)
        assert event["first_bad_id"] == str(victim) and event["kind"] == "entry_hash_mismatch"

        with pytest.raises(_Halt):
            await job.run_forever()  # the start-up run, after the one above
        await audit.writer.flush(60)
        gauge_after_runs = _gauge()  # read before the finally block resets the process-wide series
    finally:
        await audit.stop(5)
        await relational.dispose()
        cv_audit_chain_verified_state.set(math.nan)  # a process-wide series: leave it as found
    assert ended == [_MISMATCH, _MISMATCH]  # a break stops no later run
    assert _failures() == failures + 2 and gauge_after_runs == 0
    assert len(await asyncio.to_thread(_break_events, pg_dsn)) == 2
    records = await asyncio.to_thread(_verify_records, pg_dsn)
    assert [r[2] for r in records[-2:]] == ["started", f"entry_hash_mismatch@{victim}"]

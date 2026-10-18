"""Integration: the incident materialiser on real Postgres 16 (E42-T05, `21-database-schema.md`
3.10.2a), through the real `PgSystemEventWriter`.

What a compiled statement cannot show: the `ON CONFLICT` upsert under concurrent writers of one
group (one row, no occurrence lost, no unique violation), the reopen and escalation rules with
the acknowledgement they clear, the first and last seen times and the latest `detail` when
occurrences arrive out of order, and an event row that never outlives a failed incident write.
Each test uses its own error class, so its group is its own. Not run locally (no docker); the
same file was run on a scratch Postgres 16.4 first. CI integration lane."""

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
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from testcontainers.postgres import PostgresContainer

from candleviewer import health_wiring
from candleviewer.audit.redact import REDACTION_MARKER, redact
from candleviewer.db.models import incidents, system_events
from candleviewer.health_wiring import PgSystemEventWriter
from candleviewer.observability.health_probes import SystemEvent
from candleviewer.storage.repositories.incident_grouping import (
    incident_occurrence,
    incident_signature,
    normalise_message,
)
from candleviewer.storage.repositories.incidents_sqlalchemy import record_occurrence
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
ACK_USER = UUID(int=77)
_PW = "$argon2id$fixed-test-vector"  # placeholder digest, not a credential
_ACKNOWLEDGE = sa.text(
    "UPDATE incidents SET status = :status, acknowledged_by = :by, acknowledged_at = now(),"
    " resolved_at = CASE WHEN :status = 'resolved' THEN now() END"
    " WHERE component = :component AND signature = :signature"
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
        with psycopg.connect(
            url.replace("postgresql+psycopg2", "postgresql"), autocommit=True
        ) as c:
            c.execute(
                "INSERT INTO users (id, email, username, password_hash, status)"
                " VALUES (%s, 'ops@example.test', 'ops', %s, 'active')",
                (ACK_USER, _PW),
            )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield relational
    finally:
        await relational.dispose()


def _writer(rel: SqlAlchemyRelationalRepository) -> PgSystemEventWriter:
    return PgSystemEventWriter(rel, redact_details=redact)


def _event(kind: str, severity: str = "error", message: str = "probe failed") -> SystemEvent:
    return SystemEvent("recorder", kind, severity, message, {})


async def _rows(rel: SqlAlchemyRelationalRepository, stmt: Any) -> list[dict[str, Any]]:
    async with rel.unit_of_work() as uow:
        return [dict(r) for r in (await uow.session.execute(stmt)).mappings()]


async def _incident(
    rel: SqlAlchemyRelationalRepository, kind: str, message: str = "probe failed"
) -> dict[str, Any]:
    signature = incident_signature("recorder", kind, normalise_message(message))
    rows = await _rows(rel, sa.select(incidents).where(incidents.c.signature == signature))
    assert len(rows) == 1  # one row per group, whatever happened
    return rows[0]


async def _set_status(
    rel: SqlAlchemyRelationalRepository, kind: str, status: str, message: str = "probe failed"
) -> None:
    """What acknowledge (a later slice) and resolution do to the row: set here by hand."""
    signature = incident_signature("recorder", kind, normalise_message(message))
    async with rel.unit_of_work() as uow:
        params = {"status": status, "by": ACK_USER, "component": "recorder"}
        await uow.session.execute(_ACKNOWLEDGE, params | {"signature": signature})
        await uow.commit()


def _ack(row: dict[str, Any]) -> tuple[str, UUID | None, bool]:
    return row["status"], row["acknowledged_by"], row["acknowledged_at"] is not None


async def test_forty_errors_of_one_fault_are_one_open_incident_counted_forty(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    writer = _writer(rel)
    messages = [
        f"parquet write failed for {('BTCUSDT', 'ETHUSDT')[n % 2]} segment {n}" for n in range(40)
    ]
    for message in messages:
        await writer.write(_event("it_forty", message=message))
    row = await _incident(rel, "it_forty", messages[0])
    times = await _rows(
        rel,
        sa.select(
            sa.func.count().label("n"),
            sa.func.min(system_events.c.event_ts).label("first"),
            sa.func.max(system_events.c.event_ts).label("last"),
        ).where(system_events.c.kind == "it_forty"),
    )
    assert times[0]["n"] == 40  # every event row is kept; the incident groups them
    assert (row["occurrences"], row["status"], row["severity"]) == (40, "open", "error")
    assert (row["first_seen_at"], row["last_seen_at"]) == (times[0]["first"], times[0]["last"])
    assert row["title"] == "parquet write failed for <symbol> segment <n>"
    assert row["detail"] == messages[-1]  # the latest event's message
    assert (row["acknowledged_by"], row["acknowledged_at"], row["resolved_at"]) == (None,) * 3


@pytest.mark.parametrize("severity", ["error", "critical"])
async def test_concurrent_writers_of_one_group_make_one_row_and_lose_no_occurrence(
    rel: SqlAlchemyRelationalRepository, severity: str
) -> None:
    writer, kind = _writer(rel), f"it_race_{severity}"
    for wave in (1, 2):  # a group that does not exist yet, then one that does
        await asyncio.gather(*(writer.write(_event(kind, severity)) for _ in range(30)))
        row = await _incident(rel, kind)
        assert (row["occurrences"], row["severity"], row["status"]) == (30 * wave, severity, "open")


async def test_a_new_occurrence_reopens_a_resolved_incident_and_clears_its_acknowledgement(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    writer = _writer(rel)
    await writer.write(_event("it_reopen"))
    await _set_status(rel, "it_reopen", "resolved")
    resolved = await _incident(rel, "it_reopen")
    assert _ack(resolved) == ("resolved", ACK_USER, True) and resolved["resolved_at"] is not None
    await writer.write(_event("it_reopen"))
    row = await _incident(rel, "it_reopen")
    assert _ack(row) == ("open", None, False) and row["resolved_at"] is None
    assert (row["occurrences"], row["first_seen_at"]) == (2, resolved["first_seen_at"])


@pytest.mark.parametrize(
    ("first", "then", "severity"),
    [("error", "error", "error"), ("critical", "error", "critical"), ("critical",) * 3],
    ids=["error-then-error", "critical-then-error", "critical-then-critical"],
)
async def test_an_acknowledged_incident_stays_acknowledged_without_an_escalation(
    rel: SqlAlchemyRelationalRepository, first: str, then: str, severity: str
) -> None:
    writer, kind = _writer(rel), f"it_ack_{first}_{then}"
    await writer.write(_event(kind, first))
    await _set_status(rel, kind, "acknowledged")
    acknowledged = await _incident(rel, kind)
    await writer.write(_event(kind, then))
    row = await _incident(rel, kind)
    assert _ack(row) == ("acknowledged", ACK_USER, True)
    assert row["acknowledged_at"] == acknowledged["acknowledged_at"]
    assert (row["occurrences"], row["severity"]) == (2, severity)  # the worst grouped event


async def test_an_escalation_from_error_to_critical_reopens_an_acknowledged_incident(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    writer = _writer(rel)
    await writer.write(_event("it_escalate", "error"))
    await _set_status(rel, "it_escalate", "acknowledged")
    await writer.write(_event("it_escalate", "critical"))
    row = await _incident(rel, "it_escalate")
    assert _ack(row) == ("open", None, False) and row["severity"] == "critical"
    await writer.write(_event("it_escalate", "error"))  # no longer an escalation: still critical
    row = await _incident(rel, "it_escalate")
    assert (row["status"], row["severity"], row["occurrences"]) == ("open", "critical", 3)


async def test_an_older_occurrence_widens_the_window_but_keeps_the_latest_detail(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    at = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
    newer, older = "segment 2 lost", "segment 1 lost"  # one fault: the same normalised message
    for message, seen in ((newer, at), (older, at - timedelta(minutes=5))):
        occ = incident_occurrence(
            component="recorder", kind="it_order", severity="error", message=message
        )
        async with rel.unit_of_work() as uow:
            await record_occurrence(uow.session, occ, seen_at=seen)
            await uow.commit()
    row = await _incident(rel, "it_order", newer)
    assert (row["first_seen_at"], row["last_seen_at"]) == (at - timedelta(minutes=5), at)
    assert (row["detail"], row["occurrences"]) == (newer, 2)


async def test_an_incident_that_cannot_be_written_takes_its_event_with_it(
    rel: SqlAlchemyRelationalRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad(**fields: str) -> Any:  # a signature `inc_signature` refuses
        return replace(incident_occurrence(**fields), signature="not-hex")

    monkeypatch.setattr(health_wiring, "incident_occurrence", bad)
    with pytest.raises(IntegrityError):
        await _writer(rel).write(_event("it_atomic"))
    kept = await _rows(
        rel, sa.select(system_events.c.id).where(system_events.c.kind == "it_atomic")
    )
    assert kept == []  # one transaction: the event row rolled back with the incident


async def test_details_are_stored_through_the_audit_serializer(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    event = SystemEvent("db", "it_details", "warning", "m", {"probe": "x", "api_key": "k"})
    await _writer(rel).write(event)
    stored = sa.select(system_events.c.details).where(system_events.c.kind == "it_details")
    assert await _rows(rel, stored) == [{"details": {"probe": "x", "api_key": REDACTION_MARKER}}]
    grouped = sa.select(sa.func.count().label("n")).where(incidents.c.component == "db")
    assert await _rows(rel, grouped) == [{"n": 0}]  # a warning is never an incident

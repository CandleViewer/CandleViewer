"""The incident upsert (E42-T05, `21-database-schema.md` 3.10.2a), compiled for Postgres: one
`INSERT ... ON CONFLICT (component, signature) DO UPDATE` on `ux_incidents_group`, with the reopen
and escalation rules in its `SET`, run in the caller's transaction. What the rules do on a real
database, concurrent writers included, is `tests/integration/storage/test_incident_upsert_pg.py`."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from candleviewer.storage.repositories.incident_grouping import IncidentOccurrence
from candleviewer.storage.repositories.incidents_sqlalchemy import (
    record_occurrence,
    upsert_statement,
)

SEEN = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
OCC = IncidentOccurrence(
    component="db", signature="0123456789abcdef", severity="critical", title="t", detail=None
)


def _sql(stmt: Any) -> tuple[str, dict[str, Any]]:
    """The statement as Postgres gets it (a Postgres `Insert` compiles for its own dialect), bind
    casts dropped, and its bound values."""
    compiled = stmt.compile()
    return _CAST.sub("", " ".join(str(compiled).split())), compiled.params


_CAST = re.compile(r"::(?:TIMESTAMP WITH TIME ZONE|[A-Z]+)")


def test_the_upsert_inserts_one_open_row_and_conflicts_on_the_group() -> None:
    sql, params = _sql(upsert_statement(OCC, seen_at=SEEN, incident_id=UUID(int=1)))
    insert, _ = sql.split(" ON CONFLICT (component, signature) DO UPDATE SET ")
    assert insert == (
        "INSERT INTO incidents (id, component, signature, severity, status, title, detail, "
        "occurrences, first_seen_at, last_seen_at) VALUES (%(id)s, %(component)s, %(signature)s, "
        "%(severity)s, %(status)s, %(title)s, %(detail)s, %(occurrences)s, %(first_seen_at)s, "
        "%(last_seen_at)s)"
    )
    inserted = {
        k: params[k] for k in ("id", "status", "occurrences", "first_seen_at", "last_seen_at")
    }
    assert inserted == {
        "id": UUID(int=1),
        "status": "open",
        "occurrences": 1,
        "first_seen_at": SEEN,
        "last_seen_at": SEEN,
    }
    occurrence = {k: params[k] for k in ("component", "signature", "severity", "title", "detail")}
    assert occurrence == {"component": "db", "signature": "0123456789abcdef"} | {
        "severity": "critical",
        "title": "t",
        "detail": None,
    }


def test_the_update_counts_widens_the_window_and_keeps_the_worst_severity() -> None:
    sql, params = _sql(upsert_statement(OCC, seen_at=SEEN, incident_id=UUID(int=1)))
    update = sql.split(" DO UPDATE SET ", 1)[1]
    for assignment in (
        "occurrences = (incidents.occurrences + %(occurrences_1)s)",
        "first_seen_at = least(incidents.first_seen_at, excluded.first_seen_at)",
        "last_seen_at = greatest(incidents.last_seen_at, excluded.last_seen_at)",
        "severity = greatest(incidents.severity, excluded.severity)",
        "detail = CASE WHEN (excluded.last_seen_at >= incidents.last_seen_at) "
        "THEN excluded.detail ELSE incidents.detail END",
        "resolved_at = NULL",
    ):
        assert assignment in update
    assert params["occurrences_1"] == 1
    assert "title" not in update  # one group, one normalised message: the title never changes


def test_reopen_and_escalation_reset_the_status_and_the_acknowledgement() -> None:
    sql, params = _sql(upsert_statement(OCC, seen_at=SEEN, incident_id=UUID(int=1)))
    update = sql.split(" DO UPDATE SET ", 1)[1]
    reset = (
        "CASE WHEN (incidents.status = %(status_1)s OR incidents.status = %(status_2)s "
        "AND incidents.severity = %(severity_1)s AND excluded.severity = %(severity_2)s)"
    )
    assert f"status = {reset} THEN %(param_1)s ELSE incidents.status END" in update
    for column in ("acknowledged_by", "acknowledged_at"):
        assert f"{column} = {reset} THEN NULL ELSE incidents.{column} END" in update
    rule = {k: params[k] for k in ("status_1", "status_2", "severity_1", "severity_2", "param_1")}
    assert rule == {
        "status_1": "resolved",  # any new occurrence reopens a resolved incident
        "status_2": "acknowledged",  # an acknowledged one only on error -> critical
        "severity_1": "error",
        "severity_2": "critical",
        "param_1": "open",
    }


class _Session:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> None:
        self.statements.append(statement)


async def test_record_occurrence_runs_one_statement_in_the_callers_transaction() -> None:
    session = _Session()
    await record_occurrence(cast(AsyncSession, session), OCC, seen_at=SEEN)
    await record_occurrence(cast(AsyncSession, session), OCC, seen_at=SEEN)
    assert len(session.statements) == 2  # no commit, no read: the caller's unit of work owns it
    ids = [_sql(s)[1]["id"] for s in session.statements]
    assert all(isinstance(i, UUID) for i in ids) and ids[0] != ids[1]  # a fresh id per insert

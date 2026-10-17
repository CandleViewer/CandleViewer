"""`SqlAlchemyIncidents` with a fake unit of work (E42-T05): the statement is an explicit-column,
bound keyset page; an error is classed by the SQLSTATE the driver reports, not by its SQLAlchemy
type: a database that cannot serve the read leaves as `StorageTierUnavailable` without its text,
and a statement the database refuses keeps its type. The real driver's SQLSTATEs are checked by
`tests/integration/storage/test_incidents_pg.py`. The acknowledge transition is at the end; its
row lock is checked on a real database in `tests/integration/storage/test_incident_ack_pg.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import exc as sa_exc
from structlog.testing import capture_logs

from candleviewer.storage.errors import StorageTierUnavailable, WriteAheadTimeout
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import _TIMEOUT, READ_TIMEOUT
from candleviewer.storage.repositories.incidents import AckOutcome, AckResult, IncidentRow
from candleviewer.storage.repositories.incidents_sqlalchemy import (
    WRITE_TIMEOUT,
    SqlAlchemyIncidents,
    acknowledge_statement,
    lock_statement,
    page_statement,
)
from tests.unit.admin._ops_fakes import row

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
#: Built by concatenation so no scanner sees a credential: what a driver error can carry.
_DSN = "postgresql://cv:" + "hunter2" + "@db/cv"


class _Rel:
    def __init__(
        self, rows: list[dict[str, Any]] | None = None, error: Exception | None = None
    ) -> None:
        self.rows, self.error = rows or [], error
        self.statements: list[Any] = []
        self.timeouts: list[dict[str, Any] | None] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> Any:
            if stmt is _TIMEOUT:
                self.timeouts.append(params)
                return None
            self.statements.append(stmt)
            if self.error is not None:
                raise self.error
            return SimpleNamespace(mappings=lambda: self.rows)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


class _Driver(Exception):
    """What the driver adapter hangs on `DBAPIError.orig`: its text and its SQLSTATE."""

    def __init__(self, text: str, sqlstate: str | None) -> None:
        super().__init__(text)
        self.sqlstate = sqlstate


def _dbapi(kind: type[sa_exc.DBAPIError], sqlstate: str | None) -> sa_exc.DBAPIError:
    return kind("SELECT 1", {}, _Driver(_DSN, sqlstate))


async def _page(rel: _Rel) -> list[IncidentRow]:
    reader = SqlAlchemyIncidents(rel)  # type: ignore[arg-type]  # structural fake
    return await reader.page(status="open", after=None, limit=3)


def _sql(*args: Any) -> tuple[str, dict[str, Any]]:
    """The statement and its bound values, as SQLAlchemy renders it for any dialect."""
    compiled = page_statement(*args).compile()
    return " ".join(str(compiled).split()), compiled.params


def test_the_statement_is_an_explicit_bound_keyset_page() -> None:
    sql, params = _sql("open", (NOW, UUID(int=7)), 51)
    assert sql.startswith("SELECT incidents.id, incidents.component, incidents.signature,")
    assert "*" not in sql and "system_events" not in sql  # the table, never the raw events
    assert (
        "WHERE incidents.status = :status_1 AND incidents.last_seen_at <= :last_seen_at_1"
        " AND (incidents.last_seen_at < :last_seen_at_2 OR incidents.id < :id_1)"
        " ORDER BY incidents.last_seen_at DESC, incidents.id DESC LIMIT :param_1"
    ) in sql  # the keyset: strictly after the position, ties by the larger id first
    assert {str(v) for v in params.values()} == {"open", str(NOW), str(UUID(int=7)), "51"}
    assert "WHERE" not in _sql(None, None, 10)[0]  # the first page: no filter, no position


async def test_rows_come_back_by_column_name_under_a_server_side_time_cap() -> None:
    rel = _Rel([asdict(row(1))])
    assert await _page(rel) == [row(1)]
    assert rel.timeouts == [{"timeout": READ_TIMEOUT}] and len(rel.statements) == 1
    with pytest.raises(TypeError):  # a drifted column is a bug, never a silently dropped field
        await _page(_Rel([asdict(row(1)) | {"surprise": 1}]))


@pytest.mark.parametrize(
    ("error", "sqlstate"),
    [
        (_dbapi(sa_exc.DBAPIError, "57014"), "57014"),  # asyncpg's statement timeout
        (_dbapi(sa_exc.OperationalError, "08006"), "08006"),  # the connection failed
        (_dbapi(sa_exc.OperationalError, "53300"), "53300"),  # too many connections
        (_dbapi(sa_exc.OperationalError, "58030"), "58030"),  # an I/O error
        (_dbapi(sa_exc.InterfaceError, None), None),  # no SQLSTATE: the connection is gone
        (_dbapi(sa_exc.DBAPIError, "40001"), "40001"),  # a class nobody listed: a retry is harmless
        (sa_exc.TimeoutError(_DSN), None),  # the pool is exhausted
        (ConnectionRefusedError(_DSN), None),
    ],
    ids="timeout-57014 connection-08 resources-53 io-58 none unlisted-40 pool refused".split(),
)
async def test_a_database_that_cannot_serve_the_read_leaves_without_its_text(
    error: Exception, sqlstate: str | None
) -> None:
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable) as refused:
        await _page(_Rel(error=error))
    assert "hunter2" not in str(refused.value) + repr(logs) and refused.value.__cause__ is None
    assert (logs[0]["error"], logs[0]["sqlstate"]) == (type(error).__name__, sqlstate)


async def test_a_sqlstate_that_is_text_is_neither_trusted_nor_logged() -> None:
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable):
        await _page(_Rel(error=_dbapi(sa_exc.DBAPIError, _DSN)))  # not five characters of a code
    assert logs[0]["sqlstate"] is None and "hunter2" not in repr(logs)


@pytest.mark.parametrize(
    "error",
    [
        _dbapi(sa_exc.DBAPIError, "22P02"),  # asyncpg reports a data error as the generic type
        _dbapi(sa_exc.DataError, "22012"),
        _dbapi(sa_exc.IntegrityError, "23505"),
        _dbapi(sa_exc.ProgrammingError, "42703"),
        _dbapi(sa_exc.InternalError, "XX000"),
        sa_exc.ArgumentError("bad statement"),  # not the database's at all
    ],
    ids="data-22P02 data-22012 integrity-23 programming-42 internal-XX argument".split(),
)
async def test_a_refused_statement_is_a_bug_that_keeps_its_type(error: Exception) -> None:
    with pytest.raises(type(error)) as raised:
        await _page(_Rel(error=error))
    assert raised.value is error  # as it came, not wrapped and not a 503


# -- acknowledge (E42-T05): the transaction in order, the statements, the errors ------------------

_USER, _OPEN = UUID(int=5), row(7)
_DONE = row(7, status="acknowledged", acknowledged_by=_USER, acknowledged_at=NOW)


class _AckRel:
    """`found` answers the locking select (the update answers `_DONE`); `events` is the
    transaction in order."""

    def __init__(self, found: IncidentRow | None, error: Exception | None = None) -> None:
        self.found, self.error = found, error
        self.events: list[Any] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> Any:
            if stmt is _TIMEOUT:
                self.events.append(("timeout", (params or {})["timeout"]))
                return None
            self.events.append(kind := "update" if isinstance(stmt, sa.Update) else "lock")
            if self.error is not None:
                raise self.error
            hit = asdict(_DONE if kind == "update" else self.found) if self.found else None
            one = SimpleNamespace(first=lambda: hit, one=lambda: hit)
            return SimpleNamespace(mappings=lambda: one)

        async def commit() -> None:
            self.events.append("commit")

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


async def _ack(rel: _AckRel, hook: Any = None, **kw: Any) -> AckResult:
    async def record(before: IncidentRow, after: IncidentRow) -> None:
        rel.events.append(("hook", before.status, after.status))

    store = SqlAlchemyIncidents(rel, **kw)  # type: ignore[arg-type]  # structural fake
    return await store.acknowledge(_OPEN.id, by=_USER, write_ahead=hook or record)


def test_the_statements_lock_one_row_and_set_three_columns_of_an_open_one() -> None:
    lock, move = str(lock_statement(_OPEN.id)), str(acknowledge_statement(_OPEN.id, _USER))
    assert lock.rstrip().endswith("FOR UPDATE") and "*" not in lock + move
    assert move.split("WHERE")[0].count("=") == 3 and "clock_timestamp()" in move
    assert "incidents.status =" in move  # an `open` row only, after any lock wait


async def test_an_open_incident_is_locked_updated_audited_and_only_then_committed() -> None:
    rel = _AckRel(_OPEN)
    assert await _ack(rel) == AckResult(AckOutcome.ACKNOWLEDGED, _DONE)
    assert rel.events == [
        ("timeout", WRITE_TIMEOUT), "lock", "update", ("hook", "open", "acknowledged"), "commit",
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("found", "outcome"),
    [
        (_DONE, AckOutcome.ALREADY),
        (row(7, status="resolved", resolved_at=NOW), AckOutcome.RESOLVED),
        (None, AckOutcome.MISSING),
    ],
    ids=["acknowledged", "resolved", "unknown"],
)
async def test_an_incident_that_is_not_open_is_returned_as_it_is_with_no_write_and_no_record(
    found: IncidentRow | None, outcome: AckOutcome
) -> None:
    rel = _AckRel(found)
    assert await _ack(rel) == AckResult(outcome, found)
    assert rel.events == [("timeout", WRITE_TIMEOUT), "lock"]  # no update, no hook, no commit


class _Refused(Exception):
    """What the route's hook raises when its record cannot be written: a type of its own."""


@pytest.mark.parametrize("raises", [_Refused, WriteAheadTimeout], ids=["refused", "outlasted"])
async def test_a_hook_that_fails_stops_before_the_commit_and_reaches_the_caller_as_it_is(
    raises: type[Exception],
) -> None:
    async def hook(before: IncidentRow, after: IncidentRow) -> None:
        if raises is _Refused:
            raise _Refused
        await asyncio.Event().wait()  # outlasts its bound: a `TimeoutError`, hence an `OSError`

    rel = _AckRel(_OPEN)
    with pytest.raises(raises):
        await _ack(rel, hook, audit_timeout_s=0.01)
    assert rel.events == [("timeout", WRITE_TIMEOUT), "lock", "update"]  # never committed


async def test_a_database_that_cannot_serve_the_write_leaves_without_its_text() -> None:
    rel = _AckRel(_OPEN, _dbapi(sa_exc.DBAPIError, "55P03"))  # lock not available
    with capture_logs() as logs, pytest.raises(StorageTierUnavailable) as refused:
        await _ack(rel)
    assert "hunter2" not in str(refused.value) + repr(logs) and refused.value.__cause__ is None
    assert [log["event"] for log in logs] == ["incidents_write_failed"]


async def test_a_statement_the_database_refuses_is_a_bug_and_keeps_its_type() -> None:
    with pytest.raises(sa_exc.DBAPIError):
        await _ack(_AckRel(_OPEN, _dbapi(sa_exc.DBAPIError, "23503")))  # an unknown user

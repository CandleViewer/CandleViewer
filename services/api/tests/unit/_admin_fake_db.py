"""A stand-in for an `AsyncConnection` to a migrated test database, for the unit tests of the admin
fixtures (E42-Q01, #962).

An insert leaves its row in `tables`; a select answers with the rows of its table (its `where` is
not applied); the database's name and the session's user answer their reads; an update and the role
switch are kept and not applied; every statement sent is kept, and `shapes` names each. Any other
statement, a delete or an unknown text, fails the test, unless the test names the table whose delete
it expects (`deletes`). It is also the relational repository whose engine connects to it. Conflicts
and updates are Postgres's: the integration tests. `patch_audit_session` points the writer-based
seeds at it, their real `AuditWriter` over its `audit_log`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Final, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import IteratorResult
from sqlalchemy.engine.result import SimpleResultMetaData
from sqlalchemy.ext.asyncio import AsyncConnection

from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.writer import AuditWriter
from candleviewer.db import models as m
from tests.fixtures.admin import audit_session

#: The texts a seed sends that the fake answers with nothing: the role switch around OOB-WRITES.
_SILENT: Final = frozenset({"SET ROLE cv_app", "RESET ROLE"})


def _table(stmt: Any) -> str:
    """The name of the table a select reads or a DML statement writes."""
    table = stmt.get_final_froms()[0] if isinstance(stmt, sa.Select) else stmt.table
    return str(cast(sa.Table, table).name)


class FakeDb:
    def __init__(
        self,
        database: str = "test",
        login: str = "test",
        *,
        deletes: Collection[str] = (),
        **tables: list[dict[str, Any]],
    ) -> None:
        self.database, self.login = database, login
        self._deletes = frozenset(deletes)  # the tables whose delete this test expects
        self.statements: list[Any] = []
        roles: list[dict[str, Any]] = [
            {"id": uuid.uuid5(uuid.NAMESPACE_DNS, n), "name": n} for n in m.role_name.enums
        ]
        self.tables: dict[str, list[dict[str, Any]]] = {"roles": roles}
        self.tables |= {n: [dict(r) for r in rows] for n, rows in tables.items()}

    @property
    def conn(self) -> AsyncConnection:
        return cast("AsyncConnection", self)

    @property
    def engine(self) -> FakeDb:
        return self

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        yield self.conn

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[AsyncConnection]:
        yield self.conn

    async def dispose(self) -> None:
        return None

    def unit_of_work(self) -> Any:
        raise AssertionError("the fixture opened a unit of work")

    def row(self, table: str, **where: Any) -> dict[str, Any]:
        return next(r for r in self.tables[table] if all(r.get(k) == v for k, v in where.items()))

    @property
    def shapes(self) -> list[str]:
        """Each statement sent: a text as it is, any other by its verb and its table."""
        return [
            str(s) if isinstance(s, sa.TextClause) else f"{type(s).__name__.upper()} {_table(s)}"
            for s in self.statements
        ]

    async def execute(self, stmt: Any) -> IteratorResult[Any]:
        self.statements.append(stmt)
        keys: list[str] = []
        rows: list[tuple[Any, ...]] = []
        text = str(stmt) if isinstance(stmt, sa.TextClause) else None
        if isinstance(stmt, sa.Insert):
            self.tables.setdefault(_table(stmt), []).append(dict(stmt.compile().params))
        elif isinstance(stmt, sa.Select):
            keys = [str(c.key) for c in stmt.selected_columns]
            rows = [tuple(r.get(k) for k in keys) for r in self.tables.get(_table(stmt), [])]
        elif text == "SELECT current_database()":
            keys, rows = ["name"], [(self.database,)]
        elif text == "SELECT session_user":
            keys, rows = ["name"], [(self.login,)]
        elif isinstance(stmt, sa.Delete) and _table(stmt) in self._deletes:
            pass  # a delete the test expects: kept and not applied, as an update is
        elif not isinstance(stmt, sa.Update) and text not in _SILENT:
            raise AssertionError(f"the fake does not model {self.shapes[-1]!r}")
        return IteratorResult(SimpleResultMetaData(keys), iter(rows))


class FakeAuditRows:
    """The `audit_log` of a `FakeDb` as an `AuditRepository`: all the writer calls is `insert`."""

    def __init__(self, db: FakeDb) -> None:
        self._rows = db.tables.setdefault("audit_log", [])

    async def insert(self, record: dict[str, Any]) -> None:
        stored = record | {"event_ts": datetime.fromisoformat(record["event_ts"])}
        self._rows.append({"id": len(self._rows) + 1} | stored)


def patch_audit_session(monkeypatch: pytest.MonkeyPatch, db: FakeDb) -> list[str]:
    """The writer-based seeds' pool is `db`, and their writer the real `AuditWriter` over its
    `audit_log`; the WAL path of each writer built is returned."""
    built: list[str] = []

    def writer(repository: FakeAuditRows, wal_path: str) -> AuditWriter:
        built.append(wal_path)
        return AuditWriter(cast("AuditRepository", repository), wal_path)

    monkeypatch.setattr(audit_session, "SqlAlchemyRelationalRepository", lambda _dsn: db)
    monkeypatch.setattr(audit_session, "SqlAlchemyAuditRepository", FakeAuditRows)
    monkeypatch.setattr(audit_session, "AuditWriter", writer)
    return built

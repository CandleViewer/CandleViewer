"""A stand-in for an `AsyncConnection` to a migrated test database, for the unit tests of the admin
fixtures (E42-Q01, #962).

An insert leaves its row in `tables`; a select answers with the rows of its table (its `where` is
not applied); the database's name and the session's user answer their reads; an update and the role
switch are kept and not applied; every statement sent is kept, and `shapes` names each. Any other
statement, a delete or an unknown text, fails the test. It is also the relational repository whose
engine connects to it. Conflicts and updates are Postgres's: the integration tests.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final, cast

import sqlalchemy as sa
from sqlalchemy.engine import IteratorResult
from sqlalchemy.engine.result import SimpleResultMetaData
from sqlalchemy.ext.asyncio import AsyncConnection

from candleviewer.db import models as m

#: The texts a seed sends that the fake answers with nothing: the role switch around OOB-WRITES.
_SILENT: Final = frozenset({"SET ROLE cv_app", "RESET ROLE"})


def _table(stmt: Any) -> str:
    """The name of the table a select reads or a DML statement writes."""
    table = stmt.get_final_froms()[0] if isinstance(stmt, sa.Select) else stmt.table
    return str(cast(sa.Table, table).name)


class FakeDb:
    def __init__(
        self, database: str = "test", login: str = "test", **tables: list[dict[str, Any]]
    ) -> None:
        self.database, self.login = database, login
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
        elif not isinstance(stmt, sa.Update) and text not in _SILENT:
            raise AssertionError(f"the fake does not model {self.shapes[-1]!r}")
        return IteratorResult(SimpleResultMetaData(keys), iter(rows))

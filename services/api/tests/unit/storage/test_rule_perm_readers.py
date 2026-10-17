"""O5 (E42-T04 S5a, #965): both permission readers send the `users.status` predicate. Postgres
proves what it does (`tests/integration/storage/test_rule_perms_status_pg.py`, CI `integration`);
this pins, in the unit lane where no database runs, that dropping it from either one fails."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource


class _Rel:
    """A unit of work that records each statement (whitespace folded) and answers no rows."""

    def __init__(self) -> None:
        self.sql: list[str] = []

    @asynccontextmanager
    async def unit_of_work(self) -> Any:
        async def execute(stmt: Any, params: dict[str, Any]) -> Any:
            self.sql.append(" ".join(str(stmt).split()))
            return SimpleNamespace(all=lambda: [])

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


@pytest.mark.parametrize("reader", ["rule_scope", "session_info"])
async def test_permission_reader_requires_an_active_undeleted_user(reader: str) -> None:
    """The statement reads the user row and checks both columns, next to the role expiry."""
    rel, user = _Rel(), uuid.uuid4()
    if reader == "rule_scope":
        source = SqlAlchemyScopeSource(rel)  # type: ignore[arg-type]  # structural fake
        await source.load_permissions(user)
    else:
        provider = SqlAlchemyIdentityProvider(rel)  # type: ignore[arg-type]  # structural fake
        await provider.session_info(str(user))
    sql = rel.sql[0]  # `session_info` reads the permissions first, then the account scope
    assert "FROM users u" in sql
    assert "u.status = 'active'" in sql and "u.deleted_at IS NULL" in sql
    assert "ur.expires_at IS NULL OR ur.expires_at > now()" in sql

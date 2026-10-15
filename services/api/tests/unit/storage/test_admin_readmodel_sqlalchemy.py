"""`SqlAlchemyAdminCounts` with a fake unit of work (E42-T01): rows map to counts and every
statement is aggregate-only. The SQL itself runs on Postgres in
tests/integration/storage/test_admin_readmodel_pg.py (CI integration lane)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from candleviewer.storage.repositories import admin_readmodel_sqlalchemy as repo
from candleviewer.storage.repositories.admin_readmodel_sqlalchemy import (
    AccountTotals,
    SqlAlchemyAdminCounts,
    UserTotals,
)

NOW = datetime(2026, 10, 15, 18, 0, tzinfo=UTC)


class _Rel:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.calls: list[dict[str, Any] | None] = []
        self.timeouts = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> Any:
            if stmt is repo._TIMEOUT:
                self.timeouts += 1
                return None
            self.calls.append(params)
            return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: self.row))

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


def _counts(rel: _Rel) -> SqlAlchemyAdminCounts:
    return SqlAlchemyAdminCounts(rel, env="live")  # type: ignore[arg-type]  # structural fake


async def test_user_totals_map_the_aggregate_row() -> None:
    rel = _Rel({"total": 4, "active": 3, "without_mfa": 2})
    assert await _counts(rel).user_totals() == UserTotals(total=4, active=3, without_mfa=2)


async def test_account_totals_bind_the_horizon_and_the_process_environment() -> None:
    rel = _Rel({"total": 6, "enabled": 5, "keys_expiring": 1, "keys_invalid": 1})
    assert await _counts(rel).account_totals(NOW) == AccountTotals(6, 5, 1, 1)
    assert rel.calls == [{"expiring_before": NOW, "env": "live"}]
    assert rel.timeouts == 1  # every read caps server work first


async def test_subaccounts_bind_the_process_environment() -> None:
    rel = _Rel({"used": 3})
    assert await _counts(rel).subaccounts_in_use() == 3
    assert rel.calls == [{"env": "live"}]


async def test_open_incidents_is_a_single_count() -> None:
    assert await _counts(_Rel({"open": 2})).open_incidents() == 2


def test_every_statement_is_aggregate_only_and_reads_no_secret_column() -> None:
    for stmt in (repo._USERS, repo._ACCOUNTS, repo._INCIDENTS, repo._SUBACCOUNTS):
        sql = str(stmt).lower()
        assert "count(" in sql
        assert "_enc" not in sql and "password" not in sql

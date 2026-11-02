"""E35-T11: the two store reads the rule order adapter adds, in the unit lane where no database runs
(Postgres runs the statements: `tests/integration/rules/test_rule_actions_oms_pg.py`, CI
`integration`). Each is one bound statement in one unit of work, and what leaves the store is the
environment's account ids, or the day's notional sum, never a payload."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.storage.repositories import rules_sqlalchemy
from candleviewer.storage.repositories.rules_sqlalchemy import SqlAlchemyRulesRepository
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource

RULE = str(uuid.UUID(int=0x7))
START = datetime(2026, 11, 2, tzinfo=UTC)


class _Rel:
    """A unit of work that records each statement with its parameters and answers the rows
    (`all`) or the one value (`scalar_one`) it was given."""

    def __init__(self, rows: list[tuple[Any, ...]] | None = None, value: object = None) -> None:
        self.rows, self.value = rows or [], value
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    @asynccontextmanager
    async def unit_of_work(self) -> Any:
        async def execute(stmt: Any, params: dict[str, Any]) -> Any:
            self.calls.append((stmt, params))
            return SimpleNamespace(all=lambda: self.rows, scalar_one=lambda: self.value)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


async def test_the_environment_read_names_each_live_account_of_the_environment() -> None:
    a, b = uuid.UUID(int=0xB1), uuid.UUID(int=0xB2)
    rel = _Rel(rows=[(str(a),), (b,)])
    source = SqlAlchemyScopeSource(rel)  # type: ignore[arg-type]  # structural fake
    assert await source.load_environment_accounts("demo") == frozenset({a, b})
    [(stmt, params)] = rel.calls
    sql = " ".join(str(stmt).split())
    assert params == {"env": "demo"}
    assert "FROM exchange_accounts" in sql and "env::text = :env" in sql
    assert "deleted_at IS NULL" in sql


@pytest.mark.parametrize(
    ("value", "total"),
    [(Decimal("1300.25"), Decimal("1300.25")), (0, Decimal("0")), ("12.5", Decimal("12.5"))],
)
async def test_the_day_notional_is_one_windowed_sum_read_as_a_decimal(
    value: object, total: Decimal
) -> None:
    rel = _Rel(value=value)
    repository = SqlAlchemyRulesRepository(rel)  # type: ignore[arg-type]  # structural fake
    got = await repository.day_notional(RULE, START, START + timedelta(days=1))
    assert (got, type(got)) == (total, Decimal)
    [(stmt, params)] = rel.calls
    assert stmt is rules_sqlalchemy._DAY_NOTIONAL
    assert params == {"rule_id": RULE, "start": START, "end": START + timedelta(days=1)}

"""The order path's symbols store (#913 S4-S-c) without a database; Postgres: its `_pg` twin."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import Dialect, make_url

from candleviewer.storage.repositories.order_path_symbols_sqlalchemy import (
    SqlAlchemyOrderPathSymbols,
    symbols_statement,
)
from candleviewer.storage.repositories.orders import OPEN_STATES
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()


def test_symbols_statement_unions_open_positions_open_orders_and_recent_orders() -> None:
    stmt = symbols_statement(datetime(2026, 10, 26, tzinfo=UTC), 100)
    sql = " ".join(
        str(stmt.compile(dialect=_ASYNCPG, compile_kwargs={"render_postcompile": True})).split()
    )
    assert "FROM orders WHERE orders.state IN (" in sql and "orders.created_ts >= $" in sql
    assert "positions.symbol AS symbol, 0 AS prio FROM positions WHERE positions.size > 0" in sql
    assert "CASE WHEN (orders.state IN (" in sql and "ELSE 1 END AS prio" in sql
    assert all(f"'{state}'" in sql for state in OPEN_STATES)
    assert (
        " GROUP BY anon_1.symbol ORDER BY min(anon_1.prio), anon_1.symbol LIMIT $" in sql
    )  # positions and open orders ahead of the recent ones
    assert "exchange_account_id" not in sql and "SELECT *" not in sql  # symbols only


@pytest.mark.parametrize("limit", [0, -1, True])
async def test_order_path_symbols_bad_limit_is_refused_before_any_statement(limit: int) -> None:
    store = SqlAlchemyOrderPathSymbols(
        SqlAlchemyRelationalRepository("postgresql+asyncpg://u@localhost/x", "t")
    )
    with pytest.raises(ValueError, match="limit"):
        await store(since_us=0, limit=limit)


def test_order_path_symbols_is_capped_at_one_second_where_the_app_binds_it() -> None:
    store = SqlAlchemyOrderPathSymbols(
        SqlAlchemyRelationalRepository("postgresql+asyncpg://u@localhost/x", "t"),
        statement_timeout_ms=1000,
    )
    assert store._timeout == "1000"  # the server cancels before the 2 s asyncio bound

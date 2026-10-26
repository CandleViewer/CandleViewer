"""Integration: the order path's symbols (#913 S4-S-c) on real Postgres 16, as `cv_app`, over
`test_orders_store_pg.py`'s database: open positions, open orders and recent orders, distinct."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from candleviewer.storage.repositories.order_path_symbols_sqlalchemy import (
    SqlAlchemyOrderPathSymbols,
)
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.positions import PositionState
from candleviewer.storage.repositories.positions_sqlalchemy import SqlAlchemyPositionStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage import test_orders_store_pg as _pg
from tests.integration.storage.test_orders_store_pg import _account, _event, _order, _sql

#: The database fixtures of `test_orders_store_pg.py`, shared, not redefined.
pg_dsn, app_dsn, rel = _pg.pg_dsn, _pg.app_dsn, _pg.rel

pytestmark = pytest.mark.integration


def _symbol() -> str:
    return f"T{uuid.uuid4().hex[:8].upper()}USDT"


async def test_order_path_symbols_reads_positions_open_orders_and_the_last_24_hours(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    orders, account = SqlAlchemyOrderStore(rel), _account(pg_dsn)
    held, opened, recent, old = _symbol(), _symbol(), _symbol(), _symbol()
    now = datetime.now(UTC)
    await SqlAlchemyPositionStore(rel, clock=lambda: now).upsert(
        PositionState(exchange_account_id=account, symbol=held, size=Decimal("0.010"))
    )
    await orders.create(_order(account, symbol=opened, state="new"), _event())
    for symbol, hours in ((recent, 23), (old, 25)):
        done = await orders.create(_order(account, symbol=symbol, state="filled"), _event())
        _sql(pg_dsn, "UPDATE orders SET created_ts = now() - make_interval(hours => %s) "
             "WHERE id = %s", hours, done.id)  # fmt: skip
    since_us = int((now - timedelta(hours=24)).timestamp() * 1_000_000)
    symbols = await SqlAlchemyOrderPathSymbols(rel)(since_us=since_us, limit=10_000)
    assert {held, opened, recent} <= set(symbols) and old not in symbols
    assert list(symbols) == sorted(set(symbols))  # distinct, in symbol order
    assert len(await SqlAlchemyOrderPathSymbols(rel)(since_us=since_us, limit=2)) == 2

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
    held, opened, old = "Z" + _symbol(), "Y" + _symbol(), _symbol()
    recent = "A" + _symbol()  # sorts first by name, so only the rank puts it last
    now = datetime.now(UTC)
    await SqlAlchemyPositionStore(rel, clock=lambda: now).upsert(
        PositionState(exchange_account_id=account, symbol=held, size=Decimal("0.010"))
    )
    await orders.create(_order(account, symbol=opened, state="accepted"), _event())
    for symbol, hours in ((recent, 23), (old, 25)):
        done = await orders.create(_order(account, symbol=symbol, state="filled"), _event())
        _sql(pg_dsn, "UPDATE orders SET created_ts = now() - make_interval(hours => %s) "
             "WHERE id = %s", hours, done.id)  # fmt: skip
    since_us = int((now - timedelta(hours=24)).timestamp() * 1_000_000)
    symbols = await SqlAlchemyOrderPathSymbols(rel)(since_us=since_us, limit=10_000)
    assert {held, opened, recent} <= set(symbols) and old not in symbols
    assert len(symbols) == len(set(symbols))  # distinct
    ours = [symbol for symbol in symbols if symbol in {held, opened, recent}]
    assert ours == [opened, held, recent]  # positions and open orders, then recent, by name
    assert len(await SqlAlchemyOrderPathSymbols(rel)(since_us=since_us, limit=2)) == 2


def _profile_symbols(dsn: str, account: uuid.UUID, allowed: list[str] | None, **over: bool) -> None:
    """Set the account's bootstrap `Default` profile's symbol scope (a wildcard needs NULL)."""
    wild = over.get("all_symbols", False)
    _sql(dsn, "UPDATE account_profiles SET allowed_symbols = %s, all_symbols = %s, "
         "enabled = %s WHERE exchange_account_id = %s AND is_default",
         allowed, wild, over.get("enabled", True), account)  # fmt: skip


async def test_order_path_symbols_adds_the_default_profiles_allowed_symbols_at_rank_two(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    orders, account, other = SqlAlchemyOrderStore(rel), _account(pg_dsn), _account(pg_dsn)
    wild, off = _account(pg_dsn), _account(pg_dsn)
    opened, allowed, shared = "Y" + _symbol(), "A" + _symbol(), "B" + _symbol()
    await orders.create(_order(account, symbol=opened, state="accepted"), _event())
    _profile_symbols(pg_dsn, account, [allowed, shared, opened])
    _profile_symbols(pg_dsn, other, [shared])  # the same symbol twice: one row
    disabled_only = "W" + _symbol()
    _profile_symbols(pg_dsn, wild, None, all_symbols=True)
    _profile_symbols(pg_dsn, off, [disabled_only], enabled=False)  # disabled sizes nothing
    symbols = await SqlAlchemyOrderPathSymbols(rel)(since_us=0, limit=10_000)
    ours = [s for s in symbols if s in {opened, allowed, shared}]
    assert ours == [opened, allowed, shared]  # rank 0, then rank 2 by name, distinct
    assert disabled_only not in symbols  # a disabled profile sizes nothing
    assert all(symbols) and "None" not in symbols  # a wildcard (NULL scope) adds no symbol
    assert len(symbols) == len(set(symbols))

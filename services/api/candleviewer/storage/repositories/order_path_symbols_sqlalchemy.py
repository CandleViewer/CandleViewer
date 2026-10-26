"""The symbols the order path needs risk-limit tiers for (#913 S4-S-c), the instrument refresh's
seed: those of open positions, open orders and the orders created since a time. One read-only
statement in every account and environment, answering symbol names only (public market data's
keys, never an account or a value), at most `limit`, capped and mapped as `CappedStore` says."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa

from candleviewer.db.models import orders, positions
from candleviewer.storage.repositories.orders import OPEN_STATES, require_limit
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def symbols_statement(since: datetime, limit: int) -> sa.Select[Any]:
    """The distinct symbols of open positions, open orders and orders created at or after
    `since`, the open states rendered as literals as `list_open_statement`'s are. Positions and
    open orders rank ahead of the recent ones, then by symbol, so a `limit` drops the recent
    ones first. The recent-orders arm has no index on `created_ts` (a carry for the next
    `orders` migration)."""
    o, p = orders.c, positions.c
    states: sa.BindParameter[Any] = sa.bindparam(
        "open", sorted(OPEN_STATES), expanding=True, literal_execute=True
    )
    rank = sa.case(
        (o.state.in_(states), sa.literal_column("0")), else_=sa.literal_column("1")
    ).label("prio")
    by_order = sa.select(o.symbol.label("symbol"), rank).where(
        sa.or_(o.state.in_(states), o.created_ts >= since)
    )
    by_position = sa.select(p.symbol.label("symbol"), sa.literal_column("0").label("prio")).where(
        p.size > sa.literal_column("0")
    )
    both = sa.union(by_order, by_position).subquery()
    return (
        sa.select(both.c.symbol)
        .group_by(both.c.symbol)
        .order_by(sa.func.min(both.c.prio), both.c.symbol)
        .limit(limit)
    )


class SqlAlchemyOrderPathSymbols(CappedStore):
    """`OrderPathSymbols` over one relational repository (asyncpg)."""

    async def __call__(self, *, since_us: int, limit: int) -> tuple[str, ...]:
        require_limit(limit)
        since = _EPOCH + timedelta(microseconds=since_us)
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(symbols_statement(since, limit))
            return tuple(str(symbol) for symbol in result.scalars())

"""The symbols the order path needs risk-limit tiers for (#913 S4-S-c), the instrument refresh's
seed: those of open positions, open orders, the orders created since a time and the symbols the
account profiles allow. One read-only
statement in every account and environment, answering symbol names only (public market data's
keys, never an account or a value), at most `limit`, capped and mapped as `CappedStore` says."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa

from candleviewer.db.models import account_profiles, exchange_accounts, orders, positions
from candleviewer.storage.repositories.orders import OPEN_STATES, require_limit
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def symbols_statement(since: datetime, limit: int) -> sa.Select[Any]:
    """The distinct symbols of open positions, open orders, orders created at or after `since`
    and the `allowed_symbols` of the effective profiles, the open states rendered as literals as
    `list_open_statement`'s are. Rank 0: positions and open orders; 1: recent orders; 2: allowed
    symbols; then by symbol, so a `limit` drops the allowed symbols first, then the recent ones.
    The recent-orders arm has no index on `created_ts` (a carry for the next `orders`
    migration).

    The effective profiles are each account's default profile (`is_default`, the account's
    ceiling: alternates only narrow it, 21 section 3.2.4), `enabled` and not deleted, of an
    account not deleted: the default binding is the one every account has, so a symbol an
    alternate adds beyond it is never allowed anyway, and a disabled profile sizes nothing. A
    wildcard profile (`all_symbols`, whose list is NULL) contributes nothing, as an empty or NULL
    list does: the symbols it may trade are the `request_tiers` bridge's (S4-S-d), on demand."""
    o, p = orders.c, positions.c
    ap, ea = account_profiles.c, exchange_accounts.c
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
    by_profile = sa.select(
        sa.func.unnest(ap.allowed_symbols).label("symbol"), sa.literal_column("2").label("prio")
    ).where(
        ap.is_default.is_(True),
        ap.enabled.is_(True),
        ap.deleted_at.is_(None),
        ap.all_symbols.is_(False),
        ap.exchange_account_id.in_(sa.select(ea.id).where(ea.deleted_at.is_(None))),
    )
    both = sa.union(by_order, by_position, by_profile).subquery()
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

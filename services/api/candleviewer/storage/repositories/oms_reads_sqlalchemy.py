"""Postgres side of the OMS REST reads (E29-T07 #915, PR 1; `oms_reads.py`).

SQLAlchemy Core over `orders`, `order_events`, `executions` and `positions`, with the `CappedStore`
cap and error mapping of `orders_sqlalchemy.py`. Every statement holds the principal's scope in SQL
with `scope_clause` (viewing) over the row's own account, of the process's environment, beside the
accounts settled first in the same transaction (`accounts_in_scope_statement`, `trade=False`); the
order and the event reads of `getOrder` are `in_scope_statement` and `list_events_statement`, the
exit routes' own. Lists render their states with literals, as `list_open_statement` does, so the
planner matches `ix_orders_open`, and a position's `size > 0` with a literal 0 for `ix_pos_open`.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa

from candleviewer.db.models import executions, orders, positions, trade_group_legs
from candleviewer.domain.primitives import Environment
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.executions import ExecutionRow
from candleviewer.storage.repositories.executions_sqlalchemy import EXECUTION_COLUMNS
from candleviewer.storage.repositories.oms_reads import (
    MAX_ORDER_EXECUTIONS,
    ExecutionQuery,
    Keyset,
    ListedExecution,
    ListedOrder,
    OrderDetail,
    OrderQuery,
    PositionOutOfScope,
    PositionQuery,
)
from candleviewer.storage.repositories.orders import (
    EVENT_FIELDS,
    MAX_EVENT_PAGE,
    OrderEventRow,
    OutOfScope,
    ScopedOrder,
    require_limit,
    settle_accounts,
)
from candleviewer.storage.repositories.orders_sqlalchemy import (
    ORDER_COLUMNS,
    CappedStore,
    accounts_in_scope_statement,
    in_scope_statement,
    list_events_statement,
    order_row,
    scope_clause,
)
from candleviewer.storage.repositories.positions import PositionRow
from candleviewer.storage.repositories.positions_sqlalchemy import POSITION_COLUMNS
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyUnitOfWork

_O, _X, _P, _L = orders.c, executions.c, positions.c, trade_group_legs.c
#: Statements without `scope_clause` over their rows' account (a unit test pins the set): the fills
#: of an order its caller read in scope in the same transaction, by that account, and the probe of
#: the account holding a position id, for a refusal's audit alone, never served.
UNSCOPED: Final = frozenset({"order_fills_statement", "position_holder_statement"})


def _literals(name: str, values: Collection[str]) -> sa.BindParameter[Any]:
    return sa.bindparam(name, sorted(values), expanding=True, literal_execute=True)


def _text(column: sa.ColumnElement[Any]) -> sa.ColumnElement[Any]:
    """A DOMAIN column compared as text: SQLAlchemy 2.1 has no operator class for DOMAIN."""
    return sa.type_coerce(column, sa.Text)


def orders_statement(
    scope: AccountScope, query: OrderQuery, environment: Environment,
    accounts: Collection[UUID], after: Keyset | None, limit: int,
) -> sa.Select[Any]:  # fmt: skip
    """`listOrders`' page: the settled accounts' orders the scope views, newest first."""
    tree = orders.outerjoin(trade_group_legs, _L.id == _O.trade_group_leg_id)
    account = _O.exchange_account_id
    stmt = (
        sa.select(*ORDER_COLUMNS, _L.trade_group_id)
        .select_from(tree)
        .where(
            account.in_(sorted(accounts)), scope_clause(scope, environment, account, trade=False)
        )
    )
    if (states := query.wanted_states()) is not None:
        stmt = stmt.where(_O.state.in_(_literals("states", states)))
    if query.intents:
        stmt = stmt.where(_O.intent.in_(_literals("intents", query.intents)))
    if query.symbol is not None:
        stmt = stmt.where(_text(_O.symbol) == query.symbol)
    if query.trade_group_id is not None:
        stmt = stmt.where(_L.trade_group_id == query.trade_group_id)
    if query.since is not None:
        stmt = stmt.where(_O.created_ts >= query.since)
    if query.until is not None:
        stmt = stmt.where(_O.created_ts < query.until)
    if after is not None:
        stmt = stmt.where(sa.tuple_(_O.created_ts, _O.id) < sa.tuple_(after.at, after.id))
    return stmt.order_by(_O.created_ts.desc(), _O.id.desc()).limit(limit)


def _fills() -> tuple[sa.FromClause, sa.ColumnElement[Any]]:
    """`executions` with the trade group of its own leg, else of its order's leg."""
    order = orders.alias("filled_order")
    leg = sa.func.coalesce(_X.trade_group_leg_id, order.c.trade_group_leg_id)
    tree = executions.outerjoin(order, order.c.id == _X.order_id).outerjoin(
        trade_group_legs, _L.id == leg
    )
    return tree, _L.trade_group_id


def executions_statement(
    scope: AccountScope, query: ExecutionQuery, environment: Environment,
    accounts: Collection[UUID], after: Keyset | None, limit: int, *, closed: bool = False,
) -> sa.Select[Any]:  # fmt: skip
    """`listExecutions`' page: the settled accounts' fills the scope views, newest first;
    `closed`, `listClosedPnl`'s: only the fills that carry a closed PnL."""
    tree, group = _fills()
    account = _X.exchange_account_id
    stmt = (
        sa.select(*EXECUTION_COLUMNS, group)
        .select_from(tree)
        .where(
            account.in_(sorted(accounts)), scope_clause(scope, environment, account, trade=False)
        )
    )
    if closed:
        stmt = stmt.where(_X.closed_pnl.is_not(None))
    if query.symbol is not None:
        stmt = stmt.where(_text(_X.symbol) == query.symbol)
    if query.order_id is not None:
        stmt = stmt.where(_X.order_id == query.order_id)
    if query.trade_group_id is not None:
        stmt = stmt.where(group == query.trade_group_id)
    if query.since is not None:
        stmt = stmt.where(_X.exec_ts >= query.since)
    if query.until is not None:
        stmt = stmt.where(_X.exec_ts < query.until)
    if after is not None:
        stmt = stmt.where(sa.tuple_(_X.exec_ts, _X.id) < sa.tuple_(after.at, after.id))
    return stmt.order_by(_X.exec_ts.desc(), _X.id.desc()).limit(limit)


def order_fills_statement(account_id: UUID, order_id: UUID) -> sa.Select[Any]:
    """`getOrder`'s fills: the order's, in its account (already read in scope), oldest first."""
    tree, group = _fills()
    return (
        sa.select(*EXECUTION_COLUMNS, group)
        .select_from(tree)
        .where(_X.exchange_account_id == account_id, _X.order_id == order_id)
        .order_by(_X.exec_ts, _X.id)
        .limit(MAX_ORDER_EXECUTIONS)
    )


def positions_statement(
    scope: AccountScope, query: PositionQuery, environment: Environment,
    accounts: Collection[UUID],
) -> sa.Select[Any]:  # fmt: skip
    """`listPositions`' rows: the settled accounts' positions the scope views."""
    account = _P.exchange_account_id
    stmt = sa.select(*POSITION_COLUMNS).where(
        account.in_(sorted(accounts)), scope_clause(scope, environment, account, trade=False)
    )
    if query.open_only:
        stmt = stmt.where(_P.size > sa.literal_column("0"))
    if query.symbol is not None:
        stmt = stmt.where(_text(_P.symbol) == query.symbol)
    return stmt.order_by(_P.symbol, account, _P.position_idx)


def position_statement(
    scope: AccountScope, position_id: UUID, environment: Environment
) -> sa.Select[Any]:
    """`getPosition`'s row, only where the scope views its account."""
    account = _P.exchange_account_id
    return sa.select(*POSITION_COLUMNS).where(
        _P.id == position_id, scope_clause(scope, environment, account, trade=False)
    )


def position_holder_statement(position_id: UUID) -> sa.Select[Any]:
    """The account holding an id the scope does not view, for the refusal's audit alone."""
    return sa.select(_P.exchange_account_id).where(_P.id == position_id)


def _execution(row: Mapping[str, Any]) -> ListedExecution:
    found = ExecutionRow(**{c.name: row[c.name] for c in EXECUTION_COLUMNS})
    return ListedExecution(found, row["trade_group_id"])


def _position(row: Mapping[str, Any]) -> PositionRow:
    return PositionRow(**{c.name: row[c.name] for c in POSITION_COLUMNS})


class SqlAlchemyOmsReads(CappedStore):
    """`OmsReadStore` over one relational repository (asyncpg)."""

    async def _settled(
        self, uow: SqlAlchemyUnitOfWork, scope: AccountScope, environment: Environment,
        requested: Collection[UUID],
    ) -> tuple[UUID, ...]:  # fmt: skip
        stmt = accounts_in_scope_statement(scope, environment, requested, trade=False)
        found = await uow.session.execute(stmt)
        return settle_accounts((UUID(str(r["id"])) for r in found.mappings()), requested)

    async def orders(
        self, scope: AccountScope, query: OrderQuery, *, environment: Environment,
        after: Keyset | None, limit: int,
    ) -> tuple[ListedOrder, ...]:  # fmt: skip
        require_limit(limit)
        async with self._unit_of_work() as uow:
            accounts = await self._settled(uow, scope, environment, query.accounts)
            if not accounts or query.wanted_states() == frozenset():
                return ()
            stmt = orders_statement(scope, query, environment, accounts, after, limit)
            rows = (await uow.session.execute(stmt)).mappings()
            return tuple(ListedOrder(order_row(r), r["trade_group_id"]) for r in rows)

    async def order(
        self, scope: AccountScope, order_id: UUID, *, environment: Environment, events: bool
    ) -> OrderDetail | OutOfScope:
        async with self._unit_of_work() as uow:
            stmt = in_scope_statement(scope, order_id, environment)
            row = (await uow.session.execute(stmt)).mappings().one()
            if row["id"] is None:
                return OutOfScope(row["holder"])
            found = ScopedOrder(
                order_row(row), row["trade_group_id"], row["profile_id"], row["created_by"],
                bool(row["can_trade"]),
            )  # fmt: skip
            account = found.order.exchange_account_id
            chain: tuple[OrderEventRow, ...] = ()
            if events:
                listed = list_events_statement(account, order_id, -1, MAX_EVENT_PAGE)
                chain = tuple(
                    OrderEventRow(
                        order_link_id=r["order_link_id"], **{n: r[n] for n in EVENT_FIELDS}
                    )
                    for r in (await uow.session.execute(listed)).mappings()
                )
            fills = await uow.session.execute(order_fills_statement(account, order_id))
            return OrderDetail(found, chain, tuple(_execution(r) for r in fills.mappings()))

    async def executions(
        self, scope: AccountScope, query: ExecutionQuery, *, environment: Environment,
        after: Keyset | None, limit: int,
    ) -> tuple[ListedExecution, ...]:  # fmt: skip
        return await self._fills(scope, query, environment, after, limit, closed=False)

    async def closed_pnl(
        self, scope: AccountScope, query: ExecutionQuery, *, environment: Environment,
        after: Keyset | None, limit: int,
    ) -> tuple[ListedExecution, ...]:  # fmt: skip
        return await self._fills(scope, query, environment, after, limit, closed=True)

    async def _fills(
        self, scope: AccountScope, query: ExecutionQuery, environment: Environment,
        after: Keyset | None, limit: int, *, closed: bool,
    ) -> tuple[ListedExecution, ...]:  # fmt: skip
        require_limit(limit)
        async with self._unit_of_work() as uow:
            accounts = await self._settled(uow, scope, environment, query.accounts)
            if not accounts:
                return ()
            stmt = executions_statement(
                scope, query, environment, accounts, after, limit, closed=closed
            )
            return tuple(_execution(r) for r in (await uow.session.execute(stmt)).mappings())

    async def positions(
        self, scope: AccountScope, query: PositionQuery, *, environment: Environment
    ) -> tuple[PositionRow, ...]:
        async with self._unit_of_work() as uow:
            accounts = await self._settled(uow, scope, environment, query.accounts)
            if not accounts:
                return ()
            stmt = positions_statement(scope, query, environment, accounts)
            return tuple(_position(r) for r in (await uow.session.execute(stmt)).mappings())

    async def position(
        self, scope: AccountScope, position_id: UUID, *, environment: Environment
    ) -> PositionRow | PositionOutOfScope:
        async with self._unit_of_work() as uow:
            stmt = position_statement(scope, position_id, environment)
            row = (await uow.session.execute(stmt)).mappings().first()
            if row is not None:
                return _position(row)
            held = await uow.session.execute(position_holder_statement(position_id))
            return PositionOutOfScope(held.scalar_one_or_none())


__all__ = [
    "UNSCOPED", "SqlAlchemyOmsReads", "executions_statement", "order_fills_statement",
    "orders_statement", "position_holder_statement", "position_statement", "positions_statement",
]  # fmt: skip

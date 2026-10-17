"""Postgres execution store (E29-T01 #845, migration `0029_oms_core`).

Core statements and the `CappedStore` cap and error mapping, as in `orders_sqlalchemy.py`. `insert`
is `INSERT ... ON CONFLICT (exchange_account_id, exec_id) DO NOTHING` (21 Sec.3.3.6) and says
whether this call stored the row; the id is `gen_random_uuid()`. `order_id` is bound through a
subquery scoped to the execution's account: another account's order binds NULL, which `RETURNING`
shows, and the store raises `OrderNotFoundError` before committing. `get` filters on the account
(C-12.4). `insert` commits alone; E29-T03's `apply_execution`, which must store a fill with its
order's totals, is to extend the store with one unit of work for both.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from candleviewer.db.models import executions, orders
from candleviewer.storage.repositories.executions import ExecutionRow, NewExecution
from candleviewer.storage.repositories.orders import OrderNotFoundError
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore

_X = executions.c
EXECUTION_COLUMNS: Final = tuple(_X[f.name] for f in fields(ExecutionRow))
#: Statements without an `exchange_account_id` filter: the insert writes the one it is given.
UNSCOPED: Final = frozenset({"insert_statement"})


def insert_statement(execution: NewExecution) -> sa.Insert:
    values: dict[str, Any] = {f.name: getattr(execution, f.name) for f in fields(NewExecution)}
    if execution.order_id is not None:
        owned = sa.select(orders.c.id).where(
            orders.c.exchange_account_id == execution.exchange_account_id,
            orders.c.id == execution.order_id,
        )
        values["order_id"] = owned.scalar_subquery()
    stmt = pg_insert(executions).values(id=sa.func.gen_random_uuid(), **values)
    return stmt.on_conflict_do_nothing(
        index_elements=[_X.exchange_account_id, _X.exec_id]
    ).returning(_X.order_id)


def get_statement(account_id: UUID, exec_id: str) -> sa.Select[Any]:
    return sa.select(*EXECUTION_COLUMNS).where(
        _X.exchange_account_id == account_id, _X.exec_id == exec_id
    )


class SqlAlchemyExecutionStore(CappedStore):
    """`ExecutionStore` over one relational repository (asyncpg)."""

    async def insert(self, execution: NewExecution) -> bool:
        async with self._unit_of_work() as uow:
            stored = (await uow.session.execute(insert_statement(execution))).first()
            if stored is None:
                return False  # `ux_exec_id` holds the fill already
            if execution.order_id is not None and stored.order_id is None:
                raise OrderNotFoundError  # not an order of this account: rolled back
            await uow.commit()
        return True

    async def get(self, account_id: UUID, exec_id: str) -> ExecutionRow | None:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(get_statement(account_id, exec_id))
            row = result.mappings().first()
        if row is None:
            return None
        return ExecutionRow(**{c.name: row[c.name] for c in EXECUTION_COLUMNS})

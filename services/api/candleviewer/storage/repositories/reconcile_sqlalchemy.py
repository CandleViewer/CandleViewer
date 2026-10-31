"""Postgres reads and the watermark write of the reconciliation pass (E29-T06 #914 PR 2b;
24-internal-schemas.md Sec.8.5 step 1 and `gap_from`; 21-database-schema.md Sec.3.2.1, Sec.3.3.4,
Sec.3.3.6, Sec.3.3.11).

`SqlAlchemyReconcileStore` serves the pass's ports that no other store answers in one statement:

* `unfinished_for`: the account's orders in `UNFINISHED_STATES` (`held` and `untracked` included,
  which `list_open` leaves out), oldest first, at most `MAX_UNFINISHED` (C-2.18), the startup
  sweep's own statement for one account;
* `stored`: which of the `exec_id`s the pass holds the account has stored already (S4), one read,
  over `ux_exec_id`, at most `MAX_ASKED` ids;
* `live_for_account`: the account's live recorded stops (`pending`, `in_force`), oldest first, the
  copy step 1 takes before the positions (24 Sec.8.8 rule 6), over `ix_rs_live`;
* `last_reconciled` and `advance`: `exchange_accounts.last_reconciled_at`, the stored half of
  `gap_from` (the watermark), which `advance` only ever moves forward (`GREATEST`), on the account's
  own row that is not deleted.

Every statement filters on the account (C-12.4); the ids are bound parameters. The store is a
`CappedStore`: each unit of work caps its statements, and a failure leaves as
`OrderConstraintError`, `StorageQueryFailed` or `StorageTierUnavailable`, unchained and with no
value (C-12.6). Its caller bounds each call (C-2.18).
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from candleviewer.db.models import exchange_accounts, executions, recorded_stops
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.orders_sqlalchemy import (
    CappedStore,
    list_unfinished_statement,
    order_row,
)
from candleviewer.storage.repositories.recorded_stops import LIVE_STOP_STATUSES, RecordedStopRow
from candleviewer.storage.repositories.recorded_stops_sqlalchemy import STOP_COLUMNS, stop_row

__all__ = [
    "MAX_ASKED",
    "MAX_UNFINISHED",
    "SqlAlchemyReconcileStore",
    "advance_statement",
    "last_reconciled_statement",
    "live_for_account_statement",
    "stored_statement",
]

#: The most unfinished orders one pass reads for an account (C-2.18): the OMS's own cap on the
#: machines it holds, so a pass never reads more rows than B1 could hold.
MAX_UNFINISHED: Final = 10_000
#: The most `exec_id`s one `stored` read asks about (C-2.18).
MAX_ASKED: Final = 20_000
_X, _S, _A = executions.c, recorded_stops.c, exchange_accounts.c


def stored_statement(account_id: UUID, exec_ids: Collection[str]) -> sa.Select[Any]:
    """The `exec_id`s of `exec_ids` the account holds (`ux_exec_id`), bound as one array."""
    ids = sa.bindparam("exec_ids", sorted(set(exec_ids)), type_=ARRAY(sa.Text))
    return sa.select(_X.exec_id).where(
        _X.exchange_account_id == account_id, _X.exec_id == sa.any_(ids)
    )


def live_for_account_statement(account_id: UUID) -> sa.Select[Any]:
    """The account's live recorded stops, oldest first (`ix_rs_live`); the statuses render as
    literals, as `live_for_key_statement`'s do, so the planner matches the partial index."""
    live: sa.BindParameter[Any] = sa.bindparam(
        "live", sorted(LIVE_STOP_STATUSES), expanding=True, literal_execute=True
    )
    stmt = sa.select(*STOP_COLUMNS).where(_S.exchange_account_id == account_id, _S.status.in_(live))
    return stmt.order_by(_S.created_at, _S.id)


def last_reconciled_statement(account_id: UUID) -> sa.Select[Any]:
    return sa.select(_A.last_reconciled_at).where(_A.id == account_id, _A.deleted_at.is_(None))


def advance_statement(account_id: UUID, to: datetime) -> sa.Update:
    """The watermark moved to `to`, never back (`GREATEST` over its current value)."""
    at = sa.bindparam("to", to, type_=sa.TIMESTAMP(timezone=True))
    forward = sa.func.greatest(sa.func.coalesce(_A.last_reconciled_at, at), at)
    return (
        sa.update(exchange_accounts)
        .where(_A.id == account_id, _A.deleted_at.is_(None))
        .values(last_reconciled_at=forward)
        .returning(_A.id)
    )


class SqlAlchemyReconcileStore(CappedStore):
    """The pass's reads and its watermark write (module docstring) over one relational
    repository (asyncpg)."""

    async def unfinished_for(self, account_id: UUID) -> tuple[OrderRow, ...]:
        async with self._unit_of_work() as uow:
            stmt = list_unfinished_statement([account_id], MAX_UNFINISHED)
            result = await uow.session.execute(stmt)
            return tuple(order_row(row) for row in result.mappings())

    async def stored(self, account_id: UUID, exec_ids: Collection[str]) -> frozenset[str]:
        asked = frozenset(exec_ids)
        if not asked:
            return frozenset()
        if len(asked) > MAX_ASKED:
            raise ValueError(f"at most {MAX_ASKED} exec_ids are asked about at once")
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(stored_statement(account_id, asked))
            return frozenset(str(value) for value in result.scalars())

    async def live_for_account(self, account_id: UUID) -> tuple[RecordedStopRow, ...]:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(live_for_account_statement(account_id))
            return tuple(stop_row(row) for row in result.mappings())

    async def last_reconciled(self, account_id: UUID) -> datetime | None:
        async with self._unit_of_work() as uow:
            found = (await uow.session.execute(last_reconciled_statement(account_id))).first()
        return None if found is None else found[0]

    async def advance(self, account_id: UUID, to: datetime) -> bool:
        """Whether the account's row took it (a deleted or unknown account's does not)."""
        if to.tzinfo is None:
            raise ValueError("the watermark is an aware UTC time")
        async with self._unit_of_work() as uow:
            moved = (await uow.session.execute(advance_statement(account_id, to))).first()
            if moved is None:
                return False
            await uow.commit()
        return True

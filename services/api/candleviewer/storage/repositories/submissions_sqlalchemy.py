"""Postgres adapter for `SubmissionStore` (E29-T04 #913; M10).

`create_first` writes an order's first rows in one unit of work, in this order (21 Sec.3.3.10
"Writes", 24 Sec.8.4 step 5):

1. for an entry, the one-leg group, `ON CONFLICT (created_by, client_group_ref) DO NOTHING`
   (`trade_groups_sqlalchemy.insert_group_statement`): no row back means the key's group exists,
   and the persist rolls back with `AnchorTakenError(UX_TG_CREATOR_REF)`;
2. the share-locked re-check of SR-E28-15 (`require_live`): the leg's account and its profile at
   the leg's `profile_version`, `FOR SHARE`, or `TradeGroupStoreRefusedError`; a reduce-only order
   locks its account the same way;
3. the leg (`insert_legs_statement`);
4. the order and its first event in one statement (`orders_sqlalchemy.create_statement`);
5. the entry's recorded stops (`insert_stops_statement`), where `ux_rs_in_flight` refuses a second
   stop request in flight for the position;
6. the anchor, last, `ON CONFLICT ... DO NOTHING` (`insert_anchor_statement`): no row back means a
   concurrent first persist of the key committed first, and the persist rolls back with
   `AnchorTakenError(UX_IA_PRINCIPAL_REF)`;
7. the write-ahead hook, bounded by `audit_timeout_s` (`bounded_write_ahead`), then the commit.

Two first persists of one key serialise on the unique index the later one meets (the group's for an
entry, the anchor's otherwise): it waits for the earlier one's commit, then writes nothing. The
wait counts against the statement cap. The whole unit must fit B1's persist bound
(`CV_PERSIST_TIMEOUT`, 1 s), so the hook's default bound is half of it, under #3961's 5 s
default: a write that runs past B1's bound is an outcome in doubt (24 Sec.8.2 S7).

The store is a `CappedStore`: a database refusal leaves as `OrderConstraintError(name)`, any other
failure as `StorageQueryFailed(sqlstate)` or `StorageTierUnavailable`, unchained and with no value
(C-12.6); `AnchorTakenError`, `TradeGroupStoreRefusedError` and the hook's `WriteAheadTimeout` pass
as they are. Cancellation passes through.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import fields
from typing import Any, Final

from candleviewer.storage.repositories.idempotency_anchors import UX_IA_PRINCIPAL_REF
from candleviewer.storage.repositories.idempotency_anchors_sqlalchemy import (
    insert_anchor_statement,
)
from candleviewer.storage.repositories.orders import (
    NewOrder,
    NewOrderEvent,
    OrderRow,
    require_exchange_record,
)
from candleviewer.storage.repositories.orders_sqlalchemy import (
    OMS_STATEMENT_TIMEOUT_MS,
    CappedStore,
    create_statement,
)
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from candleviewer.storage.repositories.recorded_stops_sqlalchemy import (
    in_given_order,
    insert_stops_statement,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    SqlAlchemyUnitOfWork,
)
from candleviewer.storage.repositories.submissions import (
    UX_TG_CREATOR_REF,
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
)
from candleviewer.storage.repositories.trade_groups import (
    ACCOUNT_NOT_LIVE,
    TradeGroupRecord,
    TradeGroupStoreRefusedError,
)
from candleviewer.storage.repositories.trade_groups_sqlalchemy import (
    group_row,
    in_order,
    insert_group_statement,
    insert_legs_statement,
    leg_row,
    lock_accounts_statement,
    require_live,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import bounded_write_ahead

__all__ = ["SUBMISSION_AUDIT_TIMEOUT_S", "SqlAlchemySubmissionStore"]

#: The write-ahead hook's default bound (s): half of B1's 1 s persist bound (module docstring).
SUBMISSION_AUDIT_TIMEOUT_S: Final = 0.5


class SqlAlchemySubmissionStore(CappedStore):
    """`SubmissionStore` over one relational repository (asyncpg)."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        statement_timeout_ms: int = OMS_STATEMENT_TIMEOUT_MS,
        audit_timeout_s: float = SUBMISSION_AUDIT_TIMEOUT_S,
    ) -> None:
        super().__init__(relational, statement_timeout_ms=statement_timeout_ms)
        if isinstance(audit_timeout_s, bool) or not (
            isinstance(audit_timeout_s, int | float)
            and math.isfinite(audit_timeout_s)
            and audit_timeout_s > 0
        ):
            raise ValueError("audit_timeout_s must be a finite number of seconds above zero")
        self._audit_timeout_s = audit_timeout_s

    async def create_first(
        self, first: FirstPersist, order: NewOrder, event: NewOrderEvent
    ) -> FirstPersisted:
        first.check(order)
        require_exchange_record(event)
        async with self._unit_of_work() as uow:
            group = await self._group(uow, first, order)
            row = (await uow.session.execute(create_statement(order, event))).mappings().one()
            stops: tuple[RecordedStopRow, ...] = ()
            if first.recorded_stops:
                stmt = insert_stops_statement(first.recorded_stops)
                inserted = list((await uow.session.execute(stmt)).mappings())
                stops = in_given_order(inserted, [stop.id for stop in first.recorded_stops])
            anchor = await uow.session.execute(insert_anchor_statement(first.anchor))
            if anchor.first() is None:
                raise AnchorTakenError(UX_IA_PRINCIPAL_REF)
            persisted = FirstPersisted(_order_row(row), first.anchor.id, group, stops)
            if first.write_ahead is not None:
                await bounded_write_ahead(first.write_ahead(persisted), self._audit_timeout_s)
            await uow.commit()
        return persisted

    @staticmethod
    async def _group(
        uow: SqlAlchemyUnitOfWork, first: FirstPersist, order: NewOrder
    ) -> TradeGroupRecord | None:
        """Steps 1 to 3: an entry's group, its re-check and its leg; a reduce-only order's
        account, share-locked."""
        if first.group is None:
            locked = await uow.session.execute(lock_accounts_statement([order.exchange_account_id]))
            if locked.mappings().first() is None:
                raise TradeGroupStoreRefusedError(ACCOUNT_NOT_LIVE)
            return None
        stmt = insert_group_statement(first.group)
        inserted = (await uow.session.execute(stmt)).mappings().first()
        if inserted is None:
            raise AnchorTakenError(UX_TG_CREATOR_REF)
        await require_live(uow, first.group, first.legs)
        legs = await uow.session.execute(insert_legs_statement(first.group.id, first.legs))
        return TradeGroupRecord(group_row(inserted), in_order(leg_row(m) for m in legs.mappings()))


def _order_row(m: Mapping[Any, Any]) -> OrderRow:
    return OrderRow(**{f.name: m[f.name] for f in fields(OrderRow)})

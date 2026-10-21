"""Postgres adapter for `RecordedStopStore` (E29-T04 #913; M10).

SQLAlchemy Core over `db.models.recorded_stops` (revision `0043_order_submission`,
21-database-schema.md Sec.3.3.11): every value is a bound parameter, and reads select the
allow-list `STOP_COLUMNS`, every column in table order. Every statement filters on
`recorded_stops.exchange_account_id` (C-12.4) but the one in `UNSCOPED`, the insert, which writes
the account each row names (a unit test pins the set, as `orders_sqlalchemy.UNSCOPED` is pinned),
and the startup sweep when it is asked to cover every account.

`insert_stops_statement` writes one request's rows in one statement; the first persist of an entry
(`submissions_sqlalchemy.py`) runs it in its own transaction, with the order. `settle` locks the
request's rows `FOR UPDATE` in id order, so two writers of one request never deadlock, then runs
the compare-and-set: each row must still be in flight (`pending`, `answered_at` NULL), or nothing
is written (`StaleRecordedStop`). An answer sets `answered_at`; a refusal or a read that does not
show the stop makes the row `void` and stamps `closed_at` (`rs_times`).

`void_orphans_statement` is R10's startup sweep (`RecordedStopStore.void_orphans`): one UPDATE that
voids the pending entry-attach rows no order of their account still owns (an order never sent, or
ended with nothing filled), returning ids and kinds for the caller's write-ahead audit, which is
awaited, bounded, before the commit.

The store is a `CappedStore`: each unit of work caps its statements at `statement_timeout`, and
a failure leaves as `OrderConstraintError(name)` (`ux_rs_in_flight` among them),
`StorageQueryFailed(sqlstate)` or `StorageTierUnavailable`, unchained and with no value (C-12.6).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa

from candleviewer.db.models import orders, recorded_stops
from candleviewer.storage.repositories.orders import require_aware, typed_fields
from candleviewer.storage.repositories.orders_sqlalchemy import (
    OMS_STATEMENT_TIMEOUT_MS,
    CappedStore,
)
from candleviewer.storage.repositories.recorded_stops import (
    ORPHANING_STATES,
    NewRecordedStop,
    RecordedStopRow,
    StaleRecordedStop,
    StopOutcome,
    SweepWriteAhead,
    SweptStop,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    WRITE_AHEAD_TIMEOUT_S,
    bounded_write_ahead,
)

__all__ = [
    "STOP_COLUMNS", "STOP_FIELDS", "UNSCOPED", "SqlAlchemyRecordedStopStore",
    "for_order_statement", "in_given_order", "insert_stops_statement", "lock_stops_statement",
    "settle_statement", "stop_row", "void_orphans_statement",
]  # fmt: skip

_S = recorded_stops.c
STOP_FIELDS: Final = tuple(f.name for f in fields(RecordedStopRow))
STOP_COLUMNS: Final = tuple(_S[name] for name in STOP_FIELDS)
#: Statements without a `recorded_stops.exchange_account_id` filter (module docstring); tested.
UNSCOPED: Final = frozenset({"insert_stops_statement"})
_UUIDS: Final = typed_fields(RecordedStopRow, UUID)


def insert_stops_statement(stops: Sequence[NewRecordedStop]) -> sa.Insert:
    """One request's rows in one multi-row INSERT."""
    if not stops:
        raise ValueError("a stop request records at least one row")
    rows = [{f.name: getattr(stop, f.name) for f in fields(stop)} for stop in stops]
    return sa.insert(recorded_stops).values(rows).returning(*STOP_COLUMNS)


def lock_stops_statement(account_id: UUID, record_ids: Sequence[UUID]) -> sa.Select[Any]:
    """The account's rows among `record_ids`, `FOR UPDATE` in id order."""
    stmt = sa.select(_S.id).where(
        _S.exchange_account_id == account_id, _S.id.in_(sorted(set(record_ids)))
    )
    return stmt.order_by(_S.id).with_for_update()


def settle_statement(
    account_id: UUID, record_ids: Sequence[UUID], outcome: StopOutcome, at: datetime
) -> sa.Update:
    """The answer of the request in flight (module docstring), only while each row is."""
    values: dict[str, Any]
    if outcome == "answered":
        values = {"answered_at": at}
    elif outcome == "refused":
        values = {"status": "void", "answered_at": at, "closed_at": at}
    else:  # not_shown: the exchange never answered, a complete read decided it
        values = {"status": "void", "closed_at": at}
    stmt = sa.update(recorded_stops).where(
        _S.exchange_account_id == account_id,
        _S.id.in_(sorted(set(record_ids))),
        _S.status == "pending",
        _S.answered_at.is_(None),
    )
    return stmt.values(values).returning(*STOP_COLUMNS)


def for_order_statement(account_id: UUID, order_id: UUID) -> sa.Select[Any]:
    stmt = sa.select(*STOP_COLUMNS).where(
        _S.exchange_account_id == account_id, _S.order_id == order_id
    )
    return stmt.order_by(_S.created_at, _S.id)


def void_orphans_statement(account_id: UUID | None, at: datetime) -> sa.Update:
    """Pending entry-attach rows that no order of their account owns any more (module docstring):
    the account's, or with `account_id` None every account's, the sweep at startup."""
    o, rs = orders.c, recorded_stops.c
    orphaned: sa.BindParameter[Any] = sa.bindparam(
        "orphaning", sorted(ORPHANING_STATES), expanding=True, literal_execute=True
    )
    owner = sa.select(sa.literal(1)).where(
        o.id == rs.order_id,
        o.exchange_account_id == rs.exchange_account_id,
        sa.not_(sa.and_(o.state.in_(orphaned), o.cum_exec_qty == 0)),
    )
    stmt = sa.update(recorded_stops).where(
        rs.source == "entry_attach", rs.status == "pending", ~sa.exists(owner)
    )
    if account_id is not None:
        stmt = stmt.where(rs.exchange_account_id == account_id)
    stmt = stmt.values(status="void", closed_at=at)
    return stmt.returning(rs.id, rs.exchange_account_id, rs.order_id, rs.kind)


def stop_row(m: Mapping[Any, Any]) -> RecordedStopRow:
    values: dict[str, Any] = {name: m[name] for name in STOP_FIELDS}
    for name in _UUIDS:
        values[name] = None if values[name] is None else UUID(str(values[name]))
    return RecordedStopRow(**values)


def in_given_order(
    rows: Sequence[Mapping[Any, Any]], ids: Sequence[UUID]
) -> tuple[RecordedStopRow, ...]:
    """The rows a statement returned, in the order their ids were given."""
    by_id = {row.id: row for row in map(stop_row, rows)}
    return tuple(by_id[i] for i in ids if i in by_id)


class SqlAlchemyRecordedStopStore(CappedStore):
    """`RecordedStopStore` over one relational repository (asyncpg)."""

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        statement_timeout_ms: int = OMS_STATEMENT_TIMEOUT_MS,
        audit_timeout_s: float = WRITE_AHEAD_TIMEOUT_S,
    ) -> None:
        super().__init__(relational, statement_timeout_ms=statement_timeout_ms)
        self._audit_timeout_s = audit_timeout_s

    async def insert(self, stops: Sequence[NewRecordedStop]) -> tuple[RecordedStopRow, ...]:
        stmt = insert_stops_statement(stops)
        async with self._unit_of_work() as uow:
            rows = list((await uow.session.execute(stmt)).mappings())
            await uow.commit()
        return in_given_order(rows, [stop.id for stop in stops])

    async def settle(
        self,
        account_id: UUID,
        record_ids: Sequence[UUID],
        outcome: StopOutcome,
        *,
        at: datetime,
    ) -> tuple[RecordedStopRow, ...]:
        ids = tuple(record_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("a settle names each row of the request once")
        require_aware("at", at)
        async with self._unit_of_work() as uow:
            await uow.session.execute(lock_stops_statement(account_id, ids))
            stmt = settle_statement(account_id, ids, outcome, at)
            rows = list((await uow.session.execute(stmt)).mappings())
            if len(rows) != len(ids):
                raise StaleRecordedStop
            await uow.commit()
        return in_given_order(rows, ids)

    async def for_order(self, account_id: UUID, order_id: UUID) -> tuple[RecordedStopRow, ...]:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(for_order_statement(account_id, order_id))
            return tuple(stop_row(m) for m in result.mappings())

    async def void_orphans(
        self, account_id: UUID | None, *, at: datetime, write_ahead: SweepWriteAhead
    ) -> tuple[SweptStop, ...]:
        require_aware("at", at)
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(void_orphans_statement(account_id, at))
            swept = tuple(
                SweptStop(
                    id=UUID(str(m["id"])),
                    exchange_account_id=UUID(str(m["exchange_account_id"])),
                    order_id=UUID(str(m["order_id"])),
                    kind=m["kind"],
                )
                for m in result.mappings()
            )
            if swept:
                await bounded_write_ahead(write_ahead(swept), self._audit_timeout_s)
            await uow.commit()
        return swept

"""Postgres adapter for `ClosedPnlStore` (E29-S06 #981 slice 2; 21 Sec.3.3.13).

SQLAlchemy Core over `db.models.closed_pnl_records` with the `CappedStore` cap and error mapping of
`orders_sqlalchemy.py`. Every value is bound, but the literals that let the planner match a
partial index (`size = 0`); records are read whole, in table order (`RECORD_COLUMNS`). Every
statement filters on the account (C-12.4): an upsert updates only a row of its record's account,
and the page and the totals read the accounts their caller settled.

A write takes the account's transaction-scoped advisory lock (`LOCK`) first, so a venue read's
outcome (`settle_outcome`) is decided on the row its write meets. The composition's upsert writes
the local figures and `trade_group_id`, the composition's alone, always, and the provisional
`qty`, prices and `closed_at` only while `settled_at` is NULL; a venue read's upsert writes the
venue's columns and stamps `settled_at` once, never on a final row (`trg_cpr_guard` would refuse
it) and never `trade_group_id`; `finalize` stamps `final_at` once, on a settled row with an order
id (`cpr_final`). The reads are 21 Sec.13.1's rows: 55, a page read per account (`LATERAL`) by
`(closed_at, id)` either way from a `Keyset`, then merged, as `oms_reads_sqlalchemy.py` reads
(#4997), and the totals of the window the query names as a `ROLLUP`, summed in SQL with the
page's `net_pnl` (`ix_cpr_day`), both serving and counting a provisional item without a figure;
59, either filtered on the stored `trade_group_id` (`ix_cpr_group`); 56, the records not final
within the poll's reach by `closed_at`, the order `ix_cpr_pending` gives, with their order rows
(`ux_orders_exch_id`); 57, a key's confirmed flats from the last before a time, each venue time
once (`ix_psnap_flat`); and 58, a key's trade fills after a `FillKey` with their order rows
(`ix_exec_walk`, the `orders` PK).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from candleviewer.db.models import closed_pnl_records, executions, orders, position_snapshots
from candleviewer.storage.repositories.closed_pnl import (
    VENUE_COLUMNS,
    AccountTotals,
    ClosedPnlQuery,
    ClosedPnlRecordRow,
    ClosedPnlTotals,
    ComposedRecord,
    FillKey,
    ListedClosedPnl,
    PendingRecord,
    SettleOutcome,
    VenueRecord,
    WalkFill,
    require_window,
    settle_outcome,
)
from candleviewer.storage.repositories.oms_reads import CLOSING_EXEC_TYPES, Keyset
from candleviewer.storage.repositories.orders import require_aware, require_limit
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore

_C, _O, _X, _S = closed_pnl_records.c, orders.c, executions.c, position_snapshots.c
RECORD_COLUMNS: Final = tuple(_C[f.name] for f in fields(ClosedPnlRecordRow))
#: The composition's columns: always written, and the provisional ones only while unsettled.
LOCAL: Final = (
    "position_idx", "trade_group_id", "gross_pnl", "fee_pnl", "funding_pnl", "opened_at",
)  # fmt: skip
PROVISIONAL: Final = ("qty", "avg_entry_price", "avg_exit_price", "closed_at")
#: The account's lock for the transaction: every write of the account waits for the one before.
LOCK: Final = sa.text(
    "SELECT pg_advisory_xact_lock("
    "hashtextextended('cv.closed_pnl_records:' || CAST(:account AS text), 0))"
)


def _symbol(column: sa.ColumnElement[Any]) -> sa.ColumnElement[Any]:
    return sa.type_coerce(column, sa.Text)  # SQLAlchemy has no DOMAIN operator class


def get_statement(account_id: UUID, record_id: UUID) -> sa.Select[Any]:
    return sa.select(*RECORD_COLUMNS).where(
        _C.exchange_account_id == account_id, _C.id == record_id
    )


def _upsert(record: ComposedRecord | VenueRecord, values: dict[str, Any]) -> Insert:
    names = ("exchange_account_id", "exchange_order_id", "symbol", "side")
    row = {"id": record.id} | {name: getattr(record, name) for name in names}
    return pg_insert(closed_pnl_records).values(**row, **values)


def compose_statement(record: ComposedRecord) -> sa.Insert:
    """The composition's upsert by id (24 Sec.8.13): a settled row keeps the venue's columns."""
    stmt = _upsert(record, {name: getattr(record, name) for name in (*LOCAL, *PROVISIONAL)})
    changed: dict[str, Any] = {name: stmt.excluded[name] for name in LOCAL}
    for name in PROVISIONAL:
        changed[name] = sa.case((_C.settled_at.is_not(None), _C[name]), else_=stmt.excluded[name])
    return stmt.on_conflict_do_update(
        index_elements=[_C.id], set_=changed | {"updated_at": sa.func.now()},
        where=_C.exchange_account_id == stmt.excluded.exchange_account_id,
    ).returning(*RECORD_COLUMNS)  # fmt: skip


def settle_statement(record: VenueRecord) -> sa.Insert:
    """A venue read's upsert by id: the venue's columns, `settled_at` once, never a final row."""
    venue = {name: getattr(record, name) for name in VENUE_COLUMNS}
    stmt = _upsert(record, venue | {"settled_at": sa.func.now()})
    changed: dict[str, Any] = {name: stmt.excluded[name] for name in VENUE_COLUMNS}
    changed["settled_at"] = sa.func.coalesce(_C.settled_at, stmt.excluded.settled_at)
    own = _C.exchange_account_id == stmt.excluded.exchange_account_id
    return stmt.on_conflict_do_update(
        index_elements=[_C.id], set_=changed | {"updated_at": sa.func.now()},
        where=sa.and_(own, _C.final_at.is_(None)),
    ).returning(_C.id)  # fmt: skip


def finalize_statement(account_id: UUID, record_id: UUID) -> sa.Update:
    settled = (_C.settled_at.is_not(None), _C.exchange_order_id.is_not(None))
    return (
        sa.update(closed_pnl_records)
        .where(_C.exchange_account_id == account_id, _C.id == record_id, _C.final_at.is_(None))
        .where(*settled)
        .values(final_at=sa.func.now(), updated_at=sa.func.now())
        .returning(_C.id)
    )


def net_pnl() -> sa.ColumnElement[Any]:
    """24 Sec.8.13: `closed_pnl` once settled, else the local figures present, `gross_pnl` first:
    NULL without one, an item served and counted all the same."""
    fee, funding = (
        sa.func.coalesce(c, sa.literal_column("0")) for c in (_C.fee_pnl, _C.funding_pnl)
    )
    return sa.case((_C.settled_at.is_not(None), _C.closed_pnl), else_=_C.gross_pnl + fee + funding)


def _selected(query: ClosedPnlQuery) -> list[sa.ColumnElement[bool]]:
    """The filters but the accounts, which each read applies its own way."""
    where: list[sa.ColumnElement[bool]] = []
    if query.symbols:
        where.append(_symbol(_C.symbol).in_(sorted(set(query.symbols))))
    if query.trade_groups:  # a NULL matches none (row 59)
        where.append(_C.trade_group_id.in_(sorted(set(query.trade_groups))))
    if query.side is not None:
        where.append(_C.side == query.side)
    if query.since is not None:
        where.append(_C.closed_at >= query.since)
    if query.until is not None:
        where.append(_C.closed_at < query.until)
    return where


def _ordered(columns: Sequence[sa.ColumnElement[Any]], up: bool) -> list[sa.ColumnElement[Any]]:
    return list(columns) if up else [column.desc() for column in columns]


def page_statement(query: ClosedPnlQuery, after: Keyset | None, limit: int) -> sa.Select[Any]:
    """`listClosedPnl`'s page past `after`, oldest first for a window read, else newest first:
    per account (`LATERAL` over its `VALUES`) at most `limit` rows in `(closed_at, id)` order,
    then the first `limit` of those, so no read sorts every matching row (row 55, #4997)."""
    column = sa.column("account_id", sa.Uuid)
    accounts = sa.values(column, name="accounts").data([(a,) for a in sorted(set(query.accounts))])
    up, key = query.oldest_first, sa.tuple_(_C.closed_at, _C.id)
    stmt = sa.select(*RECORD_COLUMNS, net_pnl().label("net_pnl")).where(
        _C.exchange_account_id == accounts.c.account_id, *_selected(query)
    )
    if after is not None:
        at = sa.tuple_(after.at, after.id)
        stmt = stmt.where(key > at if up else key < at)
    stmt = stmt.order_by(*_ordered((_C.closed_at, _C.id), up)).limit(limit)
    page = stmt.lateral("page")
    merged = sa.select(page).select_from(accounts).join(page, sa.true())
    return merged.order_by(*_ordered((page.c.closed_at, page.c.id), up)).limit(limit)


def totals_statement(query: ClosedPnlQuery) -> sa.Select[Any]:
    """Per account and over all of them, the rollup's row with no account first, summed in SQL:
    every selected item counts, and `net_pnl` sums those that have one, 0 over none."""
    account = _C.exchange_account_id
    net = sa.func.coalesce(sa.func.sum(net_pnl()), sa.literal_column("0"))
    return (
        sa.select(
            account, sa.func.count().label("count"), net.label("net_pnl"),
            sa.func.bool_or(_C.settled_at.is_(None)).label("provisional"),
        )
        .where(account.in_(sorted(set(query.accounts))), *_selected(query))
        .group_by(sa.func.rollup(account))
        .order_by(account.nulls_first())
    )  # fmt: skip


def pending_statement(account_id: UUID, reach: datetime, limit: int) -> sa.Select[Any]:
    """Row 56: the account's records not final whose order has a row, from `reach` on, by
    `closed_at`, the order `ix_cpr_pending` gives; a tie at the cut only decides which records
    closed in the same millisecond wait for the next poll."""
    order = sa.and_(
        _O.exchange_account_id == _C.exchange_account_id,
        _O.exchange_order_id == _C.exchange_order_id,
    )
    return (
        sa.select(*RECORD_COLUMNS, _O.id.label("order_id"), _O.state.label("order_state"))
        .select_from(closed_pnl_records.join(orders, order))
        .where(_C.exchange_account_id == account_id, _C.final_at.is_(None))
        .where(_C.exchange_order_id.is_not(None), _C.closed_at >= reach)
        .where(_O.exchange_order_id.is_not(None))
        .order_by(_C.closed_at)
        .limit(limit)
    )


def walk_flats_statement(
    account_id: UUID, symbol: str, position_idx: int, before: datetime, limit: int
) -> sa.Select[Any]:
    """Row 57: the key's flats the venue confirmed, from the last one before `before`, each venue
    time once, as the stream and each reconciliation can store one reading."""
    flat = (
        _S.exchange_account_id == account_id, _symbol(_S.symbol) == symbol,
        _S.position_idx == position_idx, _S.size == sa.literal_column("0"),
        _S.exchange_updated_ts.is_not(None),
    )  # fmt: skip
    last = sa.select(sa.func.max(_S.exchange_updated_ts)).where(*flat)
    start = last.where(_S.exchange_updated_ts < before).scalar_subquery()
    return (
        sa.select(_S.exchange_updated_ts)
        .distinct()
        .where(*flat, _S.exchange_updated_ts >= start)
        .order_by(_S.exchange_updated_ts)
        .limit(limit)
    )


def walk_fills_statement(
    account_id: UUID, symbol: str, position_idx: int, after: FillKey, limit: int
) -> sa.Select[Any]:
    """Row 58: the key's trade fills after `after`, in order, with their order rows; a fill with
    no order row too, which the walk must see."""
    later = (
        _X.exec_ts > after.at if after.exec_id is None
        else sa.tuple_(_X.exec_ts, _X.exec_id) > sa.tuple_(after.at, after.exec_id)
    )  # fmt: skip
    columns = [_X[f.name] for f in fields(WalkFill) if f.name in _X]
    order = (
        _O.position_idx.label("order_position_idx"),
        _O.exchange_order_id.label("order_exchange_id"),
    )
    return (
        sa.select(*columns, *order)
        .select_from(executions.outerjoin(orders, _O.id == _X.order_id))
        .where(_X.exchange_account_id == account_id, _symbol(_X.symbol) == symbol)
        .where(_X.exec_type.in_(CLOSING_EXEC_TYPES), later)
        .where(sa.or_(_O.position_idx == position_idx, _O.id.is_(None)))
        .order_by(_X.exec_ts, _X.exec_id)
        .limit(limit)
    )


def record_row(row: Mapping[Any, Any]) -> ClosedPnlRecordRow:
    return ClosedPnlRecordRow(**{f.name: row[f.name] for f in fields(ClosedPnlRecordRow)})


def totals_of(rows: Sequence[Mapping[Any, Any]]) -> ClosedPnlTotals:
    """The rollup's rows as 22 `ClosedPnlTotals`: its total comes first, even over no item."""
    (total, *accounts), keys = rows, ("exchange_account_id", "count", "net_pnl", "provisional")
    by_account = tuple(AccountTotals(**{key: row[key] for key in keys}) for row in accounts)
    return ClosedPnlTotals(
        count=total["count"], net_pnl=total["net_pnl"], provisional=bool(total["provisional"]),
        by_account=by_account,
    )  # fmt: skip


class SqlAlchemyClosedPnlStore(CappedStore):
    """`ClosedPnlStore` over one relational repository (asyncpg)."""

    async def compose(self, record: ComposedRecord) -> ClosedPnlRecordRow:
        async with self._unit_of_work() as uow:
            await uow.session.execute(LOCK, {"account": str(record.exchange_account_id)})
            row = (await uow.session.execute(compose_statement(record))).mappings().one()
            await uow.commit()
        return record_row(row)

    async def settle(self, record: VenueRecord) -> SettleOutcome:
        account = record.exchange_account_id
        async with self._unit_of_work() as uow:
            await uow.session.execute(LOCK, {"account": str(account)})
            held = (await uow.session.execute(get_statement(account, record.id))).mappings().first()
            outcome = settle_outcome(None if held is None else record_row(held), record)
            if outcome in ("unchanged", "frozen"):
                return outcome  # nothing to write: the unit of work ends without a commit
            await uow.session.execute(settle_statement(record))
            await uow.commit()
        return outcome

    async def finalize(self, account_id: UUID, record_id: UUID) -> bool:
        async with self._unit_of_work() as uow:
            await uow.session.execute(LOCK, {"account": str(account_id)})
            stamped = await uow.session.execute(finalize_statement(account_id, record_id))
            if stamped.first() is None:
                return False
            await uow.commit()
        return True

    async def get(self, account_id: UUID, record_id: UUID) -> ClosedPnlRecordRow | None:
        rows = await self._rows(get_statement(account_id, record_id))
        return record_row(rows[0]) if rows else None

    async def page(
        self, query: ClosedPnlQuery, after: Keyset | None, limit: int
    ) -> tuple[ListedClosedPnl, ...]:
        require_limit(limit)
        rows = await self._rows(page_statement(query, after, limit))
        return tuple(ListedClosedPnl(record_row(row), row["net_pnl"]) for row in rows)

    async def totals(self, query: ClosedPnlQuery) -> ClosedPnlTotals:
        require_window(query)
        return totals_of(await self._rows(totals_statement(query)))

    async def pending(
        self, account_id: UUID, reach: datetime, limit: int
    ) -> tuple[PendingRecord, ...]:
        require_aware("reach", reach)
        require_limit(limit)
        rows = await self._rows(pending_statement(account_id, reach, limit))
        return tuple(PendingRecord(record_row(r), r["order_id"], r["order_state"]) for r in rows)

    async def walk_flats(
        self, account_id: UUID, symbol: str, position_idx: int, before: datetime, limit: int
    ) -> tuple[datetime, ...]:
        require_aware("before", before)
        require_limit(limit)
        stmt = walk_flats_statement(account_id, symbol, position_idx, before, limit)
        return tuple(row["exchange_updated_ts"] for row in await self._rows(stmt))

    async def walk_fills(
        self, account_id: UUID, symbol: str, position_idx: int, after: FillKey, limit: int
    ) -> tuple[WalkFill, ...]:
        require_aware("after", after.at)
        require_limit(limit)
        rows = await self._rows(
            walk_fills_statement(account_id, symbol, position_idx, after, limit)
        )
        return tuple(WalkFill(**{f.name: row[f.name] for f in fields(WalkFill)}) for row in rows)

    async def _rows(self, stmt: sa.Select[Any]) -> Sequence[Mapping[Any, Any]]:
        async with self._unit_of_work() as uow:
            rows: Sequence[Mapping[Any, Any]] = (await uow.session.execute(stmt)).mappings().all()
        return rows

"""Postgres adapter for `OmsHandoverStore` (E29-T06 #914 PR 1; 21 Sec.3.3.12).

SQLAlchemy Core over `db.models.oms_handovers` (21 Sec.3.3.12): every value is a bound parameter,
and reads select every column in table order (`HANDOVER_COLUMNS`). Every statement filters on
`oms_handovers.exchange_account_id` (C-12.4) but the insert, which writes the account its entry
names (`UNSCOPED`); a unit test pins both.

`append` takes the account's transaction-scoped advisory lock (`LOCK`) first, so the bound it
reads holds against every other writer of the account and two appends of one key never race. In
that transaction an execution's empty read is counted on the entry held (`count_read_statement`:
one more, the first stamped once), any other append finds the entry held and changes nothing, and
only a new entry is counted against `MAX_HANDOVERS_PER_ACCOUNT` before its insert: past it,
`HandoverStoreFull`, with nothing written. The insert is `ON CONFLICT DO NOTHING`, a second guard
under the lock. `decide` stamps an unpaired fill once; `prune` deletes the entries named, and
commits only what it changed.

The store is a `CappedStore`: each unit of work caps its statements at `statement_timeout`, and a
failure leaves as `OrderConstraintError(name)`, `StorageQueryFailed(sqlstate)` or
`StorageTierUnavailable`, unchained and with no value (C-12.6). Its caller bounds each call
(C-2.18), as the pool wait and a connection's opening are outside the cap.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import fields
from typing import Any, Final, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql.dml import ReturningDelete

from candleviewer.db.models import oms_handovers
from candleviewer.storage.repositories.oms_handovers import (
    MAX_HANDOVERS_PER_ACCOUNT,
    AppendOutcome,
    HandoverKind,
    HandoverRow,
    HandoverStoreFull,
    NewHandover,
)
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore

_H = oms_handovers.c
HANDOVER_COLUMNS: Final = tuple(_H[f.name] for f in fields(HandoverRow))
#: Statements without an `exchange_account_id` filter: the insert writes the one its entry names.
UNSCOPED: Final = frozenset({"insert_statement"})
#: The account's lock for the transaction: every append of the account waits for the one before.
LOCK: Final = sa.text(
    "SELECT pg_advisory_xact_lock("
    "hashtextextended('cv.oms_handovers:' || CAST(:account AS text), 0))"
)


def _keyed(entry: NewHandover) -> sa.ColumnElement[bool]:
    """The entry's key in its account: (account, orderId) for an order, (account, exec_id) for an
    execution, as `ux_oh_order` and `ux_oh_exec` hold them."""
    if entry.kind == "execution":
        return sa.and_(_H.kind == "execution", _H.exec_id == entry.exec_id)
    return sa.and_(_H.kind == "order", _H.exchange_order_id == entry.exchange_order_id)


def held_statement(entry: NewHandover) -> sa.Select[Any]:
    return sa.select(_H.id).where(
        _H.exchange_account_id == entry.exchange_account_id, _keyed(entry)
    )


def count_read_statement(entry: NewHandover) -> sa.Update:
    """One more empty read on the execution entry held, the first stamped once (24 Sec.8.5 3d)."""
    return (
        sa.update(oms_handovers)
        .where(_H.exchange_account_id == entry.exchange_account_id, _keyed(entry))
        .values(
            empty_reads=_H.empty_reads + 1,
            first_empty_read_at=sa.func.coalesce(_H.first_empty_read_at, sa.func.now()),
        )
        .returning(_H.id)
    )


def size_statement(account_id: UUID) -> sa.Select[Any]:
    return (
        sa.select(sa.func.count().label("n"))
        .select_from(oms_handovers)
        .where(_H.exchange_account_id == account_id)
    )


def insert_statement(entry: NewHandover) -> sa.Insert:
    stmt = pg_insert(oms_handovers).values(
        exchange_account_id=entry.exchange_account_id,
        kind=entry.kind,
        exchange_order_id=entry.exchange_order_id,
        exec_id=entry.exec_id,
        source=entry.source,
        record=dict(entry.record),
        payload=dict(entry.payload),
        empty_reads=1 if entry.empty_read else 0,
        first_empty_read_at=sa.func.now() if entry.empty_read else None,
    )
    return stmt.on_conflict_do_nothing().returning(_H.id)


def pending_statement(account_id: UUID, kind: HandoverKind) -> sa.Select[Any]:
    return (
        sa.select(*HANDOVER_COLUMNS)
        .where(_H.exchange_account_id == account_id, _H.kind == kind)
        .order_by(_H.id)
        .limit(MAX_HANDOVERS_PER_ACCOUNT)
    )


def decide_statement(account_id: UUID, exec_id: str) -> sa.Update:
    return (
        sa.update(oms_handovers)
        .where(
            _H.exchange_account_id == account_id,
            _H.kind == "execution",
            _H.exec_id == exec_id,
            _H.decided_at.is_(None),
        )
        .values(decided_at=sa.func.now())
        .returning(_H.id)
    )


def prune_statement(account_id: UUID, ids: Collection[int]) -> ReturningDelete[Any]:
    return (
        sa.delete(oms_handovers)
        .where(_H.exchange_account_id == account_id, _H.id.in_(sorted(set(ids))))
        .returning(_H.id)
    )


def handover_row(row: Mapping[Any, Any]) -> HandoverRow:
    values = {f.name: row[f.name] for f in fields(HandoverRow)}
    values["record"], values["payload"] = dict(row["record"]), dict(row["payload"])
    return HandoverRow(**values)


class SqlAlchemyHandoverStore(CappedStore):
    """`OmsHandoverStore` over one relational repository (asyncpg)."""

    async def append(self, entry: NewHandover) -> AppendOutcome:
        account = entry.exchange_account_id
        async with self._unit_of_work() as uow:
            await uow.session.execute(LOCK, {"account": str(account)})
            if entry.empty_read:
                if (await uow.session.execute(count_read_statement(entry))).first() is not None:
                    await uow.commit()
                    return "counted"
            elif (await uow.session.execute(held_statement(entry))).first() is not None:
                return "held"  # nothing changed: the unit of work ends without a commit
            held = cast(int, (await uow.session.execute(size_statement(account))).scalar_one())
            if held >= MAX_HANDOVERS_PER_ACCOUNT:
                raise HandoverStoreFull(
                    f"the account holds {MAX_HANDOVERS_PER_ACCOUNT} hand-overs (21 Sec.3.3.12)"
                )
            if (await uow.session.execute(insert_statement(entry))).first() is None:
                return "held"  # a key the lock should have shown held: nothing is written
            await uow.commit()
        return "added"

    async def pending(self, account_id: UUID, kind: HandoverKind) -> tuple[HandoverRow, ...]:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(pending_statement(account_id, kind))
            rows = result.mappings().all()
        return tuple(handover_row(row) for row in rows)

    async def decide(self, account_id: UUID, exec_id: str) -> bool:
        async with self._unit_of_work() as uow:
            stamped = (await uow.session.execute(decide_statement(account_id, exec_id))).first()
            if stamped is None:
                return False
            await uow.commit()
        return True

    async def prune(self, account_id: UUID, ids: Collection[int]) -> int:
        if not ids:
            return 0
        async with self._unit_of_work() as uow:
            pruned = (await uow.session.execute(prune_statement(account_id, ids))).mappings().all()
            if pruned:
                await uow.commit()
        return len(pruned)

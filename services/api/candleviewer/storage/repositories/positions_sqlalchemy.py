"""Postgres position and position-snapshot store (E29-T01 #845, `0029_oms_core`).

Core statements and the `CappedStore` cap and error mapping, as in `orders_sqlalchemy.py`. `upsert`
is `INSERT ... ON CONFLICT (exchange_account_id, symbol, position_idx) DO UPDATE`: the row takes the
state, `recv_ts` and `updated_at` become now(), a new row's id is `gen_random_uuid()`. The update
applies only when the stored or the new `exchange_updated_ts` is NULL or the stored one is not
later, so a stale snapshot never overwrites a newer push and `list_unprotected` cannot lose a
position without a stop-loss (C-2.6); a skipped update returns the stored row, re-selected under
the conflict's row lock. A stop of 0 or less is bound as NULL, or `ix_pos_no_sl` would miss an
unprotected position (C-2.6). The reads render `size > 0` with a literal 0 so the planner matches
the partial indexes, and filter on the account (C-12.4); the two inserts write the account they
are given (`UNSCOPED`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from candleviewer.db.models import position_snapshots, positions
from candleviewer.storage.repositories.orders_sqlalchemy import CappedStore
from candleviewer.storage.repositories.positions import (
    NewPositionSnapshot,
    PositionRow,
    PositionSnapshotRow,
    PositionState,
)

_P = positions.c
_S = position_snapshots.c
POSITION_COLUMNS: Final = tuple(_P[f.name] for f in fields(PositionRow))
SNAPSHOT_COLUMNS: Final = tuple(_S[f.name] for f in fields(PositionSnapshotRow))
#: Statements without an `exchange_account_id` filter (module docstring); tested.
UNSCOPED: Final = frozenset({"upsert_statement", "append_statement"})
_KEY: Final = ("exchange_account_id", "symbol", "position_idx")
_STOPS: Final = ("take_profit", "stop_loss", "trailing_stop")


def upsert_statement(state: PositionState) -> sa.Insert:
    values: dict[str, Any] = {f.name: getattr(state, f.name) for f in fields(PositionState)}
    for name in _STOPS:
        if values[name] is not None and values[name] <= 0:
            values[name] = None
    stmt = pg_insert(positions).values(id=sa.func.gen_random_uuid(), **values)
    update: dict[str, Any] = {name: stmt.excluded[name] for name in values if name not in _KEY}
    update |= {"recv_ts": sa.func.now(), "updated_at": sa.func.now()}
    stored, given = _P.exchange_updated_ts, stmt.excluded.exchange_updated_ts
    newer = sa.or_(stored.is_(None), given.is_(None), stored <= given)
    return stmt.on_conflict_do_update(
        index_elements=[_P[k] for k in _KEY], set_=update, where=newer
    ).returning(*POSITION_COLUMNS)


def stored_statement(state: PositionState) -> sa.Select[Any]:
    """The stored row, which `upsert` returns when the guard skipped a stale write (`symbol` as
    text: SQLAlchemy 2.1 has no operator class for DOMAIN)."""
    return sa.select(*POSITION_COLUMNS).where(
        _P.exchange_account_id == state.exchange_account_id,
        sa.type_coerce(_P.symbol, sa.Text) == state.symbol,
        _P.position_idx == state.position_idx,
    )


def list_open_statement(account_id: UUID) -> sa.Select[Any]:
    return (
        sa.select(*POSITION_COLUMNS)
        .where(_P.exchange_account_id == account_id, _P.size > sa.literal_column("0"))
        .order_by(_P.symbol, _P.position_idx)
    )


def list_unprotected_statement(account_id: UUID) -> sa.Select[Any]:
    return list_open_statement(account_id).where(_P.stop_loss.is_(None))


def append_statement(snapshot: NewPositionSnapshot) -> sa.Insert:
    values = {f.name: getattr(snapshot, f.name) for f in fields(NewPositionSnapshot)}
    return sa.insert(position_snapshots).values(values).returning(*SNAPSHOT_COLUMNS)


def _position(row: Mapping[Any, Any]) -> PositionRow:
    return PositionRow(**{c.name: row[c.name] for c in POSITION_COLUMNS})


class SqlAlchemyPositionStore(CappedStore):
    """`PositionStore` and `PositionSnapshotStore` over one relational repository (asyncpg)."""

    async def upsert(self, state: PositionState) -> PositionRow:
        async with self._unit_of_work() as uow:
            row = (await uow.session.execute(upsert_statement(state))).mappings().first()
            if row is None:  # a stale write: the guard skipped the update
                row = (await uow.session.execute(stored_statement(state))).mappings().one()
            await uow.commit()
        return _position(row)

    async def list_open(self, account_id: UUID) -> tuple[PositionRow, ...]:
        return await self._positions(list_open_statement(account_id))

    async def list_unprotected(self, account_id: UUID) -> tuple[PositionRow, ...]:
        return await self._positions(list_unprotected_statement(account_id))

    async def append(self, snapshot: NewPositionSnapshot) -> PositionSnapshotRow:
        async with self._unit_of_work() as uow:
            row = (await uow.session.execute(append_statement(snapshot))).mappings().one()
            await uow.commit()
        return PositionSnapshotRow(**{c.name: row[c.name] for c in SNAPSHOT_COLUMNS})

    async def _positions(self, stmt: sa.Select[Any]) -> tuple[PositionRow, ...]:
        async with self._unit_of_work() as uow:
            result = await uow.session.execute(stmt)
            return tuple(_position(row) for row in result.mappings())

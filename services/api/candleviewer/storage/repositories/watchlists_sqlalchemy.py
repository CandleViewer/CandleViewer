"""Postgres `WatchlistStore` (the `watchlists` migration, E08-T07, #4706; 21 Sec.3.8.6).

Static, parameterised `sa.text` only (literal SQL, so each statement repeats the column list), and
every statement names the owner (`user_id = CAST(:owner AS uuid)`, the INSERT binds it). The one
`UNSCOPED` statement, `_OTHER_OWNER`, reads another user's row for its existence alone. A write is
one unit of work: its statement, the write-ahead record bounded by `bounded_write_ahead` (C-2.9;
past the bound, `WriteAheadTimeout`), then the commit; a record that raises rolls it all back.
`replace` locks the row `FOR UPDATE` and compares the version first, then runs 21 Sec.3.8.6's
guarded UPDATE (`AND version = :expected`), so a racing writer waits for the commit and then finds
another version. A violation of `ux_wl_name` is `WatchlistNameTakenError`; any other refusal is the
shared `query_failure`, which carries no value (C-12.6). The lists are read in creation order.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    constraint_of,
    query_failure,
    sqlstate_of,
)
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    WRITE_AHEAD_TIMEOUT_S,
    bounded_write_ahead,
)
from candleviewer.storage.repositories.watchlists import (
    WatchlistFields,
    WatchlistNameTakenError,
    WatchlistNotFoundError,
    WatchlistRow,
    WatchlistStaleError,
    WatchlistWriteAhead,
)

#: Every column, in table order; literal SQL only, so each statement repeats it (a test pins it).
COLUMNS: Final = "id, user_id, name, symbols, columns, version, created_at, updated_at"
_LIST = sa.text(
    "SELECT id, user_id, name, symbols, columns, version, created_at, updated_at FROM watchlists "
    "WHERE user_id = CAST(:owner AS uuid) ORDER BY created_at, id"
)
_GET = sa.text(
    "SELECT id, user_id, name, symbols, columns, version, created_at, updated_at FROM watchlists "
    "WHERE id = CAST(:id AS uuid) AND user_id = CAST(:owner AS uuid)"
)
_LOCK = sa.text(
    "SELECT id, user_id, name, symbols, columns, version, created_at, updated_at FROM watchlists "
    "WHERE id = CAST(:id AS uuid) AND user_id = CAST(:owner AS uuid) FOR UPDATE"
)
_INSERT = sa.text(
    "INSERT INTO watchlists (id, user_id, name, symbols, columns) VALUES (CAST(:id AS uuid), "
    "CAST(:owner AS uuid), :name, CAST(:symbols AS text[]), CAST(:columns AS text[])) "
    "RETURNING id, user_id, name, symbols, columns, version, created_at, updated_at"
)
_REPLACE = sa.text(
    "UPDATE watchlists SET name = :name, symbols = CAST(:symbols AS text[]), "
    "columns = CAST(:columns AS text[]), version = version + 1, updated_at = now() "
    "WHERE id = CAST(:id AS uuid) AND user_id = CAST(:owner AS uuid) AND version = :expected "
    "RETURNING id, user_id, name, symbols, columns, version, created_at, updated_at"
)
#: Whether another user holds the id: its existence alone, never a column (`UNSCOPED`).
_OTHER_OWNER = sa.text(
    "SELECT EXISTS (SELECT 1 FROM watchlists WHERE id = CAST(:id AS uuid) "
    "AND user_id <> CAST(:owner AS uuid))"
)
_DELETE = sa.text(
    "DELETE FROM watchlists WHERE id = CAST(:id AS uuid) AND user_id = CAST(:owner AS uuid) "
    "RETURNING id, user_id, name, symbols, columns, version, created_at, updated_at"
)

#: Statements that read past the owner's own rows (see the module docstring); tested.
UNSCOPED: Final = frozenset({"_OTHER_OWNER"})


def _row(m: Any) -> WatchlistRow:  # SQLAlchemy's RowMapping is Mapping[Any, Any]
    return WatchlistRow(
        UUID(str(m["id"])), UUID(str(m["user_id"])), m["name"], tuple(m["symbols"]),
        tuple(m["columns"]), m["version"], m["created_at"], m["updated_at"],
    )  # fmt: skip


def _key(owner: UUID, watchlist_id: UUID) -> dict[str, str]:
    return {"id": str(watchlist_id), "owner": str(owner)}


def _values(owner: UUID, watchlist_id: UUID, fields: WatchlistFields) -> dict[str, Any]:
    named = {"name": fields.name, "symbols": list(fields.symbols), "columns": list(fields.columns)}
    return _key(owner, watchlist_id) | named


def _refusal(state: str | None, name: str | None) -> Exception:
    """`ux_wl_name` (23505) is the name taken; anything else, the shared typed failure."""
    if state == "23505" and name == "ux_wl_name":
        return WatchlistNameTakenError()
    return query_failure(state, name)


class SqlAlchemyWatchlistStore:
    """`WatchlistStore` over one relational repository (asyncpg)."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def list_own(self, owner: UUID) -> list[WatchlistRow]:
        async with self._relational.unit_of_work() as uow:
            found = await uow.session.execute(_LIST, {"owner": str(owner)})
            return [_row(m) for m in found.mappings()]

    async def get_own(self, owner: UUID, watchlist_id: UUID) -> WatchlistRow | None:
        async with self._relational.unit_of_work() as uow:
            found = (await uow.session.execute(_GET, _key(owner, watchlist_id))).mappings().first()
        return None if found is None else _row(found)

    async def exists_for_other_owner(self, owner: UUID, watchlist_id: UUID) -> bool:
        async with self._relational.unit_of_work() as uow:
            found = await uow.session.execute(_OTHER_OWNER, _key(owner, watchlist_id))
            return bool(found.scalar_one())

    async def create(
        self, owner: UUID, watchlist_id: UUID, fields: WatchlistFields, *,
        write_ahead: WatchlistWriteAhead,
    ) -> WatchlistRow:  # fmt: skip
        try:
            async with self._relational.unit_of_work() as uow:
                found = await uow.session.execute(_INSERT, _values(owner, watchlist_id, fields))
                after = _row(found.mappings().one())
                await bounded_write_ahead(write_ahead(None, after), WRITE_AHEAD_TIMEOUT_S)
                await uow.commit()
        except IntegrityError as exc:
            state, name = sqlstate_of(exc), constraint_of(exc)
            raise _refusal(state, name) from None
        return after

    async def replace(
        self, owner: UUID, watchlist_id: UUID, fields: WatchlistFields, *,
        expected_version: int | None, write_ahead: WatchlistWriteAhead,
    ) -> WatchlistRow:  # fmt: skip
        try:
            async with self._relational.unit_of_work() as uow:
                key = _key(owner, watchlist_id)
                held = (await uow.session.execute(_LOCK, key)).mappings().first()
                if held is None:
                    raise WatchlistNotFoundError
                before = _row(held)
                if expected_version != before.version:
                    raise WatchlistStaleError(before.version)
                values = _values(owner, watchlist_id, fields) | {"expected": expected_version}
                found = (await uow.session.execute(_REPLACE, values)).mappings().first()
                if found is None:  # the version moved after all: never applied silently
                    raise WatchlistStaleError(before.version)
                after = _row(found)
                await bounded_write_ahead(write_ahead(before, after), WRITE_AHEAD_TIMEOUT_S)
                await uow.commit()
        except IntegrityError as exc:
            state, name = sqlstate_of(exc), constraint_of(exc)
            raise _refusal(state, name) from None
        return after

    async def delete(
        self, owner: UUID, watchlist_id: UUID, *, write_ahead: WatchlistWriteAhead
    ) -> WatchlistRow:
        async with self._relational.unit_of_work() as uow:
            found = (await uow.session.execute(_DELETE, _key(owner, watchlist_id))).mappings()
            gone = found.first()
            if gone is None:
                raise WatchlistNotFoundError
            before = _row(gone)
            await bounded_write_ahead(write_ahead(before, None), WRITE_AHEAD_TIMEOUT_S)
            await uow.commit()
        return before


__all__ = ["COLUMNS", "UNSCOPED", "SqlAlchemyWatchlistStore"]

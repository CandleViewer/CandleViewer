"""Postgres `HotkeyProfileStore` (migration `0064_hotkey_profiles`, E10-T05, #5211; 21 Sec.3.8.5).

Static, parameterised `sa.text` only (literal SQL, so each statement repeats the column list), and
every statement names the owner (`owner_user_id = CAST(:owner AS uuid)`; the INSERT binds it, the
lock keys on it). The one `UNSCOPED` statement, `_OTHER_OWNER`, reads another user's row for its
existence alone. A write is one unit of work, as the watchlist store's: the owner's advisory lock
(`_LOCK_OWNER`, the scanner-preset pattern), its reads, its statements, the write-ahead record
bounded by `bounded_write_ahead` (C-2.9; past the bound, `WriteAheadTimeout`), then the commit; a
record that raises rolls it all back. So the count a create holds against `MAX_PROFILES`, the
profile an activation deactivates and the active flag a delete refuses cannot race another write
of the same owner. A replace locks the row `FOR UPDATE` and compares the version it is given, then
runs 21 Sec.3.8.5's guarded UPDATE (`AND version = :expected`); with none it is last-write-wins.
An activation deactivates the other profile before it activates its own, so `ux_hk_active` never
sees two, and changes neither `version` nor `updated_at`. A violation of `ux_hk_name` is
`HotkeyProfileNameTakenError`; any other refusal is the shared `query_failure`, which carries no
value (C-12.6). The profiles are read in creation order.
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.hotkey_profiles import (
    MAX_PROFILES,
    HotkeyActivationWriteAhead,
    HotkeyProfileActiveError,
    HotkeyProfileFields,
    HotkeyProfileLimitError,
    HotkeyProfileNameTakenError,
    HotkeyProfileNotFoundError,
    HotkeyProfileRow,
    HotkeyProfileStaleError,
    HotkeyProfileWriteAhead,
)
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

#: Every column, in table order; literal SQL only, so each statement repeats it (a test pins it).
COLUMNS: Final = "id, owner_user_id, name, is_active, bindings, version, created_at, updated_at"
_LOCK_OWNER = sa.text(
    "SELECT pg_advisory_xact_lock("
    "hashtextextended('cv.hotkey_profiles:' || CAST(:owner AS text), 0))"
)
_LIST = sa.text(
    "SELECT id, owner_user_id, name, is_active, bindings, version, created_at, updated_at "
    "FROM hotkey_profiles WHERE owner_user_id = CAST(:owner AS uuid) ORDER BY created_at, id"
)
_GET = sa.text(
    "SELECT id, owner_user_id, name, is_active, bindings, version, created_at, updated_at "
    "FROM hotkey_profiles WHERE id = CAST(:id AS uuid) AND owner_user_id = CAST(:owner AS uuid)"
)
_GET_ACTIVE = sa.text(
    "SELECT id, owner_user_id, name, is_active, bindings, version, created_at, updated_at "
    "FROM hotkey_profiles WHERE owner_user_id = CAST(:owner AS uuid) AND is_active"
)
_LOCK = sa.text(
    "SELECT id, owner_user_id, name, is_active, bindings, version, created_at, updated_at "
    "FROM hotkey_profiles WHERE id = CAST(:id AS uuid) AND owner_user_id = CAST(:owner AS uuid) "
    "FOR UPDATE"
)
_COUNT = sa.text("SELECT count(*) FROM hotkey_profiles WHERE owner_user_id = CAST(:owner AS uuid)")
_INSERT = sa.text(
    "INSERT INTO hotkey_profiles (id, owner_user_id, name, bindings) VALUES (CAST(:id AS uuid), "
    "CAST(:owner AS uuid), :name, CAST(:bindings AS jsonb)) "
    "RETURNING id, owner_user_id, name, is_active, bindings, version, created_at, updated_at"
)
#: A replace with no `If-Match`: last write wins.
_REPLACE = sa.text(
    "UPDATE hotkey_profiles SET name = :name, bindings = CAST(:bindings AS jsonb), "
    "version = version + 1, updated_at = now() "
    "WHERE id = CAST(:id AS uuid) AND owner_user_id = CAST(:owner AS uuid) "
    "RETURNING id, owner_user_id, name, is_active, bindings, version, created_at, updated_at"
)
#: 21 Sec.3.8.5's guarded replace: of two writers holding one version, exactly one wins.
_REPLACE_AT = sa.text(
    "UPDATE hotkey_profiles SET name = :name, bindings = CAST(:bindings AS jsonb), "
    "version = version + 1, updated_at = now() "
    "WHERE id = CAST(:id AS uuid) AND owner_user_id = CAST(:owner AS uuid) AND version = :expected "
    "RETURNING id, owner_user_id, name, is_active, bindings, version, created_at, updated_at"
)
#: The owner's other active profile, made inactive first; `version` and `updated_at` stay.
_DEACTIVATE = sa.text(
    "UPDATE hotkey_profiles SET is_active = false WHERE owner_user_id = CAST(:owner AS uuid) "
    "AND is_active AND id <> CAST(:id AS uuid) RETURNING id"
)
_ACTIVATE = sa.text(
    "UPDATE hotkey_profiles SET is_active = true "
    "WHERE id = CAST(:id AS uuid) AND owner_user_id = CAST(:owner AS uuid) "
    "RETURNING id, owner_user_id, name, is_active, bindings, version, created_at, updated_at"
)
_DELETE = sa.text(
    "DELETE FROM hotkey_profiles WHERE id = CAST(:id AS uuid) "
    "AND owner_user_id = CAST(:owner AS uuid) AND NOT is_active"
)
#: Whether another user holds the id: its existence alone, never a column (`UNSCOPED`).
_OTHER_OWNER = sa.text(
    "SELECT EXISTS (SELECT 1 FROM hotkey_profiles WHERE id = CAST(:id AS uuid) "
    "AND owner_user_id <> CAST(:owner AS uuid))"
)

#: Statements that read past the owner's own rows (see the module docstring); tested.
UNSCOPED: Final = frozenset({"_OTHER_OWNER"})


def _bindings(value: Any) -> dict[str, str]:
    """The stored object's string members (asyncpg answers `jsonb` as its text). `hk_bindings`
    holds it to an object, and only strings are bindings, so anything else is left out."""
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        return {}
    return {str(k): v for k, v in decoded.items() if isinstance(v, str)}


def _row(m: Any) -> HotkeyProfileRow:  # SQLAlchemy's RowMapping is Mapping[Any, Any]
    return HotkeyProfileRow(
        UUID(str(m["id"])), UUID(str(m["owner_user_id"])), m["name"], bool(m["is_active"]),
        _bindings(m["bindings"]), m["version"], m["created_at"], m["updated_at"],
    )  # fmt: skip


def _key(owner: UUID, profile_id: UUID) -> dict[str, str]:
    return {"id": str(profile_id), "owner": str(owner)}


def _values(owner: UUID, profile_id: UUID, fields: HotkeyProfileFields) -> dict[str, Any]:
    stored = json.dumps(fields.bindings, separators=(",", ":"), ensure_ascii=False)
    return _key(owner, profile_id) | {"name": fields.name, "bindings": stored}


def _refusal(state: str | None, name: str | None) -> Exception:
    """`ux_hk_name` (23505) is the name taken; anything else, the shared typed failure."""
    if state == "23505" and name == "ux_hk_name":
        return HotkeyProfileNameTakenError()
    return query_failure(state, name)


class SqlAlchemyHotkeyProfileStore:
    """`HotkeyProfileStore` over one relational repository (asyncpg)."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def _one(self, stmt: sa.TextClause, params: dict[str, str]) -> HotkeyProfileRow | None:
        async with self._relational.unit_of_work() as uow:
            found = (await uow.session.execute(stmt, params)).mappings().first()
        return None if found is None else _row(found)

    async def list_own(self, owner: UUID) -> list[HotkeyProfileRow]:
        async with self._relational.unit_of_work() as uow:
            found = await uow.session.execute(_LIST, {"owner": str(owner)})
            return [_row(m) for m in found.mappings()]

    async def get_own(self, owner: UUID, profile_id: UUID) -> HotkeyProfileRow | None:
        return await self._one(_GET, _key(owner, profile_id))

    async def get_active(self, owner: UUID) -> HotkeyProfileRow | None:
        return await self._one(_GET_ACTIVE, {"owner": str(owner)})

    async def exists_for_other_owner(self, owner: UUID, profile_id: UUID) -> bool:
        async with self._relational.unit_of_work() as uow:
            found = await uow.session.execute(_OTHER_OWNER, _key(owner, profile_id))
            return bool(found.scalar_one())

    async def create(
        self, owner: UUID, profile_id: UUID, fields: HotkeyProfileFields, *,
        write_ahead: HotkeyProfileWriteAhead,
    ) -> HotkeyProfileRow:  # fmt: skip
        try:
            async with self._relational.unit_of_work() as uow:
                session = uow.session
                await session.execute(_LOCK_OWNER, {"owner": str(owner)})
                held: int = (await session.execute(_COUNT, {"owner": str(owner)})).scalar_one()
                if held >= MAX_PROFILES:
                    raise HotkeyProfileLimitError
                found = await session.execute(_INSERT, _values(owner, profile_id, fields))
                after = _row(found.mappings().one())
                await bounded_write_ahead(write_ahead(None, after), WRITE_AHEAD_TIMEOUT_S)
                await uow.commit()
        except IntegrityError as exc:
            state, name = sqlstate_of(exc), constraint_of(exc)
            raise _refusal(state, name) from None
        return after

    async def replace(
        self, owner: UUID, profile_id: UUID, fields: HotkeyProfileFields, *,
        expected_version: int | None, write_ahead: HotkeyProfileWriteAhead,
    ) -> HotkeyProfileRow:  # fmt: skip
        try:
            async with self._relational.unit_of_work() as uow:
                session, key = uow.session, _key(owner, profile_id)
                await session.execute(_LOCK_OWNER, {"owner": str(owner)})
                held = (await session.execute(_LOCK, key)).mappings().first()
                if held is None:
                    raise HotkeyProfileNotFoundError
                before = _row(held)
                if expected_version is not None and expected_version != before.version:
                    raise HotkeyProfileStaleError(before.version)
                values = _values(owner, profile_id, fields)
                if expected_version is None:
                    found = (await session.execute(_REPLACE, values)).mappings().first()
                else:
                    values["expected"] = expected_version
                    found = (await session.execute(_REPLACE_AT, values)).mappings().first()
                if found is None:  # the version moved after all: never applied silently
                    raise HotkeyProfileStaleError(before.version)
                after = _row(found)
                await bounded_write_ahead(write_ahead(before, after), WRITE_AHEAD_TIMEOUT_S)
                await uow.commit()
        except IntegrityError as exc:
            state, name = sqlstate_of(exc), constraint_of(exc)
            raise _refusal(state, name) from None
        return after

    async def activate(
        self, owner: UUID, profile_id: UUID, *, write_ahead: HotkeyActivationWriteAhead
    ) -> HotkeyProfileRow:
        async with self._relational.unit_of_work() as uow:
            session, key = uow.session, _key(owner, profile_id)
            await session.execute(_LOCK_OWNER, {"owner": str(owner)})
            held = (await session.execute(_LOCK, key)).mappings().first()
            if held is None:
                raise HotkeyProfileNotFoundError
            before = _row(held)
            if before.is_active:  # already the active one: nothing changes, nothing is recorded
                return before
            gone = (await session.execute(_DEACTIVATE, key)).mappings().first()
            previous = None if gone is None else UUID(str(gone["id"]))
            after = _row((await session.execute(_ACTIVATE, key)).mappings().one())
            await bounded_write_ahead(write_ahead(before, after, previous), WRITE_AHEAD_TIMEOUT_S)
            await uow.commit()
        return after

    async def delete(
        self, owner: UUID, profile_id: UUID, *, write_ahead: HotkeyProfileWriteAhead
    ) -> HotkeyProfileRow:
        async with self._relational.unit_of_work() as uow:
            session, key = uow.session, _key(owner, profile_id)
            await session.execute(_LOCK_OWNER, {"owner": str(owner)})
            held = (await session.execute(_LOCK, key)).mappings().first()
            if held is None:
                raise HotkeyProfileNotFoundError
            before = _row(held)
            if before.is_active:
                raise HotkeyProfileActiveError
            await session.execute(_DELETE, key)
            await bounded_write_ahead(write_ahead(before, None), WRITE_AHEAD_TIMEOUT_S)
            await uow.commit()
        return before


__all__ = ["COLUMNS", "UNSCOPED", "SqlAlchemyHotkeyProfileStore"]

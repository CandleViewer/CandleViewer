"""Postgres scanner-presets repository (migration `0054_scanner_presets`, E08-T09 PR 2a, #4708).

Static, parameterised `sa.text` only. Every statement is owner-scoped
(`user_id = CAST(:owner AS uuid)`), and the INSERT binds the owner as a value. The one
`UNSCOPED` statement is `_IS_FOREIGN`: whether another user's row holds an id, nothing else.

The writes take the owner's advisory lock first (`_LOCK_OWNER`, the `indicator_presets_sqlalchemy`
pattern; the DELETE too), so the count held against `MAX_PRESETS` and the default being cleared
cannot race another writer of the same owner. In that transaction a write that sets `is_default`
reads the owner's other default, refuses with `conflict` unless it is the one, at the `version`,
the caller expected (the service audited that one ahead, 24 section 15.5), clears exactly that
row at that version (its `version` raised; no row cleared is `conflict` too) and then writes the
row. `ux_sp_name` maps to `name_taken`, `sp_filter_shape` to
`ScannerPresetShapeError`; `ux_sp_default`, which only a writer outside the lock can trip, is
retried once, then answered `conflict` (21 section 3.8.7). Every UPDATE raises `version` and moves
`updated_at` strictly forward, even inside one clock tick. A delete is a hard DELETE.
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    constraint_of,
    query_failure,
    sqlstate_of,
)
from candleviewer.storage.repositories.scanner_presets import (
    MAX_PRESETS,
    ExpectedDefault,
    ScannerPresetConflictError,
    ScannerPresetFields,
    ScannerPresetNotFoundError,
    ScannerPresetRow,
    ScannerPresetShapeError,
    ScannerPresetWrite,
)

#: The explicit read list. Literal SQL only, so every statement repeats it; a unit test pins each.
PRESET_COLUMNS = (
    "id::text AS id, user_id::text AS user_id, name, filter, sort, is_default, version, "
    "created_at, updated_at"
)

_LOCK_OWNER = sa.text(
    "SELECT pg_advisory_xact_lock("
    "hashtextextended('cv.scanner_presets:' || CAST(:owner AS text), 0))"
)
_LIST = sa.text(
    "SELECT id::text AS id, user_id::text AS user_id, name, filter, sort, is_default, version, "
    "created_at, updated_at FROM scanner_presets WHERE user_id = CAST(:owner AS uuid) "
    "ORDER BY lower(name), id"
)
_GET_OWN = sa.text(
    "SELECT id::text AS id, user_id::text AS user_id, name, filter, sort, is_default, version, "
    "created_at, updated_at FROM scanner_presets "
    "WHERE id = CAST(:id AS uuid) AND user_id = CAST(:owner AS uuid)"
)
_GET_DEFAULT = sa.text(
    "SELECT id::text AS id, user_id::text AS user_id, name, filter, sort, is_default, version, "
    "created_at, updated_at FROM scanner_presets "
    "WHERE user_id = CAST(:owner AS uuid) AND is_default"
)
_IS_FOREIGN = sa.text(
    "SELECT 1 FROM scanner_presets WHERE id = CAST(:id AS uuid) AND user_id <> CAST(:owner AS uuid)"
)
_OCCUPANCY = sa.text(
    "SELECT count(*) AS n, coalesce(bool_or(lower(name) = lower(CAST(:name AS text)) "
    "AND id IS DISTINCT FROM CAST(:exclude AS uuid)), false) AS taken "
    "FROM scanner_presets WHERE user_id = CAST(:owner AS uuid)"
)
_COUNT_OWN = sa.text("SELECT count(*) FROM scanner_presets WHERE user_id = CAST(:owner AS uuid)")
_OTHER_DEFAULT = sa.text(
    "SELECT id::text AS id, version FROM scanner_presets "
    "WHERE user_id = CAST(:owner AS uuid) AND is_default AND id IS DISTINCT FROM CAST(:id AS uuid)"
)
_CLEAR_DEFAULT = sa.text(
    "UPDATE scanner_presets SET is_default = false, version = version + 1, "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE user_id = CAST(:owner AS uuid) AND id = CAST(:expected AS uuid) "
    "AND version = CAST(:expected_version AS integer) AND is_default "
    "RETURNING id::text AS id, user_id::text AS user_id, name, filter, sort, is_default, "
    "version, created_at, updated_at"
)
_INSERT = sa.text(
    "INSERT INTO scanner_presets (id, user_id, name, filter, sort, is_default, version, "
    "created_at, updated_at) "
    "SELECT CAST(:id AS uuid), CAST(:owner AS uuid), :name, CAST(:filter AS jsonb), :sort, "
    ":is_default, 1, c.t, c.t FROM (SELECT clock_timestamp() AS t) c "
    "RETURNING id::text AS id, user_id::text AS user_id, name, filter, sort, is_default, "
    "version, created_at, updated_at"
)
_UPDATE = sa.text(
    "UPDATE scanner_presets SET name = :name, filter = CAST(:filter AS jsonb), sort = :sort, "
    "is_default = :is_default, version = version + 1, "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = CAST(:id AS uuid) AND user_id = CAST(:owner AS uuid) "
    "RETURNING id::text AS id, user_id::text AS user_id, name, filter, sort, is_default, "
    "version, created_at, updated_at"
)
_DELETE = sa.text(
    "DELETE FROM scanner_presets WHERE id = CAST(:id AS uuid) AND user_id = CAST(:owner AS uuid)"
)

#: Statements allowed to omit the owner filter (see the module docstring); tested.
UNSCOPED = frozenset({"_IS_FOREIGN"})
#: A racing default (`ux_sp_default`) is retried this many times before `conflict`.
_DEFAULT_RETRIES = 1


def _decode(value: Any) -> dict[str, Any]:
    return dict(json.loads(value)) if isinstance(value, str) else dict(value)


def _to_row(m: Any) -> ScannerPresetRow:  # private: SQLAlchemy RowMapping is Mapping[Any, Any]
    d = dict(m)
    d["filter"] = _decode(d["filter"])
    return ScannerPresetRow(**d)


def _params(preset_id: str, owner: str, fields: ScannerPresetFields) -> dict[str, Any]:
    flt = json.dumps(fields.filter, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return {"id": preset_id, "owner": owner, "name": fields.name, "filter": flt,
            "sort": fields.sort, "is_default": fields.is_default}  # fmt: skip


def _refusal(state: str | None, name: str | None) -> Exception:
    """The typed refusal of an integrity error other than a racing default."""
    if state == "23505" and name == "ux_sp_name":
        return ScannerPresetConflictError("name_taken")
    if state == "23514" and name == "sp_filter_shape":
        return ScannerPresetShapeError()
    return query_failure(state, name)


class SqlAlchemyScannerPresetRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def _rows(self, stmt: sa.TextClause, params: dict[str, Any]) -> list[ScannerPresetRow]:
        async with self._relational.unit_of_work() as uow:
            return [_to_row(r) for r in (await uow.session.execute(stmt, params)).mappings()]

    async def list_own(self, owner: str) -> list[ScannerPresetRow]:
        return await self._rows(_LIST, {"owner": owner})

    async def get_own(self, owner: str, preset_id: str) -> ScannerPresetRow | None:
        rows = await self._rows(_GET_OWN, {"id": preset_id, "owner": owner})
        return rows[0] if rows else None

    async def get_default(self, owner: str) -> ScannerPresetRow | None:
        rows = await self._rows(_GET_DEFAULT, {"owner": owner})
        return rows[0] if rows else None

    async def is_foreign(self, owner: str, preset_id: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_IS_FOREIGN, {"id": preset_id, "owner": owner})
            return res.scalar_one_or_none() is not None

    async def occupancy(
        self, owner: str, name: str | None = None, *, exclude_id: str | None = None
    ) -> tuple[int, bool]:
        params = {"owner": owner, "name": name, "exclude": exclude_id}
        async with self._relational.unit_of_work() as uow:
            got = (await uow.session.execute(_OCCUPANCY, params)).mappings().one()
        return int(got["n"]), bool(got["taken"])

    async def create(
        self,
        owner: str,
        preset_id: str,
        fields: ScannerPresetFields,
        *,
        expected_default: ExpectedDefault | None = None,
    ) -> ScannerPresetWrite:
        return await self._write(owner, preset_id, fields, expected_default, insert=True)

    async def update(
        self,
        owner: str,
        preset_id: str,
        fields: ScannerPresetFields,
        *,
        expected_default: ExpectedDefault | None = None,
    ) -> ScannerPresetWrite:
        return await self._write(owner, preset_id, fields, expected_default, insert=False)

    async def _write(
        self,
        owner: str,
        preset_id: str,
        fields: ScannerPresetFields,
        expected_default: ExpectedDefault | None,
        *,
        insert: bool,
    ) -> ScannerPresetWrite:
        """One transaction, retried once when a racing default trips `ux_sp_default`."""
        attempt = 0
        while True:
            try:
                return await self._write_once(owner, preset_id, fields, expected_default, insert)
            except IntegrityError as exc:
                state, name = sqlstate_of(exc), constraint_of(exc)
                if not (state == "23505" and name == "ux_sp_default"):
                    raise _refusal(state, name) from None
                if attempt >= _DEFAULT_RETRIES:
                    raise ScannerPresetConflictError("conflict") from None
                attempt += 1

    async def _write_once(
        self,
        owner: str,
        preset_id: str,
        fields: ScannerPresetFields,
        expected_default: ExpectedDefault | None,
        insert: bool,
    ) -> ScannerPresetWrite:
        async with self._relational.unit_of_work() as uow:
            session = uow.session
            await session.execute(_LOCK_OWNER, {"owner": owner})
            if insert:
                held: int = (await session.execute(_COUNT_OWN, {"owner": owner})).scalar_one()
                if held >= MAX_PRESETS:
                    raise ScannerPresetConflictError("limit_reached")
            cleared: ScannerPresetRow | None = None
            if fields.is_default:
                ids = {"owner": owner, "id": preset_id}
                other = (await session.execute(_OTHER_DEFAULT, ids)).mappings().first()
                current = None if other is None else ExpectedDefault(other["id"], other["version"])
                if current != expected_default:
                    raise ScannerPresetConflictError("conflict")
                if current is not None:
                    which = {"owner": owner, "expected": current.id,
                             "expected_version": current.version}  # fmt: skip
                    got_cleared = (await session.execute(_CLEAR_DEFAULT, which)).mappings().first()
                    if got_cleared is None:  # gone or changed since the read: never a 500
                        raise ScannerPresetConflictError("conflict")
                    cleared = _to_row(got_cleared)
            stmt = _INSERT if insert else _UPDATE
            got = (
                (await session.execute(stmt, _params(preset_id, owner, fields))).mappings().first()
            )
            if got is None:
                raise ScannerPresetNotFoundError(preset_id)
            await uow.commit()
        return ScannerPresetWrite(_to_row(got), cleared)

    async def delete(self, owner: str, preset_id: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_LOCK_OWNER, {"owner": owner})
            res = await uow.session.execute(_DELETE, {"id": preset_id, "owner": owner})
            await uow.commit()
        return bool(getattr(res, "rowcount", 0))


__all__ = ["PRESET_COLUMNS", "UNSCOPED", "SqlAlchemyScannerPresetRepository"]

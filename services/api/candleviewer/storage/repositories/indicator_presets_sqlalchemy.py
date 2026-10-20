"""Postgres indicator-presets repository (migration `0040_indicator_presets`, E13-T03, #427).

Static, parameterised `sa.text` only. Every statement is owner-scoped: reads
`(owner_user_id = CAST(:owner AS uuid) OR owner_user_id IS NULL)`, writes and the owner's own
reads `owner_user_id = CAST(:owner AS uuid) AND NOT is_builtin`, and the INSERT binds the owner
as a value with `is_builtin` false (E13 threat model IR-01, IR-02, SR-051). The two `UNSCOPED`
statements are `_OTHER_CLASS` (its purpose: a live built-in or another user's live preset holds
this id, and nothing else about the row) and `_COUNT_LIVE` (the gauge, all owners). Nothing
issues a DELETE: a soft delete sets `deleted_at`.

`create` and `import_many` take the owner's advisory lock first (`_LOCK_OWNER`, the
`workspaces_sqlalchemy` pattern), so the live count they hold against `MAX_LIVE_PRESETS` cannot
race another writer of the same owner (SR-E13-07). Uniqueness is decided by `ux_ip_name`, whose
violation maps to `PresetConflictError("name_taken")`; a CHECK violation on `ip_params_shape` or
`ip_style_shape` maps to `PresetShapeError`. Every UPDATE bumps `updated_at` strictly
monotonically, even inside one clock tick.

An import renames a held name rather than meet that index, so it compares the keys the index
compares: `lower()` in Postgres, of the stored names (`_NAMES_OWN`) and of each name it may give
(`_FOLD`, which reads no table). Python's `str.lower` folds some characters otherwise (U+0130 to
'i' plus U+0307, where Postgres under a libc collation gives 'i'), so no key is computed here.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from candleviewer.storage.repositories.indicator_presets import (
    MAX_IMPORT_PRESETS,
    MAX_LIVE_PRESETS,
    Occupancy,
    OtherClass,
    PresetConflictError,
    PresetFields,
    PresetNotFoundError,
    PresetRow,
    PresetShapeError,
    name_candidates,
)
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

#: Explicit read allow-list (`deleted_at` is never read). Literal SQL only, so every statement
#: repeats it; a unit test pins each copy.
PRESET_COLUMNS = (
    "id::text AS id, owner_user_id::text AS owner_user_id, indicator_code, name, params, style, "
    "pane_target, is_builtin, is_favourite, created_at, updated_at"
)

_LOCK_OWNER = sa.text(
    "SELECT pg_advisory_xact_lock("
    "hashtextextended('cv.indicator_presets:' || CAST(:owner AS text), 0))"
)
_LIST = sa.text(
    "SELECT id::text AS id, owner_user_id::text AS owner_user_id, indicator_code, name, params, "
    "style, pane_target, is_builtin, is_favourite, created_at, updated_at "
    "FROM indicator_presets WHERE deleted_at IS NULL "
    "AND (owner_user_id = CAST(:owner AS uuid) OR owner_user_id IS NULL) "
    "ORDER BY is_builtin DESC, indicator_code, lower(name), id"
)
_GET_OWN = sa.text(
    "SELECT id::text AS id, owner_user_id::text AS owner_user_id, indicator_code, name, params, "
    "style, pane_target, is_builtin, is_favourite, created_at, updated_at "
    "FROM indicator_presets WHERE id = CAST(:id AS uuid) "
    "AND owner_user_id = CAST(:owner AS uuid) AND NOT is_builtin AND deleted_at IS NULL"
)
_OTHER_CLASS = sa.text(
    "SELECT is_builtin FROM indicator_presets WHERE id = CAST(:id AS uuid) "
    "AND owner_user_id IS DISTINCT FROM CAST(:owner AS uuid) AND deleted_at IS NULL"
)
_OCCUPANCY = sa.text(
    "SELECT count(*) AS live, coalesce(bool_or(indicator_code = CAST(:code AS text) "
    "AND lower(name) = lower(CAST(:name AS text)) "
    "AND id IS DISTINCT FROM CAST(:exclude AS uuid)), false) AS taken "
    "FROM indicator_presets "
    "WHERE owner_user_id = CAST(:owner AS uuid) AND NOT is_builtin AND deleted_at IS NULL"
)
_COUNT_OWN = sa.text(
    "SELECT count(*) FROM indicator_presets "
    "WHERE owner_user_id = CAST(:owner AS uuid) AND NOT is_builtin AND deleted_at IS NULL"
)
_NAMES_OWN = sa.text(
    "SELECT indicator_code, lower(name) AS name_key FROM indicator_presets "
    "WHERE owner_user_id = CAST(:owner AS uuid) AND NOT is_builtin AND deleted_at IS NULL"
)
_FOLD = sa.text(
    "SELECT lower(n) AS name_key FROM unnest(CAST(:names AS text[])) "
    "WITH ORDINALITY AS c(n, i) ORDER BY i"
)
_INSERT = sa.text(
    "INSERT INTO indicator_presets (id, owner_user_id, indicator_code, name, params, style, "
    "pane_target, is_builtin, is_favourite, created_at, updated_at) "
    "SELECT CAST(:id AS uuid), CAST(:owner AS uuid), :indicator_code, :name, "
    "CAST(:params AS jsonb), CAST(:style AS jsonb), :pane_target, false, :is_favourite, c.t, c.t "
    "FROM (SELECT clock_timestamp() AS t) c RETURNING "
    "id::text AS id, owner_user_id::text AS owner_user_id, indicator_code, name, params, style, "
    "pane_target, is_builtin, is_favourite, created_at, updated_at"
)
_UPDATE = sa.text(
    "UPDATE indicator_presets SET name = :name, params = CAST(:params AS jsonb), "
    "style = CAST(:style AS jsonb), pane_target = :pane_target, is_favourite = :is_favourite, "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = CAST(:id AS uuid) AND owner_user_id = CAST(:owner AS uuid) "
    "AND NOT is_builtin AND deleted_at IS NULL RETURNING "
    "id::text AS id, owner_user_id::text AS owner_user_id, indicator_code, name, params, style, "
    "pane_target, is_builtin, is_favourite, created_at, updated_at"
)
_SOFT_DELETE = sa.text(
    "UPDATE indicator_presets SET deleted_at = clock_timestamp(), "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = CAST(:id AS uuid) AND owner_user_id = CAST(:owner AS uuid) "
    "AND NOT is_builtin AND deleted_at IS NULL"
)
_COUNT_LIVE = sa.text(
    "SELECT is_builtin, count(*) AS n FROM indicator_presets "
    "WHERE deleted_at IS NULL GROUP BY is_builtin"
)

#: Statements allowed to omit the owner filter (see the module docstring); tested.
UNSCOPED = frozenset({"_OTHER_CLASS", "_COUNT_LIVE"})
#: The constraint a mapped integrity error names -> what it means to the API.
_SHAPE_CHECKS = {"ip_params_shape": "params", "ip_style_shape": "style"}


def _json(value: dict[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _decode(value: Any) -> dict[str, Any]:
    return dict(json.loads(value)) if isinstance(value, str) else dict(value)


def _to_row(m: Any) -> PresetRow:  # private: SQLAlchemy RowMapping is Mapping[Any, Any]
    d = dict(m)
    d["params"], d["style"] = _decode(d["params"]), _decode(d["style"])
    return PresetRow(**d)


def _write_params(preset_id: str, owner: str, fields: PresetFields) -> dict[str, Any]:
    """The bound values of `_INSERT` (`_UPDATE` takes all but the code, which never changes)."""
    return {
        "id": preset_id,
        "owner": owner,
        "indicator_code": fields.indicator_code,
        "name": fields.name,
        "params": _json(fields.params),
        "style": _json(fields.style),
        "pane_target": fields.pane_target,
        "is_favourite": fields.is_favourite,
    }


def _sqlstate_and_constraint(exc: IntegrityError) -> tuple[str | None, str | None]:
    """asyncpg's wrapper carries `sqlstate`; the constraint name lives on it, its cause or the
    driver exception (`diag` for psycopg), as `workspaces_codec.map_integrity` reads them."""
    orig: Any = exc.orig
    state = getattr(orig, "sqlstate", None)
    for src in (orig, getattr(orig, "__cause__", None), getattr(orig, "driver_exception", None)):
        name = getattr(src, "constraint_name", None) or getattr(
            getattr(src, "diag", None), "constraint_name", None
        )
        if name:
            return state, str(name)
    return state, None


async def _fold(session: AsyncSession, names: list[str]) -> list[str]:
    """Postgres's own `lower()` of each of `names`, in order: the key `ux_ip_name` compares."""
    return [str(key) for (key,) in (await session.execute(_FOLD, {"names": names})).all()]


async def _free_name(session: AsyncSession, name: str, taken: set[str]) -> tuple[str, str]:
    """The first of `name_candidates(name, ...)` whose key `taken` lacks, with that key: `name`
    itself when it is free, else one of `len(taken) + 2` candidates, which always hold a free
    one (their keys are distinct but for `name` repeating one, and `taken` blocks at most
    `len(taken)` of them)."""
    (key,) = await _fold(session, [name])
    if key not in taken:
        return name, key
    candidates = name_candidates(name, len(taken) + 2)
    keys = await _fold(session, candidates)
    return next((c, k) for c, k in zip(candidates, keys, strict=True) if k not in taken)


def map_integrity(exc: IntegrityError) -> PresetConflictError | PresetShapeError | None:
    """unique_violation (23505) on `ux_ip_name` -> `name_taken`; check_violation (23514) on a
    JSON shape CHECK -> `PresetShapeError`; anything else -> None (a bug: the caller re-raises)."""
    state, name = _sqlstate_and_constraint(exc)
    if state == "23505" and name == "ux_ip_name":
        return PresetConflictError("name_taken")
    if state == "23514" and name in _SHAPE_CHECKS:
        return PresetShapeError("params" if name == "ip_params_shape" else "style")
    return None


class SqlAlchemyIndicatorPresetRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def list_visible(self, owner: str) -> list[PresetRow]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_LIST, {"owner": owner})).mappings()
            return [_to_row(r) for r in rows]

    async def get_own(self, owner: str, preset_id: str) -> PresetRow | None:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_GET_OWN, {"id": preset_id, "owner": owner})
            row = res.mappings().first()
        return None if row is None else _to_row(row)

    async def other_class(self, owner: str, preset_id: str) -> OtherClass | None:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_OTHER_CLASS, {"id": preset_id, "owner": owner})
            builtin = res.scalar_one_or_none()
        if builtin is None:
            return None
        return "builtin" if builtin else "foreign"

    async def occupancy(
        self, owner: str, name_key: tuple[str, str] | None = None, *, exclude_id: str | None = None
    ) -> Occupancy:
        code, name = (None, None) if name_key is None else name_key
        params = {"owner": owner, "code": code, "name": name, "exclude": exclude_id}
        async with self._relational.unit_of_work() as uow:
            got = (await uow.session.execute(_OCCUPANCY, params)).mappings().one()
        return Occupancy(int(got["live"]), bool(got["taken"]))

    async def create(self, owner: str, preset_id: str, fields: PresetFields) -> PresetRow:
        params = _write_params(preset_id, owner, fields)
        try:
            async with self._relational.unit_of_work() as uow:
                await uow.session.execute(_LOCK_OWNER, {"owner": owner})
                live: int = (await uow.session.execute(_COUNT_OWN, {"owner": owner})).scalar_one()
                if live >= MAX_LIVE_PRESETS:
                    raise PresetConflictError("limit_reached")
                row = (await uow.session.execute(_INSERT, params)).mappings().one()
                await uow.commit()
        except IntegrityError as exc:
            raise map_integrity(exc) or exc from exc
        return _to_row(row)

    async def update(self, owner: str, preset_id: str, fields: PresetFields) -> PresetRow:
        params = _write_params(preset_id, owner, fields)
        del params["indicator_code"]  # immutable: never written by an UPDATE
        try:
            async with self._relational.unit_of_work() as uow:
                row = (await uow.session.execute(_UPDATE, params)).mappings().first()
                if row is None:
                    raise PresetNotFoundError(preset_id)
                await uow.commit()
        except IntegrityError as exc:
            raise map_integrity(exc) or exc from exc
        return _to_row(row)

    async def soft_delete(self, owner: str, preset_id: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_SOFT_DELETE, {"id": preset_id, "owner": owner})
            await uow.commit()
        return bool(getattr(res, "rowcount", 0))

    async def import_many(
        self, owner: str, items: Sequence[tuple[str, PresetFields]]
    ) -> list[PresetRow]:
        if len(items) > MAX_IMPORT_PRESETS:
            raise ValueError(f"an import carries at most {MAX_IMPORT_PRESETS} presets")
        if not items:
            return []
        rows: list[Any] = []
        try:
            async with self._relational.unit_of_work() as uow:
                await uow.session.execute(_LOCK_OWNER, {"owner": owner})
                live: int = (await uow.session.execute(_COUNT_OWN, {"owner": owner})).scalar_one()
                if live + len(items) > MAX_LIVE_PRESETS:
                    raise PresetConflictError("limit_reached")
                taken: dict[str, set[str]] = {}
                for code, held in (await uow.session.execute(_NAMES_OWN, {"owner": owner})).all():
                    taken.setdefault(str(code), set()).add(str(held))
                for preset_id, fields in items:
                    keys = taken.setdefault(fields.indicator_code, set())
                    free, key = await _free_name(uow.session, fields.name, keys)
                    keys.add(key)
                    named = dataclasses.replace(fields, name=free)
                    params = _write_params(preset_id, owner, named)
                    rows.append((await uow.session.execute(_INSERT, params)).mappings().one())
                await uow.commit()
        except IntegrityError as exc:
            raise map_integrity(exc) or exc from exc
        return [_to_row(r) for r in rows]

    async def count_live_by_builtin(self) -> dict[bool, int]:
        """Live presets of all owners by `is_builtin` (metrics only; owner-agnostic)."""
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_COUNT_LIVE)).all()
        return {bool(builtin): int(n) for builtin, n in rows}


__all__ = [
    "PRESET_COLUMNS", "UNSCOPED", "SqlAlchemyIndicatorPresetRepository", "map_integrity",
]  # fmt: skip

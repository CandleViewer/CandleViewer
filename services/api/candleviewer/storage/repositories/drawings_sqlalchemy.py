"""Postgres drawings repository (migration `0021_drawings`, E14-T01).

Static, parameterised `sa.text` only. Every statement is filtered by
`owner_user_id = CAST(:owner AS uuid)` (C-12.4 data-layer re-check) except three:
`exists_for_other_owner` (its whole purpose), the batch snapshot (it must see foreign and
deleted rows to answer `id_unavailable` identically for all of them) and `purge_deleted`
(retention job, no caller identity). Every UPDATE bumps `updated_at` strictly
monotonically so the token never repeats, even inside one clock tick.

Batch failure rules (`BatchOpFailed.rule`): `target_unavailable`, `version_conflict`,
`id_unavailable` and `immutable_field` (an update changing `symbol` or `tool`; checked against
the row locked by the snapshot, so it is race-free).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any, assert_never

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.drawings import (
    BatchOp,
    BatchOpFailed,
    BatchResult,
    CreateOp,
    DeleteOp,
    DrawingFields,
    DrawingIdUnavailableError,
    DrawingNotFoundError,
    DrawingRow,
    DrawingVersionConflictError,
    UpdateOp,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: Explicit read allow-list; internal columns (anchors, deleted_at, alert_id) stay out.
DRAWING_COLUMNS = (
    "id::text AS id, owner_user_id::text AS owner_user_id, symbol, layout_id::text AS layout_id, "
    "tool, geometry, style, label, locked, visible, z_index, created_at, updated_at"
)
# Literal SQL only (no interpolation), repeating the column list like `alerts_sqlalchemy.py`;
# a unit test pins every copy to DRAWING_COLUMNS.
_INSERT = sa.text(
    "INSERT INTO drawings (id, owner_user_id, symbol, layout_id, tool, geometry, style, label, "
    "locked, visible, z_index, anchor_start, anchor_end) VALUES (CAST(:id AS uuid), "
    "CAST(:owner AS uuid), :symbol, CAST(:layout AS uuid), :tool, CAST(:geometry AS jsonb), "
    "CAST(:style AS jsonb), :label, :locked, :visible, :z_index, :anchor_start, :anchor_end) "
    "RETURNING "
    "id::text AS id, owner_user_id::text AS owner_user_id, symbol, layout_id::text AS layout_id, "
    "tool, geometry, style, label, locked, visible, z_index, created_at, updated_at"
)
_GET = sa.text(
    "SELECT "
    "id::text AS id, owner_user_id::text AS owner_user_id, symbol, layout_id::text AS layout_id, "
    "tool, geometry, style, label, locked, visible, z_index, created_at, updated_at"
    " FROM drawings WHERE id = CAST(:id AS uuid) "
    "AND owner_user_id = CAST(:owner AS uuid) AND deleted_at IS NULL"
)
_EXISTS_OTHER = sa.text(
    "SELECT 1 FROM drawings WHERE id = CAST(:id AS uuid) "
    "AND owner_user_id <> CAST(:owner AS uuid) AND deleted_at IS NULL"
)
# Query-28 shape: owner + symbol equality (ix_dr_user_symbol), keyset on id.
_LIST = sa.text(
    "SELECT "
    "id::text AS id, owner_user_id::text AS owner_user_id, symbol, layout_id::text AS layout_id, "
    "tool, geometry, style, label, locked, visible, z_index, created_at, updated_at"
    " FROM drawings WHERE owner_user_id = CAST(:owner AS uuid) AND symbol = :symbol "
    "AND deleted_at IS NULL "
    "AND (CAST(:layout AS uuid) IS NULL OR layout_id = CAST(:layout AS uuid)) "
    "AND (CAST(:after_id AS uuid) IS NULL OR id > CAST(:after_id AS uuid)) "
    "ORDER BY id LIMIT :limit"
)
_UPDATE = sa.text(
    "UPDATE drawings SET "
    "symbol = :symbol, layout_id = CAST(:layout AS uuid), tool = :tool, "
    "geometry = CAST(:geometry AS jsonb), style = CAST(:style AS jsonb), label = :label, "
    "locked = :locked, visible = :visible, z_index = :z_index, "
    "anchor_start = :anchor_start, anchor_end = :anchor_end, "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = CAST(:id AS uuid) AND owner_user_id = CAST(:owner AS uuid) "
    "AND deleted_at IS NULL "
    "AND (CAST(:if_match AS timestamptz) IS NULL OR updated_at = CAST(:if_match AS timestamptz)) "
    "RETURNING "
    "id::text AS id, owner_user_id::text AS owner_user_id, symbol, layout_id::text AS layout_id, "
    "tool, geometry, style, label, locked, visible, z_index, created_at, updated_at"
)
_SOFT_DELETE = sa.text(
    "UPDATE drawings SET deleted_at = now(), "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = CAST(:id AS uuid) AND owner_user_id = CAST(:owner AS uuid) "
    "AND deleted_at IS NULL"
)
_SNAPSHOT = sa.text(
    "SELECT id::text AS id, owner_user_id::text AS owner_user_id, symbol, tool, deleted_at, "
    "updated_at "
    "FROM drawings WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY id FOR UPDATE"
)
_PURGE = sa.text(
    "DELETE FROM drawings WHERE id IN (SELECT id FROM drawings WHERE deleted_at IS NOT NULL "
    "AND deleted_at < now() - make_interval(days => CAST(:days AS integer)) LIMIT :limit)"
)

#: Statements allowed to omit the owner filter (see module docstring); tested.
UNSCOPED = frozenset({"_EXISTS_OTHER", "_SNAPSHOT", "_PURGE"})

#: Upper bound for one purge call so a single transaction stays short.
MAX_PURGE_BATCH = 10_000


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decode(value: Any) -> dict[str, Any]:
    return dict(json.loads(value)) if isinstance(value, str) else dict(value)


def _to_row(m: Any) -> DrawingRow:  # private: SQLAlchemy RowMapping is Mapping[Any, Any]
    d = dict(m)
    d["geometry"] = _decode(d["geometry"])
    d["style"] = _decode(d["style"])
    return DrawingRow(**d)


def _params(fields: DrawingFields) -> dict[str, Any]:
    return {
        "symbol": fields.symbol,
        "layout": fields.layout_id,
        "tool": fields.tool,
        "geometry": _json(fields.geometry),
        "style": _json(fields.style),
        "label": fields.label,
        "locked": fields.locked,
        "visible": fields.visible,
        "z_index": fields.z_index,
        "anchor_start": fields.anchor_start,
        "anchor_end": fields.anchor_end,
    }


def _is_pk_collision(exc: IntegrityError) -> bool:
    """unique_violation (SQLSTATE 23505) on the primary key, not message text.

    asyncpg's wrapper exposes `sqlstate` but the constraint name lives on the driver
    exception (`__cause__`, or `diag` for psycopg); look in all of those places.
    """
    orig: Any = exc.orig
    if getattr(orig, "sqlstate", None) != "23505":
        return False
    for src in (orig, getattr(orig, "__cause__", None), getattr(orig, "driver_exception", None)):
        name = getattr(src, "constraint_name", None) or getattr(
            getattr(src, "diag", None), "constraint_name", None
        )
        if name:
            return bool(name == "drawings_pkey")
    return False


class SqlAlchemyDrawingRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def list_page(
        self,
        owner: str,
        *,
        symbol: str,
        layout_id: str | None,
        after_id: str | None,
        limit: int,
    ) -> list[DrawingRow]:
        params = {
            "owner": owner,
            "symbol": symbol,
            "layout": layout_id,
            "after_id": after_id,
            "limit": limit,
        }
        async with self._relational.unit_of_work() as uow:
            return [_to_row(r) for r in (await uow.session.execute(_LIST, params)).mappings()]

    async def get(self, owner: str, drawing_id: str) -> DrawingRow | None:
        async with self._relational.unit_of_work() as uow:
            row = (
                (await uow.session.execute(_GET, {"id": drawing_id, "owner": owner}))
                .mappings()
                .first()
            )
        return None if row is None else _to_row(row)

    async def exists_for_other_owner(self, owner: str, drawing_id: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_EXISTS_OTHER, {"id": drawing_id, "owner": owner})
            return res.first() is not None

    async def create(self, owner: str, drawing_id: str, fields: DrawingFields) -> DrawingRow:
        params = {"id": drawing_id, "owner": owner, **_params(fields)}
        try:
            async with self._relational.unit_of_work() as uow:
                row = (await uow.session.execute(_INSERT, params)).mappings().one()
                await uow.commit()
        except IntegrityError as exc:
            if _is_pk_collision(exc):
                raise DrawingIdUnavailableError(drawing_id) from exc
            raise
        return _to_row(row)

    async def update(
        self,
        owner: str,
        drawing_id: str,
        fields: DrawingFields,
        *,
        if_match: datetime | None,
    ) -> DrawingRow:
        params = {"id": drawing_id, "owner": owner, "if_match": if_match, **_params(fields)}
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_UPDATE, params)).mappings().first()
            if row is None:
                # Same unit of work: tell a stale token from an unavailable row. A foreign
                # or deleted row stays NotFound, so no existence oracle.
                live = await uow.session.execute(_GET, {"id": drawing_id, "owner": owner})
                if live.first() is not None:
                    raise DrawingVersionConflictError(drawing_id)
                raise DrawingNotFoundError(drawing_id)
            await uow.commit()
        return _to_row(row)

    async def soft_delete(self, owner: str, drawing_id: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_SOFT_DELETE, {"id": drawing_id, "owner": owner})
            await uow.commit()
        return bool(getattr(res, "rowcount", 0))

    async def apply_batch(self, owner: str, ops: Sequence[BatchOp]) -> BatchResult:
        created: list[DrawingRow] = []
        updated: list[DrawingRow] = []
        deleted: list[str] = []
        async with self._relational.unit_of_work() as uow:
            ids = [op.id for op in ops]
            snap = {
                r["id"]: r for r in (await uow.session.execute(_SNAPSHOT, {"ids": ids})).mappings()
            }
            for i, op in enumerate(ops):
                existing = snap.get(op.id)
                if isinstance(op, CreateOp):
                    if existing is not None:
                        raise BatchOpFailed(i, "id_unavailable")
                    params = {"id": op.id, "owner": owner, **_params(op.fields)}
                    try:
                        async with uow.session.begin_nested():
                            row = (await uow.session.execute(_INSERT, params)).mappings().one()
                    except IntegrityError as exc:
                        if _is_pk_collision(exc):
                            raise BatchOpFailed(i, "id_unavailable") from exc
                        raise
                    created.append(_to_row(row))
                    continue
                if existing is None or existing["owner_user_id"] != owner or existing["deleted_at"]:
                    raise BatchOpFailed(i, "target_unavailable")
                if existing["updated_at"] != op.if_match:
                    raise BatchOpFailed(i, "version_conflict")
                if isinstance(op, UpdateOp):
                    if op.fields.symbol != existing["symbol"] or op.fields.tool != existing["tool"]:
                        raise BatchOpFailed(i, "immutable_field")
                    params = {
                        "id": op.id,
                        "owner": owner,
                        "if_match": op.if_match,
                        **_params(op.fields),
                    }
                    got = (await uow.session.execute(_UPDATE, params)).mappings().all()
                    if len(got) != 1:  # fail closed: the locked row must be updated exactly once
                        raise BatchOpFailed(i, "target_unavailable")
                    updated.append(_to_row(got[0]))
                elif isinstance(op, DeleteOp):
                    res = await uow.session.execute(_SOFT_DELETE, {"id": op.id, "owner": owner})
                    if getattr(res, "rowcount", 0) != 1:  # fail closed
                        raise BatchOpFailed(i, "target_unavailable")
                    deleted.append(op.id)
                else:
                    assert_never(op)
            await uow.commit()
        return BatchResult(tuple(created), tuple(updated), tuple(deleted))

    async def purge_deleted(self, older_than_days: int, limit: int) -> int:
        if older_than_days < 1 or not 1 <= limit <= MAX_PURGE_BATCH:
            raise ValueError("purge needs older_than_days >= 1 and 1 <= limit <= MAX_PURGE_BATCH")
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_PURGE, {"days": older_than_days, "limit": limit})
            await uow.commit()
        return int(getattr(res, "rowcount", 0))


__all__ = ["DRAWING_COLUMNS", "MAX_PURGE_BATCH", "SqlAlchemyDrawingRepository"]

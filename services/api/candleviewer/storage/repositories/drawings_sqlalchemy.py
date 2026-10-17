"""Postgres drawings repository (migration `0021_drawings`, E14-T01).

Static, parameterised `sa.text` only. Every statement is filtered by
`owner_user_id = CAST(:owner AS uuid)` (C-12.4 data-layer re-check) except three:
`exists_for_other_owner` (its whole purpose), `purge_deleted` (retention job, no caller identity)
and `count_live_by_tool` (the rows gauge, all owners). Every UPDATE bumps `updated_at` strictly
monotonically so the token never repeats, even inside one clock tick.

The batch snapshot is owner-scoped too, so it locks and sees only the caller's own rows (live or
soft-deleted): a batch naming a foreign id never takes a lock on, or waits for, another user's row.
A create on a foreign id misses the snapshot and is refused by its INSERT's primary-key collision,
the same `id_unavailable` as for the caller's own rows.

Batch failure rules (`BatchOpFailed.rule`): `target_unavailable` (the caller's own soft-deleted
row, or an UPDATE/DELETE that unexpectedly touched no row), `target_not_owned` (an update/delete
target absent from the snapshot: another owner's or missing; internal, the API audits it and
answers it as `target_unavailable`), `version_conflict`, `id_unavailable` and `immutable_field`
(an update changing `symbol` or `tool`; checked against the row locked by the snapshot, so it is
race-free).

Layout ownership (E15-T01 spec Sec.7, D27): a write naming layouts first share-locks the caller's
live ones (`_LAYOUTS_SHARE`), before any drawings row is touched, as the layout soft deletes
lock layouts before drawings. A concurrent soft delete then either waits and cascades to the
new rows, or this write waits and finds the layout gone (`DrawingLayoutNotFoundError`, 422).
0022's composite FK is the backstop and maps to the same error. A deadlock (`40P01`) reruns the
whole transaction once; a second one is `StorageTierUnavailable` (503), never a 500.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, TypeVar, assert_never

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.drawings import (
    BatchOp,
    BatchOpFailed,
    BatchResult,
    CreateOp,
    DeleteOp,
    DrawingFields,
    DrawingIdUnavailableError,
    DrawingLayoutNotFoundError,
    DrawingNotFoundError,
    DrawingRow,
    DrawingVersionConflictError,
    UpdateOp,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    SqlAlchemyUnitOfWork,
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
# Set-based batch statements (one round trip per op kind). The rows travel as ONE jsonb array
# bound as text; `jsonb_to_recordset` types every column, so nothing is interpolated. The
# recordset columns are `n_`-prefixed so RETURNING's bare column names stay unambiguous.
_INSERT_MANY = sa.text(
    "INSERT INTO drawings (id, owner_user_id, symbol, layout_id, tool, geometry, style, label, "
    "locked, visible, z_index, anchor_start, anchor_end) "
    "SELECT n_id, CAST(:owner AS uuid), n_symbol, n_layout, n_tool, n_geometry, n_style, n_label, "
    "n_locked, n_visible, n_z_index, n_anchor_start, n_anchor_end "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(n_id uuid, n_symbol text, "
    "n_layout uuid, n_tool text, n_geometry jsonb, n_style jsonb, n_label text, n_locked boolean, "
    "n_visible boolean, n_z_index integer, n_anchor_start timestamptz, "
    "n_anchor_end timestamptz) "
    "ON CONFLICT (id) DO NOTHING RETURNING "
    "id::text AS id, owner_user_id::text AS owner_user_id, symbol, layout_id::text AS layout_id, "
    "tool, geometry, style, label, locked, visible, z_index, created_at, updated_at"
)
_UPDATE_MANY = sa.text(
    "UPDATE drawings SET "
    "layout_id = r.n_layout, geometry = r.n_geometry, "
    "style = r.n_style, label = r.n_label, locked = r.n_locked, visible = r.n_visible, "
    "z_index = r.n_z_index, anchor_start = r.n_anchor_start, anchor_end = r.n_anchor_end, "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS r(n_id uuid, n_if_match timestamptz, "
    "n_layout uuid, n_geometry jsonb, n_style jsonb, n_label text, "
    "n_locked boolean, n_visible boolean, n_z_index integer, n_anchor_start timestamptz, "
    "n_anchor_end timestamptz) "
    "WHERE drawings.id = ANY(CAST(:ids AS uuid[])) AND drawings.id = r.n_id "
    "AND drawings.owner_user_id = CAST(:owner AS uuid) "
    "AND drawings.deleted_at IS NULL AND drawings.updated_at = r.n_if_match "
    "RETURNING "
    "id::text AS id, owner_user_id::text AS owner_user_id, symbol, layout_id::text AS layout_id, "
    "tool, geometry, style, label, locked, visible, z_index, created_at, updated_at"
)
_SOFT_DELETE_MANY = sa.text(
    "UPDATE drawings SET deleted_at = now(), "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = ANY(CAST(:ids AS uuid[])) AND owner_user_id = CAST(:owner AS uuid) "
    "AND deleted_at IS NULL RETURNING id::text AS id"
)
_SNAPSHOT = sa.text(
    "SELECT id::text AS id, symbol, tool, deleted_at, updated_at "
    "FROM drawings WHERE id = ANY(CAST(:ids AS uuid[])) AND owner_user_id = CAST(:owner AS uuid) "
    "ORDER BY id FOR UPDATE"
)
# Spec Sec.7: the caller's live layouts among `:ids`, share-locked in id order (blocks a
# concurrent soft delete's row lock until this write commits).
_LAYOUTS_SHARE = sa.text(
    "SELECT id::text AS id FROM layouts WHERE id = ANY(CAST(:ids AS uuid[])) "
    "AND owner_user_id = CAST(:owner AS uuid) AND deleted_at IS NULL ORDER BY id FOR SHARE"
)
_PURGE = sa.text(
    "DELETE FROM drawings WHERE id IN (SELECT id FROM drawings WHERE deleted_at IS NOT NULL "
    "AND deleted_at < now() - make_interval(days => CAST(:days AS integer)) LIMIT :limit)"
)
_COUNT_LIVE = sa.text(
    "SELECT tool, count(*) AS n FROM drawings WHERE deleted_at IS NULL GROUP BY tool"
)

#: Statements allowed to omit the owner filter (see module docstring); tested.
UNSCOPED = frozenset({"_EXISTS_OTHER", "_PURGE", "_COUNT_LIVE"})

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


#: Storage-side cap on one batch; a test pins it equal to the API's `MAX_BATCH_OPS`
#: (storage must not import `api`).
MAX_BATCH_OPS_STORAGE = 200


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _row_json(
    op_id: str, fields: DrawingFields, if_match: datetime | None = None
) -> dict[str, Any]:
    # `jsonb_to_recordset` would coerce "yes" -> true or "7" -> 7, so `locked`, `visible`,
    # `z_index`, `label`, `symbol` and `tool` are refused here instead (SR-040). Not checked:
    # `layout_id` (a mistyped value fails the uuid cast), `geometry` (CHECK `dr_geom`) and
    # `style` (jsonb with no CHECK: stored as given, so it relies on the API building a dict).
    if not (
        isinstance(fields.locked, bool)
        and isinstance(fields.visible, bool)
        and isinstance(fields.z_index, int)
        and not isinstance(fields.z_index, bool)
        and (fields.label is None or isinstance(fields.label, str))
        and isinstance(fields.symbol, str)
        and isinstance(fields.tool, str)
    ):
        raise TypeError("DrawingFields has a mistyped value")
    row: dict[str, Any] = {
        "n_id": op_id,
        "n_symbol": fields.symbol,
        "n_layout": fields.layout_id,
        "n_tool": fields.tool,
        "n_geometry": fields.geometry,
        "n_style": fields.style,
        "n_label": fields.label,
        "n_locked": fields.locked,
        "n_visible": fields.visible,
        "n_z_index": fields.z_index,
        "n_anchor_start": _iso(fields.anchor_start),
        "n_anchor_end": _iso(fields.anchor_end),
    }
    if if_match is not None:
        row["n_if_match"] = _iso(if_match)
    return row


def _rows_param(rows: list[dict[str, Any]]) -> str:
    return json.dumps(
        rows, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    )


def _first_failure(
    ops: Sequence[BatchOp], snap: Mapping[str, Mapping[str, Any]]
) -> tuple[int, str] | None:
    """First `(index, rule)` a batch hits against the locked snapshot, in operation order.

    `snap` holds only the caller's own rows, live or soft-deleted (`_SNAPSHOT` is owner-scoped),
    so an update/delete target absent from it is another owner's or missing: `target_not_owned`,
    which nothing tells apart. The caller's own soft-deleted row is `target_unavailable`.

    Pure: the per-op rules the repository always applied, plus the write-time outcomes the old
    one-statement-per-op loop produced when an id repeats (the bulk statements would otherwise
    let those succeed): a second create collides with the first insert; an update after an
    update or delete, or a delete after a delete, finds a bumped token or a deleted row and is
    `target_unavailable`. An update followed by a delete of the same id still succeeds.
    """
    created: set[str] = set()
    bumped: set[str] = set()  # updated earlier in this batch (token moved on)
    deleted: set[str] = set()  # soft-deleted earlier in this batch
    for i, op in enumerate(ops):
        existing = snap.get(op.id)
        if isinstance(op, CreateOp):
            if existing is not None or op.id in created:
                return i, "id_unavailable"
            created.add(op.id)
            continue
        if existing is None:  # another owner's row or none at all: told apart by nothing
            return i, "target_not_owned"
        if existing["deleted_at"]:
            return i, "target_unavailable"
        if existing["updated_at"] != op.if_match:
            return i, "version_conflict"
        if isinstance(op, UpdateOp):
            if op.fields.symbol != existing["symbol"] or op.fields.tool != existing["tool"]:
                return i, "immutable_field"
            if op.id in bumped or op.id in deleted:
                return i, "target_unavailable"
            bumped.add(op.id)
        elif isinstance(op, DeleteOp):
            if op.id in deleted:
                return i, "target_unavailable"
            deleted.add(op.id)
        else:
            assert_never(op)
    return None


def _constraint_name(exc: IntegrityError) -> str | None:
    """asyncpg's wrapper exposes `sqlstate` but the constraint name lives on the driver
    exception (`__cause__`, or `diag` for psycopg); look in all of those places."""
    orig: Any = exc.orig
    for src in (orig, getattr(orig, "__cause__", None), getattr(orig, "driver_exception", None)):
        name = getattr(src, "constraint_name", None) or getattr(
            getattr(src, "diag", None), "constraint_name", None
        )
        if name:
            return str(name)
    return None


def _is_pk_collision(exc: IntegrityError) -> bool:
    """unique_violation (SQLSTATE 23505) on the primary key, not message text."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    return sqlstate == "23505" and _constraint_name(exc) == "drawings_pkey"


#: 0022's composite FK (D27); it fires only if the in-transaction layout check were bypassed.
LAYOUT_FK = "fk_drawings_layout_id_layouts"


def _is_layout_fk(exc: IntegrityError) -> bool:
    """foreign_key_violation (SQLSTATE 23503) on `LAYOUT_FK`, not message text."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    return sqlstate == "23503" and _constraint_name(exc) == LAYOUT_FK


def _is_deadlock(exc: DBAPIError) -> bool:
    """deadlock_detected (SQLSTATE 40P01) on the driver error or its cause."""
    orig: Any = exc.orig
    sources = (orig, getattr(orig, "__cause__", None))
    return any(getattr(src, "sqlstate", None) == "40P01" for src in sources)


_T = TypeVar("_T")  # not PEP 695 `[T]`: Semgrep 1.99.0 (CI) would skip the rest of this file


async def _deadlock_retry(run: Callable[[], Awaitable[_T]]) -> _T:  # noqa: UP047 (see _T)
    """Run one whole transaction; after a `40P01` (rolled back by the unit of work's exit) run
    it once more. A second deadlock is a store outage (503, retryable), never a 500."""
    try:
        return await run()
    except DBAPIError as exc:
        if not _is_deadlock(exc):
            raise
    try:
        return await run()
    except DBAPIError as exc:
        if not _is_deadlock(exc):
            raise
        raise StorageTierUnavailable("drawings write deadlocked twice") from exc


async def _lock_live_layouts(
    uow: SqlAlchemyUnitOfWork, owner: str, refs: Sequence[tuple[str, str | None]]
) -> None:
    """Share-lock the caller's live layouts named by `refs` (request field, layout id); any id
    missing (unknown, another owner's or deleted: identical) refuses the whole write."""
    ids = sorted({lid for _, lid in refs if lid is not None})
    if not ids:
        return
    got = await uow.session.execute(_LAYOUTS_SHARE, {"ids": ids, "owner": owner})
    live = {str(row[0]) for row in got.all()}
    missing = tuple(field for field, lid in refs if lid is not None and lid not in live)
    if missing:
        raise DrawingLayoutNotFoundError(missing)


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

        async def attempt() -> DrawingRow:
            async with self._relational.unit_of_work() as uow:
                await _lock_live_layouts(uow, owner, [("layout_id", fields.layout_id)])
                row = (await uow.session.execute(_INSERT, params)).mappings().one()
                await uow.commit()
            return _to_row(row)

        try:
            return await _deadlock_retry(attempt)
        except IntegrityError as exc:
            if _is_pk_collision(exc):
                raise DrawingIdUnavailableError(drawing_id) from exc
            if _is_layout_fk(exc):
                raise DrawingLayoutNotFoundError(("layout_id",)) from exc
            raise

    async def update(
        self,
        owner: str,
        drawing_id: str,
        fields: DrawingFields,
        *,
        if_match: datetime | None,
    ) -> DrawingRow:
        params = {"id": drawing_id, "owner": owner, "if_match": if_match, **_params(fields)}

        async def attempt() -> DrawingRow:
            async with self._relational.unit_of_work() as uow:
                await _lock_live_layouts(uow, owner, [("layout_id", fields.layout_id)])
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

        try:
            return await _deadlock_retry(attempt)
        except IntegrityError as exc:
            if _is_layout_fk(exc):
                raise DrawingLayoutNotFoundError(("layout_id",)) from exc
            raise

    async def soft_delete(self, owner: str, drawing_id: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_SOFT_DELETE, {"id": drawing_id, "owner": owner})
            await uow.commit()
        return bool(getattr(res, "rowcount", 0))

    async def apply_batch(self, owner: str, ops: Sequence[BatchOp]) -> BatchResult:
        """Apply `ops` atomically: the layout share-lock, the snapshot and one statement per op
        kind; a deadlock reruns the whole transaction once."""
        if len(ops) > MAX_BATCH_OPS_STORAGE:
            raise ValueError(f"a batch carries at most {MAX_BATCH_OPS_STORAGE} operations")
        refs = [
            (f"operations.{i}.drawing.layout_id", op.fields.layout_id)
            for i, op in enumerate(ops)
            if not isinstance(op, DeleteOp)
        ]
        try:
            return await _deadlock_retry(lambda: self._apply_batch_once(owner, ops, refs))
        except IntegrityError as exc:
            if _is_layout_fk(exc):
                named = tuple(field for field, lid in refs if lid is not None)
                raise DrawingLayoutNotFoundError(named) from exc
            raise

    async def _apply_batch_once(
        self, owner: str, ops: Sequence[BatchOp], refs: Sequence[tuple[str, str | None]]
    ) -> BatchResult:
        creates: list[tuple[int, CreateOp]] = [
            (i, op) for i, op in enumerate(ops) if isinstance(op, CreateOp)
        ]
        updates: list[tuple[int, UpdateOp]] = [
            (i, op) for i, op in enumerate(ops) if isinstance(op, UpdateOp)
        ]
        deletes: list[tuple[int, DeleteOp]] = [
            (i, op) for i, op in enumerate(ops) if isinstance(op, DeleteOp)
        ]
        async with self._relational.unit_of_work() as uow:
            await _lock_live_layouts(uow, owner, refs)  # layouts before drawings (spec Sec.7)
            ids = [op.id for op in ops]
            locked = await uow.session.execute(_SNAPSHOT, {"ids": ids, "owner": owner})
            snap: dict[str, Mapping[str, Any]] = {r["id"]: dict(r) for r in locked.mappings()}
            failure = _first_failure(ops, snap)  # `snap` is the caller's own rows only
            # Creates before the first snapshot failure are inserted too, so a concurrent PK
            # collision at an earlier index still wins, exactly as in operation order.
            limit = failure[0] if failure is not None else len(ops)
            first_create = [(i, op) for i, op in creates if i < limit]
            created_by_id: dict[str, DrawingRow] = {}
            if first_create:
                got = await uow.session.execute(
                    _INSERT_MANY,
                    {
                        "owner": owner,
                        "rows": _rows_param(
                            [_row_json(op.id, op.fields) for _, op in first_create]
                        ),
                    },
                )
                created_by_id = {r["id"]: _to_row(r) for r in got.mappings()}
                for i, op in first_create:
                    if op.id not in created_by_id:
                        raise BatchOpFailed(i, "id_unavailable")
            if failure is not None:
                raise BatchOpFailed(*failure)
            updated_by_id: dict[str, DrawingRow] = {}
            if updates:
                got = await uow.session.execute(
                    _UPDATE_MANY,
                    {
                        "owner": owner,
                        "ids": [op.id for _, op in updates],
                        "rows": _rows_param(
                            [_row_json(op.id, op.fields, op.if_match) for _, op in updates]
                        ),
                    },
                )
                updated_by_id = {r["id"]: _to_row(r) for r in got.mappings()}
                for i, uop in updates:  # fail closed: every locked row is updated exactly once
                    if uop.id not in updated_by_id:
                        raise BatchOpFailed(i, "target_unavailable")
            deleted_ids: set[str] = set()
            if deletes:
                gone = await uow.session.execute(
                    _SOFT_DELETE_MANY, {"owner": owner, "ids": [op.id for _, op in deletes]}
                )
                deleted_ids = {str(row[0]) for row in gone.all()}
                for i, dop in deletes:  # fail closed
                    if dop.id not in deleted_ids:
                        raise BatchOpFailed(i, "target_unavailable")
            await uow.commit()
        return BatchResult(
            tuple(created_by_id[op.id] for _, op in creates),
            tuple(updated_by_id[op.id] for _, op in updates),
            tuple(op.id for _, op in deletes),
        )

    async def purge_deleted(self, older_than_days: int, limit: int) -> int:
        if older_than_days < 1 or not 1 <= limit <= MAX_PURGE_BATCH:
            raise ValueError("purge needs older_than_days >= 1 and 1 <= limit <= MAX_PURGE_BATCH")
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_PURGE, {"days": older_than_days, "limit": limit})
            await uow.commit()
        return int(getattr(res, "rowcount", 0))

    async def count_live_by_tool(self) -> dict[str, int]:
        """Live rows per tool across all owners (metrics only; like the purge, owner-agnostic)."""
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_COUNT_LIVE)).all()
        return {str(tool): int(n) for tool, n in rows}


__all__ = [
    "DRAWING_COLUMNS",
    "MAX_BATCH_OPS_STORAGE",
    "MAX_PURGE_BATCH",
    "SqlAlchemyDrawingRepository",
]

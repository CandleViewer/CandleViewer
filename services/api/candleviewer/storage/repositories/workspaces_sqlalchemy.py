"""Postgres workspaces/layouts repository (migration `0022_workspaces`, E15-T01).

Static, parameterised `sa.text` only. Every statement is filtered by the caller (`:owner`,
C-12.4 data-layer re-check) except `UNSCOPED`: the two `exists_for_other_owner` probes (their
purpose), the recorder probes (all users, E16) and the retention purge. Transactions follow
spec Sec.5: READ COMMITTED, one `unit_of_work()` per write; lock order is always
advisory(user) -> workspace row -> layout rows -> panes/drawings. Multi-row UPDATEs carry no
`ORDER BY`: they cannot deadlock because the per-user advisory lock (workspace writes) and the
workspace row lock (layout writes) already serialise every writer of those rows; the single
layout lock (`_LAY_LOCK`) is the only multi-statement row lock and is taken by `ORDER BY id`.
No-op detection compares type-preserving canonical JSON (`1`, `1.0` and `true` differ).
Every UPDATE bumps `updated_at` strictly monotonically (D12), so a token never repeats.
Uniqueness is decided by the unique indexes, never by a pre-check; the rollback keeps the
stored pane set intact when a write fails late.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    SqlAlchemyUnitOfWork,
)
from candleviewer.storage.repositories.workspaces import (
    LayoutFields,
    LayoutRow,
    PaneFields,
    WorkspaceConflictError,
    WorkspaceDetailRow,
    WorkspaceFields,
    WorkspaceNotFoundError,
    WorkspaceRow,
    WorkspaceVersionConflictError,
    WriteResult,
)
from candleviewer.storage.repositories.workspaces_codec import (
    lay_params,
    lay_row,
    map_integrity,
    pane_payload,
    pane_row,
    same_fields,
    ws_params,
    ws_row,
)

MAX_WORKSPACES = 32
MAX_LAYOUTS = 32
#: Upper bound for one purge call so a single transaction stays short.
MAX_PURGE_BATCH = 10_000
_PAGE_ALL = 500

_LOCK_USER = sa.text(
    "SELECT pg_advisory_xact_lock(hashtextextended('cv.workspaces:' || CAST(:owner AS text), 0))"
)
_WS_LOCK = sa.text(
    "SELECT name, is_default, icon_token, sort_order, updated_at FROM workspaces "
    "WHERE id = CAST(:wid AS uuid) AND user_id = CAST(:owner AS uuid) AND deleted_at IS NULL "
    "FOR NO KEY UPDATE"
)
_WS_COUNT = sa.text(
    "SELECT count(*) FROM workspaces WHERE user_id = CAST(:owner AS uuid) AND deleted_at IS NULL"
)
_WS_CLEAR_DEFAULT = sa.text(
    "UPDATE workspaces SET is_default = false, "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE user_id = CAST(:owner AS uuid) AND is_default AND deleted_at IS NULL "
    "AND id IS DISTINCT FROM CAST(:keep AS uuid)"
)
_WS_INSERT = sa.text(
    "INSERT INTO workspaces (id, user_id, name, is_default, icon_token, sort_order, "
    "created_at, updated_at) SELECT CAST(:wid AS uuid), CAST(:owner AS uuid), :name, "
    ":is_default, :icon_token, :sort_order, c.t, c.t FROM (SELECT clock_timestamp() AS t) c"
)
_WS_UPDATE = sa.text(
    "UPDATE workspaces SET name = :name, is_default = :is_default, icon_token = :icon_token, "
    "sort_order = :sort_order, "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = CAST(:wid AS uuid) AND user_id = CAST(:owner AS uuid) AND deleted_at IS NULL"
)
_WS_GET = sa.text(
    "SELECT w.id::text AS id, w.user_id::text AS user_id, w.name, w.is_default, w.icon_token, "
    "w.sort_order, (SELECT count(*) FROM layouts l WHERE l.workspace_id = w.id "
    "AND l.owner_user_id = w.user_id AND l.deleted_at IS NULL) AS layout_count, "
    "w.created_at, w.updated_at FROM workspaces w "
    "WHERE w.id = CAST(:wid AS uuid) AND w.user_id = CAST(:owner AS uuid) "
    "AND w.deleted_at IS NULL"
)
_WS_LIST = sa.text(
    "SELECT w.id::text AS id, w.user_id::text AS user_id, w.name, w.is_default, w.icon_token, "
    "w.sort_order, (SELECT count(*) FROM layouts l WHERE l.workspace_id = w.id "
    "AND l.owner_user_id = w.user_id AND l.deleted_at IS NULL) AS layout_count, "
    "w.created_at, w.updated_at FROM workspaces w "
    "WHERE w.user_id = CAST(:owner AS uuid) AND w.deleted_at IS NULL "
    "AND (CAST(:after_id AS uuid) IS NULL OR "
    "(w.sort_order, w.id) > (CAST(:after_so AS smallint), CAST(:after_id AS uuid))) "
    "ORDER BY w.sort_order, w.id LIMIT :limit"
)
_WS_SOFT_DELETE = sa.text(
    "UPDATE workspaces SET deleted_at = clock_timestamp(), "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = CAST(:wid AS uuid) AND user_id = CAST(:owner AS uuid) AND deleted_at IS NULL "
    "RETURNING deleted_at"
)
_LAYS_SOFT_DELETE = sa.text(
    "UPDATE layouts SET deleted_at = CAST(:ts AS timestamptz), "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE workspace_id = CAST(:wid AS uuid) AND owner_user_id = CAST(:owner AS uuid) "
    "AND deleted_at IS NULL RETURNING id::text AS id"
)
_LAY_SOFT_DELETE = sa.text(
    "UPDATE layouts SET deleted_at = clock_timestamp(), "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = CAST(:lid AS uuid) AND workspace_id = CAST(:wid AS uuid) "
    "AND owner_user_id = CAST(:owner AS uuid) AND deleted_at IS NULL RETURNING deleted_at"
)
_DRAWINGS_SOFT_DELETE = sa.text(
    "UPDATE drawings SET deleted_at = CAST(:ts AS timestamptz), "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE layout_id = ANY(CAST(:ids AS uuid[])) AND owner_user_id = CAST(:owner AS uuid) "
    "AND deleted_at IS NULL"
)
_WS_LIVE = sa.text(
    "SELECT 1 FROM workspaces WHERE id = CAST(:wid AS uuid) "
    "AND user_id = CAST(:owner AS uuid) AND deleted_at IS NULL"
)
_LAY_COUNT = sa.text(
    "SELECT count(*) FROM layouts WHERE workspace_id = CAST(:wid AS uuid) "
    "AND owner_user_id = CAST(:owner AS uuid) AND deleted_at IS NULL"
)
_LAY_LOCK = sa.text(
    "SELECT id FROM layouts WHERE id = CAST(:lid AS uuid) AND workspace_id = CAST(:wid AS uuid) "
    "AND owner_user_id = CAST(:owner AS uuid) AND deleted_at IS NULL ORDER BY id FOR UPDATE"
)
_LAY_CLEAR_DEFAULT = sa.text(
    "UPDATE layouts SET is_default = false, "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE workspace_id = CAST(:wid AS uuid) AND owner_user_id = CAST(:owner AS uuid) "
    "AND is_default AND deleted_at IS NULL AND id IS DISTINCT FROM CAST(:keep AS uuid)"
)
_LAY_INSERT = sa.text(
    "INSERT INTO layouts (id, workspace_id, owner_user_id, name, grid_preset, grid_spec, "
    "crosshair_sync, level_sync, symbol_sync, hotkey_slot, is_default, created_at, updated_at) "
    "SELECT CAST(:lid AS uuid), CAST(:wid AS uuid), CAST(:owner AS uuid), :name, :grid_preset, "
    "CAST(:grid_spec AS jsonb), :crosshair_sync, :level_sync, :symbol_sync, :hotkey_slot, "
    ":is_default, c.t, c.t FROM (SELECT clock_timestamp() AS t) c"
)
_LAY_UPDATE = sa.text(
    "UPDATE layouts SET name = :name, grid_preset = :grid_preset, "
    "grid_spec = CAST(:grid_spec AS jsonb), crosshair_sync = :crosshair_sync, "
    "level_sync = :level_sync, symbol_sync = :symbol_sync, hotkey_slot = :hotkey_slot, "
    "is_default = :is_default, "
    "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
    "WHERE id = CAST(:lid AS uuid) AND workspace_id = CAST(:wid AS uuid) "
    "AND owner_user_id = CAST(:owner AS uuid) AND deleted_at IS NULL"
)
_LAY_GET = sa.text(
    "SELECT l.id::text AS id, l.workspace_id::text AS workspace_id, l.name, l.grid_preset, "
    "l.grid_spec, l.crosshair_sync, l.level_sync, l.symbol_sync, l.hotkey_slot, l.is_default, "
    "l.created_at, l.updated_at FROM layouts l WHERE l.id = CAST(:lid AS uuid) "
    "AND l.workspace_id = CAST(:wid AS uuid) AND l.owner_user_id = CAST(:owner AS uuid) "
    "AND l.deleted_at IS NULL"
)
_LAY_LIST = sa.text(
    "SELECT l.id::text AS id, l.workspace_id::text AS workspace_id, l.name, l.grid_preset, "
    "l.grid_spec, l.crosshair_sync, l.level_sync, l.symbol_sync, l.hotkey_slot, l.is_default, "
    "l.created_at, l.updated_at FROM layouts l WHERE l.workspace_id = CAST(:wid AS uuid) "
    "AND l.owner_user_id = CAST(:owner AS uuid) AND l.deleted_at IS NULL "
    "AND (CAST(:after_id AS uuid) IS NULL OR l.id > CAST(:after_id AS uuid)) "
    "ORDER BY l.id LIMIT :limit"
)
_PANES = sa.text(
    "SELECT lp.layout_id::text AS layout_id, lp.slot_index, lp.pane_kind, lp.symbol, "
    "lp.interval_code, lp.chart_template_id::text AS chart_template_id, "
    "lp.indicator_preset_ids, lp.pane_config, lp.scale_mode "
    "FROM layout_panes lp JOIN layouts l ON l.id = lp.layout_id "
    "WHERE lp.layout_id = ANY(CAST(:ids AS uuid[])) AND l.owner_user_id = CAST(:owner AS uuid) "
    "AND l.deleted_at IS NULL ORDER BY lp.layout_id, lp.slot_index"
)
_PANES_DELETE = sa.text(
    "DELETE FROM layout_panes WHERE layout_id = CAST(:lid AS uuid) AND layout_id IN "
    "(SELECT id FROM layouts WHERE id = CAST(:lid AS uuid) "
    "AND owner_user_id = CAST(:owner AS uuid))"
)
_PANES_INSERT = sa.text(
    "INSERT INTO layout_panes (id, layout_id, slot_index, pane_kind, symbol, interval_code, "
    "chart_template_id, indicator_preset_ids, pane_config, scale_mode, created_at, updated_at) "
    "SELECT p.id, CAST(:lid AS uuid), p.slot_index, p.pane_kind, p.symbol, p.interval_code, "
    "p.chart_template_id, p.indicator_preset_ids, p.pane_config, p.scale_mode, c.t, c.t "
    "FROM jsonb_to_recordset(CAST(:panes AS jsonb)) AS p(id uuid, slot_index smallint, "
    "pane_kind text, symbol text, interval_code text, chart_template_id uuid, "
    "indicator_preset_ids uuid[], pane_config jsonb, scale_mode text), "
    "(SELECT clock_timestamp() AS t) c WHERE EXISTS (SELECT 1 FROM layouts "
    "WHERE id = CAST(:lid AS uuid) AND owner_user_id = CAST(:owner AS uuid))"
)
_IS_LIVE_LAYOUT = sa.text(
    "SELECT 1 FROM layouts WHERE id = CAST(:lid AS uuid) "
    "AND owner_user_id = CAST(:owner AS uuid) AND deleted_at IS NULL"
)
_EXISTS_OTHER_WS = sa.text(
    "SELECT 1 FROM workspaces WHERE id = CAST(:oid AS uuid) "
    "AND user_id <> CAST(:owner AS uuid) AND deleted_at IS NULL"
)
_EXISTS_OTHER_LAY = sa.text(
    "SELECT 1 FROM layouts WHERE id = CAST(:oid AS uuid) "
    "AND owner_user_id <> CAST(:owner AS uuid) AND deleted_at IS NULL"
)
# Recorder probes (spec Sec.8): all users; the probe is served by ix_lp_symbol.
_CHART_OPEN = sa.text(
    "SELECT EXISTS (SELECT 1 FROM layout_panes lp JOIN layouts l ON l.id = lp.layout_id "
    "WHERE lp.symbol = :symbol AND l.deleted_at IS NULL) AS open"
)
_CHART_SYMBOLS = sa.text(
    "SELECT DISTINCT lp.symbol FROM layout_panes lp JOIN layouts l ON l.id = lp.layout_id "
    "WHERE lp.symbol IS NOT NULL AND l.deleted_at IS NULL ORDER BY lp.symbol"
)
_PURGE_LAYOUTS = sa.text(
    "DELETE FROM layouts WHERE id IN (SELECT id FROM layouts WHERE deleted_at IS NOT NULL "
    "AND deleted_at < now() - make_interval(days => CAST(:days AS integer)) "
    "ORDER BY deleted_at LIMIT :limit)"
)
_PURGE_WORKSPACES = sa.text(
    "DELETE FROM workspaces WHERE id IN (SELECT id FROM workspaces WHERE deleted_at IS NOT NULL "
    "AND deleted_at < now() - make_interval(days => CAST(:days AS integer)) "
    "ORDER BY deleted_at LIMIT :limit)"
)

#: Statements allowed to omit the `owner = :owner` filter (see module docstring); tested.
UNSCOPED = frozenset(
    {"_EXISTS_OTHER_WS", "_EXISTS_OTHER_LAY", "_CHART_OPEN", "_CHART_SYMBOLS", "_PURGE_LAYOUTS",
     "_PURGE_WORKSPACES"}
)  # fmt: skip


class SqlAlchemyWorkspaceRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    # ---- reads ---------------------------------------------------------------------------
    async def list_workspaces(
        self, owner: str, *, after: tuple[int, str] | None, limit: int
    ) -> list[WorkspaceRow]:
        params = {
            "owner": owner,
            "after_so": None if after is None else after[0],
            "after_id": None if after is None else after[1],
            "limit": limit,
        }
        async with self._relational.unit_of_work() as uow:
            return [ws_row(r) for r in (await uow.session.execute(_WS_LIST, params)).mappings()]

    async def _layouts(
        self, uow: SqlAlchemyUnitOfWork, owner: str, wid: str, after_id: str | None, limit: int
    ) -> list[LayoutRow]:
        res = await uow.session.execute(
            _LAY_LIST, {"wid": wid, "owner": owner, "after_id": after_id, "limit": limit}
        )
        heads = list(res.mappings())
        by_layout = await self._panes_of(uow, owner, [h["id"] for h in heads])
        return [lay_row(h, by_layout.get(h["id"], ())) for h in heads]

    async def _panes_of(
        self, uow: SqlAlchemyUnitOfWork, owner: str, ids: list[str]
    ) -> dict[str, tuple[PaneFields, ...]]:
        if not ids:
            return {}
        grouped: dict[str, list[PaneFields]] = {}
        for m in (await uow.session.execute(_PANES, {"ids": ids, "owner": owner})).mappings():
            grouped.setdefault(m["layout_id"], []).append(pane_row(m))
        return {k: tuple(v) for k, v in grouped.items()}

    async def get_workspace_detail(
        self, owner: str, workspace_id: str
    ) -> WorkspaceDetailRow | None:
        async with self._relational.unit_of_work() as uow:
            head = (
                (await uow.session.execute(_WS_GET, {"wid": workspace_id, "owner": owner}))
                .mappings()
                .first()
            )
            if head is None:
                return None
            layouts = await self._layouts(uow, owner, workspace_id, None, _PAGE_ALL)
        return WorkspaceDetailRow(ws_row(head), tuple(layouts))

    async def list_layouts(
        self, owner: str, workspace_id: str, *, after_id: str | None, limit: int
    ) -> list[LayoutRow] | None:
        async with self._relational.unit_of_work() as uow:
            live = await uow.session.execute(_WS_LIVE, {"wid": workspace_id, "owner": owner})
            if live.first() is None:
                return None
            return await self._layouts(uow, owner, workspace_id, after_id, limit)

    async def _get_layout(
        self, uow: SqlAlchemyUnitOfWork, owner: str, wid: str, lid: str
    ) -> LayoutRow | None:
        head = (
            (await uow.session.execute(_LAY_GET, {"lid": lid, "wid": wid, "owner": owner}))
            .mappings()
            .first()
        )
        if head is None:
            return None
        return lay_row(head, (await self._panes_of(uow, owner, [lid])).get(lid, ()))

    async def get_layout(self, owner: str, workspace_id: str, layout_id: str) -> LayoutRow | None:
        async with self._relational.unit_of_work() as uow:
            return await self._get_layout(uow, owner, workspace_id, layout_id)

    async def exists_for_other_owner(
        self, owner: str, kind: Literal["workspace", "layout"], object_id: str
    ) -> bool:
        stmt = _EXISTS_OTHER_WS if kind == "workspace" else _EXISTS_OTHER_LAY
        async with self._relational.unit_of_work() as uow:
            return (
                await uow.session.execute(stmt, {"oid": object_id, "owner": owner})
            ).first() is not None

    async def is_live_layout(self, owner: str, layout_id: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_IS_LIVE_LAYOUT, {"lid": layout_id, "owner": owner})
            return res.first() is not None

    async def is_chart_open(self, symbol: str) -> bool:
        async with self._relational.unit_of_work() as uow:
            return bool((await uow.session.execute(_CHART_OPEN, {"symbol": symbol})).scalar_one())

    async def chart_open_symbols(self) -> list[str]:
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_CHART_SYMBOLS)
            symbols: list[str] = list(res.scalars().all())
            return symbols

    # ---- workspace writes ----------------------------------------------------------------
    async def create_workspace(
        self, owner: str, workspace_id: str, fields: WorkspaceFields
    ) -> WorkspaceRow:
        params = {"wid": workspace_id, "owner": owner, **ws_params(fields)}
        try:
            async with self._relational.unit_of_work() as uow:
                await uow.session.execute(_LOCK_USER, {"owner": owner})
                count: int = (await uow.session.execute(_WS_COUNT, {"owner": owner})).scalar_one()
                if count >= MAX_WORKSPACES:
                    raise WorkspaceConflictError("limit_reached", None)
                if fields.is_default:
                    await uow.session.execute(_WS_CLEAR_DEFAULT, {"owner": owner, "keep": None})
                await uow.session.execute(_WS_INSERT, params)
                row = await self._ws(uow, owner, workspace_id)
                await uow.commit()
        except IntegrityError as exc:
            raise map_integrity(exc) or exc from exc
        return row

    async def _ws(self, uow: SqlAlchemyUnitOfWork, owner: str, wid: str) -> WorkspaceRow:
        got = (await uow.session.execute(_WS_GET, {"wid": wid, "owner": owner})).mappings().one()
        return ws_row(got)

    async def _lock_workspace(self, uow: SqlAlchemyUnitOfWork, owner: str, wid: str) -> Any:
        row = (await uow.session.execute(_WS_LOCK, {"wid": wid, "owner": owner})).mappings().first()
        if row is None:
            raise WorkspaceNotFoundError("workspace")
        return row

    async def update_workspace(
        self,
        owner: str,
        workspace_id: str,
        fields: WorkspaceFields,
        *,
        if_match: datetime | None,
    ) -> WriteResult[WorkspaceRow]:
        try:
            async with self._relational.unit_of_work() as uow:
                await uow.session.execute(_LOCK_USER, {"owner": owner})
                cur = await self._lock_workspace(uow, owner, workspace_id)
                stored = WorkspaceFields(
                    cur["name"], cur["is_default"], cur["icon_token"], cur["sort_order"]
                )
                if same_fields(stored, fields):  # no-op wins over a stale token (D13)
                    return WriteResult(await self._ws(uow, owner, workspace_id), False)
                if if_match is not None and cur["updated_at"] != if_match:
                    raise WorkspaceVersionConflictError(workspace_id)
                if fields.is_default:
                    keep = {"owner": owner, "keep": workspace_id}
                    await uow.session.execute(_WS_CLEAR_DEFAULT, keep)
                params = {"wid": workspace_id, "owner": owner, **ws_params(fields)}
                await uow.session.execute(_WS_UPDATE, params)
                row = await self._ws(uow, owner, workspace_id)
                await uow.commit()
        except IntegrityError as exc:
            raise map_integrity(exc) or exc from exc
        return WriteResult(row, True)

    async def soft_delete_workspace(self, owner: str, workspace_id: str) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_LOCK_USER, {"owner": owner})
            await self._lock_workspace(uow, owner, workspace_id)
            if (await uow.session.execute(_WS_COUNT, {"owner": owner})).scalar_one() <= 1:
                raise WorkspaceConflictError("last_workspace", "workspaceId")
            ids = {"wid": workspace_id, "owner": owner}
            ts: datetime = (await uow.session.execute(_WS_SOFT_DELETE, ids)).scalar_one()
            gone = await uow.session.execute(_LAYS_SOFT_DELETE, {**ids, "ts": ts})
            layout_ids: list[str] = list(gone.scalars().all())
            if layout_ids:
                await uow.session.execute(
                    _DRAWINGS_SOFT_DELETE, {"ids": layout_ids, "owner": owner, "ts": ts}
                )
            await uow.commit()

    # ---- layout writes -------------------------------------------------------------------
    async def create_layout(
        self, owner: str, workspace_id: str, layout_id: str, fields: LayoutFields
    ) -> LayoutRow:
        ids = {"wid": workspace_id, "owner": owner}
        try:
            async with self._relational.unit_of_work() as uow:
                await self._lock_workspace(uow, owner, workspace_id)
                if (await uow.session.execute(_LAY_COUNT, ids)).scalar_one() >= MAX_LAYOUTS:
                    raise WorkspaceConflictError("limit_reached", None)
                if fields.is_default:
                    await uow.session.execute(_LAY_CLEAR_DEFAULT, {**ids, "keep": None})
                await uow.session.execute(
                    _LAY_INSERT, {**ids, "lid": layout_id, **lay_params(fields)}
                )
                await self._write_panes(uow, owner, layout_id, fields)
                row = await self._get_layout(uow, owner, workspace_id, layout_id)
                await uow.commit()
        except IntegrityError as exc:
            raise map_integrity(exc) or exc from exc
        if row is None:  # unreachable: read back inside the inserting transaction
            raise WorkspaceNotFoundError("layout")
        return row

    async def _write_panes(
        self, uow: SqlAlchemyUnitOfWork, owner: str, lid: str, fields: LayoutFields
    ) -> None:
        if fields.panes:
            payload = {"lid": lid, "owner": owner, "panes": pane_payload(fields.panes)}
            await uow.session.execute(_PANES_INSERT, payload)

    async def replace_layout(
        self,
        owner: str,
        workspace_id: str,
        layout_id: str,
        fields: LayoutFields,
        *,
        if_match: datetime | None,
    ) -> WriteResult[LayoutRow]:
        ids = {"wid": workspace_id, "owner": owner}
        try:
            async with self._relational.unit_of_work() as uow:
                await self._lock_workspace(uow, owner, workspace_id)
                locked = await uow.session.execute(_LAY_LOCK, {**ids, "lid": layout_id})
                if locked.first() is None:
                    raise WorkspaceNotFoundError("layout")
                cur = await self._get_layout(uow, owner, workspace_id, layout_id)
                if cur is None:  # unreachable: the row lock above succeeded
                    raise WorkspaceNotFoundError("layout")
                if same_fields(cur.to_fields(), fields):  # no-op wins over a stale token (D13)
                    return WriteResult(cur, False)
                if if_match is not None and cur.updated_at != if_match:
                    raise WorkspaceVersionConflictError(layout_id)
                if fields.is_default:
                    await uow.session.execute(_LAY_CLEAR_DEFAULT, {**ids, "keep": layout_id})
                await uow.session.execute(_PANES_DELETE, {"lid": layout_id, "owner": owner})
                await self._write_panes(uow, owner, layout_id, fields)
                upd = {**ids, "lid": layout_id, **lay_params(fields)}
                await uow.session.execute(_LAY_UPDATE, upd)
                row = await self._get_layout(uow, owner, workspace_id, layout_id)
                await uow.commit()
        except IntegrityError as exc:
            raise map_integrity(exc) or exc from exc
        if row is None:  # unreachable: read back inside the writing transaction
            raise WorkspaceNotFoundError("layout")
        return WriteResult(row, True)

    async def soft_delete_layout(self, owner: str, workspace_id: str, layout_id: str) -> None:
        ids = {"wid": workspace_id, "owner": owner, "lid": layout_id}
        async with self._relational.unit_of_work() as uow:
            await self._lock_workspace(uow, owner, workspace_id)
            if (await uow.session.execute(_LAY_LOCK, ids)).first() is None:
                raise WorkspaceNotFoundError("layout")
            ts: datetime = (await uow.session.execute(_LAY_SOFT_DELETE, ids)).scalar_one()
            await uow.session.execute(
                _DRAWINGS_SOFT_DELETE, {"ids": [layout_id], "owner": owner, "ts": ts}
            )
            await uow.commit()

    # ---- retention -----------------------------------------------------------------------
    async def purge_deleted(self, older_than_days: int, limit: int) -> int:
        if older_than_days < 1 or not 1 <= limit <= MAX_PURGE_BATCH:
            raise ValueError("purge needs older_than_days >= 1 and 1 <= limit <= MAX_PURGE_BATCH")
        params = {"days": older_than_days, "limit": limit}
        async with self._relational.unit_of_work() as uow:
            layouts = await uow.session.execute(_PURGE_LAYOUTS, params)
            workspaces = await uow.session.execute(_PURGE_WORKSPACES, params)
            await uow.commit()
        return int(getattr(layouts, "rowcount", 0)) + int(getattr(workspaces, "rowcount", 0))


__all__ = ["MAX_PURGE_BATCH", "UNSCOPED", "SqlAlchemyWorkspaceRepository"]

"""workspaces, layouts, layout_panes (E15-T01)

Revision ID: 0022_workspaces
Revises: 0021_drawings
Create Date: 2026-10-14

Purely additive (C-5.1). DDL mirrors `docs/plan/21-database-schema.md`
Sec.3.8.1 (the register's `0011_workspace`; number 0011 was taken, so the
workspaces portion ships as 0022). Documented deviations (spec E15-T01 Sec.4,
recorded in Sec.3.8.1):

* `layouts.owner_user_id` (denormalised `workspaces.user_id`, written once at
  insert) plus `UNIQUE (id, user_id)` on `workspaces` and `UNIQUE (id,
  owner_user_id)` on `layouts`; both parent references are composite FKs
  (`fk_layouts_workspace_id_workspaces`, `fk_drawings_layout_id_layouts`), so
  the database guarantees workspace.user = layout.owner = drawing.owner
  (D27, #357 residual R5). `MATCH SIMPLE` leaves `layout_id IS NULL` drawings
  unchecked.
* `drawings.layout_id` FK is added here (E14-T01 left the column bare). It is
  added `NOT VALID` and then `VALIDATE`d (C-5.6: no long lock on `drawings`).
* `ux_lay_default` (one live default layout per workspace), `ix_lay_workspace`
  and `ix_dr_layout` (FK-side indexes for the purge cascades) are new.
* `ix_lp_layout` is kept exactly as Sec.3.8.1 even though `ux_lp_slot`
  (`UNIQUE (layout_id, slot_index)`) covers the same columns (ruling Q4,
  #402); the redundancy is noted for a later cleanup.
* `layout_panes.chart_template_id` has NO foreign key: `chart_templates` does
  not exist and no ticket creates it yet (0014/0017 precedent, ruling Q2,
  gap issue #2411). The API refuses non-null ids until the FK lands.
* `layout_panes.interval_code` carries `<bar_type>:<param>` (spec D4), no CHECK.
* No triggers: the repository sets `updated_at` (D12). No GRANTs (default
  privileges give cv_app DML). No seed.
* Downgrade refuses while `workspaces`, `layouts` or `layout_panes` hold rows.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022_workspaces"
down_revision: str | None = "0021_drawings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_TABLES_SQL)
    op.execute(_DRAWINGS_FK_SQL)
    op.execute("ALTER TABLE drawings VALIDATE CONSTRAINT fk_drawings_layout_id_layouts")


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_TABLES_SQL = """
CREATE TABLE workspaces (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        text NOT NULL,
  is_default  boolean NOT NULL DEFAULT false,
  icon_token  text NOT NULL DEFAULT 'workspace.default',
  sort_order  smallint NOT NULL DEFAULT 0,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  deleted_at  timestamptz,
  CONSTRAINT ux_workspaces_id_user_id UNIQUE (id, user_id)
);
CREATE UNIQUE INDEX ux_ws_name    ON workspaces (user_id, lower(name)) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX ux_ws_default ON workspaces (user_id) WHERE is_default AND deleted_at IS NULL;

CREATE TABLE layouts (
  id             uuid PRIMARY KEY,
  workspace_id   uuid NOT NULL,
  owner_user_id  uuid NOT NULL,
  name           text NOT NULL,
  grid_preset    text NOT NULL DEFAULT '1x1',
  grid_spec      jsonb NOT NULL DEFAULT '{}'::jsonb,
  crosshair_sync boolean NOT NULL DEFAULT true,
  level_sync     boolean NOT NULL DEFAULT false,
  symbol_sync    boolean NOT NULL DEFAULT false,
  hotkey_slot    smallint,
  is_default     boolean NOT NULL DEFAULT false,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  CONSTRAINT fk_layouts_workspace_id_workspaces FOREIGN KEY (workspace_id, owner_user_id)
    REFERENCES workspaces (id, user_id) ON DELETE CASCADE,
  CONSTRAINT ux_layouts_id_owner_user_id UNIQUE (id, owner_user_id),
  CONSTRAINT lay_preset CHECK (grid_preset IN ('1x1','2x1','1x2','2x2','1+3','3x3','custom')),
  CONSTRAINT lay_slot   CHECK (hotkey_slot IS NULL OR hotkey_slot BETWEEN 1 AND 9)
);
CREATE UNIQUE INDEX ux_lay_name    ON layouts (workspace_id, lower(name)) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX ux_lay_slot    ON layouts (workspace_id, hotkey_slot)
  WHERE hotkey_slot IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX ux_lay_default ON layouts (workspace_id) WHERE is_default AND deleted_at IS NULL;
CREATE INDEX ix_lay_workspace      ON layouts (workspace_id);

CREATE TABLE layout_panes (
  id                   uuid PRIMARY KEY,
  layout_id            uuid NOT NULL REFERENCES layouts(id) ON DELETE CASCADE,
  slot_index           smallint NOT NULL,
  pane_kind            text NOT NULL,
  symbol               symbol_code,
  interval_code        text,
  chart_template_id    uuid,
  indicator_preset_ids uuid[] NOT NULL DEFAULT '{}',
  pane_config          jsonb NOT NULL DEFAULT '{}'::jsonb,
  scale_mode           text NOT NULL DEFAULT 'auto',
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ux_lp_slot UNIQUE (layout_id, slot_index),
  CONSTRAINT lp_kind  CHECK (pane_kind IN ('chart','dom','tape','profile','cvd','oi','deep_stats',
                                           'regime','positions','journal','watchlist','alerts')),
  CONSTRAINT lp_slot  CHECK (slot_index BETWEEN 0 AND 15),
  CONSTRAINT lp_scale CHECK (scale_mode IN ('auto','linked','manual','log'))
);
CREATE INDEX ix_lp_layout ON layout_panes (layout_id, slot_index);
CREATE INDEX ix_lp_symbol ON layout_panes (symbol) WHERE symbol IS NOT NULL;
"""

_DRAWINGS_FK_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM drawings WHERE layout_id IS NOT NULL) THEN
    RAISE EXCEPTION '0022_workspaces: drawings.layout_id holds values although no layout could exist (E14-T01 refuses them); clean up before upgrading';
  END IF;
END $BODY$;
ALTER TABLE drawings ADD CONSTRAINT fk_drawings_layout_id_layouts
  FOREIGN KEY (layout_id, owner_user_id) REFERENCES layouts (id, owner_user_id)
  MATCH SIMPLE ON DELETE CASCADE NOT VALID;
CREATE INDEX ix_dr_layout ON drawings (layout_id) WHERE layout_id IS NOT NULL;
"""

_DOWNGRADE_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM workspaces)
     OR EXISTS (SELECT 1 FROM layouts)
     OR EXISTS (SELECT 1 FROM layout_panes) THEN
    RAISE EXCEPTION '0022_workspaces downgrade refused: workspaces/layouts/layout_panes hold data';
  END IF;
END $BODY$;
DROP INDEX ix_dr_layout;
ALTER TABLE drawings DROP CONSTRAINT IF EXISTS fk_drawings_layout_id_layouts;
DROP TABLE layout_panes;
DROP TABLE layouts;
DROP TABLE workspaces;
"""

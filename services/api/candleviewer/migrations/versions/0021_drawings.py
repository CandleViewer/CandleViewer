"""drawings (E14-T01)

Revision ID: 0021_drawings
Revises: 0020_kek_versions
Create Date: 2026-10-14

Purely additive (C-5.1). DDL mirrors `docs/plan/21-database-schema.md`
Sec.3.8.3 (the register's `0011_workspace`; number 0011 was taken, so
`drawings` ships alone as 0021). Documented deviations:

* `dr_tool` lists the 25 API tool names (trendline, horizontal_line, ...,
  anchored_vwap) instead of the 12 short names in the register.
* New nullable `layout_id uuid` column WITHOUT a foreign key: `layouts` does
  not exist yet; E15-T01 adds `REFERENCES layouts(id) ON DELETE CASCADE`.
* `label` is a column of its own (not inside `style`); `interval_scope` and
  `alert_id` exist but are not exposed by the API yet (E40 owns `alert_id`).
* Downgrade refuses (clear error) while `drawings` holds rows, and drops the
  table cleanly when empty.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021_drawings"
down_revision: str | None = "0020_kek_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(_DRAWINGS_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)


_DRAWINGS_SQL = """
CREATE TABLE drawings (
  id            uuid PRIMARY KEY,
  owner_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  symbol        symbol_code NOT NULL,
  layout_id     uuid,               -- FK to layouts(id) ON DELETE CASCADE is added by E15-T01
  tool          text NOT NULL,
  geometry      jsonb NOT NULL,
  style         jsonb NOT NULL DEFAULT '{}'::jsonb,
  label         text,
  locked        boolean NOT NULL DEFAULT false,
  visible       boolean NOT NULL DEFAULT true,
  interval_scope text,              -- NULL = all intervals (not exposed by the API yet)
  z_index       smallint NOT NULL DEFAULT 0,
  anchor_start  timestamptz,
  anchor_end    timestamptz,
  alert_id      uuid REFERENCES alerts(id) ON DELETE SET NULL,  -- E40; not exposed
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz,
  CONSTRAINT dr_tool CHECK (tool IN (
    'trendline','horizontal_line','vertical_line','ray','extended_line',
    'parallel_channel','rectangle','ellipse','triangle','fib_retracement',
    'fib_extension','fib_timezone','pitchfork','gann_fan','text',
    'arrow','callout','measure','long_position','short_position',
    'price_range','date_range','brush','polyline','anchored_vwap'
  )),
  CONSTRAINT dr_geom CHECK (jsonb_typeof(geometry) = 'object' AND geometry ? 'points')
);
CREATE INDEX ix_dr_user_symbol ON drawings (owner_user_id, symbol) WHERE deleted_at IS NULL;
CREATE INDEX ix_dr_range       ON drawings (symbol, anchor_start, anchor_end) WHERE deleted_at IS NULL;
"""

_DOWNGRADE_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM drawings) THEN
    RAISE EXCEPTION '0021_drawings downgrade refused: drawings holds data';
  END IF;
END $BODY$;
DROP TABLE IF EXISTS drawings;
"""

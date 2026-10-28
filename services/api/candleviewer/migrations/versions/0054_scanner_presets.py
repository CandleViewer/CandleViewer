"""scanner_presets and `scanner` in lp_kind (E08-T09 #4708, PR 2a)

Revision ID: 0054_scanner_presets
Revises: 0053_tg_frozen_after_draft
Create Date: 2026-10-28

`docs/plan/21-database-schema.md` Sec.3.8.7 verbatim (a user's saved SCR-104 scanner criteria,
`22` `/scanner/presets*`), then the `lp_kind` block of Sec.3.8.1: `22`'s `PaneKind` lists
`scanner`, so `layout_panes.lp_kind` admits it from this revision on. One revision for both
(C-5.3), as the contract PR (#4708 PR 1) planned.

* Additive (C-5.1): a new table, two unique indexes on it, and a CHECK that admits one more value.
  `lp_kind` is replaced `NOT VALID` and validated in its own statement, so the scan of existing
  rows holds SHARE UPDATE EXCLUSIVE, not ACCESS EXCLUSIVE (C-5.6); every existing row passes it.
* `lock_timeout = 5s` both ways (C-5.6): the `users` foreign key and the `layout_panes` ALTER
  each wait at most 5 s for their lock.
* No GRANT: `cv_app` holds table-level DML from the default privileges in
  `infra/scripts/pg_bootstrap.sql`. No column holds a credential, token or PII (Sec.12, P0).
* Reversible (C-5.2): the downgrade locks both tables and refuses while any preset exists
  (dropping the table would lose a user's data) or while a layout holds a scanner pane (0022's
  `lp_kind` cannot hold it); otherwise it restores 0022's `lp_kind` and drops the table.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0054_scanner_presets"
down_revision: str | None = "0053_tg_frozen_after_draft"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_TABLE_SQL)
    op.execute(_LP_KIND_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.8.7, verbatim.
_TABLE_SQL = """
CREATE TABLE scanner_presets (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        text NOT NULL,
  filter      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- a ScannerFilter as written; never results
  sort        text NOT NULL DEFAULT 'turnover_24h', -- a ScannerSortKey
  is_default  boolean NOT NULL DEFAULT false,
  version     integer NOT NULL DEFAULT 1,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT sp_name_len     CHECK (char_length(name) BETWEEN 1 AND 80),
  CONSTRAINT sp_filter_shape CHECK (jsonb_typeof(filter) = 'object' AND octet_length(filter::text) <= 4096),
  CONSTRAINT sp_sort         CHECK (sort ~ '^[a-z][a-z0-9_]{0,39}$'),
  CONSTRAINT sp_version      CHECK (version >= 1)
);
CREATE UNIQUE INDEX ux_sp_name    ON scanner_presets (user_id, lower(name));
CREATE UNIQUE INDEX ux_sp_default ON scanner_presets (user_id) WHERE is_default;
"""

# 21-database-schema.md Sec.3.8.1, the `lp_kind` block, verbatim.
_LP_KIND_SQL = """
ALTER TABLE layout_panes
  DROP CONSTRAINT lp_kind,
  ADD CONSTRAINT lp_kind CHECK (pane_kind IN ('chart','dom','tape','profile','cvd','oi','deep_stats','regime','positions','journal','watchlist','alerts','scanner')) NOT VALID;
ALTER TABLE layout_panes VALIDATE CONSTRAINT lp_kind;
"""

# The refusals, then 0022's `lp_kind` (verbatim but for NOT VALID and its validation), then the drop.
_DOWNGRADE_SQL = """
LOCK TABLE scanner_presets, layout_panes IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM scanner_presets) THEN
    RAISE EXCEPTION '0054_scanner_presets downgrade refused: scanner_presets holds user presets, which dropping the table would lose. Fix forward with a new revision instead (C-5.2)';
  END IF;
  IF EXISTS (SELECT 1 FROM layout_panes WHERE pane_kind = 'scanner') THEN
    RAISE EXCEPTION '0054_scanner_presets downgrade refused: a layout holds a scanner pane, which the earlier lp_kind cannot hold (C-5.2)';
  END IF;
END $BODY$;
ALTER TABLE layout_panes
  DROP CONSTRAINT lp_kind,
  ADD CONSTRAINT lp_kind CHECK (pane_kind IN ('chart','dom','tape','profile','cvd','oi','deep_stats','regime','positions','journal','watchlist','alerts')) NOT VALID;
ALTER TABLE layout_panes VALIDATE CONSTRAINT lp_kind;
DROP TABLE scanner_presets;
"""

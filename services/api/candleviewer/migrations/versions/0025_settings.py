"""settings (E42-T01 #963)

Revision ID: 0025_settings
Revises: 0024_api_keys_write_once
Create Date: 2026-10-15

Purely additive (C-5.1). The `settings` table, its four named CHECKs and both unique partial
indexes are `docs/plan/21-database-schema.md` Sec.3.9 verbatim (the register's `0012_governance`
row; number 0012 was taken by `0012_onboarding_dismissals`, so this table ships alone as 0025).
`feature_flags` and `feature_flag_overrides`, which share Sec.3.9, are NOT part of this revision.

* `value` is class S when `is_secret` (Sec.12, C-5.9), so it carries a `SECRET:` column comment
  that the model mirrors verbatim; no other column can hold a credential, token or PII. This
  revision stores no secret: the table ships empty. Sealing `is_secret` values with AES-256-GCM
  and masking them in API responses (Sec.12) belongs to the settings service, not to the schema.
* No triggers: the repository sets `updated_at` (0022 precedent, D12). No GRANTs: the default
  privileges from `infra/scripts/pg_bootstrap.sql` give `cv_app` DML. No seed.
* Both `upgrade()` and `downgrade()` bracket their statements with `SET LOCAL lock_timeout =
  '5s'` (0019/0022/0023 pattern, C-5.6): the two FKs take a SHARE ROW EXCLUSIVE lock on `users`
  on the way in and dropping the table takes an ACCESS EXCLUSIVE one on the way out (measured on
  Postgres 16), so each wait is bounded instead of queueing logins. `env.py` runs all pending
  revisions in one transaction, so the setting is reset at the end of each direction.
* Downgrade locks `settings`, refuses (clear error) while it holds rows, and drops the table,
  with its indexes and constraints, when it is empty.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025_settings"
down_revision: str | None = "0024_api_keys_write_once"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_TABLE_SQL)
    op.execute(_COMMENT_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.9 (`settings` only), verbatim.
_TABLE_SQL = """
CREATE TABLE settings (
  id          uuid PRIMARY KEY,
  scope       text NOT NULL,          -- 'system' | 'user'
  user_id     uuid REFERENCES users(id) ON DELETE CASCADE,
  key         text NOT NULL,          -- dotted path, e.g. 'ui.density' | 'recorder.default_depth'
  value       jsonb NOT NULL,
  value_type  text NOT NULL,          -- string | number | boolean | object | array
  is_secret   boolean NOT NULL DEFAULT false,
  updated_by  uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT st_scope   CHECK (scope IN ('system','user')),
  CONSTRAINT st_shape   CHECK ((scope = 'user') = (user_id IS NOT NULL)),
  CONSTRAINT st_key_fmt CHECK (key ~ '^[a-z0-9_]+([.][a-z0-9_]+){0,4}$'),
  CONSTRAINT st_vtype   CHECK (value_type IN ('string','number','boolean','object','array'))
);
CREATE UNIQUE INDEX ux_settings_sys  ON settings (key) WHERE scope = 'system';
CREATE UNIQUE INDEX ux_settings_user ON settings (user_id, key) WHERE scope = 'user';
"""

# C-5.9 / Sec.12: the classification declaration. Keep byte-identical to `models.settings`.
_COMMENT_SQL = """
COMMENT ON COLUMN settings.value IS 'SECRET: when is_secret, AES-256-GCM ciphertext only (21 Sec.12); API returns it masked; never logged';
"""

_DOWNGRADE_SQL = """
LOCK TABLE settings IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM settings) THEN
    RAISE EXCEPTION '0025_settings downgrade refused: settings holds data';
  END IF;
END $BODY$;
DROP TABLE settings;
"""

"""feature_flags + feature_flag_overrides + flag_kind (E42-T03 #964)

Revision ID: 0027_feature_flags
Revises: 0026_kek_versions_env
Create Date: 2026-10-16

Purely additive (C-5.1). Both tables, their named CHECKs, the inline `key` UNIQUE and both partial
unique indexes are `docs/plan/21-database-schema.md` Sec.3.9 verbatim (the register's
`0012_governance` row; `settings`, from the same section, shipped alone as `0025_settings`).
`flag_kind` (Sec.1.2) had no earlier owner, so it is created here, its values in doc order.

* No column can hold a credential, token or PII (Sec.12 "everything else", class P0), so no column
  carries a classification comment. `feature_flag_overrides.reason` is operator free text.
* No triggers: the flag store sets `updated_at` (0022/0025 precedent). No GRANTs: the default
  privileges from `infra/scripts/pg_bootstrap.sql` give `cv_app` DML. No seed: the flag store
  inserts every registered flag at its default on start-up (E42-T03).
* Both `upgrade()` and `downgrade()` bracket their statements with `SET LOCAL lock_timeout =
  '5s'` (0019/0022/0025 pattern, C-5.6): the FKs take a SHARE ROW EXCLUSIVE lock on `users` and
  `roles` on the way in and the drops an ACCESS EXCLUSIVE one on the way out, so each wait is
  bounded instead of queueing logins. `env.py` runs all pending revisions in one transaction, so
  the setting is reset at the end of each direction.
* Downgrade locks both tables, refuses (clear error) while either holds rows, then drops the
  overrides, the flags and the type.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027_feature_flags"
down_revision: str | None = "0026_kek_versions_env"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_ENUM_SQL)
    op.execute(_TABLES_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.1.2 (`flag_kind` only), verbatim.
_ENUM_SQL = """
CREATE TYPE flag_kind           AS ENUM ('boolean','percentage','variant');
"""

# 21-database-schema.md Sec.3.9 (`feature_flags` and `feature_flag_overrides`), verbatim.
_TABLES_SQL = """
CREATE TABLE feature_flags (
  id            uuid PRIMARY KEY,
  key           text NOT NULL UNIQUE,
  kind          flag_kind NOT NULL DEFAULT 'boolean',
  description   text NOT NULL DEFAULT '',
  default_value jsonb NOT NULL DEFAULT 'false'::jsonb,
  rollout_pct   smallint,                  -- kind='percentage'
  variants      jsonb,                     -- kind='variant'
  is_killswitch boolean NOT NULL DEFAULT false,
  owner_team    text NOT NULL DEFAULT 'platform',
  expires_at    timestamptz,               -- flag debt hygiene: CI warns past this date
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ff_key   CHECK (key ~ '^[a-z0-9_]+([.][a-z0-9_]+){0,3}$'),
  CONSTRAINT ff_pct   CHECK (rollout_pct IS NULL OR rollout_pct BETWEEN 0 AND 100),
  CONSTRAINT ff_shape CHECK ((kind <> 'percentage' OR rollout_pct IS NOT NULL)
                         AND (kind <> 'variant'    OR variants IS NOT NULL))
);

CREATE TABLE feature_flag_overrides (
  id              uuid PRIMARY KEY,
  feature_flag_id uuid NOT NULL REFERENCES feature_flags(id) ON DELETE CASCADE,
  user_id         uuid REFERENCES users(id) ON DELETE CASCADE,
  role_id         uuid REFERENCES roles(id) ON DELETE CASCADE,
  value           jsonb NOT NULL,
  reason          text NOT NULL DEFAULT '',
  set_by          uuid REFERENCES users(id) ON DELETE SET NULL,
  expires_at      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ffo_target CHECK (num_nonnulls(user_id, role_id) = 1)
);
CREATE UNIQUE INDEX ux_ffo_user ON feature_flag_overrides (feature_flag_id, user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX ux_ffo_role ON feature_flag_overrides (feature_flag_id, role_id) WHERE role_id IS NOT NULL;
"""

_DOWNGRADE_SQL = """
LOCK TABLE feature_flags, feature_flag_overrides IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM feature_flags) OR EXISTS (SELECT 1 FROM feature_flag_overrides) THEN
    RAISE EXCEPTION '0027_feature_flags downgrade refused: the feature flag tables hold data';
  END IF;
END $BODY$;
DROP TABLE feature_flag_overrides;
DROP TABLE feature_flags;
DROP TYPE flag_kind;
"""

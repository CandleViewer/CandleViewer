"""a fired trade group's create-only columns are frozen (E28-T05 #909, SEC-2-04)

Revision ID: 0053_tg_frozen_after_draft
Revises: 0052_ia_purge_anchor
Create Date: 2026-10-27

`docs/plan/21-database-schema.md` Sec.3.3.2, third block, verbatim (SEC-2-04 of #3934's review).
`tg_write_once()` is replaced in place (`CREATE OR REPLACE`; the trigger stays BEFORE UPDATE, per
row and `ENABLE ALWAYS`): 0039's list stays, and once `OLD.status` is not `draft`, `symbol`, `side`,
`entry_type`, `origin`, `is_paper`, `algo_params` and `origin_rule_id` are frozen too, with 0039's
refusal (SQLSTATE 23514, the column, never a value). `origin_rule_id` may still become NULL once its
rule row is gone (the FK's `ON DELETE SET NULL`, as a leg's `account_profile_id` in 0039).
Residuals: the statement that fires a draft is the last to take a change, and a status written back
to `draft` re-opens the window (B2 has no such transition; the store writes none).

Additive (C-5.1) and reversible (C-5.2): no row changes; `downgrade()` restores 0039's function
verbatim (rollback only). `lock_timeout` (5 s) brackets both directions (C-5.6).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0053_tg_frozen_after_draft"
down_revision: str | None = "0052_ia_purge_anchor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_GUARD_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_RESTORE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.3.2, third block, verbatim.
_GUARD_SQL = """
CREATE OR REPLACE FUNCTION tg_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.env IS DISTINCT FROM OLD.env THEN 'env'
    WHEN NEW.created_by IS DISTINCT FROM OLD.created_by THEN 'created_by'
    WHEN NEW.client_group_ref IS DISTINCT FROM OLD.client_group_ref THEN 'client_group_ref'
    WHEN NEW.client_body_sha256 IS DISTINCT FROM OLD.client_body_sha256 THEN 'client_body_sha256'
    WHEN NEW.definition_id IS DISTINCT FROM OLD.definition_id THEN 'definition_id'
    WHEN NEW.leg_failure_policy IS DISTINCT FROM OLD.leg_failure_policy THEN 'leg_failure_policy'
    WHEN OLD.status <> 'draft' THEN CASE
      WHEN NEW.symbol IS DISTINCT FROM OLD.symbol THEN 'symbol'
      WHEN NEW.side IS DISTINCT FROM OLD.side THEN 'side'
      WHEN NEW.entry_type IS DISTINCT FROM OLD.entry_type THEN 'entry_type'
      WHEN NEW.origin IS DISTINCT FROM OLD.origin THEN 'origin'
      WHEN NEW.is_paper IS DISTINCT FROM OLD.is_paper THEN 'is_paper'
      WHEN NEW.algo_params IS DISTINCT FROM OLD.algo_params THEN 'algo_params'
      WHEN NEW.origin_rule_id IS DISTINCT FROM OLD.origin_rule_id
        AND (NEW.origin_rule_id IS NOT NULL
          OR EXISTS (SELECT FROM public.rules r WHERE r.id = OLD.origin_rule_id))
        THEN 'origin_rule_id'
    END
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_tg_write_once: trade_groups.% is write-once', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_tg_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
"""

# 0039's function, verbatim (its trigger and `ENABLE ALWAYS` were never touched).
_RESTORE_SQL = """
CREATE OR REPLACE FUNCTION tg_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.env IS DISTINCT FROM OLD.env THEN 'env'
    WHEN NEW.created_by IS DISTINCT FROM OLD.created_by THEN 'created_by'
    WHEN NEW.client_group_ref IS DISTINCT FROM OLD.client_group_ref THEN 'client_group_ref'
    WHEN NEW.client_body_sha256 IS DISTINCT FROM OLD.client_body_sha256 THEN 'client_body_sha256'
    WHEN NEW.definition_id IS DISTINCT FROM OLD.definition_id THEN 'definition_id'
    WHEN NEW.leg_failure_policy IS DISTINCT FROM OLD.leg_failure_policy THEN 'leg_failure_policy'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_tg_write_once: trade_groups.% is write-once', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_tg_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
"""

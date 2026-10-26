"""idempotency_anchors: a purge of recorded data anchors its key with its bound (E16-T06 #490)

Revision ID: 0052_ia_purge_anchor
Revises: 0051_replay_symbols_streams
Create Date: 2026-10-26

`docs/plan/21-database-schema.md` Sec.3.3.10, third block, verbatim. `purgeRecordedData`
(`22-api-openapi.yaml`) anchors its `Idempotency-Key` durably for its caller, with the request's
fingerprint and the exclusive upper bound `before` of the purge window, so the key outlives the
process's job store and a restart: a retry with the same key and another `before` is refused, and
one with the same body answers the first job.

* Expand (C-5.1): `before_us bigint` arrives nullable with no default; no row is rewritten.
* `ia_operation` is replaced to admit `purgeRecordedData`, and `ia_bound` ties the column to that
  operation: a purge anchor carries its bound (microseconds since the epoch, UTC, never negative),
  every other anchor none. Both are added `NOT VALID` and validated in their own statements, so
  the scan of existing rows holds SHARE UPDATE EXCLUSIVE, not ACCESS EXCLUSIVE (C-5.6). Every
  existing row passes both: each is an order operation with no bound.
* `ia_write_once()` is replaced in place (`CREATE OR REPLACE`, the trigger keeps pointing at it)
  with `before_us` among the frozen columns.
* No GRANT (`cv_app`'s table-level INSERT and SELECT cover the column) and no comment tag: the
  bound is a time, class P0 (Sec.12).
* `lock_timeout = 5s` both ways (C-5.6).
* Reversible (C-5.2): the downgrade refuses, with a clear error, while a purge anchor exists (the
  earlier `ia_operation` cannot hold it, and the anchor is permanent, Sec.7), then restores 0043's
  function body and `ia_operation` verbatim and drops `ia_bound` and the column.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0052_ia_purge_anchor"
down_revision: str | None = "0051_replay_symbols_streams"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_UPGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.3.10, third block, verbatim.
_UPGRADE_SQL = """
ALTER TABLE idempotency_anchors
  ADD COLUMN before_us bigint,
  DROP CONSTRAINT ia_operation,
  ADD CONSTRAINT ia_operation CHECK (operation IN ('placeOrder','closePosition','reversePosition','closeAllPositions','purgeRecordedData')) NOT VALID,
  ADD CONSTRAINT ia_bound CHECK ((before_us IS NOT NULL) = (operation = 'purgeRecordedData') AND (before_us IS NULL OR before_us >= 0)) NOT VALID;
ALTER TABLE idempotency_anchors VALIDATE CONSTRAINT ia_operation;
ALTER TABLE idempotency_anchors VALIDATE CONSTRAINT ia_bound;
CREATE OR REPLACE FUNCTION ia_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.created_by IS DISTINCT FROM OLD.created_by THEN 'created_by'
    WHEN NEW.operation IS DISTINCT FROM OLD.operation THEN 'operation'
    WHEN NEW.client_ref IS DISTINCT FROM OLD.client_ref THEN 'client_ref'
    WHEN NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256 THEN 'request_sha256'
    WHEN NEW.trade_group_id IS DISTINCT FROM OLD.trade_group_id THEN 'trade_group_id'
    WHEN NEW.order_id IS DISTINCT FROM OLD.order_id THEN 'order_id'
    WHEN NEW.before_us IS DISTINCT FROM OLD.before_us THEN 'before_us'
    WHEN NEW.created_at IS DISTINCT FROM OLD.created_at THEN 'created_at'
    WHEN OLD.outcome_status IS NOT NULL
      AND (NEW.outcome_status, NEW.outcome_code, NEW.outcome_ret_code, NEW.decided_at)
        IS DISTINCT FROM (OLD.outcome_status, OLD.outcome_code, OLD.outcome_ret_code, OLD.decided_at)
      THEN 'outcome'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_ia_write_once: idempotency_anchors.% is write-once', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ia_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
"""

# The refusal, then 0043's function and `ia_operation`, verbatim.
_DOWNGRADE_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM idempotency_anchors WHERE operation = 'purgeRecordedData') THEN
    RAISE EXCEPTION '0052_ia_purge_anchor downgrade refused: a purge anchor exists and anchors are permanent';
  END IF;
END $BODY$;
CREATE OR REPLACE FUNCTION ia_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.created_by IS DISTINCT FROM OLD.created_by THEN 'created_by'
    WHEN NEW.operation IS DISTINCT FROM OLD.operation THEN 'operation'
    WHEN NEW.client_ref IS DISTINCT FROM OLD.client_ref THEN 'client_ref'
    WHEN NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256 THEN 'request_sha256'
    WHEN NEW.trade_group_id IS DISTINCT FROM OLD.trade_group_id THEN 'trade_group_id'
    WHEN NEW.order_id IS DISTINCT FROM OLD.order_id THEN 'order_id'
    WHEN NEW.created_at IS DISTINCT FROM OLD.created_at THEN 'created_at'
    WHEN OLD.outcome_status IS NOT NULL
      AND (NEW.outcome_status, NEW.outcome_code, NEW.outcome_ret_code, NEW.decided_at)
        IS DISTINCT FROM (OLD.outcome_status, OLD.outcome_code, OLD.outcome_ret_code, OLD.decided_at)
      THEN 'outcome'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_ia_write_once: idempotency_anchors.% is write-once', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ia_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
ALTER TABLE idempotency_anchors
  DROP CONSTRAINT ia_bound,
  DROP CONSTRAINT ia_operation,
  ADD CONSTRAINT ia_operation CHECK (operation IN ('placeOrder','closePosition','reversePosition','closeAllPositions')) NOT VALID;
ALTER TABLE idempotency_anchors VALIDATE CONSTRAINT ia_operation;
ALTER TABLE idempotency_anchors DROP COLUMN before_us;
"""

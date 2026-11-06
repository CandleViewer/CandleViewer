"""closed_pnl_records; executions.closed_size; position_snapshots.exchange_updated_ts (E29-S06)

Revision ID: 0070_closed_pnl_records
Revises: 0064_orders_origin
Create Date: 2026-11-03

E29-S06 (#981) slice 2: the store of 24 Sec.8.13. `docs/plan/21-database-schema.md` Sec.3.3.13's
block verbatim, then the second blocks of Sec.3.3.6 and Sec.3.3.7 verbatim; 0003, 0004, 0017,
0029 and 0039 made what they name. The store is `storage.repositories.closed_pnl`; no writer sets
the two columns yet.

* `trg_cpr_guard` (BEFORE UPDATE, `ENABLE ALWAYS`, `search_path` pinned) refuses with SQLSTATE
  23514, naming itself and the column, a change to the record's identity, a `settled_at` or
  `final_at` once set, and once `final_at` is set a change to the venue's columns. It refuses no
  change to `trade_group_id`, the composition's alone, final or not. The DELETE and TRUNCATE
  triggers keep every row, and `cv_app` loses DELETE and TRUNCATE where it exists (the 0024
  idiom). Every `numeric` column and `executions.closed_size` carry 0029's P1 comment (C-5.9);
  `trade_group_id`, an id, is P0 and carries none.
* One transaction, `lock_timeout` (5 s) bounding every lock wait (C-5.6): SHARE ROW EXCLUSIVE on
  `exchange_accounts` and `trade_groups` for the two FKs, and ACCESS EXCLUSIVE on `executions`
  and `position_snapshots`, held for their catalogue changes, `ex_closed`'s validating scan (it is
  added `NOT VALID`, then validated) and the two index builds. The columns are nullable, with no
  default and no backfill (Sec.9.3 rule 2). `ix_exec_walk` and `ix_psnap_flat` are plain builds,
  not CONCURRENTLY, which would wait for the snapshot a second booting process holds while it
  waits for the migration lock (`0034_order_vocabulary`); both tables are far below Sec.9.3 rule
  3's 1 M rows (Sec.11.3).
* The downgrade (C-5.2) refuses while a record, a `closed_size` or an `exchange_updated_ts` is
  stored, as a stored fill is never written again (`trg_exec_append`); otherwise it drops it all.

Its number is 0070, the slot assigned to it, on `0064_orders_origin`: it re-parents onto the head
below it at a rebase when a lower revision lands first (C-5.3), with its lockfile entry.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0070_closed_pnl_records"
down_revision: str | None = "0064_orders_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOCK_ON, _LOCK_OFF = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"


def upgrade() -> None:
    op.execute(_LOCK_ON)
    op.execute(_TABLE_SQL)
    op.execute(_GUARD_SQL)
    op.execute(_REVOKE_SQL)
    op.execute(_COLUMNS_SQL)
    op.execute(_COMMENT_SQL)
    op.execute(_LOCK_OFF)


def downgrade() -> None:
    op.execute(_LOCK_ON)
    op.execute(_REFUSE_SQL)
    op.execute(_DROP_SQL)
    op.execute(_LOCK_OFF)


# 21-database-schema.md Sec.3.3.13, the block, verbatim: the table, its indexes and its triggers.
_TABLE_SQL = """
CREATE TABLE closed_pnl_records (
  id                  uuid PRIMARY KEY,         -- uuid5 (24 §8.13): one id, provisional to settled
  exchange_account_id uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE RESTRICT,
  exchange_order_id   text,                     -- the closing order's venue id; NULL: the venue wrote none
  symbol              symbol_code NOT NULL,
  side                text NOT NULL,            -- the closed position's
  position_idx        smallint,                 -- the walk's key, its order rows'; NULL when nothing local composes it
  trade_group_id      uuid REFERENCES trade_groups(id) ON DELETE RESTRICT, -- the position's group (24 §8.13); NULL: none or several
  qty                 numeric(38,18),           -- the size closed: the closing fills' while provisional
  avg_entry_price     numeric(38,18),
  avg_exit_price      numeric(38,18),
  leverage            numeric(10,2),            -- the venue's; NULL while provisional
  closed_pnl          numeric(38,18),           -- the venue's figure; NULL while provisional
  gross_pnl           numeric(38,18),           -- the local composition (24 §8.13); NULL: not composed
  fee_pnl             numeric(38,18),
  funding_pnl         numeric(38,18),
  opened_at           timestamptz,              -- the walk's, never the venue's createdTime
  closed_at           timestamptz NOT NULL,     -- the venue's updatedTime once read, else the last closing fill's
  venue_created_at    timestamptz,              -- the venue's createdTime: the closing order's creation
  settled_at          timestamptz,              -- the venue's record stored; NULL: provisional
  final_at            timestamptz,              -- the record final (24 §8.13): the venue's columns frozen
  divergent           boolean NOT NULL DEFAULT false,
  audited_local_net   numeric(38,18),           -- the pair pnl.divergence_detected last recorded
  audited_closed_pnl  numeric(38,18),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT cpr_side    CHECK (side IN ('long','short')),
  CONSTRAINT cpr_posidx  CHECK (position_idx IS NULL OR position_idx IN (0,1,2)),
  CONSTRAINT cpr_order   CHECK (exchange_order_id IS NULL OR char_length(exchange_order_id) BETWEEN 1 AND 64),
  CONSTRAINT cpr_settled CHECK (CASE WHEN settled_at IS NULL
                                THEN exchange_order_id IS NOT NULL AND closed_pnl IS NULL AND leverage IS NULL
                                     AND venue_created_at IS NULL
                                ELSE closed_pnl IS NOT NULL AND qty IS NOT NULL AND avg_entry_price IS NOT NULL
                                     AND avg_exit_price IS NOT NULL AND leverage IS NOT NULL
                                     AND venue_created_at IS NOT NULL END),
  CONSTRAINT cpr_final   CHECK (final_at IS NULL OR (settled_at IS NOT NULL AND exchange_order_id IS NOT NULL
                                AND final_at >= settled_at)),
  CONSTRAINT cpr_qty     CHECK (qty IS NULL OR qty > 0),
  CONSTRAINT cpr_pair    CHECK ((audited_local_net IS NULL) = (audited_closed_pnl IS NULL)
                                AND (NOT divergent OR (settled_at IS NOT NULL AND audited_closed_pnl IS NOT NULL))),
  CONSTRAINT cpr_numbers CHECK (NOT ('NaN'::numeric IN (qty, avg_entry_price, avg_exit_price, leverage, closed_pnl,
                                gross_pnl, fee_pnl, funding_pnl, audited_local_net, audited_closed_pnl)))
);
CREATE UNIQUE INDEX ux_cpr_order ON closed_pnl_records (exchange_account_id, exchange_order_id)
  WHERE exchange_order_id IS NOT NULL;
CREATE INDEX ix_cpr_day     ON closed_pnl_records (exchange_account_id, closed_at, id);
CREATE INDEX ix_cpr_pending ON closed_pnl_records (exchange_account_id, closed_at)
  WHERE final_at IS NULL AND exchange_order_id IS NOT NULL;
CREATE INDEX ix_cpr_group   ON closed_pnl_records (exchange_account_id, trade_group_id, closed_at)
  WHERE trade_group_id IS NOT NULL;
CREATE TRIGGER trg_cpr_no_delete BEFORE DELETE ON closed_pnl_records
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER trg_cpr_no_truncate BEFORE TRUNCATE ON closed_pnl_records
  FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();
ALTER TABLE closed_pnl_records ENABLE ALWAYS TRIGGER trg_cpr_no_delete;
ALTER TABLE closed_pnl_records ENABLE ALWAYS TRIGGER trg_cpr_no_truncate;
"""

# Sec.3.3.13 "Writes": the guard; until `final_at` the venue's columns stay writable, and the
# local figures, `trade_group_id` and `divergent` with its pair always do.
_GUARD_SQL = """
CREATE FUNCTION cpr_guard() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.exchange_account_id IS DISTINCT FROM OLD.exchange_account_id THEN 'exchange_account_id'
    WHEN NEW.exchange_order_id IS DISTINCT FROM OLD.exchange_order_id THEN 'exchange_order_id'
    WHEN NEW.symbol IS DISTINCT FROM OLD.symbol THEN 'symbol'
    WHEN NEW.side IS DISTINCT FROM OLD.side THEN 'side'
    WHEN OLD.settled_at IS NOT NULL AND NEW.settled_at IS DISTINCT FROM OLD.settled_at THEN 'settled_at'
    WHEN OLD.final_at IS NOT NULL AND NEW.final_at IS DISTINCT FROM OLD.final_at THEN 'final_at'
    WHEN OLD.final_at IS NULL THEN NULL  -- not final: the venue's columns may still change
    WHEN NEW.qty IS DISTINCT FROM OLD.qty THEN 'qty'
    WHEN NEW.avg_entry_price IS DISTINCT FROM OLD.avg_entry_price THEN 'avg_entry_price'
    WHEN NEW.avg_exit_price IS DISTINCT FROM OLD.avg_exit_price THEN 'avg_exit_price'
    WHEN NEW.leverage IS DISTINCT FROM OLD.leverage THEN 'leverage'
    WHEN NEW.closed_pnl IS DISTINCT FROM OLD.closed_pnl THEN 'closed_pnl'
    WHEN NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN 'closed_at'
    WHEN NEW.venue_created_at IS DISTINCT FROM OLD.venue_created_at THEN 'venue_created_at'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_cpr_guard: closed_pnl_records.% may not change so', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_cpr_guard';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_cpr_guard BEFORE UPDATE ON closed_pnl_records
  FOR EACH ROW EXECUTE FUNCTION cpr_guard();
ALTER TABLE closed_pnl_records ENABLE ALWAYS TRIGGER trg_cpr_guard;
"""

# Sec.3.3.13 "Grants": the 0024 idiom, where `pg_bootstrap.sql` made the role.
_REVOKE_SQL = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'REVOKE DELETE, TRUNCATE ON closed_pnl_records FROM cv_app'; END IF; END $BODY$;"
)

# Sec.3.3.6 and Sec.3.3.7, the second blocks, verbatim: both builds in this transaction.
_COLUMNS_SQL = """
ALTER TABLE executions ADD COLUMN closed_size numeric(38,18);
ALTER TABLE executions ADD CONSTRAINT ex_closed CHECK (closed_size IS NULL OR closed_size BETWEEN 0 AND exec_qty) NOT VALID;
ALTER TABLE executions VALIDATE CONSTRAINT ex_closed;
CREATE INDEX ix_exec_walk ON executions (exchange_account_id, symbol, exec_ts, exec_id);
ALTER TABLE position_snapshots ADD COLUMN exchange_updated_ts timestamptz;
CREATE INDEX ix_psnap_flat ON position_snapshots (exchange_account_id, symbol, position_idx, exchange_updated_ts)
  WHERE size = 0 AND exchange_updated_ts IS NOT NULL;
"""

# C-5.9 / Sec.12, class P1: 0029's money comment, byte-identical to `db.models` (`alembic check`).
_MONEY_COMMENT = "PII: financial personal data (21 Sec.12, class P1); never sent to third parties"
_COMMENTED = (
    "closed_pnl_records.qty", "closed_pnl_records.avg_entry_price", "closed_pnl_records.avg_exit_price",
    "closed_pnl_records.leverage", "closed_pnl_records.closed_pnl", "closed_pnl_records.gross_pnl",
    "closed_pnl_records.fee_pnl", "closed_pnl_records.funding_pnl",
    "closed_pnl_records.audited_local_net", "closed_pnl_records.audited_closed_pnl",
    "executions.closed_size",
)  # fmt: skip
_COMMENT_SQL = "\n".join(f"COMMENT ON COLUMN {c} IS '{_MONEY_COMMENT}';" for c in _COMMENTED)

_REFUSE_SQL = """
LOCK TABLE closed_pnl_records, executions, position_snapshots IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM closed_pnl_records)
     OR EXISTS (SELECT 1 FROM executions WHERE closed_size IS NOT NULL)
     OR EXISTS (SELECT 1 FROM position_snapshots WHERE exchange_updated_ts IS NOT NULL) THEN
    RAISE EXCEPTION '0070_closed_pnl_records downgrade refused: a closed-PnL record, a fill''s closed size or a venue-dated position reading is stored, and a stored fill is never written again, so dropping them would lose them for good. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
"""

_DROP_SQL = """
DROP INDEX ix_psnap_flat;
ALTER TABLE position_snapshots DROP COLUMN exchange_updated_ts;
DROP INDEX ix_exec_walk;
ALTER TABLE executions DROP CONSTRAINT ex_closed;
ALTER TABLE executions DROP COLUMN closed_size;
DROP TABLE closed_pnl_records;
DROP FUNCTION cpr_guard();
"""

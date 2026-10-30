"""oms_handovers: what a lookup or the private stream hands to the next reconciliation pass (E29-T06)

Revision ID: 0058_oms_handovers
Create Date: 2026-10-30

E29-T06 (#914), PR 1 of 3, contract first. The table is `docs/plan/21-database-schema.md`
Sec.3.3.12 verbatim (24 Sec.8.3 rule 7): the orders a lookup or a reconciliation mismatch finds
under a row's id that are not that row's, and the trade executions no row takes, kept for the next
pass in Postgres, never process memory only, so they survive a restart. Nothing writes it yet: the
store is unbound until E29-T06's wiring replaces `NoHandoverStore`. `exchange_accounts` (0017)
exists already.

* `ux_oh_order` and `ux_oh_exec` make an entry idempotent on (account, orderId) and (account,
  exec_id); `oh_record` ties those keys to what the entry's `record` names, so an entry never names
  one account, order or fill while holding another's (C-2.11, SR-E29-03).
* The bound per account (1,000 entries) and its overflow policy (refused, never dropped silently)
  are the store's, under the account's advisory lock (21 Sec.3.3.12).
* `trg_oh_guard` (BEFORE UPDATE, `ENABLE ALWAYS`, its `search_path` pinned) refuses with SQLSTATE
  23514, naming itself, a change to the entry itself, a count that goes down and a stamp that
  changes once set.
* No GRANT and no REVOKE: `cv_app` keeps DELETE from `infra/scripts/pg_bootstrap.sql`'s default
  privileges, since entries are pruned once paired or recorded.
* C-5.9 / Sec.12, class P1: `record` and `payload` can repeat an order's or a fill's money values,
  so each carries a `PII:` comment, which `db.models` mirrors byte for byte.
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): the FK takes a SHARE ROW
  EXCLUSIVE lock on `exchange_accounts` for the transaction, and every index is built on the new,
  empty table.
* The downgrade (C-5.2) locks the table and refuses while any entry exists, since dropping it would
  lose hand-overs nobody has recorded elsewhere; an empty table is dropped with its guard.

Its number is 0058, on `0057_se_component_statechart` (#1025), and the lockfile entry pins it
(C-5.3).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0058_oms_handovers"
down_revision: str | None = "0057_se_component_statechart"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_TABLE_SQL)
    op.execute(_GUARD_SQL)
    op.execute(_COMMENT_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_REFUSE_SQL)
    op.execute(_DROP_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.3.12, first block, verbatim: the table and its indexes.
_TABLE_SQL = """
CREATE TABLE oms_handovers (
  id                   bigserial PRIMARY KEY,
  exchange_account_id  uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE RESTRICT,
  kind                 text NOT NULL,
  exchange_order_id    text NOT NULL,
  exec_id              text,
  source               text NOT NULL,
  record               jsonb NOT NULL,
  payload              jsonb NOT NULL DEFAULT '{}'::jsonb,
  empty_reads          smallint NOT NULL DEFAULT 0,
  first_empty_read_at  timestamptz,
  decided_at           timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT oh_kind    CHECK (kind IN ('order','execution')),
  CONSTRAINT oh_exec    CHECK ((kind = 'execution') = (exec_id IS NOT NULL)),
  CONSTRAINT oh_source  CHECK (source IN ('ws_private','rest','reconcile')),
  CONSTRAINT oh_ids     CHECK (char_length(exchange_order_id) BETWEEN 1 AND 64
    AND (exec_id IS NULL OR char_length(exec_id) BETWEEN 1 AND 64)),
  CONSTRAINT oh_record  CHECK (jsonb_typeof(record) = 'object'
    AND record->>'account_id' IS NOT DISTINCT FROM exchange_account_id::text
    AND record->>'exchange_order_id' IS NOT DISTINCT FROM exchange_order_id
    AND (exec_id IS NULL OR record->>'exec_id' IS NOT DISTINCT FROM exec_id)),
  CONSTRAINT oh_payload CHECK (jsonb_typeof(payload) = 'object'),
  CONSTRAINT oh_reads   CHECK (empty_reads >= 0
    AND (empty_reads = 0) = (first_empty_read_at IS NULL)
    AND (kind = 'execution' OR (empty_reads = 0 AND decided_at IS NULL)))
);
CREATE UNIQUE INDEX ux_oh_order ON oms_handovers (exchange_account_id, exchange_order_id)
  WHERE kind = 'order';
CREATE UNIQUE INDEX ux_oh_exec  ON oms_handovers (exchange_account_id, exec_id)
  WHERE kind = 'execution';
CREATE INDEX ix_oh_account ON oms_handovers (exchange_account_id, kind, id);
"""

# Sec.3.3.12, second block, verbatim: the guard.
_GUARD_SQL = """
CREATE FUNCTION oh_guard() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN (NEW.id, NEW.exchange_account_id, NEW.kind, NEW.exchange_order_id, NEW.exec_id, NEW.source,
          NEW.record, NEW.payload, NEW.created_at)
      IS DISTINCT FROM (OLD.id, OLD.exchange_account_id, OLD.kind, OLD.exchange_order_id, OLD.exec_id,
          OLD.source, OLD.record, OLD.payload, OLD.created_at) THEN 'entry'
    WHEN NEW.empty_reads < OLD.empty_reads THEN 'empty_reads'
    WHEN OLD.first_empty_read_at IS NOT NULL
      AND NEW.first_empty_read_at IS DISTINCT FROM OLD.first_empty_read_at THEN 'first_empty_read_at'
    WHEN OLD.decided_at IS NOT NULL AND NEW.decided_at IS DISTINCT FROM OLD.decided_at THEN 'decided_at'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_oh_guard: oms_handovers.% may not change so', changed
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_oh_guard';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_oh_guard BEFORE UPDATE ON oms_handovers
  FOR EACH ROW EXECUTE FUNCTION oh_guard();
ALTER TABLE oms_handovers ENABLE ALWAYS TRIGGER trg_oh_guard;
"""

# C-5.9 / Sec.12, class P1. Keep the text byte-identical to `db.models` (`alembic check` diffs
# comments): no quote, as it sits in a SQL string literal.
_P1_COMMENT = (
    "PII: an order or a fill as the exchange reported it, which can repeat its money values "
    "(21 Sec.12, class P1); payload redacted before insert; never logged"
)
_COMMENT_SQL = "\n".join(
    f"COMMENT ON COLUMN oms_handovers.{column} IS '{_P1_COMMENT}';"
    for column in ("record", "payload")
)

_REFUSE_SQL = """
LOCK TABLE oms_handovers IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM oms_handovers) THEN
    RAISE EXCEPTION '0058_oms_handovers downgrade refused: oms_handovers holds hand-overs to the next reconciliation pass, which dropping the table would lose. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
"""

_DROP_SQL = """
DROP TABLE oms_handovers;
DROP FUNCTION oh_guard();
"""

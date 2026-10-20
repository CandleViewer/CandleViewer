"""machine_snapshots, machine_drain_journal, machine_events: the payload columns become json (#3857)

Revision ID: 0035_machine_persistence_json
Create Date: 2026-10-20

`docs/plan/24-internal-schemas.md` Sec.17.6, "Payload columns are `json`, not `jsonb`": the seal
(CV-C53) covers `canonical_json` of `machine_snapshots.snapshot`, and `row_hash` the canonical JSON
of a `machine_events` row, `payload` and `fault` included. `jsonb` stores numbers as `numeric` and
re-renders them, so `1e16` read back as the integer `10000000000000000` and `-0.0` as `0.0`, and a
read-back value stopped verifying. `json` keeps the text as written. The drain journal's `payload`
is the restored event, so it changes too. No row exists in any deployment (nothing writes these
tables before the E50-T62 stores), so there is no backfill; the `USING` casts still convert a row.

* `json` has no equality operator, and `machine_drain_journal_stamp_once()` compares every frozen
  column with IS DISTINCT FROM, so after the type change any UPDATE of the journal, the stamp
  included, would fail (42883). The function is replaced with 0033's body comparing `payload` by
  its text: the same text written over itself passes, any other change is refused. The trigger,
  its `ENABLE ALWAYS`, the grants, the comments, the CHECKs, the keys and the indexes stay (no
  index names these columns; `me_fault_phase`'s `fault IS NOT NULL` holds for `json`).
* Not additive (C-5.1): an in-place type change of tables that no deployed reader or writer uses,
  which the orchestrator ruled on 2026-10-20 (#3857); the tables are empty in every deployment.
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): each ALTER rewrites its table
  under ACCESS EXCLUSIVE, at once on the empty tables.
* The number lives in `revision` and this file's name, the parent in `down_revision` alone (the
  lockfile mirrors both), so renumbering or re-parenting touches only those.
* The downgrade first locks the three tables in SHARE mode and refuses, naming the table, while any
  of them holds a row (0033's guard, C-5.2): the cast back to `jsonb` would re-render the sealed
  numbers, and their seals and row hashes would fail for good, so a populated database fixes
  forward. An empty database is downgraded symmetrically: 0033's function, then the four columns
  back to `jsonb`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "0035_machine_persistence_json"
down_revision: str | None = "0034_order_vocabulary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The tables whose columns this revision alters, named as literals so the migration lint's
#: CI-MIG-006 flag (`tools/ci/security-sensitive-tables.txt`) asks for a security review: it
#: matches quoted names only, and the SQL below names them unquoted.
ALTERED_TABLES: Final = ("machine_snapshots", "machine_drain_journal", "machine_events")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_TO_JSON_SQL)
    op.execute(_GUARD_BY_TEXT_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_REFUSE_IF_POPULATED_SQL)
    op.execute(_GUARD_AS_CREATED_SQL)
    op.execute(_TO_JSONB_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


_TO_JSON_SQL = """
ALTER TABLE machine_snapshots ALTER COLUMN snapshot TYPE json USING snapshot::json;
ALTER TABLE machine_drain_journal ALTER COLUMN payload TYPE json USING payload::json;
ALTER TABLE machine_events
  ALTER COLUMN payload TYPE json USING payload::json,
  ALTER COLUMN fault TYPE json USING fault::json;
"""

# 0033's downgrade guard: the refusal names the table, never a value. Static literals, like 0033's.
_REFUSE_IF_POPULATED_SQL = """
LOCK TABLE machine_snapshots, machine_drain_journal, machine_events IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM machine_snapshots) THEN
    RAISE EXCEPTION 'machine_persistence_json downgrade refused: machine_snapshots holds rows; casting them back to jsonb would re-render sealed numbers, so fix forward with a new revision instead (C-5.2)';
  END IF;
  IF EXISTS (SELECT 1 FROM machine_drain_journal) THEN
    RAISE EXCEPTION 'machine_persistence_json downgrade refused: machine_drain_journal holds rows; casting them back to jsonb would re-render sealed numbers, so fix forward with a new revision instead (C-5.2)';
  END IF;
  IF EXISTS (SELECT 1 FROM machine_events) THEN
    RAISE EXCEPTION 'machine_persistence_json downgrade refused: machine_events holds rows; casting them back to jsonb would re-render sealed numbers, so fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
"""

_TO_JSONB_SQL = """
ALTER TABLE machine_events
  ALTER COLUMN fault TYPE jsonb USING fault::jsonb,
  ALTER COLUMN payload TYPE jsonb USING payload::jsonb;
ALTER TABLE machine_drain_journal ALTER COLUMN payload TYPE jsonb USING payload::jsonb;
ALTER TABLE machine_snapshots ALTER COLUMN snapshot TYPE jsonb USING snapshot::jsonb;
"""

# 0033's `machine_drain_journal_stamp_once()` with the `payload` arm by text. Static literals, like
# 0033's: SQL built from strings at runtime trips bandit B608. The unit test pins both bodies to
# 0033's own render, so they can only differ in that one arm.
_GUARD_BY_TEXT_SQL = """
CREATE OR REPLACE FUNCTION machine_drain_journal_stamp_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.machine_kind IS DISTINCT FROM OLD.machine_kind THEN 'machine_kind'
    WHEN NEW.entity_id IS DISTINCT FROM OLD.entity_id THEN 'entity_id'
    WHEN NEW.env IS DISTINCT FROM OLD.env THEN 'env'
    WHEN NEW.send_id IS DISTINCT FROM OLD.send_id THEN 'send_id'
    WHEN NEW.lane IS DISTINCT FROM OLD.lane THEN 'lane'
    WHEN NEW.ordinal IS DISTINCT FROM OLD.ordinal THEN 'ordinal'
    WHEN NEW.event_type IS DISTINCT FROM OLD.event_type THEN 'event_type'
    WHEN NEW.payload::text IS DISTINCT FROM OLD.payload::text THEN 'payload'
    WHEN NEW.receipt_error IS DISTINCT FROM OLD.receipt_error THEN 'receipt_error'
    WHEN OLD.replayed_at IS NOT NULL
      AND NEW.replayed_at IS DISTINCT FROM OLD.replayed_at THEN 'replayed_at'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_mdj_stamp_once: machine_drain_journal.% is %', changed,
      CASE WHEN changed = 'replayed_at' THEN 'set-once' ELSE 'write-once' END
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $BODY$;
"""

_GUARD_AS_CREATED_SQL = """
CREATE OR REPLACE FUNCTION machine_drain_journal_stamp_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.machine_kind IS DISTINCT FROM OLD.machine_kind THEN 'machine_kind'
    WHEN NEW.entity_id IS DISTINCT FROM OLD.entity_id THEN 'entity_id'
    WHEN NEW.env IS DISTINCT FROM OLD.env THEN 'env'
    WHEN NEW.send_id IS DISTINCT FROM OLD.send_id THEN 'send_id'
    WHEN NEW.lane IS DISTINCT FROM OLD.lane THEN 'lane'
    WHEN NEW.ordinal IS DISTINCT FROM OLD.ordinal THEN 'ordinal'
    WHEN NEW.event_type IS DISTINCT FROM OLD.event_type THEN 'event_type'
    WHEN NEW.payload IS DISTINCT FROM OLD.payload THEN 'payload'
    WHEN NEW.receipt_error IS DISTINCT FROM OLD.receipt_error THEN 'receipt_error'
    WHEN OLD.replayed_at IS NOT NULL
      AND NEW.replayed_at IS DISTINCT FROM OLD.replayed_at THEN 'replayed_at'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_mdj_stamp_once: machine_drain_journal.% is %', changed,
      CASE WHEN changed = 'replayed_at' THEN 'set-once' ELSE 'write-once' END
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $BODY$;
"""

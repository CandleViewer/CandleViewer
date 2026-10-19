"""order_state and order_event_kind grow; orders.lifecycle_state keeps the B1 state (E29-T03 #847)

Revision ID: 0033_order_vocabulary
Revises: 0032_backups_write_once
Create Date: 2026-10-19

Slice 2 of the #847 plan, main-orchestrator's ruling 2 (2026-10-19): the persisted order
vocabulary grows by additions only (C-5.1), so REST and WS keep their names. DDL:
`docs/plan/21-database-schema.md` Sec.1.2 and Sec.3.3.4's second block, verbatim.

* `order_state` gains `triggered`, `unknown`, `quarantined`, `killed` and `held`, the B1 order
  chart's states it had no value for, and `order_event_kind` gains `kill` and `adopt`, appended
  (Sec.9.3 rule 7). `24-internal-schemas.md` Sec.8.2 maps each chart state to one value.
* `order_lifecycle_state` holds the chart's `lifecycle` states verbatim and the new nullable
  `orders.lifecycle_state` an order's, so no reader of `orders` inverts the mapping (whose
  `submitted` is the chart's `submitting`). `ord_lifecycle` admits only the pairs of that mapping,
  so the two columns never disagree. No default, so no rewrite (Sec.9.3 rule 2); no backfill, as
  nothing writes `orders` yet (E29-T04 wires the OMS). No write path sets the column yet: #847's
  remaining implementation PR sets it, beside `state`, on every path.
* `ix_orders_open`, which `list_open` reads, is rebuilt with three of the four new non-terminal
  values: `held`, like `untracked`, holds an order the OMS does not own (B1's INV-B1-n), so it is
  not open.

Postgres 16 refuses a new enum value in the transaction that added it (55P04) and the index names
them, so the `ADD VALUE`s commit in an autocommit block first (Sec.9.3 rule 6); the rest is one
transaction with the version stamp. A failure after the block keeps the values (none can be
dropped), so the block skips a value the type already holds and a rerun completes (`--sql`
renders all seven). Each `ADD VALUE` is built from its (type, label) pair in `_ADDED`. The index
is not built CONCURRENTLY: that waits for every transaction of the database holding an older
snapshot, and a second booting API process holds one while it waits for the `cv_migrations`
advisory lock (`migrations/boot.py`), so the two boots would wait on each other. The plain build
holds SHARE on `orders`, which nothing writes yet (Sec.9.3 rule 3: CONCURRENTLY over 1 M rows).
`lock_timeout` (5 s) bounds every lock wait (C-5.6).

The downgrade refuses while a row holds an added `order_state` or `order_event_kind` value, or a
`lifecycle_state` (C-5.2): it would lose its state or its history. Otherwise it drops the column
(and `ord_lifecycle` with it) and the type and swaps each enum for one with 0029's values (no enum
value can be dropped), which rewrites `orders` and `order_events`; the two partial indexes naming
`order_state` values are rebuilt as 0029 made them.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033_order_vocabulary"
down_revision: str | None = "0032_backups_write_once"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s';")
        for pair in _not_yet_added(_ADDED):
            op.execute(_add_value(pair))
        op.execute("RESET lock_timeout;")
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_LIFECYCLE_TYPE_SQL)
    op.execute(_ORDERS_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def _not_yet_added(added: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    """The (type, label) pairs whose label the type lacks. Online, a rerun skips the labels a
    failed run committed; offline (`--sql`) there is no database to read, so all are rendered."""
    if op.get_context().as_sql:
        return added
    present = {(str(t), str(v)) for t, v in op.get_bind().exec_driver_sql(_PRESENT_SQL)}
    return tuple(pair for pair in added if pair not in present)


def _add_value(pair: tuple[str, str]) -> str:
    """The `ADD VALUE` of one `_ADDED` pair; both parts are this module's constants, never input."""
    enum_type, label = pair
    return f"ALTER TYPE {enum_type} ADD VALUE '{label}';"


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_REFUSE_SQL)
    op.execute(_RESTORE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.1.2's seven `ADD VALUE`s, as (type, label) pairs in their order there.
_ADDED: tuple[tuple[str, str], ...] = (
    ("order_state", "triggered"),
    ("order_state", "unknown"),
    ("order_state", "quarantined"),
    ("order_state", "killed"),
    ("order_state", "held"),
    ("order_event_kind", "kill"),
    ("order_event_kind", "adopt"),
)
# The labels the two types hold, named as `ALTER TYPE` resolves them (through the search path).
_PRESENT_SQL = (
    "SELECT enumtypid::regtype::text, enumlabel FROM pg_enum "
    "WHERE enumtypid IN ('order_state'::regtype, 'order_event_kind'::regtype)"
)
_LIFECYCLE_TYPE_SQL = """
CREATE TYPE order_lifecycle_state AS ENUM ('draft','validated','submitting','submitted','triggered','partially_filled','cancel_pending','amend_pending','unknown','quarantined','untracked','held','filled','cancelled','rejected','expired','killed');
"""

# 21-database-schema.md Sec.3.3.4, second block, verbatim. `ord_lifecycle`'s pairs are
# `ORDER_STATE_OF` (24-internal-schemas.md Sec.8.2), pinned by a unit test.
_ORDERS_SQL = """
ALTER TABLE orders ADD COLUMN lifecycle_state order_lifecycle_state;
ALTER TABLE orders ADD CONSTRAINT ord_lifecycle CHECK (lifecycle_state IS NULL OR (lifecycle_state, state) IN (('draft','new'),('validated','pending_submit'),('submitting','submitted'),('submitted','accepted'),('triggered','triggered'),('partially_filled','partially_filled'),('cancel_pending','pending_cancel'),('amend_pending','pending_amend'),('unknown','unknown'),('quarantined','quarantined'),('untracked','untracked'),('held','held'),('filled','filled'),('cancelled','cancelled'),('rejected','rejected'),('expired','expired'),('killed','killed')));
DROP INDEX ix_orders_open;
CREATE INDEX ix_orders_open      ON orders (exchange_account_id, symbol)
  WHERE state IN ('pending_submit','submitted','accepted','partially_filled','pending_cancel','pending_amend','triggered','unknown','quarantined');
"""

_REFUSE_SQL = """
LOCK TABLE orders, order_events IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM orders WHERE lifecycle_state IS NOT NULL
               OR state IN ('triggered','unknown','quarantined','killed','held'))
     OR EXISTS (SELECT 1 FROM order_events WHERE kind IN ('kill','adopt')
               OR from_state IN ('triggered','unknown','quarantined','killed','held')
               OR to_state IN ('triggered','unknown','quarantined','killed','held')) THEN
    RAISE EXCEPTION '0033_order_vocabulary downgrade refused: a row holds an order state, an event kind or a lifecycle_state that 0032 has no value for, so the order would lose its state or its history. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
"""

# The types as 0029_oms_core created them, and the two partial indexes that name their values.
_RESTORE_SQL = """
DROP INDEX ix_orders_open;
DROP INDEX ix_orders_untracked;
ALTER TABLE orders DROP COLUMN lifecycle_state;
DROP TYPE order_lifecycle_state;
ALTER TYPE order_state RENAME TO order_state_0033;
CREATE TYPE order_state AS ENUM ('new','pending_submit','submitted','accepted','partially_filled','filled','pending_cancel','cancelled','pending_amend','rejected','expired','untracked');
ALTER TABLE orders ALTER COLUMN state DROP DEFAULT;
ALTER TABLE orders ALTER COLUMN state TYPE order_state USING state::text::order_state;
ALTER TABLE orders ALTER COLUMN state SET DEFAULT 'new';
ALTER TABLE order_events
  ALTER COLUMN from_state TYPE order_state USING from_state::text::order_state,
  ALTER COLUMN to_state TYPE order_state USING to_state::text::order_state;
DROP TYPE order_state_0033;
ALTER TYPE order_event_kind RENAME TO order_event_kind_0033;
CREATE TYPE order_event_kind AS ENUM ('local_create','submit_attempt','ack','reject','fill','partial_fill','amend_request','amend_ack','cancel_request','cancel_ack','expire','exchange_push','reconcile_diff','error');
ALTER TABLE order_events ALTER COLUMN kind TYPE order_event_kind USING kind::text::order_event_kind;
DROP TYPE order_event_kind_0033;
CREATE INDEX ix_orders_open      ON orders (exchange_account_id, symbol)
  WHERE state IN ('pending_submit','submitted','accepted','partially_filled','pending_cancel','pending_amend');
CREATE INDEX ix_orders_untracked ON orders (exchange_account_id) WHERE state = 'untracked';
"""

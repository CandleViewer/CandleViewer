"""orders.origin and orders.origin_ref: where an order's intent came from (E35-T11, #5003)

Revision ID: 0064_orders_origin
Revises: 0063_rule_version_account_refs
Create Date: 2026-11-01

`orders.origin` and `orders.origin_ref`, nullable `text` with no default (21 Sec.3.3.4 "Origin",
24 Sec.8.1 `Order.origin`): the OMS writes both at insert from the server-only
`SubmitContext.origin`, and no writer updates them. A rule action's order, an entry or a
reduce-only order alike, is `origin = 'rule'` with the rule's id in `origin_ref`. A create a
restart resumes has no request, so the command port reads the row's `origin` for its rate lane: a
rule's order rides `entry`, never the `critical` reserve (24 Sec.8.4 "Rule-originated orders",
C-12.7).

* Two CHECKs, each NULL-safe. `ord_origin` admits NULL or 24 Sec.8.1's seven values.
  `ord_origin_ref` makes `origin_ref` NULL while `origin` is NULL, a canonical lower-case UUID
  while `origin` is `rule`, and leaves it free for any other origin; it is a `CASE`, so no arm
  meets a NULL comparison that a CHECK would pass.
* No default, no backfill and no rewrite: `ADD COLUMN` of a nullable column with no default
  changes only the catalogue, and every existing row holds NULL in both, which both CHECKs admit.
  Each CHECK is added `NOT VALID`, then validated (C-5.6). No index: a rule's orders are found
  through their groups (`ix_tg_rule`, 21 Sec.3.3.2).
* No GRANT: `cv_app`'s privileges on `orders` are the table's, which cover added columns.
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): the ACCESS EXCLUSIVE lock on
  `orders` is held for the catalogue changes and the two validating scans, and its wait is
  bounded.
* The downgrade drops both CHECKs, then both columns: the code it rolls back to reads neither,
  and a rule order's group keeps `origin_rule_id`.

Additive (C-5.1); reversible (C-5.2) on an empty or a seeded database (C-5.5).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0064_orders_origin"
down_revision: str | None = "0063_rule_version_account_refs"
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


_UPGRADE_SQL = """
ALTER TABLE orders ADD COLUMN origin text;
ALTER TABLE orders ADD COLUMN origin_ref text;
ALTER TABLE orders ADD CONSTRAINT ord_origin CHECK (origin IS NULL OR origin IN ('ticket','chart','dom','hotkey','rule','algo_child','api')) NOT VALID;
ALTER TABLE orders VALIDATE CONSTRAINT ord_origin;
ALTER TABLE orders ADD CONSTRAINT ord_origin_ref CHECK (CASE WHEN origin IS NULL THEN origin_ref IS NULL WHEN origin = 'rule' THEN origin_ref IS NOT NULL AND origin_ref ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' ELSE true END) NOT VALID;
ALTER TABLE orders VALIDATE CONSTRAINT ord_origin_ref;
"""

_DOWNGRADE_SQL = """
ALTER TABLE orders DROP CONSTRAINT ord_origin_ref;
ALTER TABLE orders DROP CONSTRAINT ord_origin;
ALTER TABLE orders DROP COLUMN origin_ref;
ALTER TABLE orders DROP COLUMN origin;
"""

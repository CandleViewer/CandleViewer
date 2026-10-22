"""system_events: a row addressed to one user, the view-as start's notice (#3085 S13a)

Revision ID: 0047_system_events_recipient
Revises: 0043_order_submission
Create Date: 2026-10-21

`system_events.recipient_user_id`, nullable: the user a row is addressed to. #3085's start writes
one `view_as_started` row addressed to the target, in the start's own transaction, and
`GET /notifications` serves a caller the rows addressed to them as `system` notifications (the
Q1 ruling, option A; `04-security-program.md` Sec.7.2.2 row 34b). Every other row stays
unaddressed, and the whole stream stays the Owner's alone.

* `REFERENCES users(id) ON DELETE SET NULL`, as `resolved_by`. No `users` row is ever deleted:
  the E42-T10 purge anonymises a user in place (schema doc Sec.3.1.1), so a purged user's notices
  stay addressed to them, readable by the Owner alone (an anonymised user cannot sign in). Only a
  hard delete, which no path issues, nulls the address; the rows stay, the Owner's as every
  unaddressed row is.
* `ix_se_recipient (recipient_user_id, event_ts DESC) WHERE recipient_user_id IS NOT NULL` serves
  the addressed read. It is built in this transaction, not CONCURRENTLY (`0034_order_vocabulary`:
  that waits on a second booting process holding the migration lock): `system_events` is far below
  Sec.9.3 rule 3's 1 M rows (about 500 a day, 180 days hot, by the schema doc's sizing and
  retention tables) and no row is addressed yet.
* No GRANT: the default privileges in `infra/scripts/pg_bootstrap.sql` cover added columns (0009).
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): ACCESS EXCLUSIVE on
  `system_events`, SHARE ROW EXCLUSIVE on `users` for the FK, each wait bounded.
* The downgrade locks `system_events` and refuses while any row is addressed: dropping the column
  would hand a user's notices to the Owner alone. Otherwise it drops the index and the column.

Additive (C-5.1); reversible (C-5.2) on an empty or a seeded database (C-5.5).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0047_system_events_recipient"
down_revision: str | None = "0043_order_submission"
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
ALTER TABLE system_events
  ADD COLUMN recipient_user_id uuid REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX ix_se_recipient ON system_events (recipient_user_id, event_ts DESC)
  WHERE recipient_user_id IS NOT NULL;
"""

_DOWNGRADE_SQL = """
LOCK TABLE system_events IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM system_events WHERE recipient_user_id IS NOT NULL) THEN
    RAISE EXCEPTION '0047_system_events_recipient downgrade refused: a system_events row is addressed to a user (a view-as notice), and dropping recipient_user_id would hand it to the Owner alone. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
DROP INDEX ix_se_recipient;
ALTER TABLE system_events DROP COLUMN recipient_user_id;
"""

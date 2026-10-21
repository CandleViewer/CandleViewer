"""sessions: a session's view-as context, its two CHECKs and three partial indexes (#3085 S2a)

Revision ID: 0042_sessions_view_as
Revises: 0041_account_env_write_once
Create Date: 2026-10-20

Slice S2a of #3085: purely additive (C-5.1), `docs/plan/21-database-schema.md` Sec.3.1.4's second
block verbatim. A session's view-as context (`auth/view_as.py`, `SessionRecord.view_as`) lives on
its `sessions` row, so a restart keeps it and every read carries it. Nothing writes the columns
yet (#3085 S2b adds the writes, S13a the start).

* Eight nullable columns with no default (no rewrite, Sec.9.3 rule 2): ids and times only, class
  P0 (Sec.12), so no classification comment (C-5.9). A start's reason is never on the row.
* `sessions_view_as_shape` refuses what `ViewAsState._shape` and `SessionRecord` refuse: all NULL,
  or id, target, start and expiry set; expiry = start + 30 minutes; target <> `user_id`; end and
  reason set together; `end_recorded_at` and `cleared_at` only with an end; the end at or before
  the expiry, `expired` exactly at it. No order between the end, its record and the clear (a
  clock stepped between two writes could break one); `IS TRUE` refuses a NULL result.
  `sessions_view_as_end_reason` admits the five `ViewAsEndReason` values.
* `view_as_target_user_id ... ON DELETE RESTRICT`: no `users` row is ever deleted (the E42-T10
  purge anonymises in place, `0036_users_purge`), so RESTRICT blocks no purge, keeps every
  target readable and never writes the row, so the CHECK holds. A hard delete of a named user
  fails loudly (23503, this FK) until the row holds no context or another one. CASCADE would
  delete the viewer's row and an end whose record is owed; SET NULL would fail the CHECK instead.
* The three partial indexes are built in this transaction, not CONCURRENTLY (`0034_order_vocabulary`:
  that waits on a second booting process holding the migration lock); `sessions` is far below
  Sec.9.3 rule 3's 1 M rows and no row matches a predicate yet. `ix_sessions_view_as_context`
  serves S2b's lookup of the other rows that hold one context (a refresh carries it on).
* No GRANT: the default privileges in `infra/scripts/pg_bootstrap.sql` cover added columns (0009).
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): ACCESS EXCLUSIVE on
  `sessions`, SHARE ROW EXCLUSIVE on `users` for the FK, each wait bounded.
* The downgrade locks `sessions` and refuses while any row names a context (live, held, or ended
  with its `admin.view_as_ended` record written or owed): dropping it would end a live context
  unrecorded or lose an owed end (C-2.9). Otherwise it drops the indexes, CHECKs and columns.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0042_sessions_view_as"
down_revision: str | None = "0041_account_env_write_once"
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


# 21-database-schema.md Sec.3.1.4, second block, verbatim.
_UPGRADE_SQL = """
ALTER TABLE sessions
  ADD COLUMN view_as_context_id      uuid,
  ADD COLUMN view_as_target_user_id  uuid REFERENCES users(id) ON DELETE RESTRICT,
  ADD COLUMN view_as_started_at      timestamptz,
  ADD COLUMN view_as_expires_at      timestamptz,
  ADD COLUMN view_as_ended_at        timestamptz,
  ADD COLUMN view_as_end_recorded_at timestamptz,
  ADD COLUMN view_as_cleared_at      timestamptz,
  ADD COLUMN view_as_end_reason      text,
  ADD CONSTRAINT sessions_view_as_shape CHECK ((
        (view_as_context_id IS NULL AND view_as_target_user_id IS NULL
         AND view_as_started_at IS NULL AND view_as_expires_at IS NULL
         AND view_as_ended_at IS NULL AND view_as_end_recorded_at IS NULL
         AND view_as_cleared_at IS NULL AND view_as_end_reason IS NULL)
     OR (view_as_context_id IS NOT NULL AND view_as_target_user_id IS NOT NULL
         AND view_as_started_at IS NOT NULL AND view_as_expires_at IS NOT NULL
         AND view_as_expires_at = view_as_started_at + interval '30 minutes'
         AND view_as_target_user_id <> user_id
         AND (view_as_ended_at IS NULL) = (view_as_end_reason IS NULL)
         AND (view_as_ended_at IS NOT NULL
              OR (view_as_end_recorded_at IS NULL AND view_as_cleared_at IS NULL))
         AND (view_as_ended_at IS NULL OR (view_as_ended_at <= view_as_expires_at
              AND (view_as_end_reason = 'expired') = (view_as_ended_at = view_as_expires_at))))
  ) IS TRUE),  -- a NULL comparison would pass a bare CHECK
  ADD CONSTRAINT sessions_view_as_end_reason CHECK (view_as_end_reason IS NULL
    OR view_as_end_reason IN ('ended','expired','viewer_ineligible','target_ineligible','session_ended'));
CREATE INDEX ix_sessions_view_as_due     ON sessions (view_as_expires_at)
  WHERE view_as_context_id IS NOT NULL AND view_as_end_recorded_at IS NULL;
CREATE INDEX ix_sessions_view_as_target  ON sessions (view_as_target_user_id)
  WHERE view_as_context_id IS NOT NULL AND view_as_ended_at IS NULL;
CREATE INDEX ix_sessions_view_as_context ON sessions (view_as_context_id)
  WHERE view_as_context_id IS NOT NULL;
"""

_DOWNGRADE_SQL = """
LOCK TABLE sessions IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM sessions WHERE view_as_context_id IS NOT NULL) THEN
    RAISE EXCEPTION '0042_sessions_view_as downgrade refused: a session row names a view-as context (live, held, or ended with its admin.view_as_ended record written or still owed), and dropping the view_as columns would end a live context with no record or lose an end still owed one. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
DROP INDEX ix_sessions_view_as_context;
DROP INDEX ix_sessions_view_as_target;
DROP INDEX ix_sessions_view_as_due;
ALTER TABLE sessions
  DROP CONSTRAINT sessions_view_as_end_reason, DROP CONSTRAINT sessions_view_as_shape,
  DROP COLUMN view_as_end_reason, DROP COLUMN view_as_cleared_at,
  DROP COLUMN view_as_end_recorded_at, DROP COLUMN view_as_ended_at,
  DROP COLUMN view_as_expires_at, DROP COLUMN view_as_started_at,
  DROP COLUMN view_as_target_user_id, DROP COLUMN view_as_context_id;
"""

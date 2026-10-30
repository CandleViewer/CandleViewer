"""sessions: a session's lock by request and its last unlock (E09-S03-F1, #4743)

Revision ID: 0056_sessions_lock_state
Revises: 0055_watchlists
Create Date: 2026-10-29

Purely additive (C-5.1), `docs/plan/21-database-schema.md` Sec.3.1.4's third block verbatim. The
lock that `POST /auth/lock` (22 `authLock`, CMP-098 "Lock now") takes is a fact the session's own
row holds, so every check reads it (`SessionRecord.is_idle_locked`), on every process and after a
restart; the B16 chart only records it (28 B16.7, C-2.21).

* `locked_at`: set by the lock and cleared by an unlock only. A refresh carries it to the
  successor row; extend's write refuses a row that holds it. The lock never moves `last_seen_at`,
  and no API field serves the value.
* `unlocked_at`: the last successful unlock, set by it and never cleared. Download links end at
  any unlock of the session chain (`admin/backups/downloads.py`, `grant_ended`).
* Two nullable columns with no default (no rewrite, Sec.9.3 rule 2): times only, class P0
  (Sec.12), so no classification comment (C-5.9). No GRANT: the default privileges in
  `infra/scripts/pg_bootstrap.sql` cover added columns (0009).
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): the ACCESS EXCLUSIVE lock on
  `sessions` is a catalogue change, its wait bounded.
* The downgrade (C-5.2) locks `sessions` and refuses while a live session (not revoked, inside its
  absolute lifetime) is locked by request: dropping `locked_at` would unlock it. Otherwise it drops
  both columns.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0056_sessions_lock_state"
down_revision: str | None = "0055_watchlists"
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


# 21-database-schema.md Sec.3.1.4, third block, verbatim.
_UPGRADE_SQL = """
ALTER TABLE sessions
  ADD COLUMN locked_at   timestamptz,
  ADD COLUMN unlocked_at timestamptz;
"""

_DOWNGRADE_SQL = """
LOCK TABLE sessions IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM sessions WHERE locked_at IS NOT NULL AND revoked_at IS NULL
             AND expires_at > now()) THEN
    RAISE EXCEPTION '0056_sessions_lock_state downgrade refused: a live session is locked by request (sessions.locked_at), and dropping the column would unlock it. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
ALTER TABLE sessions DROP COLUMN unlocked_at, DROP COLUMN locked_at;
"""

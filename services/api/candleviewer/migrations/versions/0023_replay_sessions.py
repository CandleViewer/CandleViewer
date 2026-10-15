"""replay_sessions + replay_state (E26-T01 #624)

Revision ID: 0023_replay_sessions
Revises: 0022_workspaces
Create Date: 2026-10-15

Purely additive (C-5.1). The table, its five named CHECKs and both indexes are
`docs/plan/21-database-schema.md` Sec.3.6.4 verbatim (the register's
`0007_recorder` row; that number was taken, so it ships alone as 0023).
`replay_state` (Sec.1.2) had no earlier owner, so it is created here: the six
`ReplayState` API values in contract order, then B12's `stepping` (transient,
still a valid persisted snapshot state) and `destroyed` (the only final state;
idle reclaim and client destroy both land there). The status mirrors the B12
chart (28-statechart-catalogue.md, C-2.19), so every chart state is a value.
`ix_rps_live` covers `stepping` too: a session mid-step still holds buffers.

* `bookmarks` holds user notes, so it is classified P1 (Sec.12, C-5.9) and
  carries the `PII:` column comment the classification check reads.
* No path-shaped column exists: `source_tier` is a CHECK-closed enum (SR-097).
* `cv_app` keeps the default DML grants: sessions are destroyed by their owner
  (`DELETE /replay/sessions/{id}`), unlike the append-only recorder tables.
* Downgrade refuses (clear error) while `replay_sessions` holds rows, and drops
  the table, then the type, cleanly when empty.
* Both `upgrade()` and `downgrade()` bracket their statements with
  `SET LOCAL lock_timeout = '5s'` (0019/0022 pattern, C-5.6), so the SHARE ROW
  EXCLUSIVE locks the new FKs take on `users`, `recording_sessions` and
  `exchange_accounts` are bounded instead of queueing behind a long writer.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0023_replay_sessions"
down_revision: str | None = "0022_workspaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_ENUM_SQL)
    op.execute(_TABLE_SQL)
    op.execute(_COMMENTS_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


_ENUM_SQL = """
CREATE TYPE replay_state AS ENUM ('created','buffering','playing','paused','finished','error','stepping','destroyed');
"""

# 21-database-schema.md Sec.3.6.4, verbatim.
_TABLE_SQL = """
CREATE TABLE replay_sessions (
  id                   uuid PRIMARY KEY,
  user_id              uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  recording_session_id uuid REFERENCES recording_sessions(id) ON DELETE SET NULL,
  symbol               symbol_code NOT NULL,
  range_start          timestamptz NOT NULL,
  range_end            timestamptz NOT NULL,
  cursor_ts            timestamptz,
  speed                numeric(6,2) NOT NULL DEFAULT 1,
  state                replay_state NOT NULL DEFAULT 'created',
  source_tier          text NOT NULL DEFAULT 'auto',   -- auto | questdb | parquet
  paper_trading        boolean NOT NULL DEFAULT false,
  paper_account_id     uuid REFERENCES exchange_accounts(id) ON DELETE SET NULL,
  bookmarks            jsonb NOT NULL DEFAULT '[]'::jsonb,
  loop_enabled         boolean NOT NULL DEFAULT false,
  events_emitted       bigint NOT NULL DEFAULT 0,
  gap_warnings         integer NOT NULL DEFAULT 0,
  error_message        text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  finished_at          timestamptz,
  CONSTRAINT rps_range CHECK (range_end > range_start),
  CONSTRAINT rps_speed CHECK (speed BETWEEN 0.1 AND 100),
  CONSTRAINT rps_tier  CHECK (source_tier IN ('auto','questdb','parquet')),
  CONSTRAINT rps_cursor CHECK (cursor_ts IS NULL OR (cursor_ts >= range_start AND cursor_ts <= range_end)),
  CONSTRAINT rps_paper CHECK (paper_trading = false OR paper_account_id IS NOT NULL)
);
CREATE INDEX ix_rps_user_time ON replay_sessions (user_id, created_at DESC);
CREATE INDEX ix_rps_live      ON replay_sessions (state) WHERE state IN ('buffering','playing','paused','stepping');
"""

_COMMENTS_SQL = """
COMMENT ON COLUMN replay_sessions.bookmarks IS
  'PII: user notes on recorded timestamps; owner-scoped reads; purged with the user (CASCADE)';
"""

_DOWNGRADE_SQL = """
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM replay_sessions) THEN
    RAISE EXCEPTION '0023_replay_sessions downgrade refused: replay_sessions holds data';
  END IF;
END $BODY$;
DROP TABLE IF EXISTS replay_sessions;
DROP TYPE IF EXISTS replay_state;
"""

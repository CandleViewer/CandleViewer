"""watchlists (E08-T07, #4706)

Revision ID: 0055_watchlists
Revises: 0054_scanner_presets
Create Date: 2026-10-28

Purely additive (C-5.1): `docs/plan/21-database-schema.md` Sec.3.8.6 verbatim, the lists
`/watchlists` persists. A list belongs to one user; `version` is 1 on insert and the guard of the
API's replace (`UPDATE ... WHERE id = :id AND user_id = :owner AND version = :expected`), so of two
writers holding the same version exactly one wins; `ux_wl_name` makes a name unique per user as
`lower()` folds it.

* One CREATE TABLE under `lock_timeout = 5s` (C-5.6): the `users` foreign key takes a SHARE ROW
  EXCLUSIVE lock on `users` for the transaction, which then waits at most 5 s. The unique index is
  built on the new, empty table, so it holds no lock on live rows.
* No GRANT: `cv_app` holds table-level DML from the default privileges in
  `infra/scripts/pg_bootstrap.sql`. No column holds a credential, a token or PII beyond the owning
  `user_id` (Sec.12, P0).
* The downgrade (C-5.2) locks the table and refuses while any list exists, since dropping it
  would lose a user's lists; an empty table is dropped.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0055_watchlists"
down_revision: str | None = "0054_scanner_presets"
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


# 21-database-schema.md Sec.3.8.6, verbatim.
_UPGRADE_SQL = """
CREATE TABLE watchlists (
  id          uuid PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        text NOT NULL,
  symbols     text[] NOT NULL DEFAULT '{}',   -- in order; at most 200, none twice (the API checks both)
  columns     text[] NOT NULL DEFAULT '{}',   -- column ids, in order; at most 32, none twice (the API checks both)
  version     integer NOT NULL DEFAULT 1,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT wl_name_len    CHECK (char_length(name) BETWEEN 1 AND 80),
  CONSTRAINT wl_symbols_max CHECK (cardinality(symbols) <= 200),
  CONSTRAINT wl_columns_max CHECK (cardinality(columns) <= 32),
  CONSTRAINT wl_version     CHECK (version >= 1)
);
CREATE UNIQUE INDEX ux_wl_name ON watchlists (user_id, lower(name));
"""

_DOWNGRADE_SQL = """
LOCK TABLE watchlists IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM watchlists) THEN
    RAISE EXCEPTION '0055_watchlists downgrade refused: watchlists holds users'' lists, which dropping the table would lose. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
DROP TABLE watchlists;
"""

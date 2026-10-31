"""password_history: a user's retired password hashes, for SR-028's reuse rule (#2110, #2330)

Revision ID: 0061_password_history
Create Date: 2026-10-31

E09 password bundle (#2330 + #2110 + #2099), PR 1, contract first. The table is
`docs/plan/21-database-schema.md` Sec.3.1.1a verbatim: the Argon2id hashes a password change
retired, so `PUT /auth/password` can refuse the current password and the last 4 retired ones
(the last 5 in all; `04-security-program.md` Sec.6.3.1). The auth store keeps 4 rows per user,
pruned in the change's own unit of work, behind a compare-and-swap on `users.password_hash`.

* `ph_pwd_argon` admits Argon2id encodings only, as `users_pwd_argon` does (SR-011).
* The primary key `(user_id, retired_at)` is the per-user order the store prunes by; the
  compare-and-swap makes two retirements of one user at one instant impossible.
* `ON DELETE CASCADE`: a user's history goes with the user row.
* No GRANT and no REVOKE: `cv_app` keeps INSERT, SELECT and DELETE from
  `infra/scripts/pg_bootstrap.sql`'s default privileges (the prune deletes).
* C-5.9 / Sec.12, class S: `password_hash` carries a `SECRET:` comment, which `db.models` mirrors.
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): the FK takes a SHARE ROW
  EXCLUSIVE lock on `users` for the transaction; the table is new and empty.
* The downgrade (C-5.2) locks the table and refuses while any row exists, since dropping it would
  let a user reuse a retired password; an empty table is dropped.

Its number is 0061, on `0060_recording_write_owner_only` (#5265); it was planned as 0059, then
0060, and re-parented by merge order at rebase after #5253 and #5265 (`70-multi-agent.md` Sec.4).
The lockfile entry pins it (C-5.3).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0061_password_history"
down_revision: str | None = "0060_recording_write_owner_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_TABLE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_REFUSE_SQL)
    op.execute("DROP TABLE password_history;")
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.1.1a, verbatim.
_TABLE_SQL = """
CREATE TABLE password_history (
  user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  password_hash  text NOT NULL,
  retired_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, retired_at),
  CONSTRAINT ph_pwd_argon CHECK (password_hash LIKE '$argon2id$%')
);
COMMENT ON COLUMN password_history.password_hash IS 'SECRET: Argon2id digest of a retired password; never logged, never returned by API';
"""

_REFUSE_SQL = """
LOCK TABLE password_history IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM password_history) THEN
    RAISE EXCEPTION '0061_password_history downgrade refused: password_history holds retired password hashes, and dropping it would let a user reuse one. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
"""

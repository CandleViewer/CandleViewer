"""users: the deferred PII purge's schedule, purge_after and anonymised_at (E42-T10 #2650)

Revision ID: 0036_users_purge
Revises: 0035_machine_persistence_json
Create Date: 2026-10-19

Slice S2 of #2650 (#965 O6): purely additive (C-5.1), `docs/plan/21-database-schema.md` Sec.3.1.1's
second block verbatim. `DELETE /users/{userId}?purge=true` sets `purge_after` 90 days out, and the
retention reaper anonymises a disabled user once it has passed and stamps `anonymised_at`;
`users_purge_shape` admits a stamp only on a scheduled purge.

* Two nullable `timestamptz` columns with no default (no rewrite, Sec.9.3 rule 2). Neither can hold
  a credential, token or PII (Sec.12, class P0), so neither carries a classification comment.
* No GRANT: `cv_app` holds table-level DML on `users` from the default privileges in
  `infra/scripts/pg_bootstrap.sql`, which covers added columns (0009 precedent).
* One ALTER TABLE under `lock_timeout = 5s` (C-5.6): its ACCESS EXCLUSIVE lock waits at most 5 s,
  and the CHECK validates a table of a handful of rows whose new columns are all NULL.
* The downgrade locks the table and refuses while a purge is pending (`purge_after` set,
  `anonymised_at` not): dropping the column would cancel it silently, and the user's data would
  outlive the date its `users.delete` record names. An anonymised user does not block it: the
  surrogate stays, and the audit log keeps its `users.anonymise`. Otherwise it drops the CHECK and
  the two columns, and nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0036_users_purge"
down_revision: str | None = "0035_machine_persistence_json"
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


# 21-database-schema.md Sec.3.1.1, second block, verbatim.
_UPGRADE_SQL = """
ALTER TABLE users
  ADD COLUMN purge_after   timestamptz,
  ADD COLUMN anonymised_at timestamptz,
  ADD CONSTRAINT users_purge_shape CHECK (anonymised_at IS NULL OR purge_after IS NOT NULL);
"""

_DOWNGRADE_SQL = """
LOCK TABLE users IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM users WHERE purge_after IS NOT NULL AND anonymised_at IS NULL) THEN
    RAISE EXCEPTION '0036_users_purge downgrade refused: a user deleted with purge=true is still waiting for the anonymisation its users.delete audit record names, which dropping purge_after would cancel silently. Fix forward with a new revision instead (C-5.2); never clear purge_after in SQL';
  END IF;
END $BODY$;
ALTER TABLE users
  DROP CONSTRAINT users_purge_shape,
  DROP COLUMN anonymised_at,
  DROP COLUMN purge_after;
"""

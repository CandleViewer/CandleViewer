"""hotkey_profiles (E10-T05, #5211)

Revision ID: 0064_hotkey_profiles
Revises: 0063_rule_version_account_refs
Create Date: 2026-10-31

Purely additive (C-5.1): `docs/plan/21-database-schema.md` Sec.3.8.5 verbatim, the profiles
`/settings/hotkeys*` persists. A profile belongs to one user; `bindings` is one jsonb object of
command id to binding (`hk_bindings`), and `scope`, `requires_arm` and `confirm` are derived on
every read, never stored, so the table has no arm column, no `scheme_base` and no `deleted_at` (a
delete removes the row; the audit trail keeps the history). `version` is 1 on insert and the guard
of a replace that carries `If-Match` (`UPDATE ... WHERE id = :id AND owner_user_id = :owner AND
version = :expected`). `ux_hk_name` makes a name unique per user as `lower()` folds it, and
`ux_hk_active` lets a user hold at most one active profile. The 20-profile cap is the store's,
under the owner's advisory lock.

* One CREATE TABLE under `lock_timeout = 5s` (C-5.6): the `users` foreign key takes a SHARE ROW
  EXCLUSIVE lock on `users` for the transaction, which then waits at most 5 s. Both unique indexes
  are built on the new, empty table, so they hold no lock on live rows.
* No GRANT: `cv_app` holds table-level DML from the default privileges in
  `infra/scripts/pg_bootstrap.sql`. No column holds a credential, a token or PII beyond the owning
  `owner_user_id` (Sec.12, P0).
* The downgrade (C-5.2) locks the table and refuses while any profile exists, since dropping it
  would lose users' profiles; an empty table is dropped.

Its number is 0064, as the orchestrator ruled (2026-11-02): it was 0062 on `0061_password_history`
until #5359's `0063_rule_version_account_refs`, on the same parent, merged first, so it revises
that head and takes the next number, keeping the chain monotonic (C-5.3); the lockfile entry pins
it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0064_hotkey_profiles"
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


# 21-database-schema.md Sec.3.8.5, verbatim.
_UPGRADE_SQL = """
CREATE TABLE hotkey_profiles (
  id            uuid PRIMARY KEY,
  owner_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name          text NOT NULL,
  is_active     boolean NOT NULL DEFAULT false,
  bindings      jsonb NOT NULL,   -- {"ticket.side_buy":"B","positions.close_all":"Ctrl+Shift+W",…}; "" unbinds
  version       integer NOT NULL DEFAULT 1,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT hk_name_len CHECK (char_length(name) BETWEEN 1 AND 80),
  CONSTRAINT hk_bindings CHECK (jsonb_typeof(bindings) = 'object'),
  CONSTRAINT hk_version  CHECK (version >= 1)
);
CREATE UNIQUE INDEX ux_hk_name   ON hotkey_profiles (owner_user_id, lower(name));
CREATE UNIQUE INDEX ux_hk_active ON hotkey_profiles (owner_user_id) WHERE is_active;
"""

_DOWNGRADE_SQL = """
LOCK TABLE hotkey_profiles IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM hotkey_profiles) THEN
    RAISE EXCEPTION '0064_hotkey_profiles downgrade refused: hotkey_profiles holds users'' hotkey profiles, which dropping the table would lose. Fix forward with a new revision instead (C-5.2)';
  END IF;
END $BODY$;
DROP TABLE hotkey_profiles;
"""

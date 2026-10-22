"""exchange_accounts: the default binding's version, one more per default move (#906 0d)

Revision ID: 0048_account_default_binding
Revises: 0047_system_events_recipient
Create Date: 2026-10-22

`docs/plan/21-database-schema.md` Sec.3.2.1's and Sec.3.2.4's fourth blocks, verbatim. The default
binding (`getAccountDefaultProfile`, `setAccountDefaultProfile`) is tagged
`W/"<accountId>:default:<n>"`, a version and never a profile id, so a tag read before a move never
matches after it, even once the default is back on the same profile (the 2026-10-22 09:38Z ruling).

* `default_binding_version` (integer, NOT NULL DEFAULT 1, CHECK >= 1): a constant default, so the
  ALTER takes the PG 11+ fast path and rewrites no row (Sec.9.3 rule 2); every account starts at 1,
  its bootstrap `Default` being its first binding.
* `trg_ap_default_binding` (AFTER UPDATE OF is_default on `account_profiles`, per row, WHEN a
  profile becomes the default, `ENABLE ALWAYS`) adds one, whichever UPDATE moves the default;
  an unset alone, an insert and every other edit do not. Its function pins `search_path` and is
  no SECURITY DEFINER: `cv_app` holds UPDATE on `exchange_accounts`.
* Residual: the owner role, superusers and a `cv_app` session can still rewind the version, or move
  the default without a bump by unsetting it and inserting a profile as the default. A rewind
  leaves no trace in the database until #906 D2's records carry `binding_version`; the nearest
  threat-model row is PF-T08, which does not yet name this column.
* No GRANT (`cv_app`'s table-level DML covers the column) and no comment tag (P0).
* `lock_timeout = 5s` both ways (C-5.6): the ALTER waits for ACCESS EXCLUSIVE on
  `exchange_accounts`, the trigger for SHARE ROW EXCLUSIVE on `account_profiles`; the downgrade's
  DROP TRIGGER waits for ACCESS EXCLUSIVE on `account_profiles`.
* Additive (C-5.1) and reversible (C-5.2): the downgrade drops the trigger, its function, the CHECK
  and the column. The versions are lost, so a tag issued before it could match again after a
  re-upgrade: a rollback-only path.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0048_account_default_binding"
down_revision: str | None = "0047_system_events_recipient"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_COLUMN_SQL)
    op.execute(_TRIGGER_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.2.1, fourth block, verbatim.
_COLUMN_SQL = """
ALTER TABLE exchange_accounts
  ADD COLUMN default_binding_version integer NOT NULL DEFAULT 1,
  ADD CONSTRAINT ea_default_binding_version CHECK (default_binding_version >= 1);
"""

# 21-database-schema.md Sec.3.2.4, fourth block, verbatim.
_TRIGGER_SQL = """
CREATE FUNCTION ap_default_binding_bump() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  UPDATE public.exchange_accounts
     SET default_binding_version = default_binding_version + 1
   WHERE id = NEW.exchange_account_id;
  RETURN NULL;
END $$;
CREATE TRIGGER trg_ap_default_binding AFTER UPDATE OF is_default ON account_profiles
  FOR EACH ROW WHEN (NEW.is_default AND NOT OLD.is_default)
  EXECUTE FUNCTION ap_default_binding_bump();
ALTER TABLE account_profiles ENABLE ALWAYS TRIGGER trg_ap_default_binding;
"""

_DOWNGRADE_SQL = """
DROP TRIGGER trg_ap_default_binding ON account_profiles;
DROP FUNCTION ap_default_binding_bump();
ALTER TABLE exchange_accounts
  DROP CONSTRAINT ea_default_binding_version,
  DROP COLUMN default_binding_version;
"""

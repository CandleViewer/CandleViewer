"""trg_ea_env_parent fires under the replica role, its function pins search_path (#3962)

Revision ID: 0049_ea_env_parent_always
Revises: 0048_account_default_binding
Create Date: 2026-10-22

`docs/plan/21-database-schema.md` Sec.3.2.1, fifth block, verbatim. #3959's security lens
(SEC-2333-04, #2333) found `trg_ea_env_parent` (0017), which keeps a sub-account in its parent's
environment (C-2.11), a plain `ENABLE` trigger: under `session_replication_role = replica` a
cross-environment sub-account INSERT was not refused. `trg_ea_env_write_once` (0041) closed the
UPDATE side; this is the INSERT side.

* `ALTER TABLE ... ENABLE ALWAYS TRIGGER trg_ea_env_parent`: it fires whatever the session's
  replication role, as 0024's, 0039's and 0041's guards do.
* `ea_env_parent_check()` is replaced in place (`CREATE OR REPLACE`, the trigger keeps pointing at
  it) with the shape of the 0037 to 0041 guards: `SET search_path = pg_catalog, pg_temp`, the
  table schema-qualified, the environments compared as text (so no type name is looked up on the
  pinned path), and the refusal SQLSTATE 23514 naming the trigger as the constraint (`USING
  CONSTRAINT`), never a value. The rule is unchanged: a sub-account whose parent's environment
  differs from its own, or whose parent does not exist, is refused. The message keeps its
  `trg_ea_env_parent:` prefix.
* Postgres fires same-event BEFORE triggers in name order: `trg_ea_env_in_use` (0039) sorts
  first, this one next, `trg_ea_env_write_once` (0041) last; nothing here changes their order.

Additive (C-5.1) and reversible (C-5.2): `downgrade()` restores 0017's function body verbatim and
sets the trigger back to plain `ENABLE`. No row changes in either direction, so an empty or a
seeded database round-trips (C-5.5); the downgrade re-opens the replica-role hole, so it is a
rollback-only path. `lock_timeout` (5 s) bounds every lock wait on `exchange_accounts` (C-5.6):
`ALTER TABLE ... ENABLE` waits for SHARE ROW EXCLUSIVE in both directions, and `CREATE OR REPLACE
FUNCTION` takes no table lock.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0049_ea_env_parent_always"
down_revision: str | None = "0048_account_default_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_GUARD_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_RESTORE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.2.1, fifth block, verbatim.
_GUARD_SQL = """
CREATE OR REPLACE FUNCTION ea_env_parent_check() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE parent_env text;
BEGIN
  IF NEW.parent_account_id IS NOT NULL THEN
    SELECT p.env::text INTO parent_env FROM public.exchange_accounts p
      WHERE p.id = NEW.parent_account_id;
    IF parent_env IS DISTINCT FROM NEW.env::text THEN
      RAISE EXCEPTION 'trg_ea_env_parent: a sub-account is outside its parent account environment'
        USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ea_env_parent';
    END IF;
  END IF;
  RETURN NEW;
END $BODY$;
ALTER TABLE exchange_accounts ENABLE ALWAYS TRIGGER trg_ea_env_parent;
"""

# 0017's function, verbatim, and the trigger's plain ENABLE.
_RESTORE_SQL = """
CREATE OR REPLACE FUNCTION ea_env_parent_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_env exchange_env;
BEGIN
  IF NEW.parent_account_id IS NOT NULL THEN
    SELECT env INTO parent_env FROM exchange_accounts WHERE id = NEW.parent_account_id;
    IF parent_env IS DISTINCT FROM NEW.env THEN
      RAISE EXCEPTION 'trg_ea_env_parent: sub-account env % differs from parent env %',
        NEW.env, parent_env USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
ALTER TABLE exchange_accounts ENABLE TRIGGER trg_ea_env_parent;
"""

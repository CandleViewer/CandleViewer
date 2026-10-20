"""exchange_accounts.env is write-once (#2333)

Revision ID: 0040_account_env_write_once
Revises: 0039_trade_groups
Create Date: 2026-10-20

`docs/plan/21-database-schema.md` Sec.3.2.1, third block, verbatim. #2153's review item 2 (an
account's environment must not drift, or a demo key could become live, C-2.11), deferred to
E27-T03 and carried by none of its tickets, and the E28-X01 SR-E28-16 requirement that
`exchange_accounts.env` be immutable (F-05).

* `trg_ea_env_write_once` refuses any change of `env` once the row exists: `ENABLE ALWAYS`, so
  `session_replication_role = replica` does not switch it off; its function pins `search_path`
  and refuses with SQLSTATE 23514 naming the trigger as the constraint (`USING CONSTRAINT`),
  never a value. An insert takes any environment, and `trg_ea_env_parent` still keeps a
  sub-account in its parent's.
* `trg_ea_env_in_use` (0039_trade_groups), the narrower guard the orchestrator's R-14 ruling let
  stand in the interval, stays: dropping it would change 0039's own DDL, and it costs nothing.
* The API never patches `env`: `ExchangeAccountPatch` has no such field (a unit test pins it).
* `SET LOCAL lock_timeout = '5s'` brackets both directions (C-5.6): the trigger takes a SHARE ROW
  EXCLUSIVE lock on `exchange_accounts`. The downgrade drops the trigger and its function; no row
  changes in either direction, so an empty or a seeded database round-trips (C-5.5).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0040_account_env_write_once"
down_revision: str | None = "0039_trade_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_GUARD_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DROP_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.2.1, third block, verbatim.
_GUARD_SQL = """
CREATE FUNCTION ea_env_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
BEGIN
  IF NEW.env IS DISTINCT FROM OLD.env THEN
    RAISE EXCEPTION 'trg_ea_env_write_once: exchange_accounts.env is write-once'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ea_env_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_ea_env_write_once BEFORE UPDATE OF env ON exchange_accounts
  FOR EACH ROW EXECUTE FUNCTION ea_env_write_once();
ALTER TABLE exchange_accounts ENABLE ALWAYS TRIGGER trg_ea_env_write_once;
"""

_DROP_SQL = """
DROP TRIGGER trg_ea_env_write_once ON exchange_accounts;
DROP FUNCTION ea_env_write_once();
"""

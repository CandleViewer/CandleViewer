"""exchange_accounts.env is write-once (#2333)

Revision ID: 0040_account_env_write_once
Revises: 0039_trade_groups
Create Date: 2026-10-20

`docs/plan/21-database-schema.md` Sec.3.2.1, third block, verbatim. #2153's review item 2 (an
account's environment must not drift, or a demo key could become live, C-2.11), deferred to
E27-T03 and carried by none of its tickets, and the E28-X01 SR-E28-16 requirement that
`exchange_accounts.env` be immutable (F-05).

* `trg_ea_env_write_once` (BEFORE UPDATE, per row, like the write-once triggers of 0024 and 0039)
  refuses any change of `env` once the row exists. It compares with IS DISTINCT FROM, so it
  refuses changes, not writes (`SET env = env` passes). It fires on every UPDATE, not only one
  that names `env`, so a trigger that rewrote NEW.env behind another column would still meet it.
  `ENABLE ALWAYS` keeps it firing under `session_replication_role = replica`; its function pins
  `search_path` and refuses with SQLSTATE 23514 naming the trigger as the constraint (`USING
  CONSTRAINT`), never a value. An insert takes any environment, and `trg_ea_env_parent` still
  keeps a sub-account in its parent's.
* Postgres fires same-event BEFORE triggers in name order. `trg_ea_env_in_use` (0039) and
  `trg_ea_env_parent` (0017) sort first and keep their narrower refusals (an account in use, a
  sub-account outside its parent's environment); this one sorts last, so it judges NEW as every
  other BEFORE UPDATE row trigger left it (the integration test pins the order).
  `trg_ea_env_in_use`, the guard the orchestrator's R-14 ruling let stand in the interval, stays:
  dropping it would change 0039's own DDL, and it costs nothing.
* The application never assigns `env`: no SQL under `candleviewer/` sets it, the store's patch and
  the API's PATCH body carry no environment, and the accounts store maps a refusal by either
  trigger to its typed rule error (unit tests pin all three).
* Residuals: the guard covers UPDATE only. `cv_app` keeps DELETE on `exchange_accounts` (the
  `pg_bootstrap.sql` default; no revision revokes it), so an account that nothing RESTRICTs (no
  sub-account, order, execution, leg, membership, risk row or key rotation) can be deleted, its
  keys and profiles cascading with it, and its id inserted again in another environment: no
  UPDATE ever runs. The owner (`cv_owner`, migrations only) and superusers can still disable or
  drop the trigger, or rename an `exchange_env` value.

Additive (C-5.1) and reversible (C-5.2): `downgrade()` drops the trigger and its function and keeps
`trg_ea_env_in_use`. No row changes in either direction, so an empty or a seeded database
round-trips (C-5.5). The downgrade re-opens the C-2.11 hole for every account not in use, so it is a
rollback-only path. `lock_timeout` (5 s) bounds every lock wait on `exchange_accounts` (C-5.6): the
upgrade's CREATE TRIGGER and ENABLE ALWAYS wait for SHARE ROW EXCLUSIVE, the downgrade's DROP
TRIGGER for ACCESS EXCLUSIVE.
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
CREATE TRIGGER trg_ea_env_write_once BEFORE UPDATE ON exchange_accounts
  FOR EACH ROW EXECUTE FUNCTION ea_env_write_once();
ALTER TABLE exchange_accounts ENABLE ALWAYS TRIGGER trg_ea_env_write_once;
"""

_DROP_SQL = """
DROP TRIGGER trg_ea_env_write_once ON exchange_accounts;
DROP FUNCTION ea_env_write_once();
"""

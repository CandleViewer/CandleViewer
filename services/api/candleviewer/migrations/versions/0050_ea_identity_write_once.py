"""exchange_accounts.id, exchange_uid and kind are write-once (#3968, SR-E27-13)

Revision ID: 0050_ea_identity_write_once
Revises: 0049_ea_env_parent_always
Create Date: 2026-10-22

`docs/plan/21-database-schema.md` Sec.3.2.1, sixth block, verbatim. SR-E27-13 of the E27 accounts
threat model (KV-T04, F-15) asks that an account's identity not change after creation: `env`,
`exchange_uid` and `kind`. `trg_ea_env_write_once` (0041, #2333) built `env`; this revision builds
the other two, so a row can never come to name another exchange UID, or turn a main account into a
sub-account or back, once it exists. The orchestrator's ruling on SEC-2758-02 adds `id`, the row's
own key: rewriting it is the other way to free an account id (0044), and this guard refuses it
directly instead of through the children's foreign keys.

* `trg_ea_identity_write_once` (BEFORE UPDATE, per row, like 0041's guard) refuses any change of
  `id`, `exchange_uid` or `kind` once the row exists. It compares with IS DISTINCT FROM, so it refuses
  changes, not writes (`SET kind = kind` passes), and it fires on every UPDATE, not only one that
  names either column, so a trigger that rewrote NEW behind another column would still meet it.
  `ENABLE ALWAYS` keeps it firing under `session_replication_role = replica`; its function pins
  `search_path` and refuses with SQLSTATE 23514 naming the trigger as the constraint (`USING
  CONSTRAINT`), and the column, never a value. An insert takes any UID and kind, under the table's
  CHECKs (`ea_uid_fmt`, `ea_parent_shape`).
* `env` keeps its own guard: 0041's DDL and its constraint name stay as they are, and so do its
  tests, but for the trigger-order test, which now allows this guard after it.
* Postgres fires same-event BEFORE triggers in name order. This one sorts after
  `trg_ea_env_write_once` and becomes the last; neither guard rewrites NEW, so both judge NEW as
  every trigger that could rewrite it left it (the integration test pins the order).
* The application never changes either column after the INSERT: no UPDATE or upsert under
  `candleviewer/` assigns one, the store's patch and the API's PATCH body carry neither, and the
  accounts store maps a refusal to its typed rule error (unit tests pin all three).
* Residuals, as for `env`: the guard covers UPDATE only, and `cv_app` can neither delete an
  account (0044) nor free its id by rewriting it: this guard refuses that first (23514), under the
  replica role too, where the children's `ON UPDATE NO ACTION` foreign keys do not fire, and the
  keys still would elsewhere (23503). So no path re-creates an account with another identity.
  `parent_account_id` is not write-once: a sub-account can be re-pointed at any other account of
  its environment, as only the store's INSERT requires a main parent. The owner (`cv_owner`:
  migrations, and the alert purge when `CV_PG_OWNER_DSN` is set) and superusers can still disable
  or drop the trigger.

Additive (C-5.1) and reversible (C-5.2): `downgrade()` drops the trigger and its function. No row
changes in either direction, so an empty or a seeded database round-trips (C-5.5). The downgrade
re-opens SR-E27-13 for every account, so it is a rollback-only path. `lock_timeout` (5 s) bounds
every lock wait on `exchange_accounts` (C-5.6): the upgrade's CREATE TRIGGER and ENABLE ALWAYS
wait for SHARE ROW EXCLUSIVE, the downgrade's DROP TRIGGER for ACCESS EXCLUSIVE.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0050_ea_identity_write_once"
down_revision: str | None = "0049_ea_env_parent_always"
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


# 21-database-schema.md Sec.3.2.1, sixth block, verbatim.
_GUARD_SQL = """
CREATE FUNCTION ea_identity_write_once() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
BEGIN
  IF NEW.id IS DISTINCT FROM OLD.id THEN
    RAISE EXCEPTION 'trg_ea_identity_write_once: exchange_accounts.id is write-once'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ea_identity_write_once';
  END IF;
  IF NEW.exchange_uid IS DISTINCT FROM OLD.exchange_uid THEN
    RAISE EXCEPTION 'trg_ea_identity_write_once: exchange_accounts.exchange_uid is write-once'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ea_identity_write_once';
  END IF;
  IF NEW.kind IS DISTINCT FROM OLD.kind THEN
    RAISE EXCEPTION 'trg_ea_identity_write_once: exchange_accounts.kind is write-once'
      USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ea_identity_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
CREATE TRIGGER trg_ea_identity_write_once BEFORE UPDATE ON exchange_accounts
  FOR EACH ROW EXECUTE FUNCTION ea_identity_write_once();
ALTER TABLE exchange_accounts ENABLE ALWAYS TRIGGER trg_ea_identity_write_once;
"""

_DROP_SQL = """
DROP TRIGGER trg_ea_identity_write_once ON exchange_accounts;
DROP FUNCTION ea_identity_write_once();
"""

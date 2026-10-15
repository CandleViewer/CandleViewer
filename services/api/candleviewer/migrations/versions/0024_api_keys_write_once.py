"""api_keys ciphertext and identity columns become write-once (#2336, SR-003)

Revision ID: 0024_api_keys_write_once
Revises: 0023_replay_sessions

The Security sign-off on #835 (deviation 2) accepted binding SR-003's `key_version` through
`credential_id` only while a credential id is never re-sealed. This revision enforces that for
UPDATE:

* `trg_api_keys_write_once` (BEFORE UPDATE, per row) refuses any change to `id`,
  `exchange_account_id`, `key_id_enc`, `key_id_last4`, `secret_enc`, `enc_nonce` or `enc_alg`.
  It compares with IS DISTINCT FROM, so it refuses changes, not writes (`SET secret_enc =
  secret_enc` passes). A new or edited key is a new row. `dek_ref`/`kek_version` (KEK re-wrap),
  status, revocation and metadata columns stay updatable.
* The refusal is SQLSTATE 23514 (`check_violation`) with the message `trg_api_keys_write_once:
  api_keys.<column> is write-once; store a new row (SR-003)`. It names the column, never a value:
  the sealed columns are SECRET class.
* Postgres fires same-event BEFORE triggers in name order, so a later-sorting BEFORE UPDATE
  trigger could rewrite NEW after this check; the integration test pins this one last.
  `ENABLE ALWAYS` keeps it firing under `session_replication_role = replica`; the function pins
  its `search_path`.
* No UPDATE trigger fires on DELETE or INSERT, and every AAD input is reproducible under the same
  id, so re-inserting a captured older row would still decrypt. `REVOKE DELETE ON api_keys FROM
  cv_app` takes the direct DELETE away from the runtime role (M10 never deletes; `destroy()`
  revokes). Guarded like 0003/0011: the roles come from `infra/scripts/pg_bootstrap.sql`.
* Residuals: referential actions run as the table owner, so a cv_app DELETE of the parent
  `exchange_accounts` row still removes its keys, after which both rows can be re-inserted. The
  owner (`cv_owner`, migrations only) and superusers can still disable or drop the trigger and
  delete rows.

Additive (C-5.1) and reversible (C-5.2): `downgrade()` re-grants DELETE (the `pg_bootstrap.sql`
default) and drops the trigger and function. That re-opens KV-T02, so it is a rollback-only path.
`lock_timeout` (5 s) bounds every lock wait on api_keys (C-5.6): the upgrade's CREATE TRIGGER and
ENABLE ALWAYS wait for SHARE ROW EXCLUSIVE, the downgrade's DROP TRIGGER for ACCESS EXCLUSIVE.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_api_keys_write_once"
down_revision: str | None = "0023_replay_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTION = """
CREATE FUNCTION api_keys_write_once_check() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.exchange_account_id IS DISTINCT FROM OLD.exchange_account_id
      THEN 'exchange_account_id'
    WHEN NEW.key_id_enc IS DISTINCT FROM OLD.key_id_enc THEN 'key_id_enc'
    WHEN NEW.key_id_last4 IS DISTINCT FROM OLD.key_id_last4 THEN 'key_id_last4'
    WHEN NEW.secret_enc IS DISTINCT FROM OLD.secret_enc THEN 'secret_enc'
    WHEN NEW.enc_nonce IS DISTINCT FROM OLD.enc_nonce THEN 'enc_nonce'
    WHEN NEW.enc_alg IS DISTINCT FROM OLD.enc_alg THEN 'enc_alg'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_api_keys_write_once: api_keys.% is write-once; store a new row (SR-003)',
      changed USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $BODY$;
"""

_TRIGGER = """
CREATE TRIGGER trg_api_keys_write_once BEFORE UPDATE ON api_keys
  FOR EACH ROW EXECUTE FUNCTION api_keys_write_once_check();
ALTER TABLE api_keys ENABLE ALWAYS TRIGGER trg_api_keys_write_once;
"""

# Each runs only where `pg_bootstrap.sql` created `cv_app` (0003/0011 pattern). Static literals:
# SQL built from strings at runtime trips bandit B608 in the `sast` gate.
_REVOKE_DELETE = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'REVOKE DELETE ON api_keys FROM cv_app'; END IF; END $BODY$;"
)
_GRANT_DELETE = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'GRANT DELETE ON api_keys TO cv_app'; END IF; END $BODY$;"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_FUNCTION)
    op.execute(_TRIGGER)
    op.execute(_REVOKE_DELETE)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_GRANT_DELETE)
    op.execute("DROP TRIGGER IF EXISTS trg_api_keys_write_once ON api_keys;")
    op.execute("DROP FUNCTION IF EXISTS api_keys_write_once_check();")
    op.execute("SET LOCAL lock_timeout = DEFAULT;")

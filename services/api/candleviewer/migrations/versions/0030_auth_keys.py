"""auth_keys: the per-environment auth keyring, KEK-wrapped (#2152 S2, ADR-0009 Amendment 4)

Revision ID: 0030_auth_keys
Revises: 0029_oms_core
Create Date: 2026-10-17

Purely additive (C-5.1). The DDL is `docs/plan/21-database-schema.md` Sec.3.1.5a verbatim, guards
included; no row is written here (M2 does, from S5b). `ak_dek_ref` admits only the wrap format, so
a plaintext key cannot be stored. `trg_auth_keys_write_once` is BEFORE UPDATE, `ENABLE ALWAYS`,
must stay last and pins its `search_path`. `REVOKE DELETE` from `cv_app` runs where the role exists
(0024 pattern). Both directions run under `lock_timeout = 5s` (C-5.6). The downgrade locks the
table and refuses while any row exists (C-5.2): seeds and digests made since are bound to these keys.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030_auth_keys"
down_revision: str | None = "0029_oms_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_TABLE_SQL)
    op.execute(_FUNCTION_SQL)
    op.execute(_GUARD_SQL)
    op.execute(_REVOKE_DELETE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s';")
    op.execute(_DOWNGRADE_SQL)
    op.execute("SET LOCAL lock_timeout = DEFAULT;")


# 21-database-schema.md Sec.3.1.5a, verbatim.
_TABLE_SQL = """
CREATE TABLE auth_keys (
  id          uuid PRIMARY KEY,
  env         exchange_env NOT NULL,       -- no default: the process environment (as kek_versions.env)
  purpose     text NOT NULL,               -- totp_seal | recovery_hmac
  key_version integer NOT NULL DEFAULT 1,  -- the auth key's own version, not the KEK's
  origin      text NOT NULL,               -- generated | imported_env
  dek_ref     text NOT NULL,               -- SECRET: the auth key wrapped under the KEK
  kek_version integer NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),  -- moves only at a re-wrap (trg_auth_keys_touch)
  CONSTRAINT ak_purpose     CHECK (purpose IN ('totp_seal','recovery_hmac')),
  CONSTRAINT ak_origin      CHECK (origin IN ('generated','imported_env')),
  CONSTRAINT ak_key_version CHECK (key_version >= 1),
  CONSTRAINT ak_kek_version CHECK (kek_version >= 1),
  CONSTRAINT ak_dek_ref     CHECK (dek_ref ~ '^ak1:[0-9a-f]{120}$'),
  CONSTRAINT ak_env_purpose_key_version UNIQUE (env, purpose, key_version)
);
CREATE INDEX ix_auth_keys_env_kek ON auth_keys (env, kek_version);
COMMENT ON COLUMN auth_keys.dek_ref IS 'SECRET: auth key wrapped under the KEK of (env, kek_version)';
CREATE TRIGGER trg_auth_keys_touch BEFORE UPDATE ON auth_keys
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
"""

_FUNCTION_SQL = """
CREATE FUNCTION auth_keys_write_once_check() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.env IS DISTINCT FROM OLD.env THEN 'env'
    WHEN NEW.purpose IS DISTINCT FROM OLD.purpose THEN 'purpose'
    WHEN NEW.key_version IS DISTINCT FROM OLD.key_version THEN 'key_version'
    WHEN NEW.origin IS DISTINCT FROM OLD.origin THEN 'origin'
    WHEN NEW.created_at IS DISTINCT FROM OLD.created_at THEN 'created_at'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_auth_keys_write_once: auth_keys.% is write-once; store a new row (ADR-0009 Amendment 4)',
      changed USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $BODY$;
"""

_GUARD_SQL = """
CREATE TRIGGER trg_auth_keys_write_once BEFORE UPDATE ON auth_keys
  FOR EACH ROW EXECUTE FUNCTION auth_keys_write_once_check();
ALTER TABLE auth_keys ENABLE ALWAYS TRIGGER trg_auth_keys_write_once;
"""

# Only where `pg_bootstrap.sql` created `cv_app` (0003/0011/0024 pattern); static, for bandit B608.
_REVOKE_DELETE_SQL = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'REVOKE DELETE ON auth_keys FROM cv_app'; END IF; END $BODY$;"
)

_DOWNGRADE_SQL = """
LOCK TABLE auth_keys IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM auth_keys) THEN
    RAISE EXCEPTION '0030_auth_keys downgrade refused: auth_keys holds rows. Seeds and recovery-code digests made since the first boot are bound to these keys, so dropping them leaves every enrolled authenticator and unused recovery code unusable. Fix forward with a new revision instead (C-5.2). If you must roll back, have every user re-enrol and regenerate their codes, delete the rows as the owner role under change control (cv_app cannot delete them), then retry';
  END IF;
END $BODY$;
DROP TABLE auth_keys;
DROP FUNCTION auth_keys_write_once_check();
"""

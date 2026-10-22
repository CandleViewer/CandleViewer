"""audit_signing_keys: the audit export signing keys, sealed and KEK-wrapped (#889 S4, ADR-0039)

Revision ID: 0046_audit_signing_keys
Revises: 0045_audit_chain_hardening
Create Date: 2026-10-22

Purely additive (C-5.1). The DDL is `docs/plan/21-database-schema.md` Sec.3.1.5b verbatim; M2
writes the rows (#889 S6). `ask_sealed_seed` and `ask_dek_ref` admit only the sealed and wrapped
formats, so no plaintext seed or DEK is stored (a CHECK's refusal echoes the row in `DETAIL`, which
the store drops). `trg_audit_signing_keys_write_once` (BEFORE UPDATE,
`ENABLE ALWAYS`, the only one, so last; its `search_path` pinned) permits the retire, the seed's
destroy (ADR-0039 Q3) and the KEK re-wrap, and refuses every other change. `REVOKE DELETE` from
`cv_app` where the role exists (0024 pattern). `lock_timeout = 5s` both ways (C-5.6; the FK locks
`users`). The downgrade locks the table and refuses while any row exists (C-5.2).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0046_audit_signing_keys"
down_revision: str | None = "0045_audit_chain_hardening"
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


# 21-database-schema.md Sec.3.1.5b, verbatim.
_TABLE_SQL = """
CREATE TABLE audit_signing_keys (
  id                 uuid PRIMARY KEY,
  env                exchange_env NOT NULL,  -- no default: the process environment (as kek_versions.env)
  version            integer NOT NULL,       -- N of the key id: the key's own version, not the KEK's
  key_id             text NOT NULL,          -- cv-audit-export-v<N>:<first 16 hex of the fingerprint>
  public_key         bytea NOT NULL,         -- the raw 32-byte Ed25519 public key (public)
  fingerprint_sha256 sha256_hex NOT NULL,    -- SHA-256 of public_key: what a verifier pins
  sealed_seed        bytea,                  -- SECRET: the seed sealed under the row's DEK; NULL once destroyed
  dek_ref            text NOT NULL,          -- SECRET: the row's DEK wrapped under the KEK
  kek_version        integer NOT NULL,
  status             text NOT NULL,          -- active | retired
  valid_from         timestamptz NOT NULL,   -- when the key became active
  valid_until        timestamptz,            -- the event_ts of the rotation that retired it
  retired_reason     text,                   -- scheduled | compromise | unrecoverable
  created_by         uuid REFERENCES users(id) ON DELETE RESTRICT,  -- the rotating Owner
  client_ref         text,                   -- that rotation's Idempotency-Key
  client_body_sha256 sha256_hex,             -- that rotation's request fingerprint
  created_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ask_version        CHECK (version >= 1),
  CONSTRAINT ask_kek_version    CHECK (kek_version >= 1),
  CONSTRAINT ask_public_key     CHECK (octet_length(public_key) = 32),
  CONSTRAINT ask_fingerprint    CHECK (fingerprint_sha256 = encode(sha256(public_key), 'hex')),
  CONSTRAINT ask_key_id         CHECK (key_id = 'cv-audit-export-v' || version::text || ':'
                                       || left(fingerprint_sha256, 16)),
  CONSTRAINT ask_sealed_seed    CHECK (octet_length(sealed_seed) = 60),
  CONSTRAINT ask_dek_ref        CHECK (dek_ref ~ '^ek1:[0-9a-f]{120}$'),
  CONSTRAINT ask_status         CHECK (status IN ('active','retired')),
  CONSTRAINT ask_retired_reason CHECK (retired_reason IN ('scheduled','compromise','unrecoverable')),
  CONSTRAINT ask_lifecycle      CHECK (CASE status
    WHEN 'active' THEN sealed_seed IS NOT NULL AND valid_until IS NULL AND retired_reason IS NULL
    ELSE valid_until IS NOT NULL AND retired_reason IS NOT NULL END),
  CONSTRAINT ask_request        CHECK (num_nonnulls(created_by, client_ref, client_body_sha256) IN (0, 3)),
  CONSTRAINT ask_client_ref     CHECK (client_ref ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  CONSTRAINT ask_env_version     UNIQUE (env, version),
  CONSTRAINT ask_env_key_id      UNIQUE (env, key_id),
  CONSTRAINT ask_env_fingerprint UNIQUE (env, fingerprint_sha256),
  CONSTRAINT ask_env_request     UNIQUE (env, created_by, client_ref)
);
CREATE UNIQUE INDEX ux_ask_active ON audit_signing_keys (env) WHERE status = 'active';
COMMENT ON COLUMN audit_signing_keys.sealed_seed IS 'SECRET: Ed25519 seed sealed under the row''s DEK';
COMMENT ON COLUMN audit_signing_keys.dek_ref IS 'SECRET: the row''s DEK wrapped under the KEK of (env, kek_version)';
"""

# The retire and the destroy (ADR-0039 Q3) and the KEK re-wrap (decision 6) are the only changes.
_FUNCTION_SQL = """
CREATE FUNCTION audit_signing_keys_write_once_check() RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $BODY$
DECLARE changed text;
BEGIN
  changed := CASE
    WHEN NEW.id IS DISTINCT FROM OLD.id THEN 'id'
    WHEN NEW.env IS DISTINCT FROM OLD.env THEN 'env'
    WHEN NEW.version IS DISTINCT FROM OLD.version THEN 'version'
    WHEN NEW.key_id IS DISTINCT FROM OLD.key_id THEN 'key_id'
    WHEN NEW.public_key IS DISTINCT FROM OLD.public_key THEN 'public_key'
    WHEN NEW.fingerprint_sha256 IS DISTINCT FROM OLD.fingerprint_sha256 THEN 'fingerprint_sha256'
    WHEN NEW.valid_from IS DISTINCT FROM OLD.valid_from THEN 'valid_from'
    WHEN NEW.created_by IS DISTINCT FROM OLD.created_by THEN 'created_by'
    WHEN NEW.client_ref IS DISTINCT FROM OLD.client_ref THEN 'client_ref'
    WHEN NEW.client_body_sha256 IS DISTINCT FROM OLD.client_body_sha256 THEN 'client_body_sha256'
    WHEN NEW.created_at IS DISTINCT FROM OLD.created_at THEN 'created_at'
    WHEN NEW.sealed_seed IS NOT NULL AND NEW.sealed_seed IS DISTINCT FROM OLD.sealed_seed
      THEN 'sealed_seed'
    WHEN OLD.status = 'retired' AND NEW.status IS DISTINCT FROM OLD.status THEN 'status'
    WHEN OLD.valid_until IS NOT NULL AND NEW.valid_until IS DISTINCT FROM OLD.valid_until
      THEN 'valid_until'
    WHEN OLD.retired_reason IS NOT NULL AND NEW.retired_reason IS DISTINCT FROM OLD.retired_reason
      THEN 'retired_reason'
    WHEN (NEW.dek_ref IS DISTINCT FROM OLD.dek_ref) <> (NEW.kek_version IS DISTINCT FROM OLD.kek_version)
      THEN CASE WHEN NEW.dek_ref IS DISTINCT FROM OLD.dek_ref THEN 'dek_ref' ELSE 'kek_version' END
    WHEN NEW.dek_ref IS DISTINCT FROM OLD.dek_ref AND NEW.sealed_seed IS NULL THEN 'dek_ref'
  END;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'trg_audit_signing_keys_write_once: refused a change to audit_signing_keys.% (ADR-0039)',
      changed USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_audit_signing_keys_write_once';
  END IF;
  RETURN NEW;
END $BODY$;
"""

_GUARD_SQL = """
CREATE TRIGGER trg_audit_signing_keys_write_once BEFORE UPDATE ON audit_signing_keys
  FOR EACH ROW EXECUTE FUNCTION audit_signing_keys_write_once_check();
ALTER TABLE audit_signing_keys ENABLE ALWAYS TRIGGER trg_audit_signing_keys_write_once;
"""

# Only where `pg_bootstrap.sql` created `cv_app` (0003/0011/0024 pattern); static, for bandit B608.
_REVOKE_DELETE_SQL = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
    "EXECUTE 'REVOKE DELETE ON audit_signing_keys FROM cv_app'; END IF; END $BODY$;"
)

_DOWNGRADE_SQL = """
LOCK TABLE audit_signing_keys IN SHARE MODE;
DO $BODY$
BEGIN
  IF EXISTS (SELECT 1 FROM audit_signing_keys) THEN
    RAISE EXCEPTION '0046_audit_signing_keys downgrade refused: audit_signing_keys holds rows. Exports name these keys, and a later upgrade would let boot mint a second v1. Fix forward with a new revision instead (C-5.2). If you must roll back, record every fingerprint, delete the rows as the owner role under change control (cv_app cannot delete them), then retry';
  END IF;
END $BODY$;
DROP TABLE audit_signing_keys;
DROP FUNCTION audit_signing_keys_write_once_check();
"""

"""exchange_accounts, api_keys, api_key_rotations (E27-T01, #834)

Revision ID: 0017_exchange_accounts_api_keys
Revises: 0016_audit_read_grants

DDL is `docs/plan/21-database-schema.md` §3.2.1-3.2.3 verbatim. Additive (C-5.1). Credential
columns (`key_id_enc`, `secret_enc`, `enc_nonce`, `dek_ref`) hold envelope-encrypted blobs or
handles only (C-5.9); there is no plaintext key column. Also adds the FK that 0001 deferred
for `user_account_access.exchange_account_id`. Audit tables are untouched.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_exchange_accounts_api_keys"
down_revision: str | None = "0016_audit_read_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADD_FK = """
ALTER TABLE user_account_access
  ADD CONSTRAINT fk_user_account_access_exchange_account_id_exchange_accounts
  FOREIGN KEY (exchange_account_id) REFERENCES exchange_accounts(id) ON DELETE CASCADE;
"""
_DROP_FK = """
ALTER TABLE user_account_access
  DROP CONSTRAINT IF EXISTS fk_user_account_access_exchange_account_id_exchange_accounts;
"""


def upgrade() -> None:
    op.execute(_TYPES_AND_ACCOUNTS)
    op.execute(_API_KEYS)
    op.execute(_ROTATIONS)
    op.execute(_ADD_FK)


def downgrade() -> None:
    op.execute(_DROP_FK)
    op.execute("DROP TABLE IF EXISTS api_key_rotations;")
    op.execute("DROP TABLE IF EXISTS api_keys;")
    op.execute("DROP TRIGGER IF EXISTS trg_ea_env_parent ON exchange_accounts;")
    op.execute("DROP FUNCTION IF EXISTS ea_env_parent_check();")
    op.execute("DROP TABLE IF EXISTS exchange_accounts;")
    op.execute("DROP TYPE IF EXISTS key_status;")
    op.execute("DROP TYPE IF EXISTS account_kind;")


_TYPES_AND_ACCOUNTS = """
CREATE TYPE account_kind AS ENUM ('main','sub');
CREATE TYPE key_status AS ENUM ('pending','active','rotating','revoked','expired','invalid');

CREATE TABLE exchange_accounts (
  id                    uuid PRIMARY KEY,
  exchange              exchange_code NOT NULL,
  env                   exchange_env NOT NULL,
  kind                  account_kind NOT NULL,
  exchange_uid          text NOT NULL,
  parent_account_id     uuid REFERENCES exchange_accounts(id) ON DELETE RESTRICT,
  label                 text NOT NULL,
  colour_token          text NOT NULL DEFAULT 'accent.neutral',
  is_enabled            boolean NOT NULL DEFAULT true,
  trading_enabled       boolean NOT NULL DEFAULT false,
  position_mode         text NOT NULL DEFAULT 'one_way',
  margin_mode           text NOT NULL DEFAULT 'cross',
  account_type          text NOT NULL DEFAULT 'UNIFIED',
  quote_ccy             text NOT NULL DEFAULT 'USDT',
  equity_cached_usd     numeric(38,18),
  equity_cached_at      timestamptz,
  max_sub_accounts_hint smallint NOT NULL DEFAULT 5,
  last_reconciled_at    timestamptz,
  created_by            uuid REFERENCES users(id) ON DELETE SET NULL,
  updated_by            uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  deleted_at            timestamptz,
  CONSTRAINT ea_parent_shape   CHECK ((kind = 'main') = (parent_account_id IS NULL)),
  CONSTRAINT ea_no_self_parent CHECK (parent_account_id IS DISTINCT FROM id),
  CONSTRAINT ea_posmode        CHECK (position_mode IN ('one_way','hedge')),
  CONSTRAINT ea_marginmode     CHECK (margin_mode IN ('cross','isolated','portfolio')),
  CONSTRAINT ea_acct_type      CHECK (account_type = 'UNIFIED'),
  CONSTRAINT ea_quote          CHECK (quote_ccy = 'USDT'),
  CONSTRAINT ea_uid_fmt        CHECK (exchange_uid ~ '^[0-9]{1,20}$')
);
CREATE UNIQUE INDEX ux_ea_uid ON exchange_accounts (exchange, env, exchange_uid)
  WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX ux_ea_label ON exchange_accounts (env, lower(label)) WHERE deleted_at IS NULL;
CREATE INDEX ix_ea_parent ON exchange_accounts (parent_account_id);
CREATE INDEX ix_ea_tradeable ON exchange_accounts (env)
  WHERE is_enabled AND trading_enabled AND deleted_at IS NULL;

CREATE FUNCTION ea_env_parent_check() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER trg_ea_env_parent BEFORE INSERT OR UPDATE OF env, parent_account_id
  ON exchange_accounts FOR EACH ROW EXECUTE FUNCTION ea_env_parent_check();
"""

_API_KEYS = """
CREATE TABLE api_keys (
  id                       uuid PRIMARY KEY,
  exchange_account_id      uuid NOT NULL REFERENCES exchange_accounts(id) ON DELETE CASCADE,
  label                    text NOT NULL,
  key_id_enc               bytea NOT NULL,
  key_id_last4             char(4) NOT NULL,
  secret_enc               bytea NOT NULL,
  enc_nonce                bytea NOT NULL,
  enc_alg                  text NOT NULL DEFAULT 'AES-256-GCM',
  dek_ref                  text NOT NULL,
  kek_version              integer NOT NULL DEFAULT 1,
  permission_snapshot      jsonb NOT NULL,
  permission_snapshot_at   timestamptz NOT NULL DEFAULT now(),
  can_trade                boolean NOT NULL DEFAULT false,
  can_withdraw             boolean NOT NULL DEFAULT false,
  can_transfer             boolean NOT NULL DEFAULT false,
  read_only                boolean NOT NULL DEFAULT false,
  ip_whitelist             cidr[],
  ip_whitelist_verified_at timestamptz,
  status                   key_status NOT NULL DEFAULT 'pending',
  expires_at               timestamptz,
  last_used_at             timestamptz,
  last_error_code          text,
  last_error_at            timestamptz,
  rotation_due_at          timestamptz,
  created_by               uuid REFERENCES users(id) ON DELETE SET NULL,
  updated_by               uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  revoked_at               timestamptz,
  CONSTRAINT ak_no_withdraw   CHECK (can_withdraw = false),
  CONSTRAINT ak_alg           CHECK (enc_alg = 'AES-256-GCM'),
  CONSTRAINT ak_nonce_len     CHECK (octet_length(enc_nonce) = 12),
  CONSTRAINT ak_last4         CHECK (key_id_last4 ~ '^[A-Za-z0-9]{4}$'),
  CONSTRAINT ak_readonly_excl CHECK (NOT (read_only AND can_trade)),
  CONSTRAINT ak_kek_pos       CHECK (kek_version >= 1),
  CONSTRAINT ak_snapshot_shape CHECK (
    permission_snapshot ? 'permissions'
    AND permission_snapshot ? 'uid'
    AND jsonb_typeof(permission_snapshot->'permissions') = 'object'
    AND COALESCE(jsonb_array_length(permission_snapshot->'permissions'->'Withdraw'), 0) = 0
  )
);
CREATE UNIQUE INDEX ux_api_keys_label ON api_keys (exchange_account_id, lower(label))
  WHERE revoked_at IS NULL;
CREATE UNIQUE INDEX ux_api_keys_active ON api_keys (exchange_account_id)
  WHERE status = 'active' AND revoked_at IS NULL;
CREATE INDEX ix_api_keys_rotation ON api_keys (rotation_due_at) WHERE status = 'active';
CREATE INDEX ix_api_keys_kek ON api_keys (kek_version) WHERE revoked_at IS NULL;
COMMENT ON COLUMN api_keys.secret_enc IS
  'SECRET: AES-256-GCM ciphertext; decryption only inside the credential broker module';
COMMENT ON COLUMN api_keys.key_id_enc IS
  'SECRET: AES-256-GCM ciphertext of the API key id; decryption only inside the credential broker';
"""

_ROTATIONS = """
CREATE TABLE api_key_rotations (
  id             uuid PRIMARY KEY,
  old_api_key_id uuid NOT NULL REFERENCES api_keys(id) ON DELETE RESTRICT,
  new_api_key_id uuid NOT NULL REFERENCES api_keys(id) ON DELETE RESTRICT,
  started_by     uuid REFERENCES users(id) ON DELETE SET NULL,
  started_at     timestamptz NOT NULL DEFAULT now(),
  validated_at   timestamptz,
  cutover_at     timestamptz,
  completed_at   timestamptz,
  failed_at      timestamptz,
  failure_reason text,
  grace_seconds  integer NOT NULL DEFAULT 900,
  CONSTRAINT akr_distinct CHECK (old_api_key_id <> new_api_key_id),
  CONSTRAINT akr_grace    CHECK (grace_seconds BETWEEN 0 AND 86400),
  CONSTRAINT akr_outcome  CHECK (NOT (completed_at IS NOT NULL AND failed_at IS NOT NULL))
);
CREATE INDEX ix_akr_open ON api_key_rotations (started_at)
  WHERE completed_at IS NULL AND failed_at IS NULL;
"""

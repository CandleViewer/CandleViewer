"""SQLAlchemy 2.0 Core `MetaData` — the autogenerate source of truth (§9.3
rule 12, `docs/plan/21-database-schema.md`).

Mirrors, as Core `Table` objects, the schema created by the hand-written SQL
in `candleviewer/migrations/versions/0001_identity_rbac_sessions_mfa.py`
(E09-T01) plus this ticket's `0002_rbac_seed` (bootstrap-owner seed only —
no new tables). Kept in lock-step by the `alembic check` CI gate (autogenerate
drift): a column added here without a matching revision, or vice versa, fails
that check. This module is deliberately Core-`Table`-based, not declarative
ORM classes — the ticket's deliverable is "SQLAlchemy 2.0 `MetaData`", and a
Core `Table` list is the smallest artefact that satisfies `alembic check`
without introducing an ORM mapping layer no code in this ticket's scope uses.

Enum types, the `sha256_hex` domain, and the two trigger functions
(`set_updated_at`, `trg_owner_floor_fn`) are DDL constructs Alembic/SQLAlchemy
Core cannot autogenerate-compare structurally the same way it does tables and
columns; they are asserted present by `services/api/tests/unit/migrations/`
instead (drift there would show as a failing hand-authored assertion, not a
silent `alembic check` false-negative).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    BYTEA,
    CHAR,
    CIDR,
    CITEXT,
    DOMAIN,
    ENUM,
    INET,
    JSONB,
    TIMESTAMP,
    UUID,
)

#: §9.3 rule 12 — verbatim from `docs/plan/21-database-schema.md`.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "ux_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

user_status = ENUM(
    "invited",
    "active",
    "disabled",
    "locked",
    name="user_status",
    metadata=metadata,
    create_type=False,
)
role_name = ENUM(
    "owner", "manager", "viewer", name="role_name", metadata=metadata, create_type=False
)
mfa_method_kind = ENUM(
    "totp",
    "webauthn",
    "recovery_code",
    name="mfa_method_kind",
    metadata=metadata,
    create_type=False,
)

exchange_env = ENUM(
    "live", "demo", "testnet", name="exchange_env", metadata=metadata, create_type=False
)
audit_outcome = ENUM(
    "success", "failure", "denied", name="audit_outcome", metadata=metadata, create_type=False
)
severity = ENUM(
    "debug",
    "info",
    "warning",
    "error",
    "critical",
    name="severity",
    metadata=metadata,
    create_type=False,
)


#: The `sha256_hex` DOMAIN (`CREATE DOMAIN sha256_hex AS char(64) CHECK (...)`,
#: revision 0001) is modelled as a first-class `postgresql.DOMAIN` so
#: `compare_type=True` diffs against the actual domain name/definition instead
#: of a same-shaped-but-different `String(64)` (which `alembic check` reports
#: as drift: DOMAIN vs. plain `character(64)`). `create_type=False` because the
#: domain is created by the hand-written SQL in revision 0001, not by
#: autogenerate/create_all.
_sha256_hex = DOMAIN(
    "sha256_hex",
    Text(),
    check="VALUE ~ '^[0-9a-f]{64}$'",
    create_type=False,
)

users = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "email",
        CITEXT,
        nullable=False,
        comment="PII: contact identifier; purge on account erase",
    ),
    Column("username", CITEXT, nullable=False),
    Column("display_name", Text, comment="PII: purge on account erase"),
    Column(
        "password_hash",
        Text,
        nullable=False,
        comment="SECRET: Argon2id digest; never logged, never returned by API",
    ),
    Column(
        "password_algo_params",
        JSONB,
        nullable=False,
        server_default=text('\'{"m":65536,"t":3,"p":4}\'::jsonb'),
    ),
    Column(
        "password_changed_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("status", user_status, nullable=False, server_default=text("'invited'")),
    Column("mfa_required", Boolean, nullable=False, server_default=text("true")),
    Column("failed_login_count", Integer, nullable=False, server_default=text("0")),
    Column("locked_until", TIMESTAMP(timezone=True)),
    Column("last_login_at", TIMESTAMP(timezone=True)),
    Column("last_login_ip", INET, comment="PII: purge on account erase"),
    Column("timezone", Text, nullable=False, server_default=text("'UTC'")),
    Column("locale", Text, nullable=False, server_default=text("'en-GB'")),
    Column("invited_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    CheckConstraint("position('@' in email) > 1", name="users_email_fmt"),
    CheckConstraint("char_length(username) BETWEEN 3 AND 32", name="users_uname_len"),
    CheckConstraint("password_hash LIKE '$argon2id$%'", name="users_pwd_argon"),
    CheckConstraint("failed_login_count >= 0", name="users_fail_nonneg"),
    Index("ux_users_email", "email", unique=True, postgresql_where=text("deleted_at IS NULL")),
    Index(
        "ux_users_username", "username", unique=True, postgresql_where=text("deleted_at IS NULL")
    ),
    Index("ix_users_status", "status", postgresql_where=text("deleted_at IS NULL")),
)

roles = Table(
    "roles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", role_name, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("is_system", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("name", name="roles_name_key"),
)

permissions = Table(
    "permissions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("code", Text, nullable=False),
    Column("domain", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("is_dangerous", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("code ~ '^[a-z0-9_]+:[a-z0-9_]+$'", name="permissions_code_fmt"),
    UniqueConstraint("code", name="permissions_code_key"),
)

role_permissions = Table(
    "role_permissions",
    metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    Column("granted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Index("ix_role_permissions_perm", "permission_id"),
)

user_roles = Table(
    "user_roles",
    metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True),
    Column("granted_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("granted_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", TIMESTAMP(timezone=True)),
    CheckConstraint("expires_at IS NULL OR expires_at > granted_at", name="user_roles_expiry"),
    Index("ix_user_roles_role", "role_id"),
)

user_invites = Table(
    "user_invites",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("role", role_name, nullable=False),
    Column(
        "token_hash",
        Text,
        nullable=False,
        comment=(
            "SECRET-DERIVED: sha256 hex of the one-time invite token; "
            "the raw token is never stored (E09-S05)."
        ),
    ),
    Column("invited_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("consumed_at", TIMESTAMP(timezone=True)),
    Column(
        "pending_password_hash",
        Text,
        comment=(
            "SECRET: Argon2id digest held until TOTP enrolment completes; "
            "moved to users.password_hash on activation (E09-S05)."
        ),
    ),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("char_length(token_hash) = 64", name="user_invites_hash_fmt"),
    CheckConstraint("expires_at > created_at", name="user_invites_expiry"),
    Index("ux_user_invites_token_hash", "token_hash", unique=True),
    Index("ix_user_invites_user", "user_id"),
)

onboarding_dismissals = Table(
    "onboarding_dismissals",
    metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("dismissed_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
)

user_account_access = Table(
    "user_account_access",
    metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "exchange_account_id",
        UUID(as_uuid=True),
        ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("can_trade", Boolean, nullable=False, server_default=text("false")),
    Column("can_view", Boolean, nullable=False, server_default=text("true")),
    Column("frozen", Boolean, nullable=False, server_default=text("false")),
    Column("frozen_at", TIMESTAMP(timezone=True)),
    Column("frozen_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("frozen_reason", Text),
    Column("max_daily_loss_usd", Numeric(38, 18)),
    Column("granted_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("frozen = false OR frozen_at IS NOT NULL", name="uaa_frozen_consistency"),
    CheckConstraint("can_trade = false OR can_view = true", name="uaa_trade_implies_view"),
    CheckConstraint(
        "max_daily_loss_usd IS NULL OR max_daily_loss_usd > 0", name="uaa_loss_positive"
    ),
    Index("ix_uaa_account", "exchange_account_id", postgresql_where=text("can_trade")),
    Index("ix_uaa_frozen", "exchange_account_id", postgresql_where=text("frozen")),
    comment=(
        "exchange_account_id has no FK yet: exchange_accounts is created by E27; "
        "that migration adds fk_user_account_access_exchange_account_id_exchange_accounts."
    ),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column(
        "refresh_token_hash",
        _sha256_hex,
        nullable=False,
        comment="SECRET: SHA-256 of the raw refresh token; raw token never stored",
    ),
    Column("access_token_jti", UUID(as_uuid=True)),
    Column("issued_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_seen_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    Column("revoked_reason", Text),
    Column("ip", INET, comment="PII: purge on account erase / retention job"),
    Column("user_agent", Text, comment="PII: purge on account erase / retention job"),
    Column("device_label", Text),
    Column("is_electron", Boolean, nullable=False, server_default=text("false")),
    Column("mfa_satisfied_at", TIMESTAMP(timezone=True)),
    Column(
        "tailscale_node",
        Text,
        comment="PII-adjacent: node identity from Tailscale header",
    ),
    Column(
        "idle_timeout_s",
        Integer,
        nullable=False,
        server_default=text("900"),
        comment=(
            "Per-session idle-lock timeout in seconds (5-60 min, default 15); "
            "the idle deadline is last_seen_at + this."
        ),
    ),
    Column(
        "step_up_elevations",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment=(
            'Step-up elevation per action class: {"<action_class>": '
            '"<expiry ISO-8601 UTC>"} (E09-S04).'
        ),
    ),
    Column(
        "step_up_failures",
        SmallInteger,
        nullable=False,
        server_default=text("0"),
        comment="Consecutive invalid step-up codes; 3 triggers the read-only downgrade (E09-S04).",
    ),
    Column(
        "readonly_until",
        TIMESTAMP(timezone=True),
        comment=(
            "Read-only downgrade expiry after 3 failed step-up codes (E09-S04); NULL = writable."
        ),
    ),
    CheckConstraint("expires_at > issued_at", name="sessions_expiry"),
    CheckConstraint("idle_timeout_s BETWEEN 300 AND 3600", name="sessions_idle_timeout_range"),
    CheckConstraint("step_up_failures BETWEEN 0 AND 3", name="sessions_step_up_failures_range"),
    UniqueConstraint("refresh_token_hash", name="sessions_refresh_token_hash_key"),
    Index("ix_sessions_user_live", "user_id", postgresql_where=text("revoked_at IS NULL")),
    Index("ix_sessions_expiry", "expires_at", postgresql_where=text("revoked_at IS NULL")),
)

sessions_rotation = Table(
    "sessions_rotation",
    metadata,
    Column("prev_session_id", ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "next_session_id",
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("rotated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("next_session_id", name="sessions_rotation_next_session_id_key"),
)

mfa_methods = Table(
    "mfa_methods",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", mfa_method_kind, nullable=False),
    Column("label", Text, nullable=False, server_default=text("''")),
    Column(
        "secret_enc",
        BYTEA,
        comment="SECRET: envelope-encrypted TOTP seed; plaintext only in services/api/secrets/",
    ),
    Column("secret_key_ref", Text),
    Column("credential_id", BYTEA),
    Column("public_key", BYTEA),
    Column("sign_count", BigInteger, nullable=False, server_default=text("0")),
    Column("aaguid", UUID(as_uuid=True)),
    Column("transports", ARRAY(Text)),
    Column("confirmed_at", TIMESTAMP(timezone=True)),
    Column("last_used_at", TIMESTAMP(timezone=True)),
    Column(
        "last_accepted_time_step",
        BigInteger,
        comment=(
            "Highest RFC 6238 time-step accepted so far for this method; a step <= this\n"
            '   value is a replay and must be rejected (ticket E09-S02 "Reused code is\n'
            '   rejected"). NULL means no code has ever been accepted.'
        ),
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    CheckConstraint("kind <> 'totp' OR secret_enc IS NOT NULL", name="mfa_totp_shape"),
    CheckConstraint(
        "kind <> 'webauthn' OR (credential_id IS NOT NULL AND public_key IS NOT NULL)",
        name="mfa_wa_shape",
    ),
    Index(
        "ux_mfa_webauthn_cred",
        "credential_id",
        unique=True,
        postgresql_where=text("credential_id IS NOT NULL"),
    ),
    Index("ix_mfa_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
)

mfa_challenges = Table(
    "mfa_challenges",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("session_id", ForeignKey("sessions.id", ondelete="CASCADE")),
    Column("kind", mfa_method_kind, nullable=False),
    Column("nonce", BYTEA, nullable=False, comment="SECRET: anti-replay challenge nonce"),
    Column("purpose", Text, nullable=False, server_default=text("'login'")),
    Column("attempts", SmallInteger, nullable=False, server_default=text("0")),
    Column("satisfied_at", TIMESTAMP(timezone=True)),
    Column("expires_at", TIMESTAMP(timezone=True), nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("attempts BETWEEN 0 AND 10", name="mfa_ch_attempts"),
    CheckConstraint("purpose IN ('login','step_up','enroll')", name="mfa_ch_purpose"),
    Index(
        "ix_mfa_ch_user_open",
        "user_id",
        "expires_at",
        postgresql_where=text("satisfied_at IS NULL"),
    ),
)

recovery_codes = Table(
    "recovery_codes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column(
        "code_hash",
        _sha256_hex,
        nullable=False,
        comment="SECRET: SHA-256 of the one-time recovery code",
    ),
    Column("used_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("user_id", "code_hash", name="recovery_codes_user_id_code_hash_key"),
    Index("ix_recovery_unused", "user_id", postgresql_where=text("used_at IS NULL")),
)

#: `audit_log` / `audit_checkpoints` (E09-T02, revision 0003_audit_log).
#: `prev_hash`/`entry_hash` are populated by the `audit_chain()` trigger, never
#: by the app (`server_default` intentionally omitted — a bare `bigserial`-style
#: PK plus trigger-computed columns has no default SQLAlchemy can express, so
#: they are simply `nullable=False` here to match the trigger's guarantee).
audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column(
        "record_id",
        UUID(as_uuid=True),
        nullable=False,
        comment=(
            "Writer-assigned idempotency key: WAL replay is ON CONFLICT (record_id) DO NOTHING"
        ),
    ),
    Column("prev_hash", _sha256_hex, nullable=False),
    Column("entry_hash", _sha256_hex, nullable=False),
    Column("actor_user_id", ForeignKey("users.id", ondelete="SET NULL")),
    Column("actor_label", Text, nullable=False),
    Column("actor_ip", INET, comment="PII: purge on account erase / retention job"),
    Column("session_id", UUID(as_uuid=True)),
    Column("action", Text, nullable=False),
    Column("object_kind", Text),
    Column("object_id", Text),
    Column("object_label", Text),
    Column("outcome", audit_outcome, nullable=False, server_default=text("'success'")),
    Column("severity", severity, nullable=False, server_default=text("'info'")),
    Column("reason", Text),
    Column(
        "before_state",
        JSONB,
        comment=(
            "Redacted diff source — SECRET-classified fields must never appear "
            "here (candleviewer.audit.redact)"
        ),
    ),
    Column(
        "after_state",
        JSONB,
        comment=(
            "Redacted diff source — SECRET-classified fields must never appear "
            "here (candleviewer.audit.redact)"
        ),
    ),
    Column("request_id", UUID(as_uuid=True)),
    Column("env", exchange_env),
    Column("event_ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("action ~ '^[a-z0-9_]+([.][a-z0-9_]+){1,3}$'", name="au_action_fmt"),
    UniqueConstraint("record_id", name="audit_log_record_id_key"),
    UniqueConstraint("entry_hash", name="audit_log_entry_hash_key"),
    Index("ix_audit_time", text("event_ts DESC")),
    Index("ix_audit_actor", "actor_user_id", text("event_ts DESC")),
    Index("ix_audit_action", "action", text("event_ts DESC")),
    Index("ix_audit_object", "object_kind", "object_id", text("event_ts DESC")),
    Index(
        "ix_audit_sev",
        "severity",
        text("event_ts DESC"),
        postgresql_where=text("severity IN ('error','critical')"),
    ),
)

audit_checkpoints = Table(
    "audit_checkpoints",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("head_id", BigInteger, nullable=False),
    Column("head_hash", _sha256_hex, nullable=False),
    Column("row_count", BigInteger, nullable=False),
    Column("signed_by", Text, nullable=False, server_default=text("'cv-audit-key-v1'")),
    Column("signature", BYTEA),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("head_id", name="audit_checkpoints_head_id_key"),
)

#: `instruments` / `instrument_versions` (E08-S01, revision 0004_instruments).
#: `symbol_code` and `exchange_code` are DDL-level DOMAIN/ENUM constructs
#: created by 0004 itself (no earlier revision scoped them — see that
#: revision's module docstring); modelled the same way `_sha256_hex` models
#: the `sha256_hex` domain above, with `create_type=False` for both.
symbol_code = DOMAIN(
    "symbol_code",
    Text(),
    check="VALUE ~ '^[A-Z0-9]{4,20}$'",
    create_type=False,
)
# DB schema mirror of the 0004_instruments
# DDL's `exchange_code` enum (E08-S01): this is the storage-layer value
# domain, not adapter logic; C-1.3 scopes this whole product to that single
# exchange, so the enum member is a schema fact, not leaked adapter vocab.
# The justified suppressions are on the matched lines below.
exchange_code = ENUM(
    # nosemgrep: cv-adapter-isolation reason=schema-enum-0004 owner=@basiltt review=2027-03-25
    "bybit",
    name="exchange_code",
    metadata=metadata,
    create_type=False,
)

instruments = Table(
    "instruments",
    metadata,
    Column("symbol", symbol_code, primary_key=True),
    # nosemgrep: cv-adapter-isolation reason=schema-enum-0004 owner=@basiltt review=2027-03-25
    Column("exchange", exchange_code, nullable=False, server_default=text("'bybit'")),
    Column("category", Text, nullable=False, server_default=text("'linear'")),
    Column("base_coin", Text, nullable=False),
    Column("quote_coin", Text, nullable=False, server_default=text("'USDT'")),
    Column("settle_coin", Text, nullable=False, server_default=text("'USDT'")),
    Column("status", Text, nullable=False),
    Column("tick_size", Numeric(38, 18), nullable=False),
    Column("qty_step", Numeric(38, 18), nullable=False),
    Column("min_order_qty", Numeric(38, 18), nullable=False),
    Column("max_order_qty", Numeric(38, 18), nullable=False),
    Column("min_notional_value", Numeric(38, 18)),
    Column("max_leverage", Numeric(10, 2), nullable=False),
    Column("leverage_step", Numeric(10, 2), nullable=False, server_default=text("0.01")),
    Column("price_scale", SmallInteger, nullable=False, server_default=text("2")),
    Column("funding_interval_min", Integer, nullable=False, server_default=text("480")),
    Column("launch_ts", TIMESTAMP(timezone=True)),
    Column("delivery_ts", TIMESTAMP(timezone=True)),
    Column("metadata_version", Integer, nullable=False, server_default=text("1")),
    Column(
        "raw",
        JSONB,
        nullable=False,
        comment=(
            "Full, unredacted instruments-info payload for this symbol, for "
            "audit and forward-compat fields."
        ),
    ),
    Column("refreshed_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("stale_since", TIMESTAMP(timezone=True)),
    CheckConstraint("category = 'linear'", name="inst_cat"),
    CheckConstraint("quote_coin = 'USDT'", name="inst_quote"),
    CheckConstraint("tick_size > 0 AND qty_step > 0", name="inst_ticks"),
    CheckConstraint("max_order_qty >= min_order_qty", name="inst_qty_rng"),
    CheckConstraint("metadata_version >= 1", name="inst_version"),
    Index("ix_instruments_status", "status"),
)

instrument_versions = Table(
    "instrument_versions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "symbol",
        symbol_code,
        ForeignKey("instruments.symbol", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("metadata_version", Integer, nullable=False),
    Column("tick_size", Numeric(38, 18), nullable=False),
    Column("qty_step", Numeric(38, 18), nullable=False),
    Column("min_order_qty", Numeric(38, 18), nullable=False),
    Column("max_order_qty", Numeric(38, 18), nullable=False),
    Column("min_notional_value", Numeric(38, 18)),
    Column("max_leverage", Numeric(10, 2), nullable=False),
    Column("leverage_step", Numeric(10, 2), nullable=False),
    Column("price_scale", SmallInteger, nullable=False),
    Column("funding_interval_min", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column(
        "changed_fields",
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'"),
        comment=(
            "Field names that differed from the immediately preceding version, "
            "for InstrumentUpdatedEvent.changed_fields."
        ),
    ),
    Column(
        "raw",
        JSONB,
        nullable=False,
    ),
    Column("recorded_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("metadata_version >= 1", name="iv_version"),
    UniqueConstraint("symbol", "metadata_version", name="iv_unique_version"),
    Index("ix_instrument_versions_symbol", "symbol", text("metadata_version DESC")),
)

#: `system_events` (E04-T04, revision 0008_system_events).
system_events = Table(
    "system_events",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("component", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("severity", severity, nullable=False, server_default=text("'info'")),
    Column("symbol", symbol_code),
    Column("exchange_account_id", UUID(as_uuid=True)),
    Column("message", Text, nullable=False),
    Column("details", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("ret_code", Text),
    Column("correlation_id", UUID(as_uuid=True)),
    Column("resolved_at", TIMESTAMP(timezone=True)),
    Column("resolved_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("event_ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "component IN ('ingestion','book_engine','bars','orderflow','oms','rules','recorder',"
        "'replay','api','ws','db','exchange','auth','backup')",
        name="se_component",
    ),
    Index("ix_se_time", text("event_ts DESC")),
    Index(
        "ix_se_sev_open",
        "severity",
        text("event_ts DESC"),
        postgresql_where=text("resolved_at IS NULL"),
    ),
    Index("ix_se_component", "component", text("event_ts DESC")),
    Index(
        "ix_se_symbol",
        "symbol",
        text("event_ts DESC"),
        postgresql_where=text("symbol IS NOT NULL"),
    ),
)


#: Recorder tables (E16-T01, revision 0011_recorder) - `21-database-schema.md` Sec.3.6.
stream_kind = ENUM(
    "trades",
    "orderbook_delta",
    "orderbook_snapshot",
    "tickers",
    "klines",
    "liquidations",
    "open_interest",
    "funding",
    name="stream_kind",
    metadata=metadata,
    create_type=False,
)
record_reason = ENUM(
    "manual",
    "chart_open",
    "position_open",
    "rule_dependency",
    "alert_dependency",
    name="record_reason",
    metadata=metadata,
    create_type=False,
)
recording_state = ENUM(
    "idle",
    "starting",
    "recording",
    "degraded",
    "stopping",
    "stopped",
    "error",
    name="recording_state",
    metadata=metadata,
    create_type=False,
)
retention_action = ENUM(
    "drop",
    "archive_parquet",
    "downsample",
    "pin",
    name="retention_action",
    metadata=metadata,
    create_type=False,
)

recorded_symbols = Table(
    "recorded_symbols",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "symbol",
        symbol_code,
        ForeignKey("instruments.symbol", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("env", exchange_env, nullable=False, server_default=text("'live'")),
    Column("reason", record_reason, nullable=False, server_default=text("'manual'")),
    Column("reason_refs", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column(
        "streams",
        ARRAY(stream_kind),
        nullable=False,
        server_default=text("'{trades,orderbook_delta,tickers,liquidations}'"),
    ),
    Column("orderbook_depth", SmallInteger, nullable=False, server_default=text("200")),
    Column("pinned", Boolean, nullable=False, server_default=text("false")),
    Column("retention_days", Integer),
    Column("priority", SmallInteger, nullable=False, server_default=text("100")),
    Column("added_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("auto_added_at", TIMESTAMP(timezone=True)),
    Column("first_recorded_at", TIMESTAMP(timezone=True)),
    Column("last_recorded_at", TIMESTAMP(timezone=True)),
    Column("bytes_estimate", BigInteger, nullable=False, server_default=text("0")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("removed_at", TIMESTAMP(timezone=True)),
    CheckConstraint("orderbook_depth IN (1,50,200,500)", name="rs_depth"),
    CheckConstraint(
        "retention_days IS NULL OR retention_days BETWEEN 1 AND 3650", name="rs_retention"
    ),
    CheckConstraint("array_length(streams,1) >= 1", name="rs_streams"),
    CheckConstraint("reason = 'manual' OR auto_added_at IS NOT NULL", name="rs_autoshape"),
    Index(
        "ux_rs_symbol", "symbol", "env", unique=True, postgresql_where=text("removed_at IS NULL")
    ),
    Index("ix_rs_pinned", "symbol", postgresql_where=text("pinned AND removed_at IS NULL")),
    Index(
        "ix_rs_auto",
        "reason",
        postgresql_where=text("removed_at IS NULL AND reason <> 'manual'"),
    ),
)

recording_sessions = Table(
    "recording_sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "recorded_symbol_id",
        ForeignKey("recorded_symbols.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("symbol", symbol_code, nullable=False),
    Column("state", recording_state, nullable=False, server_default=text("'starting'")),
    Column("streams", ARRAY(stream_kind), nullable=False),
    Column("orderbook_depth", SmallInteger, nullable=False),
    Column("ws_endpoint", Text, nullable=False),
    Column("started_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("ended_at", TIMESTAMP(timezone=True)),
    Column("first_event_ts", TIMESTAMP(timezone=True)),
    Column("last_event_ts", TIMESTAMP(timezone=True)),
    Column("messages_received", BigInteger, nullable=False, server_default=text("0")),
    Column("messages_dropped", BigInteger, nullable=False, server_default=text("0")),
    Column("bytes_written", BigInteger, nullable=False, server_default=text("0")),
    Column("reconnect_count", Integer, nullable=False, server_default=text("0")),
    Column("snapshot_count", Integer, nullable=False, server_default=text("0")),
    Column("degraded_seconds", Integer, nullable=False, server_default=text("0")),
    Column("end_reason", Text),
    Column("error_message", Text),
    CheckConstraint("messages_received >= 0 AND messages_dropped >= 0", name="recs_counts"),
    CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="recs_window"),
    Index("ix_recs_symbol_time", "symbol", text("started_at DESC")),
    Index(
        "ix_recs_live",
        "symbol",
        postgresql_where=text("state IN ('starting','recording','degraded')"),
    ),
)

recording_gaps = Table(
    "recording_gaps",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "recording_session_id",
        ForeignKey("recording_sessions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("symbol", symbol_code, nullable=False),
    Column("stream", stream_kind, nullable=False),
    Column("gap_start", TIMESTAMP(timezone=True), nullable=False),
    Column("gap_end", TIMESTAMP(timezone=True), nullable=False),
    Column("cause", Text, nullable=False),
    Column("backfilled", Boolean, nullable=False, server_default=text("false")),
    Column("backfill_source", Text),
    CheckConstraint("gap_end > gap_start", name="rg_window"),
    CheckConstraint(
        "cause IN ('ws_disconnect','backpressure_drop','process_restart','seq_jump',"
        "'exchange_outage')",
        name="rg_cause",
    ),
    Index("ix_rg_symbol_time", "symbol", text("gap_start DESC")),
)

retention_policies = Table(
    "retention_policies",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("scope", Text, nullable=False),
    Column("symbol", symbol_code),
    Column("stream", stream_kind, nullable=False),
    Column("retain_days", Integer, nullable=False, server_default=text("30")),
    Column("action", retention_action, nullable=False, server_default=text("'archive_parquet'")),
    Column("downsample_to", Text),
    Column("archive_path", Text),
    Column("max_disk_gb", Integer),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("last_run_at", TIMESTAMP(timezone=True)),
    Column("last_run_deleted_rows", BigInteger, nullable=False, server_default=text("0")),
    Column("created_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("scope IN ('default','symbol')", name="rp_scope"),
    CheckConstraint("(scope = 'symbol') = (symbol IS NOT NULL)", name="rp_symshape"),
    CheckConstraint("retain_days BETWEEN 1 AND 3650", name="rp_days"),
    CheckConstraint("action <> 'downsample' OR downsample_to IS NOT NULL", name="rp_downshape"),
    CheckConstraint("max_disk_gb IS NULL OR max_disk_gb > 0", name="rp_disk"),
    Index("ux_rp_default", "stream", unique=True, postgresql_where=text("scope = 'default'")),
    Index(
        "ux_rp_symbol",
        "symbol",
        "stream",
        unique=True,
        postgresql_where=text("scope = 'symbol'"),
    ),
)


#: Rule-engine tables (E35-T02, revision 0013_rules) - `21-database-schema.md` Sec.3.4.
#: `scope_account_id` / `trade_group_id` carry no FK yet (E27 / E34 own those tables).
rule_scope = ENUM(
    "global",
    "account",
    "symbol",
    "position",
    "trade_group",
    name="rule_scope",
    metadata=metadata,
    create_type=False,
)
rule_mode = ENUM(
    "disabled", "simulate", "armed", name="rule_mode", metadata=metadata, create_type=False
)
rule_run_status = ENUM(
    "running",
    "ok",
    "error",
    "aborted",
    "throttled",
    name="rule_run_status",
    metadata=metadata,
    create_type=False,
)

rules = Table(
    "rules",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("owner_user_id", ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("scope", rule_scope, nullable=False, server_default=text("'global'")),
    Column("scope_account_id", UUID(as_uuid=True)),
    Column("scope_symbol", symbol_code),
    Column("mode", rule_mode, nullable=False, server_default=text("'disabled'")),
    Column(
        "active_version_id",
        ForeignKey(
            "rule_versions.id", ondelete="RESTRICT", name="rules_active_version_fk", use_alter=True
        ),
    ),
    Column("editor", Text, nullable=False, server_default=text("'form'")),
    Column("priority", SmallInteger, nullable=False, server_default=text("100")),
    Column("eval_interval_ms", Integer, nullable=False, server_default=text("250")),
    Column("cooldown_seconds", Integer, nullable=False, server_default=text("0")),
    Column("max_fires_per_day", Integer),
    Column("max_fires_per_hour", Integer),
    Column("requires_confirmation", Boolean, nullable=False, server_default=text("false")),
    Column("armed_at", TIMESTAMP(timezone=True)),
    Column("armed_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("disabled_reason", Text),
    Column("last_fired_at", TIMESTAMP(timezone=True)),
    Column("fire_count", BigInteger, nullable=False, server_default=text("0")),
    Column("error_count", BigInteger, nullable=False, server_default=text("0")),
    Column("created_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("updated_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    Column("last_edit_session_id", Text),
    Column("last_edit_at", TIMESTAMP(timezone=True)),
    CheckConstraint("editor IN ('form','graph')", name="rule_editor"),
    CheckConstraint("eval_interval_ms BETWEEN 50 AND 3600000", name="rule_interval"),
    CheckConstraint("cooldown_seconds BETWEEN 0 AND 86400", name="rule_cooldown"),
    CheckConstraint("priority BETWEEN 0 AND 1000", name="rule_prio"),
    CheckConstraint("scope <> 'account' OR scope_account_id IS NOT NULL", name="rule_scope_acct"),
    CheckConstraint("scope <> 'symbol' OR scope_symbol IS NOT NULL", name="rule_scope_sym"),
    CheckConstraint(
        "mode <> 'armed' OR (armed_at IS NOT NULL AND armed_by IS NOT NULL "
        "AND active_version_id IS NOT NULL)",
        name="rule_armed_shape",
    ),
    CheckConstraint(
        "(max_fires_per_day IS NULL OR max_fires_per_day > 0) "
        "AND (max_fires_per_hour IS NULL OR max_fires_per_hour > 0)",
        name="rule_fires_pos",
    ),
    Index(
        "ux_rules_name",
        "owner_user_id",
        text("lower(name)"),
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    ),
    Index(
        "ix_rules_active",
        "mode",
        "priority",
        postgresql_where=text("mode <> 'disabled' AND deleted_at IS NULL"),
    ),
    Index("ix_rules_symbol", "scope_symbol", postgresql_where=text("scope_symbol IS NOT NULL")),
    Index(
        "ix_rules_account",
        "scope_account_id",
        postgresql_where=text("scope_account_id IS NOT NULL"),
    ),
)

rule_versions = Table(
    "rule_versions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("rule_id", ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("ir", JSONB, nullable=False),
    Column("ir_hash", _sha256_hex, nullable=False),
    Column("graph_layout", JSONB),
    Column("form_model", JSONB),
    Column("compiler_version", Text, nullable=False),
    Column("notes", Text, nullable=False, server_default=text("''")),
    Column("is_valid", Boolean, nullable=False, server_default=text("false")),
    Column("validation_errors", JSONB),
    Column("backtest_summary", JSONB),
    Column("created_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("rule_id", "version", name="rule_versions_rule_id_version_key"),
    UniqueConstraint("rule_id", "ir_hash", name="rule_versions_rule_id_ir_hash_key"),
    CheckConstraint("version >= 1", name="rv_version_pos"),
    CheckConstraint(
        "jsonb_typeof(ir) = 'object' AND ir ? 'conditions' AND ir ? 'actions'",
        name="rv_ir_obj",
    ),
    Index("ix_rv_rule", "rule_id", text("version DESC")),
)

rule_runs = Table(
    "rule_runs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("rule_id", ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
    Column("rule_version_id", ForeignKey("rule_versions.id", ondelete="RESTRICT"), nullable=False),
    Column("status", rule_run_status, nullable=False, server_default=text("'running'")),
    Column("mode", rule_mode, nullable=False),
    Column("trigger_reason", Text, nullable=False),
    Column("scope_account_id", UUID(as_uuid=True)),
    Column("scope_symbol", symbol_code),
    Column(
        "input_snapshot",
        JSONB,
        nullable=False,
        comment="financial/confidential: may hold equity, PnL and position size; never log at INFO",
    ),
    Column("matched", Boolean, nullable=False, server_default=text("false")),
    Column("actions_planned", JSONB),
    Column("actions_executed", JSONB),
    Column("trade_group_id", UUID(as_uuid=True)),
    Column("error_code", Text),
    Column("error_message", Text),
    Column("duration_ms", Integer),
    Column("started_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("finished_at", TIMESTAMP(timezone=True)),
    CheckConstraint(
        "trigger_reason IN ('tick','bar_close','fill','manual','schedule',"
        "'position_change','alert')",
        name="rr_trigger",
    ),
    CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="rr_duration"),
    Index("ix_rr_rule_time", "rule_id", text("started_at DESC")),
    Index("ix_rr_matched", "rule_id", text("started_at DESC"), postgresql_where=text("matched")),
    Index("ix_rr_errors", text("started_at DESC"), postgresql_where=text("status = 'error'")),
    Index("ix_rr_group", "trade_group_id", postgresql_where=text("trade_group_id IS NOT NULL")),
)

rule_events = Table(
    "rule_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("rule_run_id", ForeignKey("rule_runs.id", ondelete="CASCADE"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("node_ref", Text),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("severity", severity, nullable=False, server_default=text("'info'")),
    Column("event_ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("rule_run_id", "seq", name="rule_events_rule_run_id_seq_key"),
    CheckConstraint(
        "kind IN ('condition_eval','action_start','action_ok','action_fail','throttled','log')",
        name="re_kind",
    ),
    Index("ix_re_run", "rule_run_id", "seq"),
    Index("ix_re_time", text("event_ts DESC")),
)

# --- 0014_alerts (E40-T01) -------------------------------------------------------------------
alert_channel = ENUM(
    "in_app",
    "email",
    "webhook",
    "push",
    "desktop",
    name="alert_channel",
    metadata=metadata,
    create_type=False,
)
alert_trigger_mode = ENUM(
    "once",
    "every_time",
    "once_per_bar",
    name="alert_trigger_mode",
    metadata=metadata,
    create_type=False,
)
delivery_status = ENUM(
    "queued",
    "sent",
    "failed",
    "suppressed",
    "acked",
    name="delivery_status",
    metadata=metadata,
    create_type=False,
)

alerts = Table(
    "alerts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("owner_user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("symbol", symbol_code),
    Column("scope_account_id", UUID(as_uuid=True)),
    Column("condition_ir", JSONB, nullable=False),
    Column("condition_hash", _sha256_hex, nullable=False),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("trigger_mode", alert_trigger_mode, nullable=False, server_default=text("'once'")),
    Column("cooldown_seconds", Integer, nullable=False, server_default=text("60")),
    Column("snoozed_until", TIMESTAMP(timezone=True)),
    Column("expires_at", TIMESTAMP(timezone=True)),
    Column("severity", severity, nullable=False, server_default=text("'info'")),
    Column("channels", ARRAY(alert_channel), nullable=False, server_default=text("'{in_app}'")),
    Column(
        "webhook_url_enc", BYTEA, comment="SECRET: envelope-encrypted; never selected into API DTOs"
    ),
    Column("webhook_secret_enc", BYTEA, comment="SECRET: envelope-encrypted HMAC key"),
    Column("message_template", Text, nullable=False, server_default=text("''")),
    Column("last_fired_at", TIMESTAMP(timezone=True)),
    Column("fire_count", BigInteger, nullable=False, server_default=text("0")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    CheckConstraint("cooldown_seconds BETWEEN 0 AND 86400", name="al_cooldown"),
    CheckConstraint("array_length(channels,1) BETWEEN 1 AND 5", name="al_channels"),
    CheckConstraint(
        "NOT ('webhook' = ANY(channels)) OR webhook_url_enc IS NOT NULL", name="al_webhook"
    ),
    Index(
        "ux_alerts_name",
        "owner_user_id",
        text("lower(name)"),
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    ),
    Index("ix_alerts_live", "symbol", postgresql_where=text("enabled AND deleted_at IS NULL")),
    Index("ix_alerts_snooze", "snoozed_until", postgresql_where=text("snoozed_until IS NOT NULL")),
    Index(
        "ix_alerts_expiry",
        "expires_at",
        postgresql_where=text("expires_at IS NOT NULL AND deleted_at IS NULL"),
    ),
)

alert_deliveries = Table(
    "alert_deliveries",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("alert_id", ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", ForeignKey("users.id", ondelete="SET NULL")),
    Column("channel", alert_channel, nullable=False),
    Column("status", delivery_status, nullable=False, server_default=text("'queued'")),
    Column("title", Text, nullable=False),
    Column("body", Text, nullable=False, server_default=text("''")),
    Column("context", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("attempt", SmallInteger, nullable=False, server_default=text("0")),
    Column("http_status", SmallInteger),
    Column("error_message", Text),
    Column("queued_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("sent_at", TIMESTAMP(timezone=True)),
    Column("acked_at", TIMESTAMP(timezone=True)),
    Column("acked_by", ForeignKey("users.id", ondelete="SET NULL")),
    CheckConstraint("attempt BETWEEN 0 AND 10", name="ad_attempt"),
    Index("ix_ad_alert_time", "alert_id", text("queued_at DESC")),
    Index("ix_ad_pending", "queued_at", postgresql_where=text("status = 'queued'")),
    Index(
        "ix_ad_user_unack",
        "user_id",
        text("queued_at DESC"),
        postgresql_where=text("status = 'sent' AND acked_at IS NULL"),
    ),
)

outbox = Table(
    "outbox",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("topic", Text, nullable=False),
    Column("dedup_key", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("available_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("attempts", SmallInteger, nullable=False, server_default=text("0")),
    Column("max_attempts", SmallInteger, nullable=False, server_default=text("8")),
    Column("locked_by", Text),
    Column("locked_until", TIMESTAMP(timezone=True)),
    Column("processed_at", TIMESTAMP(timezone=True)),
    Column("dead_at", TIMESTAMP(timezone=True)),
    Column("last_error", Text),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("attempts >= 0 AND attempts <= max_attempts + 1", name="ob_attempts"),
    Index("ux_outbox_dedup", "topic", "dedup_key", unique=True),
    Index(
        "ix_outbox_ready",
        "available_at",
        postgresql_where=text("processed_at IS NULL AND dead_at IS NULL"),
    ),
)

#: `exchange_accounts` / `api_keys` / `api_key_rotations` (E27-T01, revision
#: 0017_exchange_accounts_api_keys). The trigger `trg_ea_env_parent` and the
#: CHECK constraints are asserted by the 0017 migration tests, not autogenerate.
account_kind = ENUM("main", "sub", name="account_kind", metadata=metadata, create_type=False)
key_status = ENUM(
    "pending",
    "active",
    "rotating",
    "revoked",
    "expired",
    "invalid",
    name="key_status",
    metadata=metadata,
    create_type=False,
)

exchange_accounts = Table(
    "exchange_accounts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("exchange", exchange_code, nullable=False),
    Column("env", exchange_env, nullable=False),
    Column("kind", account_kind, nullable=False),
    Column("exchange_uid", Text, nullable=False),
    Column("parent_account_id", ForeignKey("exchange_accounts.id", ondelete="RESTRICT")),
    Column("label", Text, nullable=False),
    Column("colour_token", Text, nullable=False, server_default=text("'accent.neutral'")),
    Column("is_enabled", Boolean, nullable=False, server_default=text("true")),
    Column("trading_enabled", Boolean, nullable=False, server_default=text("false")),
    Column("position_mode", Text, nullable=False, server_default=text("'one_way'")),
    Column("margin_mode", Text, nullable=False, server_default=text("'cross'")),
    Column("account_type", Text, nullable=False, server_default=text("'UNIFIED'")),
    Column("quote_ccy", Text, nullable=False, server_default=text("'USDT'")),
    Column("equity_cached_usd", Numeric(38, 18)),
    Column("equity_cached_at", TIMESTAMP(timezone=True)),
    Column("max_sub_accounts_hint", SmallInteger, nullable=False, server_default=text("5")),
    Column("last_reconciled_at", TIMESTAMP(timezone=True)),
    Column("created_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("updated_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    CheckConstraint("(kind = 'main') = (parent_account_id IS NULL)", name="ea_parent_shape"),
    CheckConstraint("parent_account_id IS DISTINCT FROM id", name="ea_no_self_parent"),
    CheckConstraint("position_mode IN ('one_way','hedge')", name="ea_posmode"),
    CheckConstraint("margin_mode IN ('cross','isolated','portfolio')", name="ea_marginmode"),
    CheckConstraint("account_type = 'UNIFIED'", name="ea_acct_type"),
    CheckConstraint("quote_ccy = 'USDT'", name="ea_quote"),
    CheckConstraint("exchange_uid ~ '^[0-9]{1,20}$'", name="ea_uid_fmt"),
    Index(
        "ux_ea_uid",
        "exchange",
        "env",
        "exchange_uid",
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    ),
    Index(
        "ux_ea_label",
        "env",
        text("lower(label)"),
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    ),
    Index("ix_ea_parent", "parent_account_id"),
    Index(
        "ix_ea_tradeable",
        "env",
        postgresql_where=text("is_enabled AND trading_enabled AND deleted_at IS NULL"),
    ),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "exchange_account_id",
        ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("label", Text, nullable=False),
    Column(
        "key_id_enc",
        BYTEA,
        nullable=False,
        comment=(
            "SECRET: AES-256-GCM ciphertext of the API key id; decryption only inside "
            "the credential broker"
        ),
    ),
    Column("key_id_last4", CHAR(4), nullable=False),
    Column(
        "secret_enc",
        BYTEA,
        nullable=False,
        comment=(
            "SECRET: AES-256-GCM ciphertext; decryption only inside the credential broker module"
        ),
    ),
    Column("enc_nonce", BYTEA, nullable=False),
    Column("enc_alg", Text, nullable=False, server_default=text("'AES-256-GCM'")),
    Column("dek_ref", Text, nullable=False),
    Column("kek_version", Integer, nullable=False, server_default=text("1")),
    Column("permission_snapshot", JSONB, nullable=False),
    Column(
        "permission_snapshot_at",
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("can_trade", Boolean, nullable=False, server_default=text("false")),
    Column("can_withdraw", Boolean, nullable=False, server_default=text("false")),
    Column("can_transfer", Boolean, nullable=False, server_default=text("false")),
    Column("read_only", Boolean, nullable=False, server_default=text("false")),
    Column("ip_whitelist", ARRAY(CIDR)),
    Column("ip_whitelist_verified_at", TIMESTAMP(timezone=True)),
    Column("status", key_status, nullable=False, server_default=text("'pending'")),
    Column("expires_at", TIMESTAMP(timezone=True)),
    Column("last_used_at", TIMESTAMP(timezone=True)),
    Column("last_error_code", Text),
    Column("last_error_at", TIMESTAMP(timezone=True)),
    Column("rotation_due_at", TIMESTAMP(timezone=True)),
    Column("created_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("updated_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("revoked_at", TIMESTAMP(timezone=True)),
    CheckConstraint("can_withdraw = false", name="ak_no_withdraw"),
    CheckConstraint("enc_alg = 'AES-256-GCM'", name="ak_alg"),
    CheckConstraint("octet_length(enc_nonce) = 12", name="ak_nonce_len"),
    CheckConstraint("key_id_last4 ~ '^[A-Za-z0-9]{4}$'", name="ak_last4"),
    CheckConstraint("NOT (read_only AND can_trade)", name="ak_readonly_excl"),
    CheckConstraint("kek_version >= 1", name="ak_kek_pos"),
    Index(
        "ux_api_keys_label",
        "exchange_account_id",
        text("lower(label)"),
        unique=True,
        postgresql_where=text("revoked_at IS NULL"),
    ),
    Index(
        "ux_api_keys_active",
        "exchange_account_id",
        unique=True,
        postgresql_where=text("status = 'active' AND revoked_at IS NULL"),
    ),
    Index("ix_api_keys_rotation", "rotation_due_at", postgresql_where=text("status = 'active'")),
    Index("ix_api_keys_kek", "kek_version", postgresql_where=text("revoked_at IS NULL")),
)

api_key_rotations = Table(
    "api_key_rotations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("old_api_key_id", ForeignKey("api_keys.id", ondelete="RESTRICT"), nullable=False),
    Column("new_api_key_id", ForeignKey("api_keys.id", ondelete="RESTRICT"), nullable=False),
    Column("started_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("started_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("validated_at", TIMESTAMP(timezone=True)),
    Column("cutover_at", TIMESTAMP(timezone=True)),
    Column("completed_at", TIMESTAMP(timezone=True)),
    Column("failed_at", TIMESTAMP(timezone=True)),
    Column("failure_reason", Text),
    Column("grace_seconds", Integer, nullable=False, server_default=text("900")),
    CheckConstraint("old_api_key_id <> new_api_key_id", name="akr_distinct"),
    CheckConstraint("grace_seconds BETWEEN 0 AND 86400", name="akr_grace"),
    CheckConstraint("NOT (completed_at IS NOT NULL AND failed_at IS NOT NULL)", name="akr_outcome"),
    Index(
        "ix_akr_open",
        "started_at",
        postgresql_where=text("completed_at IS NULL AND failed_at IS NULL"),
    ),
)

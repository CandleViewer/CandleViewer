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
    Computed,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
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
    JSON,
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
    # E42-T10 (`0036_users_purge`): the deferred PII purge's schedule and its mark (#965 O6).
    Column("purge_after", TIMESTAMP(timezone=True)),
    Column("anonymised_at", TIMESTAMP(timezone=True)),
    CheckConstraint("position('@' in email) > 1", name="users_email_fmt"),
    CheckConstraint("char_length(username) BETWEEN 3 AND 32", name="users_uname_len"),
    CheckConstraint("password_hash LIKE '$argon2id$%'", name="users_pwd_argon"),
    CheckConstraint("failed_login_count >= 0", name="users_fail_nonneg"),
    CheckConstraint("anonymised_at IS NULL OR purge_after IS NOT NULL", name="users_purge_shape"),
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

#: Replay sessions (E26-T01, revision 0023_replay_sessions) - `21-database-schema.md` Sec.3.6.4.
#: `replay_state` mirrors every B12 `replay` chart state (C-2.19): the six API values, then the
#: transient `stepping` and the final `destroyed`.
replay_state = ENUM(
    "created",
    "buffering",
    "playing",
    "paused",
    "finished",
    "error",
    "stepping",
    "destroyed",
    name="replay_state",
    metadata=metadata,
    create_type=False,
)

replay_sessions = Table(
    "replay_sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("recording_session_id", ForeignKey("recording_sessions.id", ondelete="SET NULL")),
    Column("symbol", symbol_code, nullable=False),
    Column("range_start", TIMESTAMP(timezone=True), nullable=False),
    Column("range_end", TIMESTAMP(timezone=True), nullable=False),
    Column("cursor_ts", TIMESTAMP(timezone=True)),
    Column("speed", Numeric(6, 2), nullable=False, server_default=text("1")),
    Column("state", replay_state, nullable=False, server_default=text("'created'")),
    Column("source_tier", Text, nullable=False, server_default=text("'auto'")),
    Column("paper_trading", Boolean, nullable=False, server_default=text("false")),
    Column("paper_account_id", ForeignKey("exchange_accounts.id", ondelete="SET NULL")),
    Column(
        "bookmarks",
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment=(
            "PII: user notes on recorded timestamps; owner-scoped reads; "
            "purged with the user (CASCADE)"
        ),
    ),
    Column("loop_enabled", Boolean, nullable=False, server_default=text("false")),
    Column("events_emitted", BigInteger, nullable=False, server_default=text("0")),
    Column("gap_warnings", Integer, nullable=False, server_default=text("0")),
    Column("error_message", Text),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("finished_at", TIMESTAMP(timezone=True)),
    CheckConstraint("range_end > range_start", name="rps_range"),
    CheckConstraint("speed BETWEEN 0.1 AND 100", name="rps_speed"),
    CheckConstraint("source_tier IN ('auto','questdb','parquet')", name="rps_tier"),
    CheckConstraint(
        "cursor_ts IS NULL OR (cursor_ts >= range_start AND cursor_ts <= range_end)",
        name="rps_cursor",
    ),
    CheckConstraint("paper_trading = false OR paper_account_id IS NOT NULL", name="rps_paper"),
    Index("ix_rps_user_time", "user_id", text("created_at DESC")),
    Index(
        "ix_rps_live",
        "state",
        postgresql_where=text("state IN ('buffering','playing','paused','stepping')"),
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
    # 0031_policy_disarm (#836 slice 2d): the self-check's last force-disable, owed its record
    # until `policy_disarm_audited_at` is set.
    Column("policy_disarm_code", Text),
    Column("policy_disarmed_at", TIMESTAMP(timezone=True)),
    Column("policy_disarm_audited_at", TIMESTAMP(timezone=True)),
    CheckConstraint("(kind = 'main') = (parent_account_id IS NULL)", name="ea_parent_shape"),
    CheckConstraint("parent_account_id IS DISTINCT FROM id", name="ea_no_self_parent"),
    CheckConstraint("position_mode IN ('one_way','hedge')", name="ea_posmode"),
    CheckConstraint("margin_mode IN ('cross','isolated','portfolio')", name="ea_marginmode"),
    CheckConstraint("account_type = 'UNIFIED'", name="ea_acct_type"),
    CheckConstraint("quote_ccy = 'USDT'", name="ea_quote"),
    CheckConstraint("exchange_uid ~ '^[0-9]{1,20}$'", name="ea_uid_fmt"),
    CheckConstraint("policy_disarm_code ~ '^[a-z0-9_]{1,40}$'", name="ea_disarm_code_fmt"),
    CheckConstraint(
        "(policy_disarm_code IS NULL) = (policy_disarmed_at IS NULL) "
        "AND (policy_disarm_audited_at IS NULL OR policy_disarmed_at IS NOT NULL)",
        name="ea_disarm_shape",
    ),
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
    CheckConstraint("can_transfer = false", name="ak_no_transfer"),  # revision 0019 (#2240)
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

#: `kek_versions` (E27-T02, revision 0020_kek_versions): non-secret KEK key-check values.
#: 0026_kek_versions_env (#2338): one lineage per environment, keyed (env, version).
kek_versions = Table(
    "kek_versions",
    metadata,
    Column("version", Integer, autoincrement=False),
    Column("kcv", BYTEA, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("retired_at", TIMESTAMP(timezone=True)),
    Column("env", exchange_env, nullable=False),
    PrimaryKeyConstraint("env", "version", name="kek_versions_pkey"),
    CheckConstraint("version >= 1", name="kv_version_pos"),
    CheckConstraint("octet_length(kcv) = 8", name="kv_kcv_len"),
    UniqueConstraint("kcv", name="kv_kcv_unique"),
)

#: `auth_keys` (#2152 S2, 0030_auth_keys): the per-environment auth keyring, each key wrapped under
#: the KEK of (env, kek_version). The 0030 tests pin the triggers and the cv_app DELETE revoke.
auth_keys = Table(
    "auth_keys",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("env", exchange_env, nullable=False),
    Column("purpose", Text, nullable=False),
    Column("key_version", Integer, nullable=False, server_default=text("1")),
    Column("origin", Text, nullable=False),
    Column(
        "dek_ref",
        Text,
        nullable=False,
        comment="SECRET: auth key wrapped under the KEK of (env, kek_version)",
    ),
    Column("kek_version", Integer, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("purpose IN ('totp_seal','recovery_hmac')", name="ak_purpose"),
    CheckConstraint("origin IN ('generated','imported_env')", name="ak_origin"),
    CheckConstraint("key_version >= 1", name="ak_key_version"),
    CheckConstraint("kek_version >= 1", name="ak_kek_version"),
    CheckConstraint("dek_ref ~ '^ak1:[0-9a-f]{120}$'", name="ak_dek_ref"),
    UniqueConstraint("env", "purpose", "key_version", name="ak_env_purpose_key_version"),
    Index("ix_auth_keys_env_kek", "env", "kek_version"),
)


#: `account_profiles` and `account_profile_revisions` (E28-T01 #905, revision
#: 0037_account_profiles, 21 Sec.3.2.4 and Sec.3.2.5). `version`, the revision rows and the
#: bootstrap profile are written by triggers, which `alembic check` does not compare;
#: `tests/unit/migrations/` pins them.
SIZING_MODES: tuple[str, ...] = ("fixed_qty", "fixed_notional", "pct_equity", "risk_based")
OFFSET_UNITS: tuple[str, ...] = ("ticks", "percent", "r_multiple", "atr")
sizing_mode = ENUM(*SIZING_MODES, name="sizing_mode", metadata=metadata, create_type=False)
offset_unit = ENUM(*OFFSET_UNITS, name="offset_unit", metadata=metadata, create_type=False)
#: Percentages are stored as the percent a user sees (0..100), 21 Sec.3.2.4.
_PERCENT = Numeric(9, 6)

account_profiles = Table(
    "account_profiles",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "exchange_account_id",
        ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text, nullable=False),
    Column("is_default", Boolean, nullable=False, server_default=text("false")),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("trading_enabled", Boolean, nullable=False, server_default=text("false")),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("leverage", Numeric(10, 2), nullable=False, server_default=text("1")),
    Column("margin_mode", Text, nullable=False, server_default=text("'cross'")),
    Column("position_mode", Text, nullable=False, server_default=text("'one_way'")),
    Column("sizing_mode", sizing_mode, nullable=False, server_default=text("'risk_based'")),
    Column("size_fixed_qty", Numeric(38, 18)),
    Column("size_fixed_notional_usd", Numeric(38, 18)),
    Column("size_pct_equity", _PERCENT),
    Column("risk_pct_equity", _PERCENT),
    Column("risk_fixed_amount_usd", Numeric(38, 18)),
    Column("min_leg_notional_usd", Numeric(38, 18), nullable=False, server_default=text("0")),
    Column("sl_offset_value", Numeric(38, 18), nullable=False, server_default=text("10")),
    Column("sl_offset_unit", offset_unit, nullable=False, server_default=text("'ticks'")),
    Column("sl_atr_period", SmallInteger, nullable=False, server_default=text("14")),
    Column("sl_atr_multiple", Numeric(10, 4), nullable=False, server_default=text("2")),
    Column("fallback_sl_offset_pct", _PERCENT, nullable=False, server_default=text("2")),
    Column("tp_offset_value", Numeric(38, 18)),
    Column("tp_offset_unit", offset_unit),
    Column("tp_ladder", JSONB),
    Column("require_native_sl", Boolean, nullable=False, server_default=text("true")),
    Column("max_position_notional_usd", Numeric(38, 18)),
    Column("max_position_pct_equity", _PERCENT),
    Column("max_daily_loss_usd", Numeric(38, 18)),
    Column("max_daily_loss_pct", _PERCENT),
    Column("max_open_positions", SmallInteger),
    Column("max_concurrent_orders", SmallInteger),
    Column("max_leverage_cap", Numeric(10, 2)),
    Column("max_orders_per_minute", SmallInteger, nullable=False, server_default=text("30")),
    Column("all_symbols", Boolean, nullable=False, server_default=text("false")),
    Column("allowed_symbols", ARRAY(Text)),
    Column("blocked_symbols", ARRAY(Text)),
    Column("reduce_only_default", Boolean, nullable=False, server_default=text("false")),
    Column("time_in_force_default", Text, nullable=False, server_default=text("'GTC'")),
    Column("slippage_tolerance_bps", Integer, nullable=False, server_default=text("10")),
    Column("created_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("updated_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    CheckConstraint("leverage BETWEEN 1 AND 100", name="ap_leverage"),
    CheckConstraint("require_native_sl = true", name="ap_native_sl"),
    CheckConstraint("time_in_force_default IN ('GTC','IOC','FOK','PostOnly')", name="ap_tif"),
    CheckConstraint("slippage_tolerance_bps BETWEEN 0 AND 1000", name="ap_slip"),
    CheckConstraint("max_orders_per_minute BETWEEN 1 AND 600", name="ap_opm"),
    CheckConstraint("sl_offset_value > 0", name="ap_sl_pos"),
    CheckConstraint("(tp_offset_value IS NULL) = (tp_offset_unit IS NULL)", name="ap_tp_pair"),
    CheckConstraint("tp_offset_value IS NULL OR tp_offset_value > 0", name="ap_tp_pos"),
    CheckConstraint(
        "max_open_positions IS NULL OR max_open_positions BETWEEN 1 AND 50", name="ap_maxpos"
    ),
    CheckConstraint(
        "((sizing_mode = 'fixed_qty' AND size_fixed_qty > 0 AND size_fixed_notional_usd IS NULL "
        "AND size_pct_equity IS NULL AND risk_pct_equity IS NULL "
        "AND risk_fixed_amount_usd IS NULL) "
        "OR (sizing_mode = 'fixed_notional' AND size_fixed_notional_usd > 0 "
        "AND size_fixed_qty IS NULL AND size_pct_equity IS NULL AND risk_pct_equity IS NULL "
        "AND risk_fixed_amount_usd IS NULL) "
        "OR (sizing_mode = 'pct_equity' AND size_pct_equity > 0 AND size_pct_equity <= 100 "
        "AND size_fixed_qty IS NULL AND size_fixed_notional_usd IS NULL "
        "AND risk_pct_equity IS NULL AND risk_fixed_amount_usd IS NULL) "
        "OR (sizing_mode = 'risk_based' AND size_fixed_qty IS NULL "
        "AND size_fixed_notional_usd IS NULL AND size_pct_equity IS NULL "
        "AND ((risk_pct_equity > 0 AND risk_pct_equity <= 100 AND risk_fixed_amount_usd IS NULL) "
        "OR (risk_fixed_amount_usd > 0 AND risk_pct_equity IS NULL)))) IS TRUE",
        name="ap_sizing_shape",
    ),
    CheckConstraint(
        "tp_ladder IS NULL OR jsonb_typeof(tp_ladder) = 'array'", name="ap_ladder_shape"
    ),
    CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="ap_name"),
    CheckConstraint("version >= 1", name="ap_version"),
    CheckConstraint("margin_mode IN ('cross','isolated')", name="ap_margin_mode"),
    CheckConstraint("position_mode IN ('one_way','hedge')", name="ap_position_mode"),
    CheckConstraint("sl_offset_unit <> 'r_multiple'", name="ap_sl_unit"),
    CheckConstraint("sl_atr_period BETWEEN 2 AND 200 AND sl_atr_multiple > 0", name="ap_atr"),
    CheckConstraint(
        "fallback_sl_offset_pct > 0 AND fallback_sl_offset_pct < 100", name="ap_fallback_sl"
    ),
    CheckConstraint("min_leg_notional_usd >= 0", name="ap_min_leg"),
    CheckConstraint(
        "max_position_notional_usd IS NULL OR max_position_notional_usd > 0",
        name="ap_max_notional",
    ),
    CheckConstraint(
        "max_position_pct_equity IS NULL "
        "OR (max_position_pct_equity > 0 AND max_position_pct_equity <= 100)",
        name="ap_max_pos_pct",
    ),
    CheckConstraint("max_daily_loss_usd IS NULL OR max_daily_loss_usd > 0", name="ap_daily_loss"),
    CheckConstraint(
        "max_daily_loss_pct IS NULL OR (max_daily_loss_pct > 0 AND max_daily_loss_pct <= 100)",
        name="ap_daily_loss_pct",
    ),
    CheckConstraint(
        "max_concurrent_orders IS NULL OR max_concurrent_orders BETWEEN 1 AND 500",
        name="ap_max_orders",
    ),
    CheckConstraint(
        "max_leverage_cap IS NULL "
        "OR (max_leverage_cap BETWEEN 1 AND 100 AND leverage <= max_leverage_cap)",
        name="ap_lev_cap",
    ),
    CheckConstraint(
        "NOT trading_enabled OR ("
        "(max_position_notional_usd IS NOT NULL OR max_position_pct_equity IS NOT NULL) "
        "AND (max_daily_loss_usd IS NOT NULL OR max_daily_loss_pct IS NOT NULL) "
        "AND max_open_positions IS NOT NULL AND max_concurrent_orders IS NOT NULL "
        "AND max_leverage_cap IS NOT NULL)",
        name="ap_trading_caps",
    ),
    CheckConstraint("NOT all_symbols OR allowed_symbols IS NULL", name="ap_all_symbols"),
    CheckConstraint(
        "leverage <> 'NaN' AND max_leverage_cap <> 'NaN' AND sl_atr_multiple <> 'NaN' "
        "AND size_fixed_qty <> 'NaN' AND size_fixed_notional_usd <> 'NaN' "
        "AND size_pct_equity <> 'NaN' AND risk_pct_equity <> 'NaN' "
        "AND risk_fixed_amount_usd <> 'NaN' AND min_leg_notional_usd <> 'NaN' "
        "AND sl_offset_value <> 'NaN' AND fallback_sl_offset_pct <> 'NaN' "
        "AND tp_offset_value <> 'NaN' AND max_position_notional_usd <> 'NaN' "
        "AND max_position_pct_equity <> 'NaN' AND max_daily_loss_usd <> 'NaN' "
        "AND max_daily_loss_pct <> 'NaN'",
        name="ap_finite",
    ),
    Index(
        "ux_ap_name",
        "exchange_account_id",
        text("lower(name)"),
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    ),
    Index(
        "ux_ap_default",
        "exchange_account_id",
        unique=True,
        postgresql_where=text("is_default AND deleted_at IS NULL"),
    ),
)

#: Append-only (trg_apr_append, trg_apr_no_truncate); no FK to `account_profiles`, the history
#: outlives the row.
account_profile_revisions = Table(
    "account_profile_revisions",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("profile_id", UUID(as_uuid=True), nullable=False),
    Column("version", Integer, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("changed_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("changed_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("version >= 1", name="apr_version"),
    CheckConstraint("jsonb_typeof(payload) = 'object'", name="apr_payload"),
    UniqueConstraint("profile_id", "version", name="ux_apr_version"),
)


#: `drawings` (E14-T01, revision 0021_drawings; the layouts FK is in 0022_workspaces).
DRAWING_TOOLS: tuple[str, ...] = (
    "trendline",
    "horizontal_line",
    "vertical_line",
    "ray",
    "extended_line",
    "parallel_channel",
    "rectangle",
    "ellipse",
    "triangle",
    "fib_retracement",
    "fib_extension",
    "fib_timezone",
    "pitchfork",
    "gann_fan",
    "text",
    "arrow",
    "callout",
    "measure",
    "long_position",
    "short_position",
    "price_range",
    "date_range",
    "brush",
    "polyline",
    "anchored_vwap",
)

drawings = Table(
    "drawings",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("owner_user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("symbol", symbol_code, nullable=False),
    Column("layout_id", UUID(as_uuid=True)),
    Column("tool", Text, nullable=False),
    Column("geometry", JSONB, nullable=False),
    Column("style", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("label", Text),
    Column("locked", Boolean, nullable=False, server_default=text("false")),
    Column("visible", Boolean, nullable=False, server_default=text("true")),
    Column("interval_scope", Text),
    Column("z_index", SmallInteger, nullable=False, server_default=text("0")),
    Column("anchor_start", TIMESTAMP(timezone=True)),
    Column("anchor_end", TIMESTAMP(timezone=True)),
    Column("alert_id", ForeignKey("alerts.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    CheckConstraint(
        "tool IN (" + ",".join(f"'{t}'" for t in DRAWING_TOOLS) + ")",
        name="dr_tool",
    ),
    CheckConstraint("jsonb_typeof(geometry) = 'object' AND geometry ? 'points'", name="dr_geom"),
    Index(
        "ix_dr_user_symbol",
        "owner_user_id",
        "symbol",
        postgresql_where=text("deleted_at IS NULL"),
    ),
    Index(
        "ix_dr_range",
        "symbol",
        "anchor_start",
        "anchor_end",
        postgresql_where=text("deleted_at IS NULL"),
    ),
    # Same-owner composite FK (0022_workspaces, D27); MATCH SIMPLE skips layout_id IS NULL.
    ForeignKeyConstraint(
        ["layout_id", "owner_user_id"],
        ["layouts.id", "layouts.owner_user_id"],
        name="fk_drawings_layout_id_layouts",
        ondelete="CASCADE",
    ),
    Index("ix_dr_layout", "layout_id", postgresql_where=text("layout_id IS NOT NULL")),
)


#: `workspaces`, `layouts`, `layout_panes` (E15-T01, revision 0022_workspaces).
PANE_KINDS: tuple[str, ...] = (
    "chart",
    "dom",
    "tape",
    "profile",
    "cvd",
    "oi",
    "deep_stats",
    "regime",
    "positions",
    "journal",
    "watchlist",
    "alerts",
)

workspaces = Table(
    "workspaces",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("is_default", Boolean, nullable=False, server_default=text("false")),
    Column("icon_token", Text, nullable=False, server_default=text("'workspace.default'")),
    Column("sort_order", SmallInteger, nullable=False, server_default=text("0")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    UniqueConstraint("id", "user_id", name="ux_workspaces_id_user_id"),
    Index(
        "ux_ws_name",
        "user_id",
        text("lower(name)"),
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    ),
    Index(
        "ux_ws_default",
        "user_id",
        unique=True,
        postgresql_where=text("is_default AND deleted_at IS NULL"),
    ),
)

layouts = Table(
    "layouts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("workspace_id", UUID(as_uuid=True), nullable=False),
    Column("owner_user_id", UUID(as_uuid=True), nullable=False),
    Column("name", Text, nullable=False),
    Column("grid_preset", Text, nullable=False, server_default=text("'1x1'")),
    Column("grid_spec", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("crosshair_sync", Boolean, nullable=False, server_default=text("true")),
    Column("level_sync", Boolean, nullable=False, server_default=text("false")),
    Column("symbol_sync", Boolean, nullable=False, server_default=text("false")),
    Column("hotkey_slot", SmallInteger),
    Column("is_default", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("deleted_at", TIMESTAMP(timezone=True)),
    ForeignKeyConstraint(
        ["workspace_id", "owner_user_id"],
        ["workspaces.id", "workspaces.user_id"],
        name="fk_layouts_workspace_id_workspaces",
        ondelete="CASCADE",
    ),
    UniqueConstraint("id", "owner_user_id", name="ux_layouts_id_owner_user_id"),
    CheckConstraint(
        "grid_preset IN ('1x1','2x1','1x2','2x2','1+3','3x3','custom')", name="lay_preset"
    ),
    CheckConstraint("hotkey_slot IS NULL OR hotkey_slot BETWEEN 1 AND 9", name="lay_slot"),
    Index(
        "ux_lay_name",
        "workspace_id",
        text("lower(name)"),
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    ),
    Index(
        "ux_lay_slot",
        "workspace_id",
        "hotkey_slot",
        unique=True,
        postgresql_where=text("hotkey_slot IS NOT NULL AND deleted_at IS NULL"),
    ),
    Index(
        "ux_lay_default",
        "workspace_id",
        unique=True,
        postgresql_where=text("is_default AND deleted_at IS NULL"),
    ),
    Index("ix_lay_workspace", "workspace_id"),
)

layout_panes = Table(
    "layout_panes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("layout_id", ForeignKey("layouts.id", ondelete="CASCADE"), nullable=False),
    Column("slot_index", SmallInteger, nullable=False),
    Column("pane_kind", Text, nullable=False),
    Column("symbol", symbol_code),
    Column("interval_code", Text),
    # No FK: chart_templates does not exist yet (0014/0017 precedent, #2411).
    Column("chart_template_id", UUID(as_uuid=True)),
    Column(
        "indicator_preset_ids",
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        server_default=text("'{}'"),
    ),
    Column("pane_config", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("scale_mode", Text, nullable=False, server_default=text("'auto'")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("layout_id", "slot_index", name="ux_lp_slot"),
    CheckConstraint(
        "pane_kind IN (" + ",".join(f"'{k}'" for k in PANE_KINDS) + ")", name="lp_kind"
    ),
    CheckConstraint("slot_index BETWEEN 0 AND 15", name="lp_slot"),
    CheckConstraint("scale_mode IN ('auto','linked','manual','log')", name="lp_scale"),
    Index("ix_lp_layout", "layout_id", "slot_index"),
    Index("ix_lp_symbol", "symbol", postgresql_where=text("symbol IS NOT NULL")),
)

#: `settings` (E42-T01, revision 0025_settings): 21-database-schema.md Sec.3.9, `settings` only.
settings = Table(
    "settings",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("scope", Text, nullable=False),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE")),
    Column("key", Text, nullable=False),
    Column(
        "value",
        JSONB,
        nullable=False,
        comment=(
            "SECRET: when is_secret, AES-256-GCM ciphertext only (21 Sec.12); "
            "API returns it masked; never logged"
        ),
    ),
    Column("value_type", Text, nullable=False),
    Column("is_secret", Boolean, nullable=False, server_default=text("false")),
    Column("updated_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("scope IN ('system','user')", name="st_scope"),
    CheckConstraint("(scope = 'user') = (user_id IS NOT NULL)", name="st_shape"),
    CheckConstraint("key ~ '^[a-z0-9_]+([.][a-z0-9_]+){0,4}$'", name="st_key_fmt"),
    CheckConstraint(
        "value_type IN ('string','number','boolean','object','array')", name="st_vtype"
    ),
    Index("ux_settings_sys", "key", unique=True, postgresql_where=text("scope = 'system'")),
    Index(
        "ux_settings_user",
        "user_id",
        "key",
        unique=True,
        postgresql_where=text("scope = 'user'"),
    ),
)

#: `feature_flags`, `feature_flag_overrides` (E42-T03, revision 0027_feature_flags): Sec.3.9.
flag_kind = ENUM(
    "boolean", "percentage", "variant", name="flag_kind", metadata=metadata, create_type=False
)
feature_flags = Table(
    "feature_flags",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("key", Text, nullable=False),
    Column("kind", flag_kind, nullable=False, server_default=text("'boolean'")),
    Column("description", Text, nullable=False, server_default=text("''")),
    Column("default_value", JSONB, nullable=False, server_default=text("'false'::jsonb")),
    Column("rollout_pct", SmallInteger),
    Column("variants", JSONB),
    Column("is_killswitch", Boolean, nullable=False, server_default=text("false")),
    Column("owner_team", Text, nullable=False, server_default=text("'platform'")),
    Column("expires_at", TIMESTAMP(timezone=True)),
    Column("updated_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("key", name="feature_flags_key_key"),
    CheckConstraint("key ~ '^[a-z0-9_]+([.][a-z0-9_]+){0,3}$'", name="ff_key"),
    CheckConstraint("rollout_pct IS NULL OR rollout_pct BETWEEN 0 AND 100", name="ff_pct"),
    CheckConstraint(
        "(kind <> 'percentage' OR rollout_pct IS NOT NULL) "
        "AND (kind <> 'variant' OR variants IS NOT NULL)",
        name="ff_shape",
    ),
)
feature_flag_overrides = Table(
    "feature_flag_overrides",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("feature_flag_id", ForeignKey("feature_flags.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE")),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE")),
    Column("value", JSONB, nullable=False),
    Column("reason", Text, nullable=False, server_default=text("''")),
    Column("set_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("expires_at", TIMESTAMP(timezone=True)),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("num_nonnulls(user_id, role_id) = 1", name="ffo_target"),
    Index(
        "ux_ffo_user",
        "feature_flag_id",
        "user_id",
        unique=True,
        postgresql_where=text("user_id IS NOT NULL"),
    ),
    Index(
        "ux_ffo_role",
        "feature_flag_id",
        "role_id",
        unique=True,
        postgresql_where=text("role_id IS NOT NULL"),
    ),
)

#: `incidents` and `backups` (E42-T05, revision 0028_incidents_backups): Sec.3.10.2a, Sec.3.10.3.
BACKUP_KINDS = ("pg_basebackup", "pg_dump", "questdb_snapshot", "parquet_sync", "config_bundle")
BACKUP_STATUSES = ("running", "ok", "failed", "verified", "restored")
backup_kind = ENUM(*BACKUP_KINDS, name="backup_kind", metadata=metadata, create_type=False)
backup_status = ENUM(*BACKUP_STATUSES, name="backup_status", metadata=metadata, create_type=False)
incidents = Table(
    "incidents",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("component", Text, nullable=False),
    Column("signature", Text, nullable=False),
    Column("severity", severity, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'open'")),
    Column("title", Text, nullable=False),
    Column("detail", Text),
    Column("occurrences", Integer, nullable=False, server_default=text("1")),
    Column("first_seen_at", TIMESTAMP(timezone=True), nullable=False),
    Column("last_seen_at", TIMESTAMP(timezone=True), nullable=False),
    Column("acknowledged_by", ForeignKey("users.id", ondelete="SET NULL")),
    Column("acknowledged_at", TIMESTAMP(timezone=True)),
    Column("resolved_at", TIMESTAMP(timezone=True)),
    Column("runbook_ref", Text),
    CheckConstraint("signature ~ '^[0-9a-f]{16}$'", name="inc_signature"),
    CheckConstraint("severity IN ('error','critical')", name="inc_severity"),
    CheckConstraint("status IN ('open','acknowledged','resolved')", name="inc_status"),
    CheckConstraint("occurrences >= 1", name="inc_count"),
    CheckConstraint("last_seen_at >= first_seen_at", name="inc_seen"),
    CheckConstraint("status <> 'acknowledged' OR acknowledged_at IS NOT NULL", name="inc_ack"),
    CheckConstraint("(status = 'resolved') = (resolved_at IS NOT NULL)", name="inc_resolved"),
    Index("ux_incidents_group", "component", "signature", unique=True),
    Index("ix_incidents_seen", text("last_seen_at DESC")),
    Index("ix_incidents_status_seen", "status", text("last_seen_at DESC")),
)
backups = Table(
    "backups",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("kind", backup_kind, nullable=False),
    Column("status", backup_status, nullable=False, server_default=text("'running'")),
    Column("target_path", Text, nullable=False),
    Column("size_bytes", BigInteger),
    Column("checksum_sha256", _sha256_hex),
    Column("encrypted", Boolean, nullable=False, server_default=text("true")),
    Column(
        "encryption_ref",
        Text,
        comment=(
            "SECRET: opaque keyring alias of the backup encryption key, never key material "
            "(21 Sec.12); never returned by any API, never logged"
        ),
    ),
    Column("covers_from", TIMESTAMP(timezone=True)),
    Column("covers_to", TIMESTAMP(timezone=True)),
    Column("wal_start_lsn", Text),
    Column("wal_end_lsn", Text),
    Column("duration_ms", Integer),
    Column("verified_at", TIMESTAMP(timezone=True)),
    Column("verify_method", Text),
    Column("restored_at", TIMESTAMP(timezone=True)),
    Column("error_message", Text),
    Column("triggered_by", Text, nullable=False, server_default=text("'schedule'")),
    Column("triggered_by_user", ForeignKey("users.id", ondelete="SET NULL")),
    Column("started_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("finished_at", TIMESTAMP(timezone=True)),
    Column("retention_until", TIMESTAMP(timezone=True)),
    # 0032_backups_write_once (E42-T05 BK-2): a deleted artefact keeps its row (Q4 on #966). The
    # write-once trigger and cv_app's revoked DELETE are pinned by the 0032 tests, not autogenerate.
    Column("deleted_at", TIMESTAMP(timezone=True)),
    Column("deleted_by", ForeignKey("users.id", ondelete="SET NULL")),
    CheckConstraint(
        "triggered_by IN ('schedule','manual','pre_migration','pre_release','pre_restore')",
        name="bk_trigger",
    ),
    CheckConstraint(
        "verify_method IS NULL OR verify_method IN "
        "('restore_smoke','checksum','pg_verifybackup','duckdb_scan')",
        name="bk_verify",
    ),
    CheckConstraint("deleted_by IS NULL OR deleted_at IS NOT NULL", name="bk_deleted"),
    Index("ix_backups_kind_time", "kind", text("started_at DESC")),
    Index("ix_backups_failed", text("started_at DESC"), postgresql_where=text("status = 'failed'")),
)

#: OMS core (E29-T01, revision 0029_oms_core): Sec.1.2 enums and Sec.3.3.4-3.3.7. Both
#: `trade_group_leg_id` columns carry no FK until E28-T01 (#905) creates `trade_group_legs`; the
#: append-only triggers and the C-5.7 revocations are asserted by the 0029 tests, not autogenerate.
#: 0034_order_vocabulary (E29-T03) appends to `order_state` and `order_event_kind`, adds
#: `order_lifecycle_state` (the B1 chart's states verbatim), `orders.lifecycle_state` and the
#: `ord_lifecycle` CHECK that pairs it with `state` (`ORDER_STATE_OF`).
ORDER_INTENTS = (
    "entry", "stop_loss", "take_profit", "scale_in", "scale_out", "flatten", "reverse",
    "algo_child",
)  # fmt: skip
ORDER_STATES = (
    "new", "pending_submit", "submitted", "accepted", "partially_filled", "filled",
    "pending_cancel", "cancelled", "pending_amend", "rejected", "expired", "untracked",
    "triggered", "unknown", "quarantined", "killed", "held",
)  # fmt: skip
ORDER_EVENT_KINDS = (
    "local_create", "submit_attempt", "ack", "reject", "fill", "partial_fill", "amend_request",
    "amend_ack", "cancel_request", "cancel_ack", "expire", "exchange_push", "reconcile_diff",
    "error", "kill", "adopt",
)  # fmt: skip
ORDER_LIFECYCLE_STATES = (
    "draft", "validated", "submitting", "submitted", "triggered", "partially_filled",
    "cancel_pending", "amend_pending", "unknown", "quarantined", "untracked", "held", "filled",
    "cancelled", "rejected", "expired", "killed",
)  # fmt: skip
order_intent = ENUM(*ORDER_INTENTS, name="order_intent", metadata=metadata, create_type=False)
order_state = ENUM(*ORDER_STATES, name="order_state", metadata=metadata, create_type=False)
order_event_kind = ENUM(
    *ORDER_EVENT_KINDS, name="order_event_kind", metadata=metadata, create_type=False
)
order_lifecycle_state = ENUM(
    *ORDER_LIFECYCLE_STATES, name="order_lifecycle_state", metadata=metadata, create_type=False
)

#: C-5.9 / Sec.12 class P1 on every numeric(38,18) column of the OMS tables (all but order_events);
#: byte-identical to the 0029 COMMENT statements (`alembic check` diffs column comments).
OMS_MONEY_COMMENT = (
    "PII: financial personal data (21 Sec.12, class P1); never sent to third parties"
)
#: C-5.9 / Sec.12 class P1 on the columns that keep the exchange's answer to an order
#: (`orders.reject_code`, `reject_message`; `order_events.payload`, `ret_code`, `ret_msg`): it can
#: repeat the order's money values. Byte-identical to the 0029 COMMENT statements, like the above.
OMS_EXCHANGE_TEXT_COMMENT = (
    "PII: exchange answer text that can repeat order values (21 Sec.12, class P1); "
    "redacted before insert; never logged"
)
_P1 = OMS_MONEY_COMMENT
_P1_TEXT = OMS_EXCHANGE_TEXT_COMMENT
_MONEY = Numeric(38, 18)

orders = Table(
    "orders",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("trade_group_leg_id", UUID(as_uuid=True)),
    Column(
        "exchange_account_id",
        ForeignKey("exchange_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("parent_order_id", ForeignKey("orders.id", ondelete="SET NULL")),
    Column("oco_group_ref", Text),
    Column("order_link_id", Text, nullable=False),
    Column("exchange_order_id", Text),
    Column("symbol", symbol_code, nullable=False),
    Column("side", Text, nullable=False),
    Column("intent", order_intent, nullable=False),
    Column("order_type", Text, nullable=False),
    Column("qty", _MONEY, nullable=False, comment=_P1),
    Column("price", _MONEY, comment=_P1),
    Column("trigger_price", _MONEY, comment=_P1),
    Column("trigger_by", Text),
    Column("trigger_direction", SmallInteger),
    Column("take_profit", _MONEY, comment=_P1),
    Column("stop_loss", _MONEY, comment=_P1),
    Column("tpsl_mode", Text, nullable=False, server_default=text("'Full'")),
    Column("time_in_force", Text, nullable=False, server_default=text("'GTC'")),
    Column("reduce_only", Boolean, nullable=False, server_default=text("false")),
    Column("close_on_trigger", Boolean, nullable=False, server_default=text("false")),
    Column("position_idx", SmallInteger, nullable=False, server_default=text("0")),
    Column("state", order_state, nullable=False, server_default=text("'new'")),
    Column("cum_exec_qty", _MONEY, nullable=False, server_default=text("0"), comment=_P1),
    Column("cum_exec_value", _MONEY, nullable=False, server_default=text("0"), comment=_P1),
    Column("avg_price", _MONEY, comment=_P1),
    Column("leaves_qty", _MONEY, Computed("qty - cum_exec_qty", persisted=True), comment=_P1),
    Column("fee_paid", _MONEY, nullable=False, server_default=text("0"), comment=_P1),
    Column("reject_code", Text, comment=_P1_TEXT),
    Column("reject_message", Text, comment=_P1_TEXT),
    Column("submit_attempts", SmallInteger, nullable=False, server_default=text("0")),
    Column("idempotency_state", Text, nullable=False, server_default=text("'unsent'")),
    Column("created_ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("submitted_ts", TIMESTAMP(timezone=True)),
    Column("exchange_created_ts", TIMESTAMP(timezone=True)),
    Column("exchange_updated_ts", TIMESTAMP(timezone=True)),
    Column("last_reconciled_at", TIMESTAMP(timezone=True)),
    Column("is_paper", Boolean, nullable=False, server_default=text("false")),
    Column("lifecycle_state", order_lifecycle_state),
    CheckConstraint("side IN ('Buy','Sell')", name="ord_side"),
    CheckConstraint("order_type IN ('Market','Limit')", name="ord_type"),
    CheckConstraint("qty > 0", name="ord_qty"),
    CheckConstraint("order_type <> 'Limit' OR price > 0", name="ord_limit_px"),
    CheckConstraint("cum_exec_qty >= 0 AND cum_exec_qty <= qty", name="ord_cum"),
    CheckConstraint("time_in_force IN ('GTC','IOC','FOK','PostOnly')", name="ord_tif"),
    CheckConstraint("position_idx IN (0,1,2)", name="ord_posidx"),
    CheckConstraint("trigger_direction IS NULL OR trigger_direction IN (1,2)", name="ord_trigdir"),
    CheckConstraint(
        "trigger_by IS NULL OR trigger_by IN ('LastPrice','MarkPrice','IndexPrice')",
        name="ord_trigby",
    ),
    CheckConstraint("take_profit IS NULL OR take_profit > 0", name="ord_tp_px"),
    CheckConstraint("stop_loss IS NULL OR stop_loss > 0", name="ord_sl_px"),
    CheckConstraint("tpsl_mode IN ('Full','Partial')", name="ord_tpslmode"),
    CheckConstraint("submit_attempts BETWEEN 0 AND 10", name="ord_attempts"),
    CheckConstraint(
        "idempotency_state IN ('unsent','in_flight','acked','failed')", name="ord_idem"
    ),
    CheckConstraint(
        "order_link_id ~ "
        "'^cv[ldtp]-[0-7][0-9A-Za-z]{21}-[0-9A-Za-z]{4}-[0-9A-Za-z]{2}(en|sl|tp|sc|fl|ac)$' "
        "OR order_link_id ~ '^ext-[0-9a-f]{32}$'",
        name="ord_link_fmt",
    ),
    CheckConstraint("parent_order_id IS DISTINCT FROM id", name="ord_no_self"),
    CheckConstraint(
        "lifecycle_state IS NULL OR (lifecycle_state, state) IN (('draft','new'),"
        "('validated','pending_submit'),('submitting','submitted'),('submitted','accepted'),"
        "('triggered','triggered'),('partially_filled','partially_filled'),"
        "('cancel_pending','pending_cancel'),('amend_pending','pending_amend'),"
        "('unknown','unknown'),('quarantined','quarantined'),('untracked','untracked'),"
        "('held','held'),('filled','filled'),('cancelled','cancelled'),('rejected','rejected'),"
        "('expired','expired'),('killed','killed'))",
        name="ord_lifecycle",
    ),
    Index("ux_orders_link", "order_link_id", unique=True),
    Index(
        "ux_orders_exch_id",
        "exchange_account_id",
        "exchange_order_id",
        unique=True,
        postgresql_where=text("exchange_order_id IS NOT NULL"),
    ),
    Index(
        "ix_orders_open",
        "exchange_account_id",
        "symbol",
        postgresql_where=text(
            "state IN ('pending_submit','submitted','accepted','partially_filled',"
            "'pending_cancel','pending_amend','triggered','unknown','quarantined')"
        ),
    ),
    Index("ix_orders_leg", "trade_group_leg_id"),
    Index(
        "ix_orders_parent", "parent_order_id", postgresql_where=text("parent_order_id IS NOT NULL")
    ),
    Index("ix_orders_oco", "oco_group_ref", postgresql_where=text("oco_group_ref IS NOT NULL")),
    Index("ix_orders_recent", "exchange_account_id", text("created_ts DESC")),
    Index(
        "ix_orders_inflight", "created_ts", postgresql_where=text("idempotency_state = 'in_flight'")
    ),
    Index(
        "ix_orders_untracked", "exchange_account_id", postgresql_where=text("state = 'untracked'")
    ),
)
order_events = Table(
    "order_events",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("order_id", ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("kind", order_event_kind, nullable=False),
    Column("from_state", order_state),
    Column("to_state", order_state),
    Column("source", Text, nullable=False),
    Column(
        "payload",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment=_P1_TEXT,
    ),
    Column("ret_code", Text, comment=_P1_TEXT),
    Column("ret_msg", Text, comment=_P1_TEXT),
    Column("latency_ms", Integer),
    Column("event_ts", TIMESTAMP(timezone=True), nullable=False),
    Column("recv_ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "source IN ('local','rest','ws_private','reconcile','paper')", name="oe_source"
    ),
    CheckConstraint("seq >= 0", name="oe_seq"),
    CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="oe_latency"),
    UniqueConstraint("order_id", "seq", name="order_events_order_id_seq_key"),
    Index("ix_oe_order_time", "order_id", "event_ts"),
    Index("ix_oe_time", text("event_ts DESC")),
    Index("ix_oe_kind_time", "kind", text("event_ts DESC")),
)
executions = Table(
    "executions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("order_id", ForeignKey("orders.id", ondelete="SET NULL")),
    Column(
        "exchange_account_id",
        ForeignKey("exchange_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("trade_group_leg_id", UUID(as_uuid=True)),
    Column("exec_id", Text, nullable=False),
    Column("order_link_id", Text),
    Column("symbol", symbol_code, nullable=False),
    Column("side", Text, nullable=False),
    Column("exec_qty", _MONEY, nullable=False, comment=_P1),
    Column("exec_price", _MONEY, nullable=False, comment=_P1),
    Column("exec_value", _MONEY, nullable=False, comment=_P1),
    Column("exec_type", Text, nullable=False),
    Column("exec_fee", _MONEY, nullable=False, server_default=text("0"), comment=_P1),
    Column("fee_rate", Numeric(18, 10)),
    Column("fee_currency", Text, nullable=False, server_default=text("'USDT'")),
    Column("is_maker", Boolean, nullable=False),
    Column("closed_pnl", _MONEY, comment=_P1),
    Column("mark_price", _MONEY, comment=_P1),
    Column("underlying_price", _MONEY, comment=_P1),
    Column("block_trade_id", Text),
    Column("position_idx", SmallInteger, nullable=False, server_default=text("0")),
    Column("is_paper", Boolean, nullable=False, server_default=text("false")),
    Column("exec_ts", TIMESTAMP(timezone=True), nullable=False),
    Column("recv_ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("exec_qty > 0", name="ex_qty"),
    CheckConstraint("exec_price > 0", name="ex_px"),
    CheckConstraint("side IN ('Buy','Sell')", name="ex_side"),
    CheckConstraint(
        "exec_type IN ('Trade','AdlTrade','Funding','BustTrade','Settle','SessionSettlePnl')",
        name="ex_type",
    ),
    CheckConstraint("position_idx IN (0,1,2)", name="ex_posidx"),
    Index("ux_exec_id", "exchange_account_id", "exec_id", unique=True),
    Index("ix_exec_order", "order_id", "exec_ts"),
    Index("ix_exec_acct_time", "exchange_account_id", text("exec_ts DESC")),
    Index("ix_exec_symbol_time", "symbol", text("exec_ts DESC")),
    Index(
        "ix_exec_leg", "trade_group_leg_id", postgresql_where=text("trade_group_leg_id IS NOT NULL")
    ),
)
positions = Table(
    "positions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "exchange_account_id",
        ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("symbol", symbol_code, nullable=False),
    Column("position_idx", SmallInteger, nullable=False, server_default=text("0")),
    Column("side", Text),
    Column("size", _MONEY, nullable=False, server_default=text("0"), comment=_P1),
    Column("avg_price", _MONEY, comment=_P1),
    Column("position_value", _MONEY, comment=_P1),
    Column("leverage", Numeric(10, 2)),
    Column("mark_price", _MONEY, comment=_P1),
    Column("liq_price", _MONEY, comment=_P1),
    Column("bust_price", _MONEY, comment=_P1),
    Column("position_im", _MONEY, comment=_P1),
    Column("position_mm", _MONEY, comment=_P1),
    Column("unrealised_pnl", _MONEY, comment=_P1),
    Column("cur_realised_pnl", _MONEY, comment=_P1),
    Column("cum_realised_pnl", _MONEY, comment=_P1),
    Column("take_profit", _MONEY, comment=_P1),
    Column("stop_loss", _MONEY, comment=_P1),
    Column("trailing_stop", _MONEY, comment=_P1),
    Column("tpsl_mode", Text),
    Column("adl_rank_indicator", SmallInteger),
    Column("auto_add_margin", Boolean, nullable=False, server_default=text("false")),
    Column("is_paper", Boolean, nullable=False, server_default=text("false")),
    Column("exchange_updated_ts", TIMESTAMP(timezone=True)),
    Column("recv_ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("size >= 0", name="pos_size"),
    CheckConstraint("side IS NULL OR side IN ('Buy','Sell','None')", name="pos_side"),
    CheckConstraint("position_idx IN (0,1,2)", name="pos_posidx"),
    CheckConstraint("tpsl_mode IS NULL OR tpsl_mode IN ('Full','Partial')", name="pos_tpslmode"),
    UniqueConstraint(
        "exchange_account_id",
        "symbol",
        "position_idx",
        name="positions_exchange_account_id_symbol_position_idx_key",
    ),
    Index("ix_pos_open", "exchange_account_id", postgresql_where=text("size > 0")),
    Index("ix_pos_symbol", "symbol", postgresql_where=text("size > 0")),
    Index(
        "ix_pos_no_sl",
        "exchange_account_id",
        "symbol",
        postgresql_where=text("size > 0 AND stop_loss IS NULL"),
    ),
)
position_snapshots = Table(
    "position_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column(
        "exchange_account_id",
        ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("symbol", symbol_code, nullable=False),
    Column("position_idx", SmallInteger, nullable=False, server_default=text("0")),
    Column("size", _MONEY, nullable=False, comment=_P1),
    Column("avg_price", _MONEY, comment=_P1),
    Column("mark_price", _MONEY, comment=_P1),
    Column("unrealised_pnl", _MONEY, comment=_P1),
    Column("cum_realised_pnl", _MONEY, comment=_P1),
    Column("liq_price", _MONEY, comment=_P1),
    Column("equity_usd", _MONEY, comment=_P1),
    Column("reason", Text, nullable=False),
    Column("snap_ts", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint(
        "reason IN ('ws_push','rest_reconcile','minute_tick','risk_eval')", name="psnap_reason"
    ),
    Index("ix_psnap_acct_time", "exchange_account_id", text("snap_ts DESC")),
    Index("ix_psnap_sym_time", "symbol", text("snap_ts DESC")),
)


#: `machine_snapshots`, `machine_drain_journal`, `machine_events` (E50-T61, revision
#: 0033_machine_persistence): 24-internal-schemas.md Sec.17.6, the statechart runtime's persistence.
#: The four seal- and digest-bearing columns are `json` since the machine_persistence_json
#: revision (#3857), which keeps the text as written: `jsonb` re-rendered numbers the seal and
#: `row_hash` cover.
#: C-5.9 / 21 Sec.12: every column is classified in its comment, `PII:` on the three P1 columns and
#: `P0:` with its meaning on every other one. Byte-identical to the 0033 COMMENT statements
#: (`alembic check` diffs column comments); no quote, as each sits in a SQL string literal. The 0033
#: tests pin the CHECK bodies, the stamp-once trigger and the grants, which `alembic check` ignores.
_MACHINE_KEY = {
    "machine_kind": "P0: catalogue machine kind (28 B1-B20); part of the machine key",
    "entity_id": (
        "P0: MachineKey.entity_id, the owning module canonical id; part of the machine key"
    ),
    "env": "P0: environment, live, demo or testnet; part of the machine key",
}
_MACHINE_P1 = (
    "PII: financial personal data (21 Sec.12, class P1): {}; holds no credential, token or key; "
    "never logged"
)
_EVENT_TYPE = "P0: event name"
_MS = _MACHINE_KEY | {
    "cv_schema_version": "P0: persistence.SEAL_LAYOUT_V at write time; diagnostic only",
    "lib_snapshot_ver": (
        "P0: SealedSnapshot.version, the library snapshot version (CV-C52, 3 or more)"
    ),
    "machine_hash": "P0: sha256 of the canonical chart JSON; equals machine_hashes.lock",
    "snapshot": _MACHINE_P1.format("machine context, HMAC-sealed (CV-C53)"),
    "hmac_key_id": "P0: Seal.key_id, a reference to the HMAC key, never key material",
    "hmac_tag": "P0: the 32 raw bytes of the HMAC-SHA256 seal tag (CV-C53); an integrity tag",
    "state_ids": "P0: active state ids, denormalised from the sealed blob for query only",
    "chain_trips": (
        "P0: chain-trip count, denormalised; above 0 latches the machine degraded (CV-C63)"
    ),
    "updated_at": "P0: time of the last snapshot write; outside the seal",
}
_MDJ = _MACHINE_KEY | {
    "send_id": "P0: stable send id, 32 hex of sha256; de-dup key for re-submits (R14-02)",
    "lane": "P0: drain lane, priority or inbox",
    "ordinal": "P0: position in the drain output, priority lane first; the replay order",
    "event_type": _EVENT_TYPE,
    "payload": _MACHINE_P1.format("a drained event replayed once after restore"),
    "receipt_error": "P0: Receipt.error class name when the drain failed a waiter",
    "replayed_at": "P0: set once, when replay_once re-enqueued the event",
}
_ME = _MACHINE_KEY | {
    "seq": "P0: insertion order; the chain order within one machine",
    "event_type": _EVENT_TYPE,
    "payload": _MACHINE_P1.format("event data, hash-chained (row_hash)"),
    "from_states": "P0: active state ids before the transition",
    "to_states": "P0: active state ids after the transition",
    "actions_run": "P0: names of the actions actually executed (MUST-02)",
    "fault": (
        "P0: action names, exception class names and refusal reasons; "
        "never a payload or context value"
    ),
    "occurred_at": "P0: transition time (UTC), as the plugin emitted it",
    "phase": "P0: ahead (write-ahead), commit or fault",
    "prev_hash": "P0: row_hash of the previous row of the same machine; 64 zeros first",
    "row_hash": (
        "P0: sha256 over the canonical JSON of the other fields; the WAL-replay idempotency key"
    ),
}
_UTC = TIMESTAMP(timezone=True)

machine_snapshots = Table(
    "machine_snapshots",
    metadata,
    Column("machine_kind", Text, nullable=False, comment=_MS["machine_kind"]),
    Column("entity_id", Text, nullable=False, comment=_MS["entity_id"]),
    Column("env", Text, nullable=False, comment=_MS["env"]),
    Column("cv_schema_version", Integer, nullable=False, comment=_MS["cv_schema_version"]),
    Column("lib_snapshot_ver", Integer, nullable=False, comment=_MS["lib_snapshot_ver"]),
    Column("machine_hash", _sha256_hex, nullable=False, comment=_MS["machine_hash"]),
    Column("snapshot", JSON, nullable=False, comment=_MS["snapshot"]),
    Column("hmac_key_id", Text, nullable=False, comment=_MS["hmac_key_id"]),
    Column("hmac_tag", BYTEA, nullable=False, comment=_MS["hmac_tag"]),
    Column("state_ids", ARRAY(Text), nullable=False, comment=_MS["state_ids"]),
    Column(
        "chain_trips",
        Integer,
        nullable=False,
        server_default=text("0"),
        comment=_MS["chain_trips"],
    ),
    Column("updated_at", _UTC, nullable=False, comment=_MS["updated_at"]),
    PrimaryKeyConstraint("machine_kind", "entity_id", "env", name="machine_snapshots_pkey"),
    CheckConstraint("entity_id <> ''", name="ms_entity"),
    CheckConstraint("env IN ('live','demo','testnet')", name="ms_env"),
    CheckConstraint("cv_schema_version >= 1", name="ms_schema"),
    CheckConstraint("lib_snapshot_ver >= 3", name="ms_lib_ver"),
    CheckConstraint("octet_length(hmac_tag) = 32", name="ms_tag_len"),
    CheckConstraint("chain_trips >= 0", name="ms_trips"),
)
machine_drain_journal = Table(
    "machine_drain_journal",
    metadata,
    Column("machine_kind", Text, nullable=False, comment=_MDJ["machine_kind"]),
    Column("entity_id", Text, nullable=False, comment=_MDJ["entity_id"]),
    Column("env", Text, nullable=False, comment=_MDJ["env"]),
    Column("send_id", Text, nullable=False, comment=_MDJ["send_id"]),
    Column("lane", Text, nullable=False, comment=_MDJ["lane"]),
    Column("ordinal", Integer, nullable=False, comment=_MDJ["ordinal"]),
    Column("event_type", Text, nullable=False, comment=_MDJ["event_type"]),
    Column("payload", JSON, nullable=False, comment=_MDJ["payload"]),
    Column("receipt_error", Text, comment=_MDJ["receipt_error"]),
    Column("replayed_at", _UTC, comment=_MDJ["replayed_at"]),
    PrimaryKeyConstraint(
        "machine_kind", "entity_id", "env", "send_id", name="machine_drain_journal_pkey"
    ),
    CheckConstraint("entity_id <> ''", name="mdj_entity"),
    CheckConstraint("env IN ('live','demo','testnet')", name="mdj_env"),
    CheckConstraint("send_id ~ '^[0-9a-f]{32}$'", name="mdj_send_id"),
    CheckConstraint("lane IN ('priority','inbox')", name="mdj_lane"),
    CheckConstraint("ordinal >= 0", name="mdj_ordinal"),
    Index(
        "ix_mdj_pending",
        "machine_kind",
        "entity_id",
        "env",
        "ordinal",
        postgresql_where=text("replayed_at IS NULL"),
    ),
)
machine_events = Table(
    "machine_events",
    metadata,
    Column("seq", BigInteger, primary_key=True, comment=_ME["seq"]),
    Column("machine_kind", Text, nullable=False, comment=_ME["machine_kind"]),
    Column("entity_id", Text, nullable=False, comment=_ME["entity_id"]),
    Column("env", Text, nullable=False, comment=_ME["env"]),
    Column("event_type", Text, nullable=False, comment=_ME["event_type"]),
    Column("payload", JSON, nullable=False, comment=_ME["payload"]),
    Column("from_states", ARRAY(Text), nullable=False, comment=_ME["from_states"]),
    Column("to_states", ARRAY(Text), nullable=False, comment=_ME["to_states"]),
    Column("actions_run", ARRAY(Text), nullable=False, comment=_ME["actions_run"]),
    # `none_as_null`: Python None binds SQL NULL, which `me_fault_phase` needs, not JSON `null`.
    Column("fault", JSON(none_as_null=True), comment=_ME["fault"]),
    Column("occurred_at", _UTC, nullable=False, comment=_ME["occurred_at"]),
    Column("phase", Text, nullable=False, comment=_ME["phase"]),
    Column("prev_hash", _sha256_hex, nullable=False, comment=_ME["prev_hash"]),
    Column("row_hash", _sha256_hex, nullable=False, comment=_ME["row_hash"]),
    CheckConstraint("entity_id <> ''", name="me_entity"),
    CheckConstraint("env IN ('live','demo','testnet')", name="me_env"),
    CheckConstraint("phase IN ('ahead','commit','fault')", name="me_phase"),
    CheckConstraint("(phase = 'fault') = (fault IS NOT NULL)", name="me_fault_phase"),
    UniqueConstraint("row_hash", name="machine_events_row_hash_key"),
    Index("ix_me_machine_seq", "machine_kind", "entity_id", "env", "seq"),
)

#: `risk_lockouts`, `risk_policy`, `kill_switch_state` (E39-T02, revision 0038_risk_state):
#: Sec.3.11. `actual_value` carries the Sec.12 `PII:` comment byte-identical to the revision's.
RISK_LOCKOUT_ACTUAL_VALUE_COMMENT = (
    "PII: financial data of the account (a measured loss), as positions; "
    "never sent to third parties"
)
risk_lockouts = Table(
    "risk_lockouts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "exchange_account_id",
        ForeignKey("exchange_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("user_id", ForeignKey("users.id", ondelete="RESTRICT")),
    Column("reason", Text, nullable=False),
    Column("threshold", Numeric(38, 18)),
    Column("actual_value", Numeric(38, 18), comment=RISK_LOCKOUT_ACTUAL_VALUE_COMMENT),
    Column("since", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("until", TIMESTAMP(timezone=True)),
    Column("released_at", TIMESTAMP(timezone=True)),
    Column("released_by", ForeignKey("users.id", ondelete="RESTRICT")),
    Column("release_reason", Text),
    Column("actions_taken", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    CheckConstraint(
        "reason IN ('daily_loss','consecutive_losses','max_positions','manual')", name="rl_reason"
    ),
    CheckConstraint("reason <> 'manual' OR until IS NULL", name="rl_manual"),
    CheckConstraint("until IS NULL OR until > since", name="rl_until"),
    CheckConstraint("released_at IS NULL OR released_at >= since", name="rl_released"),
    CheckConstraint(
        "(released_at IS NULL AND released_by IS NULL AND release_reason IS NULL) OR "
        "(released_at IS NOT NULL AND released_by IS NOT NULL AND release_reason IS NOT NULL) "
        "OR (released_at IS NOT NULL AND released_by IS NULL AND release_reason IS NULL AND "
        "until IS NOT NULL AND released_at >= until)",
        name="rl_release",
    ),
    CheckConstraint(
        "release_reason IS NULL OR (char_length(release_reason) <= 280 AND "
        "char_length(btrim(release_reason, E' \\t\\r\\n')) >= 3)",
        name="rl_text",
    ),
    CheckConstraint(
        "threshold <> 'NaN'::numeric AND actual_value <> 'NaN'::numeric", name="rl_numbers"
    ),
    CheckConstraint("jsonb_typeof(actions_taken) = 'object'", name="rl_actions"),
    Index(
        "ux_risk_lockout_active",
        "exchange_account_id",
        "user_id",
        unique=True,
        postgresql_where=text("released_at IS NULL"),
        postgresql_nulls_not_distinct=True,
    ),
)
risk_policy = Table(
    "risk_policy",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("singleton", Boolean, nullable=False, server_default=text("true")),
    Column("max_total_notional_usd", Numeric(38, 18), nullable=False),
    Column("max_daily_loss_usd", Numeric(38, 18), nullable=False),
    Column("max_drawdown_pct", Numeric(9, 6), nullable=False),
    Column("max_open_positions", SmallInteger, nullable=False),
    Column("max_leverage", Numeric(10, 2), nullable=False),
    Column("max_orders_per_minute", SmallInteger, nullable=False),
    Column("per_symbol_concentration_pct", Numeric(9, 6), nullable=False),
    Column(
        "override_extra_loss_max_usd", Numeric(38, 18), nullable=False, server_default=text("0")
    ),
    Column("breach_behaviour", JSONB, nullable=False),
    Column("lockout_minutes_default", SmallInteger, nullable=False, server_default=text("60")),
    Column("block_trading_when_degraded", Boolean, nullable=False, server_default=text("true")),
    Column(
        "day_boundary_utc_offset_minutes", SmallInteger, nullable=False, server_default=text("0")
    ),
    Column("updated_by", ForeignKey("users.id", ondelete="RESTRICT")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("singleton", name="risk_policy_singleton_key"),
    CheckConstraint("singleton", name="rp_singleton"),
    CheckConstraint(
        "max_total_notional_usd >= 0 AND max_daily_loss_usd >= 0 AND "
        "override_extra_loss_max_usd >= 0 AND max_total_notional_usd <> 'NaN'::numeric AND "
        "max_daily_loss_usd <> 'NaN'::numeric AND override_extra_loss_max_usd <> "
        "'NaN'::numeric",
        name="rp_money",
    ),
    CheckConstraint(
        "max_drawdown_pct BETWEEN 0 AND 100 AND per_symbol_concentration_pct BETWEEN 0 AND 100",
        name="rp_pct",
    ),
    CheckConstraint("max_open_positions BETWEEN 0 AND 100", name="rp_positions"),
    CheckConstraint("max_leverage BETWEEN 1 AND 100", name="rp_leverage"),
    CheckConstraint("max_orders_per_minute BETWEEN 1 AND 600", name="rp_orders"),
    CheckConstraint("lockout_minutes_default BETWEEN 0 AND 1440", name="rp_lockout"),
    CheckConstraint("day_boundary_utc_offset_minutes BETWEEN -720 AND 840", name="rp_day"),
    CheckConstraint(
        "jsonb_typeof(breach_behaviour) = 'object' AND breach_behaviour ?& "
        "ARRAY['max_total_notional_usd','max_daily_loss_usd','max_drawdown_pct',"
        "'max_open_positions', "
        "'max_leverage','max_orders_per_minute','per_symbol_concentration_pct'] AND "
        "breach_behaviour - "
        "ARRAY['max_total_notional_usd','max_daily_loss_usd','max_drawdown_pct',"
        "'max_open_positions', "
        "'max_leverage','max_orders_per_minute','per_symbol_concentration_pct'] = '{}'::jsonb "
        'AND NOT jsonb_path_exists(breach_behaviour, \'strict $.* ? (@.type() != "string" || (@ != '
        '"warn" && @ != "block" && @ != "flatten"))\')',
        name="rp_behaviour",
    ),
)
kill_switch_state = Table(
    "kill_switch_state",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("scope", Text, nullable=False),
    Column("exchange_account_id", ForeignKey("exchange_accounts.id", ondelete="RESTRICT")),
    Column("engaged", Boolean, nullable=False),
    Column("engaged_at", TIMESTAMP(timezone=True)),
    Column("engaged_by", ForeignKey("users.id", ondelete="RESTRICT")),
    Column("reason", Text),
    Column("options", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("scope IN ('global','accounts')", name="kss_scope"),
    CheckConstraint("(scope = 'global') = (exchange_account_id IS NULL)", name="kss_target"),
    CheckConstraint(
        "NOT engaged OR (engaged_at IS NOT NULL AND reason IS NOT NULL)", name="kss_engaged"
    ),
    CheckConstraint(
        "reason IS NULL OR (char_length(reason) <= 280 AND "
        "char_length(btrim(reason, E' \\t\\r\\n')) >= 3)",
        name="kss_reason",
    ),
    CheckConstraint("jsonb_typeof(options) = 'object'", name="kss_options"),
    Index(
        "ux_kill_switch_state_scope",
        "scope",
        "exchange_account_id",
        unique=True,
        postgresql_nulls_not_distinct=True,
    ),
)

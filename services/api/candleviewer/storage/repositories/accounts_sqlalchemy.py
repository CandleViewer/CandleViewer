"""Postgres adapter for `AccountsStore` (E27-T01; tables from migrations 0017/0019).

Literal `sa.text` with bound parameters only. Column lists are explicit allow-lists that never
name an envelope column (`key_id_enc`, `secret_enc`, `enc_nonce`, `dek_ref`, `enc_alg`) nor
`ip_whitelist`/`last_error_*` (C-3.2): api_keys writes (insert, revoke, touch) stay in M2's
credential store, so this module adds no second writer of those rows.

SR-051 scoping lives in SQL, never as a Python post-filter:
- owner scope: a live-owner gate bound to `:caller` (same predicate as `trg_owner_floor_fn`),
  then liveness only. Ownership is a role, not a column.
- grant scope: `ea.id = ANY(:granted)` AND a live `user_account_access` row for `:caller` with
  `can_view AND NOT frozen`, so a stale snapshot only ever narrows.
Every `OwnerScope` call, reads included, runs the gate first and raises
`AccountsStoreScopeDeniedError` for a caller who is not a live owner (a uniform 403 that depends
only on the caller). The owner read statements also carry the owner predicate inline, so they
stay scoped by `:caller` even on a path that skipped the gate.
The `count_*` reads (M13 row gauges, #2314) are the one principal-free surface: env-bound
aggregate counts that return no row, id or label, and that no route reaches.
No hard DELETE exists. Mapped errors are raised `from None`: IntegrityError text carries P1
parameters (exchange_uid, label).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from candleviewer.storage.repositories.accounts import (
    AccountKey,
    AccountScope,
    AccountsPage,
    AccountsStoreConflictError,
    AccountsStoreRuleError,
    AccountsStoreScopeDeniedError,
    AccountsStoreStaleError,
    ApiKeyRotationRow,
    ApiKeyRow,
    ExchangeAccountPatch,
    ExchangeAccountRow,
    GrantScope,
    NewExchangeAccount,
    NewKeyRotation,
    OwnerScope,
    RotationStep,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_ENVS = frozenset({"live", "demo", "testnet"})
_KINDS = frozenset({"main", "sub"})
_STATUSES = frozenset({"pending", "active", "rotating", "revoked", "expired", "invalid"})
#: Targets of `transition_key_status`; `revoked` stays in M2 (broker flushes the DEK cache).
_TRANSITION_TARGETS = frozenset({"active", "rotating", "expired", "invalid"})
MAX_PAGE = 500
#: Upper bound of `list_rotations(limit=...)`. `_LIST_KEYS` has its own literal `LIMIT 100`
#: (the contract has no key pagination; live keys are 3 or fewer), pinned by a unit test.
_ROTATION_LIMIT = 100

#: Pinned read allow-lists (C-3.2: no envelope column, no `ip_whitelist`/`last_error_*`). SQL is
#: literal only, as in `drawings_sqlalchemy.py`: every statement repeats its list verbatim instead
#: of concatenating it, and a unit test pins each copy to these constants.
_EA_COLS = (
    "ea.id::text AS id, ea.exchange::text AS exchange, ea.env::text AS env, "
    "ea.kind::text AS kind, ea.exchange_uid AS exchange_uid, "
    "ea.parent_account_id::text AS parent_account_id, ea.label AS label, "
    "ea.colour_token AS colour_token, ea.is_enabled AS is_enabled, "
    "ea.trading_enabled AS trading_enabled, ea.position_mode AS position_mode, "
    "ea.margin_mode AS margin_mode, ea.account_type AS account_type, ea.quote_ccy AS quote_ccy, "
    "ea.equity_cached_usd AS equity_cached_usd, ea.equity_cached_at AS equity_cached_at, "
    "ea.max_sub_accounts_hint AS max_sub_accounts_hint, "
    "ea.last_reconciled_at AS last_reconciled_at, ea.created_at AS created_at, "
    "ea.updated_at AS updated_at, ea.deleted_at AS deleted_at"
)
_KEY_COLS = (
    "k.id::text AS id, k.exchange_account_id::text AS exchange_account_id, k.label AS label, "
    "k.key_id_last4 AS key_id_last4, k.kek_version AS kek_version, "
    "k.permission_snapshot AS permission_snapshot, "
    "k.permission_snapshot_at AS permission_snapshot_at, k.can_trade AS can_trade, "
    "k.can_withdraw AS can_withdraw, k.can_transfer AS can_transfer, k.read_only AS read_only, "
    "k.status::text AS status, k.expires_at AS expires_at, k.last_used_at AS last_used_at, "
    "k.rotation_due_at AS rotation_due_at, k.created_at AS created_at, k.revoked_at AS revoked_at"
)
_ROT_COLS = (
    "r.id::text AS id, r.old_api_key_id::text AS old_api_key_id, "
    "r.new_api_key_id::text AS new_api_key_id, r.started_at AS started_at, "
    "r.validated_at AS validated_at, r.cutover_at AS cutover_at, "
    "r.completed_at AS completed_at, r.failed_at AS failed_at, "
    "r.failure_reason AS failure_reason, r.grace_seconds AS grace_seconds"
)
#: SR-051 predicates, repeated verbatim in the statements below and pinned the same way.
_OWNER_PRED = (
    "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "JOIN users u ON u.id = ur.user_id WHERE ur.user_id = CAST(:caller AS uuid) "
    "AND r.name = 'owner' AND u.deleted_at IS NULL AND u.status = 'active' "
    "AND (ur.expires_at IS NULL OR ur.expires_at > now()))"
)
_GRANT_PRED = (
    "ea.id = ANY(CAST(:granted AS uuid[])) AND EXISTS (SELECT 1 FROM user_account_access uaa "
    "WHERE uaa.user_id = CAST(:caller AS uuid) AND uaa.exchange_account_id = ea.id "
    "AND uaa.can_view AND NOT uaa.frozen)"
)

_OWNER_GATE = sa.text(
    "SELECT EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "JOIN users u ON u.id = ur.user_id WHERE ur.user_id = CAST(:caller AS uuid) "
    "AND r.name = 'owner' AND u.deleted_at IS NULL AND u.status = 'active' "
    "AND (ur.expires_at IS NULL OR ur.expires_at > now()))"
)

_CREATE = sa.text(
    "INSERT INTO exchange_accounts AS ea (id, exchange, env, kind, exchange_uid, "
    "parent_account_id, label, created_by, updated_by) "
    "SELECT CAST(:id AS uuid), CAST(:exchange AS exchange_code), CAST(:env AS exchange_env), "
    "CAST(:kind AS account_kind), CAST(:uid AS text), CAST(:parent AS uuid), "
    "CAST(:label AS text), CAST(:caller AS uuid), CAST(:caller AS uuid) "
    "WHERE CAST(:parent AS uuid) IS NULL OR EXISTS (SELECT 1 FROM exchange_accounts p "
    "WHERE p.id = CAST(:parent AS uuid) AND p.deleted_at IS NULL AND p.kind = 'main' "
    "AND p.env::text = CAST(:env AS text)) "
    "RETURNING "
    "ea.id::text AS id, ea.exchange::text AS exchange, ea.env::text AS env, "
    "ea.kind::text AS kind, ea.exchange_uid AS exchange_uid, "
    "ea.parent_account_id::text AS parent_account_id, ea.label AS label, "
    "ea.colour_token AS colour_token, ea.is_enabled AS is_enabled, "
    "ea.trading_enabled AS trading_enabled, ea.position_mode AS position_mode, "
    "ea.margin_mode AS margin_mode, ea.account_type AS account_type, ea.quote_ccy AS quote_ccy, "
    "ea.equity_cached_usd AS equity_cached_usd, ea.equity_cached_at AS equity_cached_at, "
    "ea.max_sub_accounts_hint AS max_sub_accounts_hint, "
    "ea.last_reconciled_at AS last_reconciled_at, ea.created_at AS created_at, "
    "ea.updated_at AS updated_at, ea.deleted_at AS deleted_at"
)
_GET_OWNER = sa.text(
    "SELECT "
    "ea.id::text AS id, ea.exchange::text AS exchange, ea.env::text AS env, "
    "ea.kind::text AS kind, ea.exchange_uid AS exchange_uid, "
    "ea.parent_account_id::text AS parent_account_id, ea.label AS label, "
    "ea.colour_token AS colour_token, ea.is_enabled AS is_enabled, "
    "ea.trading_enabled AS trading_enabled, ea.position_mode AS position_mode, "
    "ea.margin_mode AS margin_mode, ea.account_type AS account_type, ea.quote_ccy AS quote_ccy, "
    "ea.equity_cached_usd AS equity_cached_usd, ea.equity_cached_at AS equity_cached_at, "
    "ea.max_sub_accounts_hint AS max_sub_accounts_hint, "
    "ea.last_reconciled_at AS last_reconciled_at, ea.created_at AS created_at, "
    "ea.updated_at AS updated_at, ea.deleted_at AS deleted_at"
    " FROM exchange_accounts ea WHERE ea.deleted_at IS NULL AND ea.id = CAST(:id AS uuid) AND "
    "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "JOIN users u ON u.id = ur.user_id WHERE ur.user_id = CAST(:caller AS uuid) "
    "AND r.name = 'owner' AND u.deleted_at IS NULL AND u.status = 'active' "
    "AND (ur.expires_at IS NULL OR ur.expires_at > now()))"
)
_GET_GRANT = sa.text(
    "SELECT "
    "ea.id::text AS id, ea.exchange::text AS exchange, ea.env::text AS env, "
    "ea.kind::text AS kind, ea.exchange_uid AS exchange_uid, "
    "ea.parent_account_id::text AS parent_account_id, ea.label AS label, "
    "ea.colour_token AS colour_token, ea.is_enabled AS is_enabled, "
    "ea.trading_enabled AS trading_enabled, ea.position_mode AS position_mode, "
    "ea.margin_mode AS margin_mode, ea.account_type AS account_type, ea.quote_ccy AS quote_ccy, "
    "ea.equity_cached_usd AS equity_cached_usd, ea.equity_cached_at AS equity_cached_at, "
    "ea.max_sub_accounts_hint AS max_sub_accounts_hint, "
    "ea.last_reconciled_at AS last_reconciled_at, ea.created_at AS created_at, "
    "ea.updated_at AS updated_at, ea.deleted_at AS deleted_at"
    " FROM exchange_accounts ea WHERE ea.deleted_at IS NULL AND ea.id = CAST(:id AS uuid) AND "
    "ea.id = ANY(CAST(:granted AS uuid[])) AND EXISTS (SELECT 1 FROM user_account_access uaa "
    "WHERE uaa.user_id = CAST(:caller AS uuid) AND uaa.exchange_account_id = ea.id "
    "AND uaa.can_view AND NOT uaa.frozen)"
)
_LIST_OWNER = sa.text(
    "SELECT "
    "ea.id::text AS id, ea.exchange::text AS exchange, ea.env::text AS env, "
    "ea.kind::text AS kind, ea.exchange_uid AS exchange_uid, "
    "ea.parent_account_id::text AS parent_account_id, ea.label AS label, "
    "ea.colour_token AS colour_token, ea.is_enabled AS is_enabled, "
    "ea.trading_enabled AS trading_enabled, ea.position_mode AS position_mode, "
    "ea.margin_mode AS margin_mode, ea.account_type AS account_type, ea.quote_ccy AS quote_ccy, "
    "ea.equity_cached_usd AS equity_cached_usd, ea.equity_cached_at AS equity_cached_at, "
    "ea.max_sub_accounts_hint AS max_sub_accounts_hint, "
    "ea.last_reconciled_at AS last_reconciled_at, ea.created_at AS created_at, "
    "ea.updated_at AS updated_at, ea.deleted_at AS deleted_at"
    " FROM exchange_accounts ea WHERE ea.deleted_at IS NULL AND "
    "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
    "JOIN users u ON u.id = ur.user_id WHERE ur.user_id = CAST(:caller AS uuid) "
    "AND r.name = 'owner' AND u.deleted_at IS NULL AND u.status = 'active' "
    "AND (ur.expires_at IS NULL OR ur.expires_at > now())) "
    "AND (CAST(:env AS text) IS NULL OR ea.env::text = CAST(:env AS text)) "
    "AND (CAST(:kind AS text) IS NULL OR ea.kind::text = CAST(:kind AS text)) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR "
    "(ea.created_at, ea.id) > (CAST(:after_ts AS timestamptz), CAST(:after_id AS uuid))) "
    "ORDER BY ea.created_at, ea.id LIMIT :limit"
)
_LIST_GRANT = sa.text(
    "SELECT "
    "ea.id::text AS id, ea.exchange::text AS exchange, ea.env::text AS env, "
    "ea.kind::text AS kind, ea.exchange_uid AS exchange_uid, "
    "ea.parent_account_id::text AS parent_account_id, ea.label AS label, "
    "ea.colour_token AS colour_token, ea.is_enabled AS is_enabled, "
    "ea.trading_enabled AS trading_enabled, ea.position_mode AS position_mode, "
    "ea.margin_mode AS margin_mode, ea.account_type AS account_type, ea.quote_ccy AS quote_ccy, "
    "ea.equity_cached_usd AS equity_cached_usd, ea.equity_cached_at AS equity_cached_at, "
    "ea.max_sub_accounts_hint AS max_sub_accounts_hint, "
    "ea.last_reconciled_at AS last_reconciled_at, ea.created_at AS created_at, "
    "ea.updated_at AS updated_at, ea.deleted_at AS deleted_at"
    " FROM exchange_accounts ea WHERE ea.deleted_at IS NULL AND "
    "ea.id = ANY(CAST(:granted AS uuid[])) AND EXISTS (SELECT 1 FROM user_account_access uaa "
    "WHERE uaa.user_id = CAST(:caller AS uuid) AND uaa.exchange_account_id = ea.id "
    "AND uaa.can_view AND NOT uaa.frozen) "
    "AND (CAST(:env AS text) IS NULL OR ea.env::text = CAST(:env AS text)) "
    "AND (CAST(:kind AS text) IS NULL OR ea.kind::text = CAST(:kind AS text)) "
    "AND (CAST(:after_ts AS timestamptz) IS NULL OR "
    "(ea.created_at, ea.id) > (CAST(:after_ts AS timestamptz), CAST(:after_id AS uuid))) "
    "ORDER BY ea.created_at, ea.id LIMIT :limit"
)
_UPDATE = sa.text(
    "UPDATE exchange_accounts AS ea SET "
    "label = COALESCE(CAST(:label AS text), ea.label), "
    "is_enabled = COALESCE(CAST(:is_enabled AS boolean), ea.is_enabled), "
    "position_mode = COALESCE(CAST(:position_mode AS text), ea.position_mode), "
    "margin_mode = COALESCE(CAST(:margin_mode AS text), ea.margin_mode), "
    "updated_by = CAST(:caller AS uuid), "
    "updated_at = greatest(clock_timestamp(), ea.updated_at + interval '1 microsecond') "
    "WHERE ea.id = CAST(:id AS uuid) AND ea.deleted_at IS NULL "
    "AND (CAST(:if_match AS timestamptz) IS NULL OR ea.updated_at = CAST(:if_match AS timestamptz))"
    " RETURNING "
    "ea.id::text AS id, ea.exchange::text AS exchange, ea.env::text AS env, "
    "ea.kind::text AS kind, ea.exchange_uid AS exchange_uid, "
    "ea.parent_account_id::text AS parent_account_id, ea.label AS label, "
    "ea.colour_token AS colour_token, ea.is_enabled AS is_enabled, "
    "ea.trading_enabled AS trading_enabled, ea.position_mode AS position_mode, "
    "ea.margin_mode AS margin_mode, ea.account_type AS account_type, ea.quote_ccy AS quote_ccy, "
    "ea.equity_cached_usd AS equity_cached_usd, ea.equity_cached_at AS equity_cached_at, "
    "ea.max_sub_accounts_hint AS max_sub_accounts_hint, "
    "ea.last_reconciled_at AS last_reconciled_at, ea.created_at AS created_at, "
    "ea.updated_at AS updated_at, ea.deleted_at AS deleted_at"
)
_SOFT_DELETE = sa.text(
    "UPDATE exchange_accounts AS ea SET deleted_at = now(), trading_enabled = false, "
    "updated_by = CAST(:caller AS uuid), "
    "updated_at = greatest(clock_timestamp(), ea.updated_at + interval '1 microsecond') "
    "WHERE ea.id = CAST(:id AS uuid) AND ea.deleted_at IS NULL"
)

_GET_KEY = sa.text(
    "SELECT "
    "k.id::text AS id, k.exchange_account_id::text AS exchange_account_id, k.label AS label, "
    "k.key_id_last4 AS key_id_last4, k.kek_version AS kek_version, "
    "k.permission_snapshot AS permission_snapshot, "
    "k.permission_snapshot_at AS permission_snapshot_at, k.can_trade AS can_trade, "
    "k.can_withdraw AS can_withdraw, k.can_transfer AS can_transfer, k.read_only AS read_only, "
    "k.status::text AS status, k.expires_at AS expires_at, k.last_used_at AS last_used_at, "
    "k.rotation_due_at AS rotation_due_at, k.created_at AS created_at, k.revoked_at AS revoked_at"
    " FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE ea.deleted_at IS NULL AND k.exchange_account_id = CAST(:account AS uuid)"
    " AND k.id = CAST(:key AS uuid)"
)
_LIST_KEYS = sa.text(
    "SELECT "
    "k.id::text AS id, k.exchange_account_id::text AS exchange_account_id, k.label AS label, "
    "k.key_id_last4 AS key_id_last4, k.kek_version AS kek_version, "
    "k.permission_snapshot AS permission_snapshot, "
    "k.permission_snapshot_at AS permission_snapshot_at, k.can_trade AS can_trade, "
    "k.can_withdraw AS can_withdraw, k.can_transfer AS can_transfer, k.read_only AS read_only, "
    "k.status::text AS status, k.expires_at AS expires_at, k.last_used_at AS last_used_at, "
    "k.rotation_due_at AS rotation_due_at, k.created_at AS created_at, k.revoked_at AS revoked_at"
    " FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE ea.deleted_at IS NULL AND k.exchange_account_id = CAST(:account AS uuid)"
    " AND k.revoked_at IS NULL "
    "ORDER BY k.created_at, k.id LIMIT 100"
)
_TRANSITION = sa.text(
    "UPDATE api_keys AS k SET status = CAST(:new AS key_status), "
    "updated_by = CAST(:caller AS uuid), updated_at = now() "
    "FROM exchange_accounts ea WHERE ea.id = k.exchange_account_id AND ea.deleted_at IS NULL "
    "AND k.exchange_account_id = CAST(:account AS uuid) AND k.id = CAST(:key AS uuid) "
    "AND k.revoked_at IS NULL AND k.status::text = CAST(:expected AS text) "
    "RETURNING "
    "k.id::text AS id, k.exchange_account_id::text AS exchange_account_id, k.label AS label, "
    "k.key_id_last4 AS key_id_last4, k.kek_version AS kek_version, "
    "k.permission_snapshot AS permission_snapshot, "
    "k.permission_snapshot_at AS permission_snapshot_at, k.can_trade AS can_trade, "
    "k.can_withdraw AS can_withdraw, k.can_transfer AS can_transfer, k.read_only AS read_only, "
    "k.status::text AS status, k.expires_at AS expires_at, k.last_used_at AS last_used_at, "
    "k.rotation_due_at AS rotation_due_at, k.created_at AS created_at, k.revoked_at AS revoked_at"
)

_START_ROT = sa.text(
    "INSERT INTO api_key_rotations (id, old_api_key_id, new_api_key_id, started_by, "
    "grace_seconds) SELECT CAST(:id AS uuid), o.id, n.id, CAST(:caller AS uuid), "
    "CAST(:grace AS integer) FROM api_keys o "
    "JOIN api_keys n ON n.id = CAST(:new_key AS uuid) "
    "AND n.exchange_account_id = o.exchange_account_id "
    "JOIN exchange_accounts ea ON ea.id = o.exchange_account_id "
    "WHERE o.id = CAST(:old_key AS uuid) AND o.exchange_account_id = CAST(:account AS uuid) "
    "AND o.revoked_at IS NULL AND n.revoked_at IS NULL AND ea.deleted_at IS NULL "
    "RETURNING id::text AS id, old_api_key_id::text AS old_api_key_id, "
    "new_api_key_id::text AS new_api_key_id, started_at AS started_at, "
    "validated_at AS validated_at, cutover_at AS cutover_at, completed_at AS completed_at, "
    "failed_at AS failed_at, failure_reason AS failure_reason, grace_seconds AS grace_seconds"
)
_GET_ROT = sa.text(
    "SELECT "
    "r.id::text AS id, r.old_api_key_id::text AS old_api_key_id, "
    "r.new_api_key_id::text AS new_api_key_id, r.started_at AS started_at, "
    "r.validated_at AS validated_at, r.cutover_at AS cutover_at, "
    "r.completed_at AS completed_at, r.failed_at AS failed_at, "
    "r.failure_reason AS failure_reason, r.grace_seconds AS grace_seconds"
    " FROM api_key_rotations r JOIN api_keys o ON o.id = r.old_api_key_id "
    "JOIN exchange_accounts ea ON ea.id = o.exchange_account_id "
    "WHERE ea.deleted_at IS NULL AND o.exchange_account_id = CAST(:account AS uuid)"
    " AND r.id = CAST(:rot AS uuid)"
)
_LIST_ROTS = sa.text(
    "SELECT "
    "r.id::text AS id, r.old_api_key_id::text AS old_api_key_id, "
    "r.new_api_key_id::text AS new_api_key_id, r.started_at AS started_at, "
    "r.validated_at AS validated_at, r.cutover_at AS cutover_at, "
    "r.completed_at AS completed_at, r.failed_at AS failed_at, "
    "r.failure_reason AS failure_reason, r.grace_seconds AS grace_seconds"
    " FROM api_key_rotations r JOIN api_keys o ON o.id = r.old_api_key_id "
    "JOIN exchange_accounts ea ON ea.id = o.exchange_account_id "
    "WHERE ea.deleted_at IS NULL AND o.exchange_account_id = CAST(:account AS uuid)"
    " ORDER BY r.started_at DESC, r.id DESC LIMIT :limit"
)
# Rotation steps: one CAS UPDATE each, scoped to the path account and to an open rotation.
_STEP_VALIDATED = sa.text(
    "UPDATE api_key_rotations AS r SET validated_at = clock_timestamp()"
    " FROM api_keys o, exchange_accounts ea WHERE o.id = r.old_api_key_id "
    "AND ea.id = o.exchange_account_id AND ea.deleted_at IS NULL "
    "AND o.exchange_account_id = CAST(:account AS uuid) AND r.id = CAST(:rot AS uuid) "
    "AND r.completed_at IS NULL AND r.failed_at IS NULL"
    " AND r.validated_at IS NULL RETURNING "
    "r.id::text AS id, r.old_api_key_id::text AS old_api_key_id, "
    "r.new_api_key_id::text AS new_api_key_id, r.started_at AS started_at, "
    "r.validated_at AS validated_at, r.cutover_at AS cutover_at, "
    "r.completed_at AS completed_at, r.failed_at AS failed_at, "
    "r.failure_reason AS failure_reason, r.grace_seconds AS grace_seconds"
)
_STEP_CUTOVER = sa.text(
    "UPDATE api_key_rotations AS r SET cutover_at = clock_timestamp()"
    " FROM api_keys o, exchange_accounts ea WHERE o.id = r.old_api_key_id "
    "AND ea.id = o.exchange_account_id AND ea.deleted_at IS NULL "
    "AND o.exchange_account_id = CAST(:account AS uuid) AND r.id = CAST(:rot AS uuid) "
    "AND r.completed_at IS NULL AND r.failed_at IS NULL"
    " AND r.validated_at IS NOT NULL AND r.cutover_at IS NULL RETURNING "
    "r.id::text AS id, r.old_api_key_id::text AS old_api_key_id, "
    "r.new_api_key_id::text AS new_api_key_id, r.started_at AS started_at, "
    "r.validated_at AS validated_at, r.cutover_at AS cutover_at, "
    "r.completed_at AS completed_at, r.failed_at AS failed_at, "
    "r.failure_reason AS failure_reason, r.grace_seconds AS grace_seconds"
)
_STEP_COMPLETED = sa.text(
    "UPDATE api_key_rotations AS r SET completed_at = clock_timestamp()"
    " FROM api_keys o, exchange_accounts ea WHERE o.id = r.old_api_key_id "
    "AND ea.id = o.exchange_account_id AND ea.deleted_at IS NULL "
    "AND o.exchange_account_id = CAST(:account AS uuid) AND r.id = CAST(:rot AS uuid) "
    "AND r.completed_at IS NULL AND r.failed_at IS NULL"
    " AND r.cutover_at IS NOT NULL RETURNING "
    "r.id::text AS id, r.old_api_key_id::text AS old_api_key_id, "
    "r.new_api_key_id::text AS new_api_key_id, r.started_at AS started_at, "
    "r.validated_at AS validated_at, r.cutover_at AS cutover_at, "
    "r.completed_at AS completed_at, r.failed_at AS failed_at, "
    "r.failure_reason AS failure_reason, r.grace_seconds AS grace_seconds"
)
_STEP_FAILED = sa.text(
    "UPDATE api_key_rotations AS r SET failed_at = clock_timestamp(), "
    "failure_reason = CAST(:reason AS text)"
    " FROM api_keys o, exchange_accounts ea WHERE o.id = r.old_api_key_id "
    "AND ea.id = o.exchange_account_id AND ea.deleted_at IS NULL "
    "AND o.exchange_account_id = CAST(:account AS uuid) AND r.id = CAST(:rot AS uuid) "
    "AND r.completed_at IS NULL AND r.failed_at IS NULL"
    " RETURNING "
    "r.id::text AS id, r.old_api_key_id::text AS old_api_key_id, "
    "r.new_api_key_id::text AS new_api_key_id, r.started_at AS started_at, "
    "r.validated_at AS validated_at, r.cutover_at AS cutover_at, "
    "r.completed_at AS completed_at, r.failed_at AS failed_at, "
    "r.failure_reason AS failure_reason, r.grace_seconds AS grace_seconds"
)
_STEPS = {
    "validated": _STEP_VALIDATED,
    "cutover": _STEP_CUTOVER,
    "completed": _STEP_COMPLETED,
    "failed": _STEP_FAILED,
}
#: M13 row-gauge aggregates (#2314): counts for the process environment only (20 §7.1), never a
#: row, an id or a label. No principal scope; `AccountsService` is the only caller (unit-pinned).
_COUNT_ACCOUNTS = sa.text(
    "SELECT ea.kind::text AS kind, count(*) AS n FROM exchange_accounts ea "
    "WHERE ea.deleted_at IS NULL AND ea.env::text = CAST(:env AS text) GROUP BY ea.kind"
)
_COUNT_KEYS = sa.text(
    "SELECT k.status::text AS status, count(*) AS n FROM api_keys k "
    "JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE ea.env::text = CAST(:env AS text) GROUP BY k.status"
)

OWNER_STATEMENTS = frozenset(
    {
        _CREATE, _GET_OWNER, _LIST_OWNER, _UPDATE, _SOFT_DELETE, _GET_KEY, _LIST_KEYS,
        _TRANSITION, _START_ROT, _GET_ROT, _LIST_ROTS, *_STEPS.values(),
    }
)  # fmt: skip
GRANT_STATEMENTS = frozenset({_GET_GRANT, _LIST_GRANT})
TELEMETRY_STATEMENTS = frozenset({_COUNT_ACCOUNTS, _COUNT_KEYS})

_CONFLICT_CONSTRAINTS = frozenset(
    {"exchange_accounts_pkey", "ux_ea_uid", "ux_ea_label", "ux_api_keys_active",
     "api_key_rotations_pkey"}
)  # fmt: skip
_RULE_CONSTRAINTS = frozenset(
    {"ea_parent_shape", "ea_no_self_parent", "ea_uid_fmt", "ea_posmode", "ea_marginmode",
     "akr_distinct", "akr_grace"}
)  # fmt: skip


def _sqlstate_and_constraint(exc: IntegrityError) -> tuple[str | None, str | None]:
    """SQLSTATE + constraint name; asyncpg hides the name on the wrapper, so look on
    `orig`, `__cause__`, `driver_exception` and `diag`."""
    orig: Any = exc.orig
    state = getattr(orig, "sqlstate", None)
    for src in (orig, getattr(orig, "__cause__", None), getattr(orig, "driver_exception", None)):
        name = getattr(src, "constraint_name", None) or getattr(
            getattr(src, "diag", None), "constraint_name", None
        )
        if name:
            return state, str(name)
    return state, None


def _raise_mapped(exc: IntegrityError) -> None:
    state, name = _sqlstate_and_constraint(exc)
    if state == "23505" and name in _CONFLICT_CONSTRAINTS:
        raise AccountsStoreConflictError(name) from None
    if state == "23514" and name in _RULE_CONSTRAINTS:
        raise AccountsStoreRuleError(name) from None


def _decode(value: object) -> dict[str, object]:
    """`permission_snapshot` jsonb arrives as `str` (no asyncpg codec) or as a mapping. Any other
    shape fails closed; `ak_snapshot_shape` already makes it an object in the database."""
    parsed: object = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping):
        raise TypeError("permission_snapshot is not a JSON object")
    return dict(parsed)


def _uuid(value: object) -> UUID:
    return UUID(str(value))


def _opt_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _account(m: Any) -> ExchangeAccountRow:
    d = dict(m)
    d["id"] = _uuid(d["id"])
    d["parent_account_id"] = _opt_uuid(d["parent_account_id"])
    return ExchangeAccountRow(**d)


def _key(m: Any) -> ApiKeyRow:
    d = dict(m)
    d["id"] = _uuid(d["id"])
    d["exchange_account_id"] = _uuid(d["exchange_account_id"])
    d["permission_snapshot"] = _decode(d["permission_snapshot"])
    return ApiKeyRow(**d)


def _rotation(m: Any) -> ApiKeyRotationRow:
    d = dict(m)
    for k in ("id", "old_api_key_id", "new_api_key_id"):
        d[k] = _uuid(d[k])
    return ApiKeyRotationRow(**d)


def _require_owner(scope: object) -> OwnerScope:
    if not isinstance(scope, OwnerScope):
        raise AccountsStoreScopeDeniedError
    return scope


class SqlAlchemyAccountsStore:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    @staticmethod
    async def _gate(uow: Any, scope: OwnerScope) -> None:
        res = await uow.session.execute(_OWNER_GATE, {"caller": str(scope.user_id)})
        if not res.scalar_one():
            raise AccountsStoreScopeDeniedError

    async def _scoped_rows(
        self,
        scope: AccountScope,
        owner_stmt: sa.TextClause,
        grant_stmt: sa.TextClause,
        params: dict[str, Any],
    ) -> list[Any]:
        """Run the SR-051 variant of an account read for `scope`.

        `GrantScope`: the grant statement, which narrows silently in SQL; an empty grant set
        sees nothing and runs no SQL (fail closed). `OwnerScope`: the live-owner gate first, so
        a non-owner gets `AccountsStoreScopeDeniedError` exactly as on the owner-only methods.
        """
        if isinstance(scope, GrantScope):
            if not scope.account_ids:
                return []
            bound = {
                **params,
                "granted": sorted(map(str, scope.account_ids)),
                "caller": str(scope.user_id),
            }
            async with self._relational.unit_of_work() as uow:
                return list((await uow.session.execute(grant_stmt, bound)).mappings())
        owner = _require_owner(scope)
        async with self._relational.unit_of_work() as uow:
            await self._gate(uow, owner)
            res = await uow.session.execute(owner_stmt, {**params, "caller": str(owner.user_id)})
            return list(res.mappings())

    # -- accounts ---------------------------------------------------------------------------
    async def create_account(
        self, scope: OwnerScope, new: NewExchangeAccount
    ) -> ExchangeAccountRow:
        owner = _require_owner(scope)
        if new.env not in _ENVS or new.kind not in _KINDS:
            raise ValueError("unknown env or kind")
        params: dict[str, Any] = {
            "id": str(new.id),
            "exchange": new.exchange,
            "env": new.env,
            "kind": new.kind,
            "uid": new.exchange_uid,
            "parent": None if new.parent_account_id is None else str(new.parent_account_id),
            "label": new.label,
            "caller": str(owner.user_id),
        }
        try:
            async with self._relational.unit_of_work() as uow:
                await self._gate(uow, owner)
                row = (await uow.session.execute(_CREATE, params)).mappings().first()
                if row is None:
                    raise AccountsStoreRuleError("parent_unavailable")
                await uow.commit()
        except IntegrityError as exc:
            _raise_mapped(exc)
            raise
        return _account(row)

    async def get_account(self, scope: AccountScope, account_id: UUID) -> ExchangeAccountRow | None:
        rows = await self._scoped_rows(scope, _GET_OWNER, _GET_GRANT, {"id": str(account_id)})
        return _account(rows[0]) if rows else None

    async def list_accounts(
        self,
        scope: AccountScope,
        *,
        env: str | None,
        kind: str | None,
        after: AccountKey | None,
        limit: int,
    ) -> AccountsPage[ExchangeAccountRow]:
        if not 1 <= limit <= MAX_PAGE:
            raise ValueError("limit out of range")
        if (env is not None and env not in _ENVS) or (kind is not None and kind not in _KINDS):
            raise ValueError("unknown env or kind")
        params: dict[str, Any] = {
            "env": env,
            "kind": kind,
            "after_ts": None if after is None else after.created_at,
            "after_id": None if after is None else str(after.id),
            "limit": limit + 1,
        }
        rows = [
            _account(r) for r in await self._scoped_rows(scope, _LIST_OWNER, _LIST_GRANT, params)
        ]
        page = rows[:limit]
        nxt = None
        if len(rows) > limit:
            nxt = AccountKey(page[-1].created_at, page[-1].id)
        return AccountsPage(tuple(page), nxt)

    async def update_account(
        self,
        scope: OwnerScope,
        account_id: UUID,
        patch: ExchangeAccountPatch,
        *,
        if_match: datetime | None,
    ) -> ExchangeAccountRow | None:
        owner = _require_owner(scope)
        if (
            patch.label is None
            and patch.is_enabled is None
            and patch.position_mode is None
            and patch.margin_mode is None
        ):
            raise ValueError("empty patch")
        params: dict[str, Any] = {
            "id": str(account_id),
            "caller": str(owner.user_id),
            "label": patch.label,
            "is_enabled": patch.is_enabled,
            "position_mode": patch.position_mode,
            "margin_mode": patch.margin_mode,
            "if_match": if_match,
        }
        try:
            async with self._relational.unit_of_work() as uow:
                await self._gate(uow, owner)
                row = (await uow.session.execute(_UPDATE, params)).mappings().first()
                if row is None:
                    live = await uow.session.execute(
                        _GET_OWNER, {"id": str(account_id), "caller": str(owner.user_id)}
                    )
                    if live.mappings().first() is not None:
                        raise AccountsStoreStaleError
                    return None
                await uow.commit()
        except IntegrityError as exc:
            _raise_mapped(exc)
            raise
        return _account(row)

    async def soft_delete_account(self, scope: OwnerScope, account_id: UUID) -> bool:
        owner = _require_owner(scope)
        async with self._relational.unit_of_work() as uow:
            await self._gate(uow, owner)
            # A DML `text()` statement returns a CursorResult at runtime; `AsyncSession.execute`
            # is typed as the base `Result`, so the cast only informs mypy. No getattr default:
            # a wrong result object fails loudly instead of reading as "not found".
            res = cast(
                "sa.CursorResult[Any]",
                await uow.session.execute(
                    _SOFT_DELETE, {"id": str(account_id), "caller": str(owner.user_id)}
                ),
            )
            await uow.commit()
        return res.rowcount == 1

    # -- api_keys (metadata only) -----------------------------------------------------------
    async def get_key(self, scope: OwnerScope, account_id: UUID, key_id: UUID) -> ApiKeyRow | None:
        owner = _require_owner(scope)
        async with self._relational.unit_of_work() as uow:
            await self._gate(uow, owner)
            res = await uow.session.execute(
                _GET_KEY, {"account": str(account_id), "key": str(key_id)}
            )
            row = res.mappings().first()
        return None if row is None else _key(row)

    async def list_keys(self, scope: OwnerScope, account_id: UUID) -> tuple[ApiKeyRow, ...]:
        owner = _require_owner(scope)
        async with self._relational.unit_of_work() as uow:
            await self._gate(uow, owner)
            res = await uow.session.execute(_LIST_KEYS, {"account": str(account_id)})
            return tuple(_key(r) for r in res.mappings())

    async def transition_key_status(
        self, scope: OwnerScope, account_id: UUID, key_id: UUID, *, expected: str, new: str
    ) -> ApiKeyRow | None:
        owner = _require_owner(scope)
        if expected not in _STATUSES or new not in _TRANSITION_TARGETS:
            raise ValueError("unknown or forbidden key status")
        params: dict[str, Any] = {
            "account": str(account_id),
            "key": str(key_id),
            "expected": expected,
            "new": new,
            "caller": str(owner.user_id),
        }
        try:
            async with self._relational.unit_of_work() as uow:
                await self._gate(uow, owner)
                row = (await uow.session.execute(_TRANSITION, params)).mappings().first()
                if row is None:
                    cur = (
                        (
                            await uow.session.execute(
                                _GET_KEY, {"account": params["account"], "key": params["key"]}
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if cur is None or cur["revoked_at"] is not None:
                        return None
                    raise AccountsStoreConflictError("key_status")
                await uow.commit()
        except IntegrityError as exc:
            _raise_mapped(exc)
            raise
        return _key(row)

    # -- api_key_rotations ------------------------------------------------------------------
    async def start_rotation(
        self, scope: OwnerScope, new: NewKeyRotation
    ) -> ApiKeyRotationRow | None:
        owner = _require_owner(scope)
        params: dict[str, Any] = {
            "id": str(new.id),
            "account": str(new.exchange_account_id),
            "old_key": str(new.old_api_key_id),
            "new_key": str(new.new_api_key_id),
            "grace": new.grace_seconds,
            "caller": str(owner.user_id),
        }
        try:
            async with self._relational.unit_of_work() as uow:
                await self._gate(uow, owner)
                row = (await uow.session.execute(_START_ROT, params)).mappings().first()
                if row is None:
                    return None
                await uow.commit()
        except IntegrityError as exc:
            _raise_mapped(exc)
            raise
        return _rotation(row)

    async def get_rotation(
        self, scope: OwnerScope, account_id: UUID, rotation_id: UUID
    ) -> ApiKeyRotationRow | None:
        owner = _require_owner(scope)
        async with self._relational.unit_of_work() as uow:
            await self._gate(uow, owner)
            res = await uow.session.execute(
                _GET_ROT, {"account": str(account_id), "rot": str(rotation_id)}
            )
            row = res.mappings().first()
        return None if row is None else _rotation(row)

    async def list_rotations(
        self, scope: OwnerScope, account_id: UUID, *, limit: int
    ) -> tuple[ApiKeyRotationRow, ...]:
        owner = _require_owner(scope)
        if not 1 <= limit <= _ROTATION_LIMIT:
            raise ValueError("limit out of range")
        async with self._relational.unit_of_work() as uow:
            await self._gate(uow, owner)
            res = await uow.session.execute(
                _LIST_ROTS, {"account": str(account_id), "limit": limit}
            )
            return tuple(_rotation(r) for r in res.mappings())

    async def record_rotation_step(
        self,
        scope: OwnerScope,
        account_id: UUID,
        rotation_id: UUID,
        step: RotationStep,
        *,
        failure_reason: str | None,
    ) -> ApiKeyRotationRow | None:
        owner = _require_owner(scope)
        stmt = _STEPS.get(step)
        if stmt is None:
            raise ValueError("unknown rotation step")
        params: dict[str, Any] = {"account": str(account_id), "rot": str(rotation_id)}
        if step == "failed":
            if failure_reason is None or not 1 <= len(failure_reason) <= 200:
                raise ValueError("failure_reason must be 1-200 characters")
            params["reason"] = failure_reason
        elif failure_reason is not None:
            raise ValueError("failure_reason only applies to 'failed'")
        async with self._relational.unit_of_work() as uow:
            await self._gate(uow, owner)
            row = (await uow.session.execute(stmt, params)).mappings().first()
            if row is None:
                cur = await uow.session.execute(
                    _GET_ROT, {"account": params["account"], "rot": params["rot"]}
                )
                if cur.mappings().first() is None:
                    return None
                raise AccountsStoreConflictError("rotation_state")
            await uow.commit()
        return _rotation(row)

    # -- system telemetry (#2314) -----------------------------------------------------------
    async def count_accounts_by_kind(self, env: str) -> dict[str, int]:
        return await self._counts(_COUNT_ACCOUNTS, env, "kind")

    async def count_api_keys_by_status(self, env: str) -> dict[str, int]:
        return await self._counts(_COUNT_KEYS, env, "status")

    async def _counts(self, stmt: sa.TextClause, env: str, key: str) -> dict[str, int]:
        if env not in _ENVS:  # a typo'd env would silently count nothing
            raise ValueError("unknown env")
        async with self._relational.unit_of_work() as uow:  # read-only: no commit
            res = await uow.session.execute(stmt, {"env": env})
            return {str(r[key]): int(r["n"]) for r in res.mappings()}

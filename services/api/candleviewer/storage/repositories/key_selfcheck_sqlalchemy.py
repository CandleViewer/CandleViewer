"""Postgres adapter for `KeySelfCheckStore`, the stored-key self-check's port (E27-T03, #836).

Bound to one environment at construction: every statement filters on `env` (C-2.11), so the job
never reads or writes another environment's rows. Literal `sa.text` with bound parameters only.
No UPDATE sets an envelope column, `status` or `last_used_at`: no statement names an envelope
column or `last_used_at`, and only the targets read filters on `status` (the write-once and
single-writer guards in `tests/unit/credentials_m2/test_write_once_surface.py` scan this file).
A pass merges the verified key-info fields into `permission_snapshot` (`||`), so a field the
import stored and the check does not read stays, and `ak_snapshot_shape` still checks the
result, and clears `last_error_*`. A verdict or an inconclusive check writes `last_error_*` only.
More usable keys than one pass reads is an error, never a silently shorter list (the job then
fails closed). The disarm writes its rule code and time in its own conditional update (#836
slice 2d); the record's mark is bookkeeping, so it leaves `updated_at`, the accounts' If-Match
token, alone.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa

from candleviewer.storage.repositories.accounts import (
    AccountsStoreError,
    ExchangeAccountRow,
    PolicyDisarm,
    SelfCheckTargetRow,
    VerifiedKey,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_ENVS: Final = frozenset({"live", "demo", "testnet"})
#: Usable keys one pass reads: an account holds a handful (21 §3.2.2).
MAX_TARGETS: Final = 500

_TARGETS = sa.text(
    "SELECT k.id::text AS key_id, k.read_only AS read_only, "
    "k.permission_snapshot_at AS verified_at, k.last_error_code AS last_error_code, "
    "k.expires_at AS expires_at, "
    "ea.id::text AS id, ea.exchange::text AS exchange, ea.env::text AS env, "
    "ea.kind::text AS kind, ea.exchange_uid AS exchange_uid, "
    "ea.parent_account_id::text AS parent_account_id, ea.label AS label, "
    "ea.colour_token AS colour_token, ea.is_enabled AS is_enabled, "
    "ea.trading_enabled AS trading_enabled, ea.position_mode AS position_mode, "
    "ea.margin_mode AS margin_mode, ea.account_type AS account_type, ea.quote_ccy AS quote_ccy, "
    "ea.equity_cached_usd AS equity_cached_usd, ea.equity_cached_at AS equity_cached_at, "
    "ea.max_sub_accounts_hint AS max_sub_accounts_hint, "
    "ea.last_reconciled_at AS last_reconciled_at, ea.created_at AS created_at, "
    "ea.updated_at AS updated_at, ea.deleted_at AS deleted_at "
    "FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE ea.env::text = :env AND ea.deleted_at IS NULL AND k.revoked_at IS NULL "
    "AND k.status IN ('active', 'rotating') ORDER BY k.id LIMIT :cap"
)
_PASS = sa.text(
    "UPDATE api_keys AS k SET "
    "permission_snapshot = k.permission_snapshot || CAST(:snapshot AS jsonb), "
    "permission_snapshot_at = :at, can_trade = :can_trade, read_only = :read_only, "
    "ip_whitelist = CAST(:ips AS cidr[]), ip_whitelist_verified_at = :at, "
    "expires_at = :expires_at, last_error_code = NULL, last_error_at = NULL, updated_at = now() "
    "FROM exchange_accounts ea WHERE k.id = CAST(:id AS uuid) "
    "AND ea.id = k.exchange_account_id AND ea.env::text = :env AND k.revoked_at IS NULL"
)
_ERROR = sa.text(
    "UPDATE api_keys AS k SET last_error_code = :code, last_error_at = :at, updated_at = now() "
    "FROM exchange_accounts ea WHERE k.id = CAST(:id AS uuid) "
    "AND ea.id = k.exchange_account_id AND ea.env::text = :env AND k.revoked_at IS NULL"
)
_DISABLE = sa.text(
    "UPDATE exchange_accounts SET trading_enabled = false, "
    "policy_disarm_code = :code, policy_disarmed_at = :at, policy_disarm_audited_at = NULL, "
    "updated_at = now() "
    "WHERE id = CAST(:id AS uuid) AND env::text = :env AND deleted_at IS NULL AND trading_enabled"
)
_OWED = sa.text(
    "SELECT id::text AS account_id, policy_disarm_code AS code, policy_disarmed_at AS at "
    "FROM exchange_accounts WHERE env::text = :env AND policy_disarmed_at IS NOT NULL "
    "AND policy_disarm_audited_at IS NULL ORDER BY id LIMIT :cap"
)
_AUDITED = sa.text(
    "UPDATE exchange_accounts SET policy_disarm_audited_at = :at "
    "WHERE id = CAST(:id AS uuid) AND env::text = :env AND policy_disarmed_at = :disarmed_at "
    "AND policy_disarm_audited_at IS NULL"
)


def _target(m: Any) -> SelfCheckTargetRow:
    d = dict(m)
    key, read_only, verified_at = UUID(d.pop("key_id")), d.pop("read_only"), d.pop("verified_at")
    error, expires = d.pop("last_error_code"), d.pop("expires_at")
    d["id"] = UUID(d["id"])
    parent = d["parent_account_id"]
    d["parent_account_id"] = None if parent is None else UUID(parent)
    return SelfCheckTargetRow(key, read_only, verified_at, ExchangeAccountRow(**d), error, expires)


class SqlAlchemyKeySelfCheckStore:
    def __init__(self, relational: SqlAlchemyRelationalRepository, *, env: str) -> None:
        if env not in _ENVS:  # a misspelt environment would match no row and check nothing
            raise ValueError("unknown env")
        self._relational, self._env = relational, env

    async def targets(self) -> tuple[SelfCheckTargetRow, ...]:
        async with self._relational.unit_of_work() as uow:  # a read: nothing to commit
            res = await uow.session.execute(_TARGETS, {"env": self._env, "cap": MAX_TARGETS + 1})
            rows = tuple(_target(m) for m in res.mappings())
        if len(rows) > MAX_TARGETS:
            raise AccountsStoreError("more usable keys than one self-check pass reads")
        return rows

    async def _write(self, stmt: sa.TextClause, **params: object) -> bool:
        async with self._relational.unit_of_work() as uow:
            res: Any = await uow.session.execute(stmt, {**params, "env": self._env})
            await uow.commit()
        return bool(res.rowcount == 1)

    async def record_pass(self, key_id: UUID, verified: VerifiedKey) -> bool:
        return await self._write(
            _PASS,
            id=str(key_id),
            snapshot=json.dumps(verified.snapshot),
            at=verified.at,
            can_trade=verified.can_trade,
            read_only=verified.read_only,
            ips=list(verified.ip_whitelist),
            expires_at=verified.expires_at,
        )

    async def record_error(self, key_id: UUID, *, code: str, at: datetime) -> bool:
        return await self._write(_ERROR, id=str(key_id), code=code, at=at)

    async def disable_trading(self, account_id: UUID, *, code: str, at: datetime) -> bool:
        return await self._write(_DISABLE, id=str(account_id), code=code, at=at)

    async def owed_disarms(self) -> tuple[PolicyDisarm, ...]:
        async with self._relational.unit_of_work() as uow:  # a read: nothing to commit
            res = await uow.session.execute(_OWED, {"env": self._env, "cap": MAX_TARGETS})
            return tuple(
                PolicyDisarm(UUID(m["account_id"]), m["code"], m["at"]) for m in res.mappings()
            )

    async def mark_disarm_audited(self, disarm: PolicyDisarm, *, at: datetime) -> bool:
        return await self._write(_AUDITED, id=str(disarm.account_id), disarmed_at=disarm.at, at=at)

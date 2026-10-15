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
No hard DELETE exists. Mapped errors are raised `from None`: IntegrityError text carries P1
parameters (exchange_uid, label).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa

from candleviewer.storage.repositories.accounts import (
    AccountKey,
    AccountScope,
    AccountsPage,
    AccountsStoreScopeDeniedError,
    ExchangeAccountRow,
    GrantScope,
    OwnerScope,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_ENVS = frozenset({"live", "demo", "testnet"})
_KINDS = frozenset({"main", "sub"})
MAX_PAGE = 500

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

OWNER_STATEMENTS = frozenset({_GET_OWNER, _LIST_OWNER})
GRANT_STATEMENTS = frozenset({_GET_GRANT, _LIST_GRANT})


def _uuid(value: object) -> UUID:
    return UUID(str(value))


def _opt_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _account(m: Any) -> ExchangeAccountRow:
    d = dict(m)
    d["id"] = _uuid(d["id"])
    d["parent_account_id"] = _opt_uuid(d["parent_account_id"])
    return ExchangeAccountRow(**d)


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

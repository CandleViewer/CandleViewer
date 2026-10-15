"""`SqlAlchemyAdminCounts` — read-only Postgres counts for the admin read models (E42-T01).

Feeds `GET /admin/overview` (users, accounts and keys, open incidents) and `GET /admin/capacity`
(sub-accounts in use). It lives in M10 so M21 never imports a storage driver (ADR-0003); the
composition root adapts these results to the admin ports. Every statement is static,
parameterised, aggregate-only SQL: only counts leave this module, never a row, a name or key
material. The recorded sub-account tier needs the `settings` table, which no migration has
created yet (planned `0012_governance`, 21-database-schema.md 9.4), so it is not read here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_USERS = sa.text("""
    SELECT count(*) AS total,
           count(*) FILTER (WHERE u.status = 'active') AS active,
           count(*) FILTER (WHERE u.status = 'active' AND NOT EXISTS (
               SELECT 1 FROM mfa_methods m WHERE m.user_id = u.id
                 AND m.confirmed_at IS NOT NULL AND m.revoked_at IS NULL)) AS without_mfa
    FROM users u WHERE u.deleted_at IS NULL
    """)
_ACCOUNTS = sa.text("""
    SELECT count(*) AS total, count(*) FILTER (WHERE a.is_enabled) AS enabled,
           (SELECT count(*) FROM api_keys k JOIN exchange_accounts ka
              ON ka.id = k.exchange_account_id AND ka.deleted_at IS NULL
            WHERE k.status = 'active' AND k.revoked_at IS NULL
              AND k.expires_at < :expiring_before) AS keys_expiring,
           (SELECT count(*) FROM api_keys k JOIN exchange_accounts ka
              ON ka.id = k.exchange_account_id AND ka.deleted_at IS NULL
            WHERE k.status = 'invalid') AS keys_invalid
    FROM exchange_accounts a WHERE a.deleted_at IS NULL
    """)
_INCIDENTS = sa.text("""
    SELECT count(*) AS open FROM (
      SELECT DISTINCT component, kind FROM system_events
      WHERE resolved_at IS NULL AND severity IN ('error', 'critical')) AS incidents
    """)
_SUBACCOUNTS = sa.text("""
    SELECT coalesce(max(n), 0) AS used FROM (
      SELECT count(*) AS n FROM exchange_accounts
      WHERE kind = 'sub' AND env = 'live' AND deleted_at IS NULL
      GROUP BY parent_account_id) AS per_main
    """)


@dataclass(frozen=True, slots=True)
class UserTotals:
    total: int
    active: int
    #: Active users with no confirmed, unrevoked MFA method.
    without_mfa: int


@dataclass(frozen=True, slots=True)
class AccountTotals:
    total: int
    enabled: int
    #: Active keys whose `expires_at` falls before the caller's horizon.
    keys_expiring: int
    keys_invalid: int


class SqlAlchemyAdminCounts:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._rel = relational

    async def _row(self, stmt: sa.TextClause, params: dict[str, Any] | None = None) -> Any:
        async with self._rel.unit_of_work() as uow:  # read-only: no commit
            res: Any = await uow.session.execute(stmt, params or {})
            return res.mappings().first()

    async def user_totals(self) -> UserTotals:
        r = await self._row(_USERS)
        return UserTotals(int(r["total"]), int(r["active"]), int(r["without_mfa"]))

    async def account_totals(self, expiring_before: datetime) -> AccountTotals:
        r = await self._row(_ACCOUNTS, {"expiring_before": expiring_before})
        return AccountTotals(
            int(r["total"]), int(r["enabled"]), int(r["keys_expiring"]), int(r["keys_invalid"])
        )

    async def open_incidents(self) -> int:
        """Distinct (component, kind) of unresolved `error`/`critical` system events."""
        return int((await self._row(_INCIDENTS))["open"])

    async def subaccounts_in_use(self) -> int:
        """Most non-deleted live sub-accounts under any one main account: the cap binds live
        exchange UIDs, per main (C-2.11); demo and testnet sub-accounts never count."""
        return int((await self._row(_SUBACCOUNTS))["used"])

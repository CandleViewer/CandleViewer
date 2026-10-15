"""`SqlAlchemyAdminCounts` — read-only Postgres counts for the admin read models (E42-T01).

Feeds `GET /admin/overview` (users, accounts and keys, open incidents) and `GET /admin/capacity`
(sub-accounts in use). It lives in M10 so M21 never imports a storage driver (ADR-0003); the
composition root adapts these results to the admin ports. Every statement is static,
parameterised, aggregate-only SQL: only counts leave this module, never a row, a name or key
material. Account and key counts are scoped to the process environment bound at construction
(C-2.11: demo rows never show as live). Each read caps server work at 1 s
(`SET LOCAL statement_timeout`); the 300 ms slice budget is the client-side cancellation.
The recorded sub-account tier needs the `settings` table, which no migration has created yet
(planned `0012_governance`, 21-database-schema.md 9.4), so it is not read here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_TIMEOUT = sa.text("SET LOCAL statement_timeout = '1s'")
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
              ON ka.id = k.exchange_account_id AND ka.deleted_at IS NULL AND ka.env::text = :env
            WHERE k.status = 'active' AND k.revoked_at IS NULL
              AND k.expires_at < :expiring_before) AS keys_expiring,
           (SELECT count(*) FROM api_keys k JOIN exchange_accounts ka
              ON ka.id = k.exchange_account_id AND ka.deleted_at IS NULL AND ka.env::text = :env
            WHERE k.status = 'invalid') AS keys_invalid
    FROM exchange_accounts a WHERE a.deleted_at IS NULL AND a.env::text = :env
    """)
_INCIDENTS = sa.text("""
    SELECT count(*) AS open FROM (
      SELECT DISTINCT component, kind FROM system_events
      WHERE resolved_at IS NULL AND severity IN ('error', 'critical')) AS incidents
    """)
_SUBACCOUNTS = sa.text("""
    SELECT coalesce(max(n), 0) AS used FROM (
      SELECT count(*) AS n FROM exchange_accounts
      WHERE kind = 'sub' AND env::text = :env AND deleted_at IS NULL
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
    #: `active`, unrevoked keys on non-deleted accounts whose `expires_at` falls before the
    #: horizon, including keys already past it; `rotating` keys are not counted.
    keys_expiring: int
    keys_invalid: int


class SqlAlchemyAdminCounts:
    def __init__(self, relational: SqlAlchemyRelationalRepository, *, env: str) -> None:
        self._rel, self._env = relational, env

    async def _row(self, stmt: sa.TextClause, params: dict[str, Any] | None = None) -> Any:
        async with self._rel.unit_of_work() as uow:  # read-only: no commit
            await uow.session.execute(_TIMEOUT)
            res: Any = await uow.session.execute(stmt, params or {})
            return res.mappings().first()

    async def user_totals(self) -> UserTotals:
        r = await self._row(_USERS)
        return UserTotals(int(r["total"]), int(r["active"]), int(r["without_mfa"]))

    async def account_totals(self, expiring_before: datetime) -> AccountTotals:
        r = await self._row(_ACCOUNTS, {"expiring_before": expiring_before, "env": self._env})
        return AccountTotals(
            int(r["total"]), int(r["enabled"]), int(r["keys_expiring"]), int(r["keys_invalid"])
        )

    async def open_incidents(self) -> int:
        """Interim: distinct (component, kind) of unresolved `error`/`critical` system events.

        Process-local, not environment-scoped: `system_events` has no env column. To be aligned
        with E42-T05's incident grouping by (component, signature) when that read model lands.
        """
        return int((await self._row(_INCIDENTS))["open"])

    async def subaccounts_in_use(self) -> int:
        """Most non-deleted sub-accounts under any one main account in the bound environment:
        the exchange caps sub-accounts per main account UID (C-2.11)."""
        return int((await self._row(_SUBACCOUNTS, {"env": self._env}))["used"])

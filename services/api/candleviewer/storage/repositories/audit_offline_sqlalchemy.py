"""Read-only Postgres side of the offline audit-integrity check (E43-T10,
`candleviewer.admin.audit_chain_verify`).

Every session of its pool starts with `default_transaction_read_only = on` (in the startup
packet), so nothing the check runs can write, whatever role the connection string names. Chain
batches, the head and the checkpoints come from `SqlAlchemyAuditRepository`, the same bounded,
keyset reads the in-process verify uses; this module adds the two catalogue reads the grant model
needs. Tables are looked up by name in schema `public`, never through the `search_path`. A
database failure surfaces as `AuditReadFailed` with the SQLSTATE only (C-12.6).
"""

from __future__ import annotations

from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from candleviewer.storage.repositories.audit_sqlalchemy import (
    AuditReadFailed,
    SqlAlchemyAuditRepository,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    sqlstate_of,
)

_HELD: Final = sa.text(
    "SELECT r.rolname AS role, c.relname AS table_name, p.priv AS privilege, "
    "has_table_privilege(r.oid, c.oid, p.priv) AS held "
    "FROM pg_roles r CROSS JOIN pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public' "
    "CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(priv) "
    "WHERE r.rolname = ANY(CAST(:roles AS text[])) "
    "AND c.relname = ANY(CAST(:tables AS name[])) AND c.relkind = 'r' "
    "ORDER BY 1, 2, 3"
)
_TRIGGERS: Final = sa.text(
    "SELECT t.tgname AS name, c.relname AS table_name, t.tgenabled <> 'D' AS enabled "
    "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public' "
    "WHERE NOT t.tgisinternal AND c.relname = ANY(CAST(:tables AS name[])) ORDER BY 1"
)


class SqlAlchemyAuditOfflineReader:
    """One read-only pool for one run. `audit` serves the chain reads."""

    def __init__(self, dsn: str) -> None:
        self._relational = SqlAlchemyRelationalRepository(
            dsn, "audit-chain-verify", pool_size=1, max_overflow=0
        )
        sa.event.listen(self._relational.engine.sync_engine, "do_connect", _read_only)
        self.audit = SqlAlchemyAuditRepository(self._relational)

    async def held_privileges(
        self, roles: list[str], tables: list[str], privileges: list[str]
    ) -> dict[tuple[str, str], frozenset[str]]:
        """(role, table) -> privileges held; a role or table that does not exist has no key."""
        params = {"roles": roles, "tables": tables, "privileges": privileges}
        rows = await self._read(_HELD, params)
        held: dict[tuple[str, str], set[str]] = {}
        for row in rows:
            pair = held.setdefault((str(row["role"]), str(row["table_name"])), set())
            if row["held"]:
                pair.add(str(row["privilege"]))
        return {pair: frozenset(privs) for pair, privs in held.items()}

    async def triggers(self, tables: list[str]) -> dict[str, tuple[str, bool]]:
        """Trigger name -> (table, enabled) for the user triggers on `tables`."""
        rows = await self._read(_TRIGGERS, {"tables": tables})
        return {str(r["name"]): (str(r["table_name"]), bool(r["enabled"])) for r in rows}

    async def close(self) -> None:
        await self._relational.dispose()

    async def _read(self, statement: sa.TextClause, params: dict[str, Any]) -> list[Any]:
        state: str | None = None
        failed = False
        try:
            async with self._relational.unit_of_work() as uow:  # a read: nothing to commit
                rows = list((await uow.session.execute(statement, params)).mappings().all())
        except SQLAlchemyError as exc:
            failed, state = True, sqlstate_of(exc)
        if failed:
            raise AuditReadFailed(state)
        return rows


def _read_only(_dialect: Any, _record: Any, _cargs: Any, cparams: dict[str, Any]) -> None:
    """asyncpg's startup parameters: every transaction of the session is read-only."""
    settings = {**cparams.get("server_settings", {}), "default_transaction_read_only": "on"}
    cparams["server_settings"] = settings

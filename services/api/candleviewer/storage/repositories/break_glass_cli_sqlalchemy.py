"""`SqlAlchemyBreakGlassDatabase`: the offline break-glass CLI's whole Postgres side (E09-S11
#2119 slice 5, decision R2c); `SqlAlchemyBootstrapOwnerDatabase`, the bootstrap-Owner CLI's (#4479);
`SqlAlchemyAuditAckDatabase`, the audit-chain break acknowledgement CLI's (#2904: `audit_log` and
the read of an active Owner, no writer but the audit append); `SqlAlchemyAuditVerifyDatabase`, its
read-only sibling for the offline chain check (#1238: every session read-only, no writer at all).

One pool serves the CLI's stores (`audit_log`, `kek_versions` and the one-transaction reset
store) and the cv-api probe. Every session of the pool carries this run's `application_name`,
from the startup packet (so an idle one has it too) and again per transaction
(`unit_of_work()`), so `others_connected` tells the CLI's own sessions from any other session of
the database role: cv-api's pool, another run, a `psql`. Only the entry points
`candleviewer.breakglass`, `candleviewer.bootstrap_owner` (#4479 C2), `candleviewer.audit_ack_break`
and `candleviewer.audit_chain_verify` construct them, and nothing
cv-api serves imports this module (S8). Each CLI holds only its own writer (DC-4479-17): the
bootstrap run the Owner-invite mint (`bootstrap_owners`) instead of the reset store (`owners`).
`kcv` has no audit row builder, so it cannot enrol a KEK (decision O1). No I/O until a store is
used.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from candleviewer.domain.primitives import Environment
from candleviewer.storage.repositories.audit_sqlalchemy import (
    AuditReadFailed,
    SqlAlchemyAuditRepository,
)
from candleviewer.storage.repositories.auth_keys_sqlalchemy import SqlAlchemyAuthKeyRows
from candleviewer.storage.repositories.bootstrap_owner_sqlalchemy import (
    SqlAlchemyBootstrapOwnerRepository,
)
from candleviewer.storage.repositories.break_glass_sqlalchemy import (
    SqlAlchemyActiveOwners,
    SqlAlchemyBreakGlassRepository,
)
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    sqlstate_of,
)

#: R2c: client sessions of this login role other than the probe's own and the CLI's, which all
#: carry the run's `application_name`, idle ones too (it is in their startup packet).
_OTHER_SESSIONS = sa.text(
    "SELECT count(*) FROM pg_stat_activity WHERE usename = session_user "
    "AND backend_type = 'client backend' AND pid <> pg_backend_pid() "
    "AND application_name IS DISTINCT FROM :name"
)
_PING = sa.text("SELECT 1")
#: Bound on `reachable` (an unreachable host would hold the connect).
PING_TIMEOUT_S = 5.0


class _CliDatabase:
    """What every CLI run shares: its pool, named for the run, the journal's stores and the
    cv-api probe. `cli` is the name's prefix. `read_only` puts `default_transaction_read_only = on`
    in each session's startup packet: no statement of the run can write, whatever the login."""

    def __init__(self, dsn: str, cli: str, *, read_only: bool = False) -> None:
        suffix = f"{cli}:{os.urandom(4).hex()}"
        #: What every session of the pool reports; `unit_of_work()` sets it per transaction too.
        self.application_name = f"candleviewer:{suffix}"
        self._read_only = read_only
        self._relational = SqlAlchemyRelationalRepository(dsn, suffix)
        sa.event.listen(self._relational.engine.sync_engine, "do_connect", self._name_session)
        self.audit_log = SqlAlchemyAuditRepository(self._relational)
        self.kcv = SqlAlchemyCredentialStore(self._relational)

    def _name_session(
        self, _dialect: Any, _record: Any, _cargs: Any, cparams: dict[str, Any]
    ) -> None:
        """asyncpg's startup parameters, so the name holds before the first statement."""
        settings = {**cparams.get("server_settings", {}), "application_name": self.application_name}
        if self._read_only:
            settings["default_transaction_read_only"] = "on"
        cparams["server_settings"] = settings

    async def others_connected(self) -> bool:
        """R2c: whether another session of this database role is connected (cv-api running)."""
        async with self._relational.unit_of_work() as uow:
            name = {"name": self.application_name}
            others: int = (await uow.session.execute(_OTHER_SESSIONS, name)).scalar_one()
        return others > 0

    async def reachable(self) -> bool:
        """Whether Postgres answers within `PING_TIMEOUT_S`; any failure is False."""
        try:
            async with asyncio.timeout(PING_TIMEOUT_S), self._relational.unit_of_work() as uow:
                await uow.session.execute(_PING)
        except Exception:  # down, refused, timed out: no `audit_log` to write to
            return False
        return True

    async def dispose(self) -> None:
        await self._relational.dispose()


class SqlAlchemyBreakGlassDatabase(_CliDatabase):
    """The stores of one CLI run on one pool named for the run (`application_name`), with the
    read of the environment's auth keyring rows its live digest session opens (#2152 S6)."""

    def __init__(self, dsn: str, *, env: Environment) -> None:
        super().__init__(dsn, "breakglass")
        self.owners = SqlAlchemyBreakGlassRepository(self._relational)
        self.auth_keys = SqlAlchemyAuthKeyRows(self._relational, env=env)


class SqlAlchemyBootstrapOwnerDatabase(_CliDatabase):
    """A bootstrap-Owner run's stores: the mint, and no reset store (DC-4479-17)."""

    def __init__(self, dsn: str) -> None:
        super().__init__(dsn, "bootstrap")
        self.bootstrap_owners = SqlAlchemyBootstrapOwnerRepository(self._relational)


class SqlAlchemyAuditAckDatabase(_CliDatabase):
    """An acknowledgement run's stores (#2904): `audit_log` and the active-Owner read. It runs
    beside cv-api: the chain's append is serialised by its advisory lock."""

    def __init__(self, dsn: str) -> None:
        super().__init__(dsn, "audit-ack")
        self.owners = SqlAlchemyActiveOwners(self._relational)


#: (role, table, privilege, held) per named role, `public` table and privilege. Held: the role or
#: any role it is a member of (inherited or by `SET ROLE`) holds it on the table, through PUBLIC
#: too, or on any of its columns (column grants exist for SELECT, INSERT, UPDATE, REFERENCES only).
_HELD: Final = sa.text(
    "SELECT r.rolname AS role, c.relname AS table_name, p.priv AS privilege, "
    "EXISTS (SELECT 1 FROM pg_roles m WHERE pg_has_role(r.oid, m.oid, 'MEMBER') AND "
    "CASE WHEN p.priv = ANY(ARRAY['SELECT', 'INSERT', 'UPDATE', 'REFERENCES']) "
    "THEN has_any_column_privilege(m.oid, c.oid, p.priv) "
    "ELSE has_table_privilege(m.oid, c.oid, p.priv) END) AS held "
    "FROM pg_roles r CROSS JOIN pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public' "
    "CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(priv) "
    "WHERE r.rolname = ANY(CAST(:roles AS text[])) "
    "AND c.relname = ANY(CAST(:tables AS name[])) AND c.relkind = 'r' ORDER BY 1, 2, 3"
)
#: A trigger fires for an ordinary session only in state 'O' (origin) or 'A' (always): 'D' never
#: fires and 'R' only under `session_replication_role = replica`.
_TRIGGERS: Final = sa.text(
    "SELECT t.tgname AS name, c.relname AS table_name, t.tgenabled IN ('O', 'A') AS enabled "
    "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public' "
    "WHERE NOT t.tgisinternal AND c.relname = ANY(CAST(:tables AS name[])) ORDER BY 1"
)


class SqlAlchemyAuditVerifyDatabase(_CliDatabase):
    """An offline chain check's stores (#1238): `audit_log` with the in-app verify reads and their
    budgets, and two catalogue reads, all on read-only sessions; tables in schema `public`, never
    via `search_path`. A failed catalogue read raises `AuditReadFailed`, SQLSTATE only (C-12.6)."""

    def __init__(self, dsn: str, *, statement_timeout_ms: int, max_entry_bytes: int) -> None:
        super().__init__(dsn, "audit-verify", read_only=True)
        self.audit_log = SqlAlchemyAuditRepository(
            self._relational,
            verify_read_timeout_ms=statement_timeout_ms,
            verify_max_entry_bytes=max_entry_bytes,
        )

    async def held_privileges(
        self, roles: list[str], tables: list[str], privileges: list[str]
    ) -> dict[tuple[str, str], frozenset[str]]:
        """(role, table) -> the privileges held; a role or table that does not exist has no key."""
        params = {"roles": roles, "tables": tables, "privileges": privileges}
        held: dict[tuple[str, str], set[str]] = {}
        for row in await self._read(_HELD, params):
            pair = held.setdefault((str(row["role"]), str(row["table_name"])), set())
            if row["held"]:
                pair.add(str(row["privilege"]))
        return {pair: frozenset(privileges) for pair, privileges in held.items()}

    async def triggers(self, tables: list[str]) -> dict[str, tuple[str, bool]]:
        """User trigger on `tables` -> (its table, whether it fires for an ordinary session)."""
        rows = await self._read(_TRIGGERS, {"tables": tables})
        return {str(r["name"]): (str(r["table_name"]), r["enabled"] is True) for r in rows}

    async def _read(self, statement: sa.TextClause, params: dict[str, Any]) -> list[Any]:
        state: str | None = None
        try:
            async with self._relational.unit_of_work() as uow:
                return list((await uow.session.execute(statement, params)).mappings().all())
        except SQLAlchemyError as exc:
            state = sqlstate_of(exc)
        raise AuditReadFailed(state)  # outside the handler: no driver text in its context

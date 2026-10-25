"""`SqlAlchemyBreakGlassDatabase`: the offline break-glass CLI's whole Postgres side (E09-S11
#2119 slice 5, decision R2c); `SqlAlchemyBootstrapOwnerDatabase`, the bootstrap-Owner CLI's (#4479).

One pool serves the CLI's stores (`audit_log`, `kek_versions` and the one-transaction reset
store) and the cv-api probe. Every session of the pool carries this run's `application_name`,
from the startup packet (so an idle one has it too) and again per transaction
(`unit_of_work()`), so `others_connected` tells the CLI's own sessions from any other session of
the database role: cv-api's pool, another run, a `psql`. Only the entry points
`candleviewer.breakglass` and `candleviewer.bootstrap_owner` (#4479 C2) construct them, and nothing
cv-api serves imports this module (S8). Each CLI holds only its own writer (DC-4479-17): the
bootstrap run the Owner-invite mint (`bootstrap_owners`) instead of the reset store (`owners`).
`kcv` has no audit row builder, so it cannot enrol a KEK (decision O1). No I/O until a store is
used.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.bootstrap_owner_sqlalchemy import (
    SqlAlchemyBootstrapOwnerRepository,
)
from candleviewer.storage.repositories.break_glass_sqlalchemy import (
    SqlAlchemyBreakGlassRepository,
)
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
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
    cv-api probe. `cli` is the name's prefix."""

    def __init__(self, dsn: str, cli: str) -> None:
        suffix = f"{cli}:{os.urandom(4).hex()}"
        #: What every session of the pool reports; `unit_of_work()` sets it per transaction too.
        self.application_name = f"candleviewer:{suffix}"
        self._relational = SqlAlchemyRelationalRepository(dsn, suffix)
        sa.event.listen(self._relational.engine.sync_engine, "do_connect", self._name_session)
        self.audit_log = SqlAlchemyAuditRepository(self._relational)
        self.kcv = SqlAlchemyCredentialStore(self._relational)

    def _name_session(
        self, _dialect: Any, _record: Any, _cargs: Any, cparams: dict[str, Any]
    ) -> None:
        """asyncpg's startup parameters, so the name holds before the first statement."""
        settings = {**cparams.get("server_settings", {}), "application_name": self.application_name}
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
    """The stores of one CLI run on one pool named for the run (`application_name`)."""

    def __init__(self, dsn: str) -> None:
        super().__init__(dsn, "breakglass")
        self.owners = SqlAlchemyBreakGlassRepository(self._relational)


class SqlAlchemyBootstrapOwnerDatabase(_CliDatabase):
    """A bootstrap-Owner run's stores: the mint, and no reset store (DC-4479-17)."""

    def __init__(self, dsn: str) -> None:
        super().__init__(dsn, "bootstrap")
        self.bootstrap_owners = SqlAlchemyBootstrapOwnerRepository(self._relational)

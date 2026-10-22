"""The `real` backend's tier clients for `StorageService.start()` (#3874).

Wiring only: the clients are E07-T02's `SqlAlchemyRelationalRepository`, E07-T03's
`QuestDbMarketDataRepository` (the ILP writer from `build_hot_tier_writer` plus one `LazyPgWire`,
`storage`) and E07-T04's `ParquetColdTierRepository`, built from `Settings`. Building one opens no
connection: each client connects on first use, so `StorageService` decides when the network is
first touched (its start probes). A `RealTier` pairs a tier with its probe, which raises when the
tier cannot answer, and its close, which is told how long it may take. The tiers come in start
order (postgres, questdb, cold) and are closed in reverse. Credentials stay inside the clients:
nothing here formats or logs a DSN or a password, and the probes' own errors carry neither
(C-12.6). The guarded-privilege read (#3998) runs on the relational client's connection, the role
the app logs in as.

The questdb probe checks both of QuestDB's ports the tier uses: PG-wire answers `SELECT 1`, and the
ILP port accepts a connection (nothing is sent); an ILP failure is `QuestDbIlpUnreachable`, so a
probe's detail tells the two apart. The probe queues on the `storage` wire's lock like any read, so
a read longer than the probe's bound (a cold export, say) shows the tier `degraded` for that
round. The cold tier's export source reads through that same wire; nothing calls
`StorageService.cold` on a hot path today (the recorder's roll-off and retention have their own
wires, `rolloff` and `retention`).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

import structlog
from sqlalchemy import text

from candleviewer.settings import QUESTDB_PG_DEFAULT_PORT, Settings
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.parquet_repository import ParquetColdTierRepository
from candleviewer.storage.cold.questdb_source import QuestDbHotTierSource
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.guarded_privileges import PrivilegeReport
from candleviewer.storage.models import StorageTier
from candleviewer.storage.questdb.reader import QuestDbReader
from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from candleviewer.storage.questdb.wiring import LazyPgWire, TcpIlpTransport, build_hot_tier_writer
from candleviewer.storage.repositories import (
    ColdTierRepository,
    MarketDataRepository,
    RelationalRepository,
)
from candleviewer.storage.repositories.guarded_privileges_sqlalchemy import (
    SqlAlchemyGuardedPrivileges,
)
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

#: QuestDB's line-protocol port, for a `questdb_ilp` `host[:port]` that omits it.
QUESTDB_ILP_DEFAULT_PORT: Final = 9009
#: Bound on closing the `storage` wire's connection (then it is terminated), reserved at the end of
#: the questdb close's budget: the drain stops this much short of it.
WIRE_CLOSE_S: Final = 1.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class QuestDbIlpUnreachable(ConnectionError):
    """The questdb probe's connection to the ILP port was refused or timed out."""


@dataclass(frozen=True, slots=True)
class RealTier:
    """One tier as `StorageService` drives it: `probe` raises when the tier cannot answer;
    `close(budget_s)` releases its client within `budget_s`. The service also bounds both."""

    tier: StorageTier
    probe: Callable[[], Awaitable[None]]
    close: Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RealTiers:
    """The three repositories `StorageService` serves, and their tiers in start order."""

    market_data: MarketDataRepository
    relational: RelationalRepository
    cold: ColdTierRepository
    tiers: tuple[RealTier, ...]
    #: Reads the runtime role's guarded privileges (#3998), which `StorageService.start()` checks
    #: once the tiers answer. `build_real_tiers` always sets it; a test's tiers may leave it out.
    guarded_privileges: Callable[[], Awaitable[PrivilegeReport]] | None = None


def build_real_tiers(settings: Settings) -> RealTiers:
    """The E07 clients for `settings`, unconnected (no I/O)."""
    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "storage")
    pg_host, _, pg_port = settings.questdb_pg.partition(":")
    pgwire = LazyPgWire(
        pg_host,
        int(pg_port or QUESTDB_PG_DEFAULT_PORT),
        settings.questdb_pg_user,
        settings.questdb_pg_password.get_secret_value(),
        name="storage",
        close_timeout_s=WIRE_CLOSE_S,
    )
    ilp_host, _, ilp_port_text = settings.questdb_ilp.partition(":")
    ilp_port = int(ilp_port_text or QUESTDB_ILP_DEFAULT_PORT)
    writer = build_hot_tier_writer(TcpIlpTransport(ilp_host, ilp_port), ALL_SCHEMAS, pgwire)
    cold_root = Path(settings.parquet_root)

    async def probe_postgres() -> None:
        async with relational.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def probe_questdb() -> None:
        if not await pgwire.fetch("SELECT 1"):
            raise ConnectionError("questdb answered SELECT 1 with no row")
        ilp = TcpIlpTransport(ilp_host, ilp_port)  # its own socket: the writer's stays lazy
        try:
            await ilp.connect()
        except Exception:  # its message names the host and port: only the type is reported
            raise QuestDbIlpUnreachable("questdb ILP port unreachable") from None
        finally:
            await ilp.close()

    async def probe_cold() -> None:
        await asyncio.to_thread(_require_writable_dir, cold_root)

    async def close_postgres(_budget_s: float) -> None:
        await relational.dispose()

    async def close_questdb(budget_s: float) -> None:
        try:
            # Drains rows a caller still buffers; on its own bound the writer logs how many it
            # kept (`questdb_ilp_drain_failed`) and raises StorageTierUnavailable.
            await writer.stop(timeout_s=max(0.0, budget_s - WIRE_CLOSE_S))
        except StorageTierUnavailable:
            raise
        except BaseException:  # cut before the writer's own bound: say what it still held
            if buffered := writer.total_buffered:
                _log().error("storage_questdb_drain_cut", buffered=buffered)
            raise
        finally:
            # Bounded even after a cancellation: the wire's lock may be held by a read.
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(WIRE_CLOSE_S):
                    await pgwire.close()  # within WIRE_CLOSE_S itself, then terminated

    async def close_cold(_budget_s: float) -> None:
        """Nothing to release: each cold query opens and closes its own DuckDB connection."""

    return RealTiers(
        market_data=QuestDbMarketDataRepository(writer, QuestDbReader(pgwire)),
        # E07-T02's `unit_of_work()` returns a deferred context manager whose `__aenter__` gives
        # the full `UnitOfWork`: the Protocol's documented use (`async with`) holds, its static
        # shape (no `commit` on the factory's result) does not.
        relational=cast(RelationalRepository, relational),
        cold=ParquetColdTierRepository(DatasetRegistry(cold_root), QuestDbHotTierSource(pgwire)),
        tiers=(
            RealTier("postgres", probe_postgres, close_postgres),
            RealTier("questdb", probe_questdb, close_questdb),
            RealTier("cold", probe_cold, close_cold),
        ),
        guarded_privileges=SqlAlchemyGuardedPrivileges(relational).held,
    )


def _require_writable_dir(path: Path) -> None:
    """The cold root must already exist and be writable; the probe creates nothing."""
    if not path.is_dir():
        raise NotADirectoryError("the cold-tier root is not a directory")
    if not os.access(path, os.W_OK | os.X_OK):
        raise PermissionError("the cold-tier root is not writable")

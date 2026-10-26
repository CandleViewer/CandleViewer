"""Composition-root wiring (not a module) for the account profiles (E28-T02, #906 slice D1a).

It builds the process's one profile store over Postgres (`SqlAlchemyAccountProfileStore`, a pool of
its own), the order path's effective-profile cache over it (`EffectiveProfiles`) and the domain
facade over both (`ProfilesRepository`): every profile route reads and writes through the facade,
and each write invalidates the very cache the order path reads (SR-E28-15). The two E28-T01
counters go to their owners here. The fake backend (dev, CI) has no store: `None`, and the profile
routes answer `503 store_unavailable`. Nothing here does I/O; `main._lifespan` calls `dispose`.
Given the process's bus, the facade announces each committed write on it (`BusProfileChanges`,
#906 D3a; 24 Sec.9.2). The writes' stores share that pool: the accounts the writes resolve and the
armed rules a delete names (#906 D2-m); `profile_writes` builds the routes' `ProfileWrites` over
them, with this environment's catalogue (C-2.11).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol
from uuid import UUID

from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.accounts.profile_repository import ArmedRules, ProfilesRepository
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.api.profile_writes import ProfileWrites
from candleviewer.bus import Topic
from candleviewer.domain.primitives import Environment
from candleviewer.instrument_limits_wiring import CatalogueLimits
from candleviewer.rules_store_pg import PostgresArmedRules
from candleviewer.storage.repositories.account_profiles_sqlalchemy import (
    SqlAlchemyAccountProfileStore,
)
from candleviewer.storage.repositories.accounts_sqlalchemy import SqlAlchemyAccountsStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

if TYPE_CHECKING:
    from candleviewer.accounts.profile_changes import ProfilesChanged
    from candleviewer.accounts.profile_validator import SizingWarningsPort
    from candleviewer.bus import Bus
    from candleviewer.ingestion.service import IngestionService
    from candleviewer.observability.metrics import Metrics
    from candleviewer.settings import Settings

__all__ = ["DISPOSE_S", "BusProfileChanges", "ProfilesWiring", "profile_writes", "wire_profiles"]

#: The shutdown's wait, as `key_import_wiring.DRAIN_S`: the container's stop budget (#2565).
DISPOSE_S: Final = 5.0


@dataclass(frozen=True, slots=True)
class ProfilesWiring:
    repository: ProfilesRepository
    effective: EffectiveProfiles  # E28-T04's guard reads this one instance
    release: Callable[[], Awaitable[None]]
    accounts: AccountsRepository  # the writes' account resolution, over the same pool
    rules: ArmedRules  # a delete's armed-rule blockers (ruling B6), over the same pool
    dispose_s: float = DISPOSE_S

    async def dispose(self) -> None:
        """Cancel the cache's loads, then dispose of the pool, within `dispose_s` (a TimeoutError
        is the teardown's to log)."""
        async with asyncio.timeout(self.dispose_s):
            await self.effective.aclose()
            await self.release()


class BusProfileChanges:
    """`ProfileChanges` over the in-process bus (M5): each change on
    `{env}.profiles.{account_id}.changed`, one at a time, so this adapter is those topics' one
    producer (the bus orders a topic for a single producer)."""

    def __init__(self, bus: Bus, environment: str) -> None:
        self._bus = bus
        self._environment = environment
        self._lock = asyncio.Lock()

    def topic(self, account_id: UUID) -> Topic:
        """The account's id in the segment where a market topic carries its symbol (20 Sec.3)."""
        return Topic(
            env=self._environment, domain="profiles", symbol=str(account_id), detail="changed"
        )

    async def changed(self, event: ProfilesChanged) -> None:
        async with self._lock:
            await self._bus.publish(self.topic(event.exchange_account_id), event)


def wire_profiles(
    settings: Settings, metrics: Metrics, bus: Bus | None = None
) -> ProfilesWiring | None:
    """The profile store, its cache and the facade over both, with the T01 counters taken from
    `metrics` (the catalogue's live entries) and, given `bus`, the facade's announcements on it
    under the process's environment; `None` on the fake backend."""
    if settings.storage_backend != "real":
        return None
    relational = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "profiles")
    store = SqlAlchemyAccountProfileStore(relational)
    effective = EffectiveProfiles(store, lookups=metrics.get("cv_profile_cache_lookups_total"))
    bumps = metrics.get("cv_profile_version_bumps_total")
    changes = None if bus is None else BusProfileChanges(bus, settings.environment.value)
    repository = ProfilesRepository(store, cache=effective, version_bumps=bumps, changes=changes)
    return ProfilesWiring(
        repository=repository,
        effective=effective,
        release=relational.dispose,
        accounts=AccountsRepository(SqlAlchemyAccountsStore(relational)),
        rules=PostgresArmedRules(relational),
    )


class _Context(Protocol):
    """What `profile_writes` reads of `app.AppContext`."""

    @property
    def settings(self) -> Settings: ...

    @property
    def ingestion(self) -> IngestionService: ...


def profile_writes(
    wiring: ProfilesWiring | None, ctx: _Context, *, warnings: SizingWarningsPort | None = None
) -> ProfileWrites | None:
    """The writes' stores (#906 D2-m): the reads' facade, so one cache (SR-E28-15), the wiring's
    accounts and armed rules, and the catalogue of the process's environment, read per call as
    it is attached late (C-2.11); `None` with no wiring (the fake backend: 503)."""
    if wiring is None:
        return None
    env: Environment = ctx.settings.environment.value
    limits = CatalogueLimits(env, lambda: ctx.ingestion.instruments)
    return ProfileWrites(
        wiring.repository, wiring.accounts, limits, wiring.rules, env, warnings=warnings
    )

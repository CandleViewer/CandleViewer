"""Composition-root wiring (not a module) for the account profiles (E28-T02, #906 slice D1a).

It builds the process's one profile store over Postgres (`SqlAlchemyAccountProfileStore`, a pool of
its own), the order path's effective-profile cache over it (`EffectiveProfiles`) and the domain
facade over both (`ProfilesRepository`): every profile route reads and writes through the facade,
and each write invalidates the very cache the order path reads (SR-E28-15). The two E28-T01
counters go to their owners here. The fake backend (dev, CI) has no store: `None`, and the profile
routes answer `503 store_unavailable`. Nothing here does I/O; `main._lifespan` calls `dispose`.
Given the process's bus, the facade announces each committed write on it (`BusProfileChanges`,
#906 D3a; 24 Sec.9.2).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID

from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.accounts.profile_repository import ProfilesRepository
from candleviewer.bus import Topic
from candleviewer.storage.repositories.account_profiles_sqlalchemy import (
    SqlAlchemyAccountProfileStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

if TYPE_CHECKING:
    from candleviewer.accounts.profile_changes import ProfilesChanged
    from candleviewer.bus import Bus
    from candleviewer.observability.metrics import Metrics
    from candleviewer.settings import Settings

__all__ = ["DISPOSE_S", "BusProfileChanges", "ProfilesWiring", "wire_profiles"]

#: The shutdown's wait, as `key_import_wiring.DRAIN_S`: the container's stop budget (#2565).
DISPOSE_S: Final = 5.0


@dataclass(frozen=True, slots=True)
class ProfilesWiring:
    repository: ProfilesRepository
    effective: EffectiveProfiles  # E28-T04's guard reads this one instance
    release: Callable[[], Awaitable[None]]
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
    return ProfilesWiring(repository, effective, relational.dispose)

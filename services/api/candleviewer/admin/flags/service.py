"""Feature-flag service, read path (E42-T03, module M21): cached server-side resolution.

Reads come from one cached snapshot of the store. A kill-switch-class flag is served from it for
at most 5 s and every other flag for at most 30 s (`21-database-schema.md` 3.9), so a value
changed directly in the database is reflected within 5 s without a restart. When the store cannot
be read, flags resolve to their restrictive value (fail closed), and the store is retried after
1 s rather than on every request. Resolution itself is the pure `resolve`; this class only feeds
it and counts evaluations.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import structlog

from candleviewer.admin.flags.metrics import flag_evaluations_total
from candleviewer.admin.flags.registry import FlagRegistry, FlagSpec, FlagValue, Visibility
from candleviewer.admin.flags.resolver import StoredFlag, resolve
from candleviewer.admin.flags.store import FlagStore, StoreUnavailableError

TTL_S: Final = 30.0
KILLSWITCH_TTL_S: Final = 5.0
RETRY_S: Final = 1.0


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


@dataclass(frozen=True, slots=True)
class ResolvedFlag:
    spec: FlagSpec
    value: FlagValue
    #: `None` while the store cannot be read (the value is then the restrictive one).
    stored: StoredFlag | None


class FlagService:
    def __init__(
        self,
        registry: FlagRegistry,
        store: FlagStore,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registry, self.store, self._clock = registry, store, clock
        self._snapshot: Mapping[str, StoredFlag] | None = None
        self._loaded_at = float("-inf")
        self._retry_at = float("-inf")

    async def start(self) -> None:
        """Log the registry and give every flag a stored row; the registry itself was already
        validated when it was built, so an unsafe definition never gets this far."""
        self.registry.log_startup()
        await self.store.ensure(self.registry.values())

    def invalidate(self) -> None:
        """Drop the snapshot; the next read reloads (after a write)."""
        self._snapshot = None
        self._loaded_at = float("-inf")

    async def stored(self, spec: FlagSpec) -> StoredFlag | None:
        """The stored row for `spec`, or `None` while the store cannot be read (fail closed)."""
        now = self._clock()
        ttl = KILLSWITCH_TTL_S if spec.is_killswitch else TTL_S
        if self._snapshot is None or now - self._loaded_at >= ttl:
            if now < self._retry_at:
                return None
            try:
                self._snapshot, self._loaded_at = await self.store.load(), now
            except StoreUnavailableError:
                self._snapshot, self._retry_at = None, now + RETRY_S
                logger().warning("feature_flag_store_unavailable", key=spec.key)
                return None
        return self._snapshot.get(spec.key) or StoredFlag(spec.default)

    async def value(
        self, key: str, *, user_id: UUID | None = None, roles: frozenset[str] = frozenset()
    ) -> FlagValue:
        """One flag resolved server-side; `user_id=None` is a system read (order gate, push)."""
        spec = self.registry[key]
        flag_evaluations_total.labels(key).inc()
        return resolve(spec, await self.stored(spec), user_id=user_id, roles=roles)

    async def visible(self, user_id: UUID, roles: frozenset[str]) -> list[ResolvedFlag]:
        """Every flag the caller's role may see, resolved for the caller; owner-only flags never
        reach a manager or viewer."""
        out: list[ResolvedFlag] = []
        for spec in self.registry.values():
            if spec.visibility is Visibility.OWNER_ONLY and "owner" not in roles:
                continue
            stored = await self.stored(spec)
            flag_evaluations_total.labels(spec.key).inc()
            value = resolve(spec, stored, user_id=user_id, roles=roles)
            out.append(ResolvedFlag(spec, value, stored))
        return out

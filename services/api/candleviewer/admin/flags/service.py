"""Feature-flag service, read path (E42-T03, module M21): cached server-side resolution.

Reads come from one cached snapshot of the store. A kill-switch-class flag is served from it for
at most 5 s and every other flag for at most 30 s (`21-database-schema.md` 3.9), so a value
changed directly in the database is reflected within 5 s without a restart. A load is bounded
by `store_timeout_s`; a store that times out or raises resolves every flag to its restrictive
value (fail closed) and is retried after 1 s rather than on every request. Reloads are
single-flight, and a load that started before `invalidate()` is dropped rather than installed.
Resolution itself is the pure `resolve`; this class only feeds it and counts evaluations.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import structlog

from candleviewer.admin.flags.metrics import flag_evaluations_total
from candleviewer.admin.flags.registry import FlagRegistry, FlagSpec, FlagValue, Visibility
from candleviewer.admin.flags.resolver import StoredFlag, resolve
from candleviewer.admin.flags.store import FlagStore
from candleviewer.observability import spawn

TTL_S: Final = 30.0
KILLSWITCH_TTL_S: Final = 5.0
RETRY_S: Final = 1.0
STORE_TIMEOUT_S: Final = 0.5


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
        store_timeout_s: float = STORE_TIMEOUT_S,
    ) -> None:
        self.registry, self.store, self._clock = registry, store, clock
        self._timeout = store_timeout_s
        self._snapshot: Mapping[str, StoredFlag] | None = None
        self._loaded_at = float("-inf")
        self._retry_at = float("-inf")
        self._generation = 0
        self._inflight: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Log the registry and give every flag a stored row; the registry itself was already
        validated when it was built, so an unsafe definition never gets this far."""
        self.registry.log_startup()
        await self.store.ensure(self.registry.values())

    def invalidate(self) -> None:
        """Drop the snapshot; the next read reloads, and an in-flight load is not installed."""
        self._generation += 1
        self._snapshot = None
        self._loaded_at = float("-inf")

    async def stored(self, spec: FlagSpec, *, fresh: bool = False) -> StoredFlag | None:
        """The stored row for `spec`, or `None` while the store cannot be read (fail closed).
        `fresh` forces a reload (the maintenance poll), still single-flight."""
        if fresh:
            self.invalidate()
        ttl = KILLSWITCH_TTL_S if spec.is_killswitch else TTL_S
        for _ in range(2):  # a load overtaken by invalidate() is dropped, then retried once
            snapshot = self._snapshot
            if snapshot is not None and self._clock() - self._loaded_at < ttl:
                return snapshot.get(spec.key) or StoredFlag(spec.default)
            if self._clock() < self._retry_at:
                return None
            await self._reload()
        return None

    async def _reload(self) -> None:
        task = self._inflight
        if task is None or task.done():
            task = spawn(self._load(self._generation), name="feature-flag-load")
            self._inflight = task
        await asyncio.shield(task)

    async def _load(self, generation: int) -> None:
        started = self._clock()
        try:
            async with asyncio.timeout(self._timeout):
                snapshot = await self.store.load()
        except Exception as exc:  # timeout or store failure (CancelledError is not an Exception)
            self._snapshot, self._retry_at = None, started + RETRY_S
            logger().warning("feature_flag_store_unavailable", error=type(exc).__name__)
            return
        if generation == self._generation:
            self._snapshot, self._loaded_at = snapshot, started

    async def value(
        self,
        key: str,
        *,
        user_id: UUID | None = None,
        roles: frozenset[str] = frozenset(),
        fresh: bool = False,
    ) -> FlagValue:
        """One flag resolved server-side; `user_id=None` is a system read (order gate, push).
        Audience-unfiltered: only `visible()` applies the role audience, so a caller that serves
        a user must use `visible()` (or check `FlagSpec.audience`) before revealing a value."""
        spec = self.registry[key]
        flag_evaluations_total.labels(key).inc()
        return resolve(spec, await self.stored(spec, fresh=fresh), user_id=user_id, roles=roles)

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

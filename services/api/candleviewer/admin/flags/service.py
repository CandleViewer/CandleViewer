"""Feature-flag service, read path (E42-T03, module M21): cached server-side resolution.

Reads come from one cached snapshot of the store. A kill-switch-class flag is served from it for
at most 5 s and every other flag for at most 30 s (`21-database-schema.md` 3.9), so a value
changed directly in the database is reflected within 5 s without a restart; `trading.live_enabled`
is not kill-switch-class, so the 30 s cache applies to it. A load is bounded by the read budget,
the system setting `flags.read_budget_ms` (default 500 ms, 50-2000 ms, refused at startup
outside that). A store that fails or exceeds the budget is an outage (D1a): every flag resolves
to its fail-closed value, the list answers `resolution: fail_closed`, and the store is retried
after 1 s rather than on every request. One unreadable row (D1b) is not an outage: that flag
alone fails closed and is marked `unreadable`, and an unreadable override row on a non-safety
flag is ignored and counted. Reloads are single-flight, and a load that started before
`invalidate()` is dropped rather than installed. Resolution itself is the pure `resolve`.
"""

from __future__ import annotations

import asyncio
import enum
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import structlog

from candleviewer.admin.flags.metrics import flag_evaluations_total, unreadable_overrides_total
from candleviewer.admin.flags.registry import FlagRegistry, FlagSpec, FlagValue, value_matches
from candleviewer.admin.flags.resolver import StoredFlag, override_matches, resolve
from candleviewer.admin.flags.store import FlagStore
from candleviewer.observability import spawn

TTL_S: Final = 30.0
KILLSWITCH_TTL_S: Final = 5.0
RETRY_S: Final = 1.0
#: The system setting that holds the store's read budget, its default and its bounds (D1b).
READ_BUDGET_SETTING: Final = "flags.read_budget_ms"
DEFAULT_READ_BUDGET_MS: Final = 500
READ_BUDGET_BOUNDS_MS: Final = (50, 2000)


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


class Resolution(enum.StrEnum):
    """How a list resolved (`FeatureFlagResolution`, D1a)."""

    STORED = "stored"
    FAIL_CLOSED = "fail_closed"


@dataclass(frozen=True, slots=True)
class ResolvedFlag:
    spec: FlagSpec
    value: FlagValue
    #: `None` while the store cannot be read (the value is then the fail-closed one).
    stored: StoredFlag | None

    @property
    def unreadable(self) -> bool:
        """This flag's stored row is unreadable (D1b): it alone fails closed and stays writable."""
        return self.stored is not None and not value_matches(self.spec, self.stored.value)

    def members(self) -> dict[str, object]:
        """The `FeatureFlag` members the API sends. A store outage omits `default_value`,
        `overrides`, `updated_at` and `updated_by` (D1a); an unreadable row omits
        `default_value` and `updated_by` and keeps `updated_at` for the repairing write (D1b)."""
        spec, row = self.spec, self.stored
        out: dict[str, object] = {"key": spec.key, "kind": spec.kind.value}
        out |= {"description": spec.description, "value": self.value}
        if row is None:
            return out
        if not self.unreadable:
            out |= {"default_value": row.value, "updated_by": row.updated_by}
        out["overrides"] = [{"user_id": u, "value": v} for u, v in row.user_overrides.items()]
        if row.updated_at is not None:
            out["updated_at"] = row.updated_at
        return out | ({"unreadable": True} if self.unreadable else {})


@dataclass(frozen=True, slots=True)
class FlagList:
    resolution: Resolution
    items: tuple[ResolvedFlag, ...]


class FlagService:
    def __init__(
        self,
        registry: FlagRegistry,
        store: FlagStore,
        *,
        clock: Callable[[], float] = time.monotonic,
        read_budget_ms: int = DEFAULT_READ_BUDGET_MS,
    ) -> None:
        low, high = READ_BUDGET_BOUNDS_MS
        if isinstance(read_budget_ms, bool) or not low <= read_budget_ms <= high:
            raise ValueError(
                f"{READ_BUDGET_SETTING} must be {low}-{high} ms, not {read_budget_ms!r}"
            )
        self.registry, self.store, self._clock = registry, store, clock
        self._timeout = read_budget_ms / 1000
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

    async def stored(self, spec: FlagSpec) -> StoredFlag | None:
        """The stored row for `spec`, or `None` while the store cannot be read (fail closed)."""
        rows = await self._rows(KILLSWITCH_TTL_S if spec.is_killswitch else TTL_S)
        return None if rows is None else rows.get(spec.key) or StoredFlag(spec.default)

    async def _rows(self, ttl: float) -> Mapping[str, StoredFlag] | None:
        # Check, load, check, load, check: a load overtaken by invalidate() is dropped and the
        # read retries once; overtaken again, it fails closed rather than loop.
        for attempt in range(3):
            snapshot = self._snapshot
            if snapshot is not None and self._clock() - self._loaded_at < ttl:
                return snapshot
            if attempt == 2 or self._clock() < self._retry_at:
                break
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
            self._snapshot, self._retry_at = None, self._clock() + RETRY_S
            logger().warning("feature_flag_store_unavailable", error=type(exc).__name__)
            return
        if generation == self._generation:
            self._snapshot, self._loaded_at = snapshot, started

    async def value(
        self, key: str, *, user_id: UUID | None = None, roles: frozenset[str] = frozenset()
    ) -> FlagValue:
        """One flag resolved server-side; `user_id=None` is a system read (order gate, push).
        Visibility-unfiltered: only `visible()` applies it, so a caller that serves a user must
        use `visible()` (or check `FlagSpec.visible_to`) before revealing a value."""
        spec = self.registry[key]
        return self.resolved(spec, await self.stored(spec), user_id, roles).value

    async def visible(self, user_id: UUID, roles: frozenset[str]) -> FlagList:
        """Every flag the caller may see (`FlagSpec.visible_to` its roles), resolved for the
        caller from one snapshot no older than the kill-switch bound."""
        rows = await self._rows(KILLSWITCH_TTL_S)
        items: list[ResolvedFlag] = []
        for key, spec in self.registry.items():
            if not spec.visible_to(roles):
                continue
            row = None if rows is None else rows.get(key) or StoredFlag(spec.default)
            items.append(self.resolved(spec, row, user_id, roles))
        return FlagList(Resolution.FAIL_CLOSED if rows is None else Resolution.STORED, tuple(items))

    def resolved(
        self, spec: FlagSpec, row: StoredFlag | None, user_id: UUID | None, roles: frozenset[str]
    ) -> ResolvedFlag:
        """`row` resolved for one caller: the list item, a `PUT` answer or a 409's `current`.
        A spec this registry does not hold raises `KeyError` before any series is touched."""
        if self.registry.get(spec.key) is not spec:
            raise KeyError(spec.key)
        flag_evaluations_total.labels(spec.key).inc()
        if row is not None and spec.overridable and value_matches(spec, row.value):
            applied = [v for user, v in row.user_overrides.items() if user == user_id]
            applied += [v for role, v in row.role_overrides.items() if role in roles]
            if unreadable := sum(not override_matches(spec, v) for v in applied):
                unreadable_overrides_total.labels(spec.key).inc(unreadable)  # ignored (D1b)
        return ResolvedFlag(spec, resolve(spec, row, user_id=user_id, roles=roles), row)

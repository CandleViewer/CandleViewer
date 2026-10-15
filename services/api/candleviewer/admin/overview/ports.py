"""Ports the admin read models read through (E42-T01).

CONSTITUTION §3 / C-3.1: M21 may not import the recorder (M11), ingestion (M6), the exchange
adapter (M4) or the OMS (M14). Each of those sources is therefore a Protocol here, and the
composition root (`candleviewer.app`) injects an adapter. A port that is not wired yet makes
its slice `unavailable` (`SourceUnavailable`); the read model never guesses a value.

The snapshots are plain frozen dataclasses so no foreign module type crosses the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserCounts:
    total: int
    active: int
    without_mfa: int


@dataclass(frozen=True, slots=True)
class AccountCounts:
    total: int
    enabled: int
    keys_expiring_30d: int
    keys_invalid: int


class CountsPort(Protocol):
    """Relational counts; implemented in M10 (`storage`), so admin imports no driver."""

    async def user_counts(self) -> UserCounts: ...

    async def account_counts(self, expiring_before: datetime) -> AccountCounts: ...

    async def open_incidents(self) -> int:
        """Distinct (component, kind) of unresolved `error`/`critical` system events."""

    async def subaccounts_in_use(self) -> int:
        """Most non-deleted sub-accounts under any one main account (the cap is per main)."""


@dataclass(frozen=True, slots=True)
class RecorderStatus:
    symbols_recording: int
    symbols_degraded: int
    lag_seconds_p99: float | None


@dataclass(frozen=True, slots=True)
class SymbolStorage:
    symbol: str
    used_bytes: int
    #: `None` until the recorder has a measured growth fit for this symbol.
    daily_growth_bytes: int | None
    pinned: bool
    #: `None` for a pinned symbol: kept forever, so its growth is unbounded.
    retention_days: int | None
    #: In the current recorded-symbol set (only these grow).
    recording: bool


@dataclass(frozen=True, slots=True)
class StorageSnapshot:
    """The recorder's DiskBudget view: measured, never assumed (`None` = not measured yet)."""

    used_bytes: int
    free_bytes: int
    daily_growth_bytes: int | None
    days_until_full: float | None
    symbols: tuple[SymbolStorage, ...]


class RecorderPort(Protocol):
    async def recorder_status(self) -> RecorderStatus: ...

    async def storage_snapshot(self) -> StorageSnapshot | None:
        """The last DiskBudget sample, or `None` before the first one. Design intent, in the
        spirit of SR-096 (fail closed): an adapter returns `None` or raises `SourceUnavailable`
        once the last sample is older than a few sample intervals, never a stale headroom."""


@dataclass(frozen=True, slots=True)
class IngestionStats:
    messages_per_sec: float
    queue_depth: int
    dropped_last_hour: int


class IngestionPort(Protocol):
    async def ingestion_stats(self) -> IngestionStats: ...


@dataclass(frozen=True, slots=True)
class RateBudgetUse:
    """Per-UID budget from the backend's own accounting; never fetched from the exchange."""

    exchange_account_id: UUID
    label: str
    limit_per_minute: int
    peak_used_per_minute: int


class RateLimitPort(Protocol):
    async def rate_budget(self) -> tuple[RateBudgetUse, ...]: ...


@dataclass(frozen=True, slots=True)
class RecordedTier:
    tier: str
    recorded_at: datetime


class TierPort(Protocol):
    async def recorded_tier(self) -> RecordedTier | None:
        """The `accounts.subaccount_tier` system setting, or `None` if never recorded."""


class OmsPort(Protocol):
    async def open_positions(self) -> int: ...

    async def kill_switch_engaged(self) -> bool:
        """Read live on every call (never cached), like `is_killswitch` flags."""

    async def live_enabled(self) -> bool:
        """The `trading.live_enabled` flag, read live on every call (never cached)."""

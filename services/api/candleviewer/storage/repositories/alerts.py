"""Driver-free alert repository surface (E40-T01 rows, E40-T02 Protocol).

The `api` module (M23) may not import a storage driver (ADR-0003), so routers type against
`AlertRepository` and these plain dataclasses; `alerts_sqlalchemy.py` is the implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class AlertConflictError(Exception):
    """Optimistic-concurrency failure: `updated_at` no longer matches (HTTP 412)."""


class AlertNameTakenError(Exception):
    """`ux_alerts_name`: the owner already has a live alert with this name (HTTP 409)."""


@dataclass(frozen=True, slots=True)
class AlertRow:
    id: str
    owner_user_id: str
    name: str
    symbol: str | None
    scope_account_id: str | None
    condition_ir: dict[str, Any]
    condition_hash: str
    enabled: bool
    trigger_mode: str
    cooldown_seconds: int
    snoozed_until: datetime | None
    expires_at: datetime | None
    severity: str
    channels: tuple[str, ...]
    has_webhook: bool
    message_template: str
    last_fired_at: datetime | None
    fire_count: int
    created_at: datetime
    updated_at: datetime
    disarm_reason: str | None = None

    @property
    def etag(self) -> str:
        return self.updated_at.isoformat()


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None


class AlertRepository(Protocol):
    """What `/alerts` needs from storage. Writes never accept the SECRET webhook columns here."""

    async def create(
        self,
        *,
        owner_user_id: str,
        alert_id: str | None = ...,
        name: str,
        condition_ir: dict[str, Any],
        condition_hash: str,
        symbol: str | None = ...,
        scope_account_id: str | None = ...,
        enabled: bool = ...,
        trigger_mode: str = ...,
        expires_at: datetime | None = ...,
        severity: str = ...,
        channels: tuple[str, ...] = ...,
        message_template: str = ...,
    ) -> AlertRow: ...

    async def get(self, alert_id: str) -> AlertRow | None: ...

    async def list_page(
        self,
        owner_user_id: str,
        *,
        cursor: str | None = ...,
        limit: int = ...,
        enabled: bool | None = ...,
        symbol: str | None = ...,
    ) -> Page[AlertRow]: ...

    async def update(
        self,
        alert_id: str,
        *,
        if_match: datetime,
        name: str,
        condition_ir: dict[str, Any],
        condition_hash: str,
        trigger_mode: str,
        cooldown_seconds: int,
        expires_at: datetime | None,
        severity: str,
        channels: tuple[str, ...],
        message_template: str,
        symbol: str | None = ...,
        scope_account_id: str | None = ...,
        enabled: bool = ...,
    ) -> AlertRow: ...

    async def soft_delete(self, alert_id: str) -> bool: ...

    async def set_enabled(self, alert_id: str, enabled: bool) -> AlertRow | None: ...

    async def set_snooze(self, alert_id: str, until: datetime | None) -> AlertRow | None: ...

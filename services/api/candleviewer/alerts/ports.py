"""Driver-free collaborators of the alert evaluator (E40-T03).

M22 may not import `storage` (CONSTITUTION §3) or `audit`; the app wires the
SQLAlchemy repository and the M19 emitter in structurally. `record_firing` is
the single firing transaction (21-database-schema.md §3.10.4): the
`alert_deliveries` row(s), the `outbox` row(s) and the `last_fired_at` /
`fire_count` / `enabled` updates commit together or not at all.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

import structlog

#: The only reason the server disarms an alert (the OpenAPI `Alert.disarm_reason` enum).
DisarmReason = Literal["source_unavailable"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class AlertRecord(Protocol):
    """The `alerts` columns the evaluator reads (satisfied by `AlertRow`)."""

    @property
    def id(self) -> str: ...
    @property
    def owner_user_id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def symbol(self) -> str | None: ...
    @property
    def condition_ir(self) -> dict[str, Any]: ...
    @property
    def condition_hash(self) -> str: ...
    @property
    def enabled(self) -> bool: ...
    @property
    def trigger_mode(self) -> str: ...
    @property
    def cooldown_seconds(self) -> int: ...
    @property
    def snoozed_until(self) -> datetime | None: ...
    @property
    def expires_at(self) -> datetime | None: ...
    @property
    def severity(self) -> str: ...
    @property
    def channels(self) -> tuple[str, ...]: ...
    @property
    def message_template(self) -> str: ...
    @property
    def last_fired_at(self) -> datetime | None: ...


class FiringStore(Protocol):
    async def load_live(self) -> Sequence[AlertRecord]:
        """Warm-up: `enabled AND deleted_at IS NULL` (index `ix_alerts_live`)."""
        ...

    async def get(self, alert_id: str) -> AlertRecord | None: ...

    async def record_firing(
        self,
        *,
        alert_id: str,
        user_id: str,
        channels: Sequence[str],
        status: str,
        title: str,
        body: str,
        context: dict[str, Any],
        fired_at: datetime,
        once: bool,
        bump: bool,
        disarm_reason: DisarmReason | None = None,
    ) -> list[int] | None:
        """One transaction. `once`: `UPDATE ... SET enabled = false WHERE enabled`; zero
        rows means another worker won the race -> roll back, return None. `disarm_reason`
        (a server-side disarm, e.g. `source_unavailable`, stored on the alert) uses the same
        conditional update: zero rows -> None. Queued rows get an `alert.deliver` outbox row;
        `suppressed` rows are history only.
        Returns the delivery ids."""
        ...


class WakingFiringStore:
    """A `FiringStore` that wakes the delivery dispatcher once a firing with queued deliveries
    commits (E40-T04: its in-app row is visible over the `alerts` topic within 250 ms, not at the
    dispatcher's next poll). *wake* must not raise and must not block (`AlertDispatcher.notify`)."""

    def __init__(self, inner: FiringStore, wake: Callable[[], None]) -> None:
        self._inner, self._wake = inner, wake

    async def load_live(self) -> Sequence[AlertRecord]:
        return await self._inner.load_live()

    async def get(self, alert_id: str) -> AlertRecord | None:
        return await self._inner.get(alert_id)

    async def record_firing(
        self,
        *,
        alert_id: str,
        user_id: str,
        channels: Sequence[str],
        status: str,
        title: str,
        body: str,
        context: dict[str, Any],
        fired_at: datetime,
        once: bool,
        bump: bool,
        disarm_reason: DisarmReason | None = None,
    ) -> list[int] | None:
        ids = await self._inner.record_firing(
            alert_id=alert_id, user_id=user_id, channels=channels, status=status, title=title,
            body=body, context=context, fired_at=fired_at, once=once, bump=bump,
            disarm_reason=disarm_reason,
        )  # fmt: skip
        if ids and status == "queued":  # committed with outbox rows: deliver them now
            try:  # past the commit nothing may raise: the evaluator would re-fire a committed one
                self._wake()
            except Exception as exc:  # the next poll delivers them
                _log().warning("alerts_dispatcher_wake_failed", error=type(exc).__name__)
        return ids


class OwnerDirectory(Protocol):
    """Which alert owners may still be served (#3349): the identity read path, ids only."""

    async def active_users(self, user_ids: Collection[str]) -> frozenset[str]:
        """The members of *user_ids* whose user is `active` and not deleted; raises when the store
        cannot be read (`OwnerGate` fails closed)."""
        ...


class AuditSink(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class WebhookSealerPort(Protocol):
    """M2's `WebhookSealer` (#1400 S3, ADR-0009 Amendment 9), which the composition root binds:
    seals a webhook's URL or secret for one alert into the `webhook_url_enc` or
    `webhook_secret_enc` blob. M22 never imports `secrets` (C-3.2); a refusal raises, its text a
    reason code only, and the caller maps any failure but a cancellation to its own code (the
    `destroy_key` precedent)."""

    async def seal_target(self, url: str, alert_id: UUID) -> bytes: ...

    async def seal_secret(self, secret: bytes | bytearray, alert_id: UUID) -> bytes: ...


class WebhookTargetOpenerPort(Protocol):
    """M2's `WebhookTargetOpener` (Amendment 9): the webhook URL of one alert's blob, for the
    egress client, held in memory for one delivery and never logged or stored. No port opens the
    secret. Refusals as `WebhookSealerPort`'s."""

    async def open_target(self, sealed: bytes, alert_id: UUID) -> str: ...


class WebhookSignerPort(Protocol):
    """M2's bounded `WebhookSigner` (Amendment 9): the hex HMAC-SHA256, under the alert's sealed
    secret, of `cv.alert.webhook.v1:{timestamp}:{delivery_id}:{hex body_digest}`, where
    `body_digest` is the 32-byte SHA-256 of the raw body sent; nothing else is signable. Refusals
    as `WebhookSealerPort`'s."""

    async def sign_delivery(
        self,
        sealed_secret: bytes,
        alert_id: UUID,
        delivery_id: int,
        timestamp: int,
        body_digest: bytes,
    ) -> str: ...


class MetricChildLike(Protocol):
    def inc(self, amount: float = ...) -> None: ...
    def set(self, value: float) -> None: ...
    def observe(self, amount: float) -> None: ...

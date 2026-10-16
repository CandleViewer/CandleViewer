"""Per-account connection health (E27-T04, US-ACCT-010): one explicit FSM per account.

`healthy` while an authenticated private-WS heartbeat is fresh, `degraded` while a WS or REST
success is inside the down window, `down` after it. Only positive evidence counts and it decays
on silence. Plain synchronous code, not a statechart: the order-entry gate reads the enum
published on each transition (C-2.20, C-2.21). Ages run on a clock that counts through suspend
(`CLOCK_BOOTTIME`), so a laptop that slept past the window resumes `down`.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict

from candleviewer.accounts.models import UtcDatetime
from candleviewer.settings import Settings


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


#: REST `ExchangeAccount.connection_state` per state (decision Q2 on #837).
CONNECTION_STATE: Final[Mapping[HealthState, str]] = {
    HealthState.HEALTHY: "connected",
    HealthState.DEGRADED: "degraded",
    HealthState.DOWN: "disconnected",
}


def epoch_ms(value: datetime) -> int:
    """Wire `*_ms` timestamp (23-ws-protocol.md `epochMs`)."""
    return (value - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1)


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def now(self) -> datetime: ...


class SystemClock:
    def monotonic(self) -> float:
        """`CLOCK_BOOTTIME` on Linux keeps counting through suspend; `time.monotonic` may not."""
        if sys.platform == "linux":
            return time.clock_gettime(time.CLOCK_BOOTTIME)
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class HealthThresholds:
    """`CV_ACCOUNT_HEARTBEAT_S`: max heartbeat age; `CV_ACCOUNT_DOWN_S`: silence before down."""

    heartbeat_s: float = 10.0
    down_s: float = 30.0

    def __post_init__(self) -> None:
        if not 0 < self.heartbeat_s < self.down_s:
            raise ValueError("health thresholds need 0 < heartbeat_s < down_s")

    @classmethod
    def from_settings(cls, settings: Settings) -> HealthThresholds:
        return cls(settings.account_heartbeat_s, settings.account_down_s)


class AccountHealth(BaseModel):
    """`AccountHealth` (22-api-openapi.yaml); `ws_fields()` is a `wallet` item's `health`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: HealthState
    reason: str
    heartbeat_age_ms: int | None
    rest_only: bool
    changed_at: UtcDatetime

    def ws_fields(self) -> dict[str, object]:
        fields = self.model_dump(mode="json", exclude={"changed_at"})
        return fields | {"changed_at_ms": epoch_ms(self.changed_at)}


@dataclass(frozen=True, slots=True)
class HealthTransition:
    account_id: UUID
    from_state: HealthState
    to_state: HealthState
    reason: str
    at: datetime


class DeadMansSwitch(Protocol):
    """The dead-man's-switch policy hook, called once per transition into `down` (E39 owns it)."""

    def account_down(self, account_id: UUID, reason: str) -> None: ...


@dataclass(slots=True)
class _Account:
    changed_at: datetime
    state: HealthState = HealthState.DOWN
    reason: str = "never_connected"
    ws_at: float | None = None
    ws_live: bool = False
    rest_at: float | None = None


class AccountHealthMonitor:
    """Health for every tracked account. Feed it evidence as it arrives and call `tick()` at
    least once a second; `state()` is the published enum the order-entry gate reads."""

    def __init__(
        self, clock: Clock, dms: DeadMansSwitch, thresholds: HealthThresholds | None = None
    ) -> None:
        self._clock = clock
        self._dms = dms
        self._th = thresholds or HealthThresholds()
        self._accounts: dict[UUID, _Account] = {}

    def track(self, account_id: UUID) -> None:
        """Start monitoring an account; it is `down` until the first success."""
        self._accounts.setdefault(account_id, _Account(self._clock.now()))

    def untrack(self, account_id: UUID) -> None:
        self._accounts.pop(account_id, None)

    def ws_heartbeat(self, account_id: UUID) -> HealthTransition | None:
        """An authenticated private-WS heartbeat: auth success, or a pong on an authed socket."""
        acc = self._accounts[account_id]
        acc.ws_at, acc.ws_live = self._clock.monotonic(), True
        return self._evaluate(account_id, acc)

    def ws_dropped(self, account_id: UUID) -> HealthTransition | None:
        acc = self._accounts[account_id]
        acc.ws_live = False
        return self._evaluate(account_id, acc)

    def rest_ok(self, account_id: UUID) -> HealthTransition | None:
        acc = self._accounts[account_id]
        acc.rest_at = self._clock.monotonic()
        return self._evaluate(account_id, acc)

    def tick(self) -> list[HealthTransition]:
        moved = (self._evaluate(aid, acc) for aid, acc in list(self._accounts.items()))
        return [t for t in moved if t is not None]

    def state(self, account_id: UUID) -> HealthState | None:
        acc = self._accounts.get(account_id)
        return None if acc is None else acc.state

    def view(self, account_id: UUID) -> AccountHealth | None:
        acc = self._accounts.get(account_id)
        if acc is None:
            return None
        now = self._clock.monotonic()
        age = None if acc.ws_at is None else max(0, round((now - acc.ws_at) * 1000))
        return AccountHealth(
            state=acc.state,
            reason=acc.reason,
            heartbeat_age_ms=age,
            rest_only=acc.state is HealthState.DEGRADED,
            changed_at=acc.changed_at,
        )

    def _derive(self, acc: _Account, now: float) -> tuple[HealthState, str]:
        if acc.ws_live and acc.ws_at is not None and now - acc.ws_at <= self._th.heartbeat_s:
            return HealthState.HEALTHY, "ws_heartbeat"
        last = max((t for t in (acc.ws_at, acc.rest_at) if t is not None), default=None)
        if last is None:
            return HealthState.DOWN, "never_connected"
        if now - last >= self._th.down_s:
            return HealthState.DOWN, "no_success"
        rest_recent = acc.rest_at is not None and now - acc.rest_at < self._th.down_s
        return HealthState.DEGRADED, "rest_only" if rest_recent else "ws_silent"

    def _evaluate(self, account_id: UUID, acc: _Account) -> HealthTransition | None:
        state, acc.reason = self._derive(acc, self._clock.monotonic())
        if state is acc.state:
            return None
        moved = HealthTransition(account_id, acc.state, state, acc.reason, self._clock.now())
        acc.state, acc.changed_at = state, moved.at
        log = structlog.get_logger(__name__).bind(account_id=str(account_id), reason=acc.reason)
        log.info("account.health_changed", from_state=moved.from_state.value, to_state=state.value)
        if state is HealthState.DOWN:
            self._dms.account_down(account_id, acc.reason)
        return moved

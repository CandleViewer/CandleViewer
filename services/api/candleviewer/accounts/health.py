"""Per-account connection health (E27-T04, US-ACCT-010): one explicit FSM per account.

`healthy` while an authenticated private-WS heartbeat is fresh, `degraded` while a WS or REST
success is inside the down window, `down` after it. Only positive evidence counts and it decays
on silence. Plain synchronous code, not a statechart: the order-entry gate needs an answer, not a
recorded fact (C-2.21). A read derives the state from the evidence in a few float comparisons, so
the gate never depends on `tick()` having run; `tick()` and the evidence calls commit transitions
and log them. Ages run on the boot-time clock (`CLOCK_BOOTTIME` on Linux): on a platform whose
boot-time clock counts a suspend, a laptop that slept past the window resumes `down`. Where it
does not (a WSL2 guest may not see the host suspend; unverified, #837), a resumed account can
read `healthy` for at most one heartbeat window, until its silence lapses.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Literal, Protocol
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict

from candleviewer.accounts.models import UtcDatetime
from candleviewer.settings import Settings


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


#: `AccountHealth.reason`: a closed set of codes, never exchange-supplied text.
HealthReason = Literal["ws_heartbeat", "rest_only", "ws_silent", "no_success", "never_connected"]

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
        """`CLOCK_BOOTTIME` on Linux counts a suspend its kernel performs; `time.monotonic` may
        not."""
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
    """`AccountHealth` (22-api-openapi.yaml); `ws_entry()` is one `wallet` frame `health` entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: HealthState
    reason: HealthReason
    heartbeat_age_ms: int | None
    rest_only: bool
    changed_at: UtcDatetime

    def ws_entry(self, account_id: UUID) -> dict[str, object]:
        fields = self.model_dump(mode="json", exclude={"changed_at"})
        changed = {"changed_at_ms": epoch_ms(self.changed_at)}
        return {"exchange_account_id": str(account_id)} | fields | changed


@dataclass(frozen=True, slots=True)
class HealthTransition:
    account_id: UUID
    from_state: HealthState
    to_state: HealthState
    reason: HealthReason
    at: datetime


@dataclass(slots=True)
class _Account:
    changed_at: datetime
    since: float  # `changed_at` on the monotonic clock
    state: HealthState = HealthState.DOWN
    reason: HealthReason = "never_connected"
    ws_at: float | None = None
    ws_live: bool = False
    rest_at: float | None = None

    def last_success(self) -> float | None:
        return max((t for t in (self.ws_at, self.rest_at) if t is not None), default=None)


class AccountHealthMonitor:
    """Health for every tracked account. Feed it evidence as it arrives and call `tick()` at
    least once a second to commit transitions; `current()` and `view()` derive on every read.

    An evidence call first commits any lapse the old evidence reached, so a down window that
    passed between two ticks is still a transition, and returns the latest transition. Evidence
    for an untracked account is ignored: it can race `untrack()`.
    """

    def __init__(self, clock: Clock, thresholds: HealthThresholds | None = None) -> None:
        self._clock = clock
        self._th = thresholds or HealthThresholds()
        self._accounts: dict[UUID, _Account] = {}

    def track(self, account_id: UUID) -> None:
        """Start monitoring an account; it is `down` until the first success."""
        if account_id not in self._accounts:
            self._accounts[account_id] = _Account(self._clock.now(), self._clock.monotonic())

    def untrack(self, account_id: UUID) -> None:
        """Stop monitoring an account."""
        self._accounts.pop(account_id, None)

    def ws_heartbeat(self, account_id: UUID) -> HealthTransition | None:
        """Evidence that the account's private WS is connected and authenticated: its successful
        auth reply, then any pong or topic message received on that socket. Nothing sent counts,
        nor anything from a public or unauthenticated socket.

        Cadence contract for the private-WS client (E08, E29-T05): evidence at least every
        `heartbeat_s` (`CV_ACCOUNT_HEARTBEAT_S`, capped at US-ACCT-010's 10 s), so it pings every
        `heartbeat_s / 2`, 5 s at the default (`ExchangeConfig.ws_ping_interval_s` note,
        24-internal-schemas.md §16.1). The public streams' 20 s ping would degrade every idle
        account between pongs, flipping `rest_only` and logging two transitions each time.
        """
        if (acc := self._accounts.get(account_id)) is None:
            return None
        lapse = self._commit(account_id, acc)
        acc.ws_at, acc.ws_live = self._clock.monotonic(), True
        return self._commit(account_id, acc) or lapse

    def ws_dropped(self, account_id: UUID) -> HealthTransition | None:
        if (acc := self._accounts.get(account_id)) is None:
            return None
        lapse = self._commit(account_id, acc)
        acc.ws_live = False
        return self._commit(account_id, acc) or lapse

    def rest_ok(self, account_id: UUID) -> HealthTransition | None:
        if (acc := self._accounts.get(account_id)) is None:
            return None
        lapse = self._commit(account_id, acc)
        acc.rest_at = self._clock.monotonic()
        return self._commit(account_id, acc) or lapse

    def tick(self) -> list[HealthTransition]:
        moved = (self._commit(aid, acc) for aid, acc in list(self._accounts.items()))
        return [t for t in moved if t is not None]

    def current(self, account_id: UUID) -> HealthState | None:
        """The state the evidence supports now, without side effects; `None` if untracked."""
        acc = self._accounts.get(account_id)
        return None if acc is None else self._derive(acc, self._clock.monotonic())[0]

    def view(self, account_id: UUID) -> AccountHealth | None:
        acc = self._accounts.get(account_id)
        if acc is None:
            return None
        now = self._clock.monotonic()
        state, reason, _, changed_at = self._project(acc, now)
        age = None if acc.ws_at is None else max(0, round((now - acc.ws_at) * 1000))
        return AccountHealth(
            state=state,
            reason=reason,
            heartbeat_age_ms=age,
            rest_only=state is HealthState.DEGRADED,
            changed_at=changed_at,
        )

    def _derive(self, acc: _Account, now: float) -> tuple[HealthState, HealthReason]:
        if acc.ws_live and acc.ws_at is not None and now - acc.ws_at <= self._th.heartbeat_s:
            return HealthState.HEALTHY, "ws_heartbeat"
        last = acc.last_success()
        if last is None:
            return HealthState.DOWN, "never_connected"
        if now - last >= self._th.down_s:
            return HealthState.DOWN, "no_success"
        rest_recent = acc.rest_at is not None and now - acc.rest_at < self._th.down_s
        return HealthState.DEGRADED, "rest_only" if rest_recent else "ws_silent"

    def _project(
        self, acc: _Account, now: float
    ) -> tuple[HealthState, HealthReason, float, datetime]:
        """The derived state and reason, and when that state began (monotonic, wall). A state
        other than the committed one began now, or when the old evidence lapsed if it did: the
        heartbeat window into `degraded`, the down window into `down`. A lapse is dated from the
        committed transition, so a read before `tick()` and the commit after it agree."""
        state, reason = self._derive(acc, now)
        if state is acc.state:
            return state, reason, acc.since, acc.changed_at
        began, last = now, acc.last_success()
        if state is HealthState.DOWN and last is not None:
            began = min(now, last + self._th.down_s)
        elif acc.state is HealthState.HEALTHY and acc.ws_at is not None:
            began = min(now, acc.ws_at + self._th.heartbeat_s)
        if began >= now:
            return state, reason, now, self._clock.now()
        return state, reason, began, acc.changed_at + timedelta(seconds=began - acc.since)

    def _commit(self, account_id: UUID, acc: _Account) -> HealthTransition | None:
        state, acc.reason, began, at = self._project(acc, self._clock.monotonic())
        if state is acc.state:
            return None
        moved = HealthTransition(account_id, acc.state, state, acc.reason, at)
        acc.state, acc.since, acc.changed_at = state, began, at
        log = structlog.get_logger(__name__).bind(account_id=str(account_id), reason=acc.reason)
        log.info("account.health_changed", from_state=moved.from_state.value, to_state=state.value)
        return moved

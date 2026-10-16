"""Per-account connection health (E27-T04, US-ACCT-010): one explicit FSM per account.

`healthy` while an authenticated private-WS heartbeat is fresh, `degraded` while a WS or REST
success is inside the down window, `down` after it. Only positive evidence counts and it decays
on silence. Plain synchronous code, not a statechart: the order-entry gate needs an answer, not a
recorded fact (C-2.21). A read derives the state from the evidence in a few float comparisons, so
the gate never depends on `tick()` having run; `tick()` and the evidence calls commit transitions
and log them, and a transition into `down` owes the dead-man's switch a call that runs as its own
task. Ages run on a clock that counts through suspend (`CLOCK_BOOTTIME`), so a laptop that slept
past the window resumes `down`.
"""

from __future__ import annotations

import asyncio
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
from candleviewer.observability import bind_context, spawn
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

#: How long one dead-man's-switch hook call may run before it counts as failed and is retried.
DMS_HOOK_TIMEOUT_S: Final = 5.0


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


class DeadMansSwitch(Protocol):
    """The dead-man's-switch policy hook (E39 owns the policy), owed a call for every transition
    into `down`. The monitor makes each call as its own task under `DMS_HOOK_TIMEOUT_S`, so the
    hook can neither block nor abort an evidence call or `tick()`. The task runs in the caller's
    correlation context with `account_id` bound, so the hook's logs carry the account. A call
    that raises or times out is logged and made again at the account's next evaluation until one
    returns, so the hook must be idempotent, and a retry may land after the account recovered
    (`transition.at` dates the episode). An account has at most one call in flight and one owed:
    a newer transition into `down` replaces an older one whose call never succeeded. A call still
    owed at shutdown is logged and listed by `owed()`; replaying it after a restart is the
    wiring's job (E39), as a restarted monitor starts every account `down` owing nothing."""

    async def account_down(self, transition: HealthTransition) -> None: ...


@dataclass(slots=True)
class _Account:
    changed_at: datetime
    since: float  # `changed_at` on the monotonic clock
    state: HealthState = HealthState.DOWN
    reason: HealthReason = "never_connected"
    ws_at: float | None = None
    ws_live: bool = False
    rest_at: float | None = None
    dms_owed: HealthTransition | None = None  # no hook call for it has returned yet
    dms_call: asyncio.Task[None] | None = None

    def last_success(self) -> float | None:
        return max((t for t in (self.ws_at, self.rest_at) if t is not None), default=None)


def _log_dropped(owed: HealthTransition) -> None:
    """An owed hook call this process will not make: its account was untracked, or shutdown."""
    structlog.get_logger(__name__).warning(
        "account.dms_hook_dropped", account_id=str(owed.account_id), reason=owed.reason
    )


class AccountHealthMonitor:
    """Health for every tracked account. Feed it evidence as it arrives and call `tick()` at
    least once a second to commit transitions and retry owed dead-man's-switch calls; `current()`
    and `view()` derive on every read. Evidence and `tick()` run on the event loop, which runs
    the hook calls; `drain()` waits for them at shutdown and logs the calls still owed.

    An evidence call first commits any lapse the old evidence reached, so a down window that
    passed between two ticks is still a transition and a dead-man's-switch call, and returns the
    latest transition. Evidence for an untracked account is ignored: it can race `untrack()`.
    """

    def __init__(
        self,
        clock: Clock,
        dms: DeadMansSwitch,
        thresholds: HealthThresholds | None = None,
        *,
        dms_timeout_s: float = DMS_HOOK_TIMEOUT_S,
    ) -> None:
        self._clock = clock
        self._dms = dms
        self._th = thresholds or HealthThresholds()
        self._dms_timeout_s = dms_timeout_s
        self._accounts: dict[UUID, _Account] = {}
        self._dms_calls: set[asyncio.Task[None]] = set()

    def track(self, account_id: UUID) -> None:
        """Start monitoring an account; it is `down` until the first success."""
        if account_id not in self._accounts:
            self._accounts[account_id] = _Account(self._clock.now(), self._clock.monotonic())

    def untrack(self, account_id: UUID) -> None:
        """Stop monitoring an account. A call in flight finishes; an owed one is not retried."""
        acc = self._accounts.pop(account_id, None)
        if acc is not None and acc.dms_owed is not None:
            _log_dropped(acc.dms_owed)

    def ws_heartbeat(self, account_id: UUID) -> HealthTransition | None:
        """Evidence that the account's private WS is connected and authenticated: its successful
        auth reply, then any pong or topic message received on that socket. Nothing sent counts,
        nor anything from a public or unauthenticated socket.

        Cadence contract for the private-WS client (E08): evidence at least every `heartbeat_s`
        (`CV_ACCOUNT_HEARTBEAT_S`, capped at US-ACCT-010's 10 s), so it pings every
        `heartbeat_s / 2` (5 s at the default). Bybit's suggested 20 s ping would degrade every
        idle account between pongs, flipping `rest_only` and logging two transitions each time.
        """
        if (acc := self._accounts.get(account_id)) is None:
            return None
        lapse = self._evaluate(account_id, acc)
        acc.ws_at, acc.ws_live = self._clock.monotonic(), True
        return self._evaluate(account_id, acc) or lapse

    def ws_dropped(self, account_id: UUID) -> HealthTransition | None:
        if (acc := self._accounts.get(account_id)) is None:
            return None
        lapse = self._evaluate(account_id, acc)
        acc.ws_live = False
        return self._evaluate(account_id, acc) or lapse

    def rest_ok(self, account_id: UUID) -> HealthTransition | None:
        if (acc := self._accounts.get(account_id)) is None:
            return None
        lapse = self._evaluate(account_id, acc)
        acc.rest_at = self._clock.monotonic()
        return self._evaluate(account_id, acc) or lapse

    def tick(self) -> list[HealthTransition]:
        moved = (self._evaluate(aid, acc) for aid, acc in list(self._accounts.items()))
        return [t for t in moved if t is not None]

    async def drain(self) -> None:
        """Shutdown: wait until no dead-man's-switch call is in flight; each ends within the hook
        timeout. This process makes no call still owed afterwards, so each is logged as
        `account.dms_hook_dropped`; `owed()` lists them for the wiring to persist and replay
        after a restart (E39)."""
        while self._dms_calls:
            await asyncio.wait(set(self._dms_calls))
        for owed in self.owed():
            _log_dropped(owed)

    def owed(self) -> list[HealthTransition]:
        """The transitions into `down` whose hook call has not returned, one per account."""
        return [acc.dms_owed for acc in self._accounts.values() if acc.dms_owed is not None]

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

    def _evaluate(self, account_id: UUID, acc: _Account) -> HealthTransition | None:
        """Commit the account's transition, if any, then start the owed hook call unless one is
        in flight. The call is a task bound to the account's correlation context, on top of the
        caller's: nothing here waits for the hook or sees it raise."""
        moved = self._commit(account_id, acc)
        if moved is not None and moved.to_state is HealthState.DOWN:
            acc.dms_owed = moved
        if acc.dms_owed is not None and (acc.dms_call is None or acc.dms_call.done()):
            with bind_context(account_id=account_id):
                call = spawn(self._call_dms(acc, acc.dms_owed), name=f"account-dms:{account_id}")
            acc.dms_call = call
            self._dms_calls.add(call)
            call.add_done_callback(self._dms_calls.discard)
        return moved

    def _commit(self, account_id: UUID, acc: _Account) -> HealthTransition | None:
        state, acc.reason, began, at = self._project(acc, self._clock.monotonic())
        if state is acc.state:
            return None
        moved = HealthTransition(account_id, acc.state, state, acc.reason, at)
        acc.state, acc.since, acc.changed_at = state, began, at
        log = structlog.get_logger(__name__).bind(account_id=str(account_id), reason=acc.reason)
        log.info("account.health_changed", from_state=moved.from_state.value, to_state=state.value)
        return moved

    async def _call_dms(self, acc: _Account, owed: HealthTransition) -> None:
        try:
            async with asyncio.timeout(self._dms_timeout_s):
                await self._dms.account_down(owed)
        except Exception as exc:  # incl. TimeoutError; CancelledError still propagates
            # The call stays owed and the next evaluation makes it again. Log the type only: a
            # message may echo an exchange response (C-12.6).
            log = structlog.get_logger(__name__)
            log.error(
                "account.dms_hook_failed",
                account_id=str(owed.account_id),
                reason=owed.reason,
                error=type(exc).__name__,
            )
        else:
            if acc.dms_owed is owed:
                acc.dms_owed = None

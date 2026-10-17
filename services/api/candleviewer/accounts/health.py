"""Per-account connection health (E27-T04, US-ACCT-010): one explicit FSM per account.

`healthy` while an authenticated private-WS heartbeat is fresh, `degraded` while a WS or REST
success is inside the down window, `down` after it. Only positive evidence counts and it decays
on silence. Plain synchronous code, not a statechart: the order-entry gate needs an answer, not a
recorded fact (C-2.21). A read derives the state from the evidence in a few float comparisons, so
the gate never depends on `tick()` having run; `tick()` and the evidence calls commit transitions
and log them, and a transition into `down` owes the dead-man's switch a call that runs as its own
task. Ages run on the boot-time clock (`CLOCK_BOOTTIME` on Linux): on a platform whose boot-time
clock counts a suspend, a laptop that slept past the window resumes `down`. Where it does not (a
WSL2 guest may not see the host suspend; unverified, #837), a resumed account can read `healthy`
for at most one heartbeat window, until its silence lapses.
"""

from __future__ import annotations

import asyncio
import math
import random
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
from candleviewer.settings import ACCOUNT_DOWN_MAX_S, ACCOUNT_HEARTBEAT_MAX_S, Settings


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
#: The backoff after a hook call first fails; each further failure of the same call doubles it,
#: up to the down window. The call is made again after a wait drawn from the upper half of the
#: backoff (equal jitter, from the injected RNG), so accounts that went down together do not
#: retry in step, and a broken hook costs one error log every `down_s / 2` to `down_s` per
#: account, not one per tick.
DMS_RETRY_MIN_S: Final = 1.0


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
    """`CV_ACCOUNT_HEARTBEAT_S`: max heartbeat age; `CV_ACCOUNT_DOWN_S`: silence before down.
    Neither may exceed its US-ACCT-010 cap, which is also its default: `ACCOUNT_HEARTBEAT_MAX_S`
    and `ACCOUNT_DOWN_MAX_S`, written once in `settings`, where `Settings` bounds both fields by
    them. A heartbeat older than 10 s must not show `healthy`, and order entry must close within
    30 s of the last WS or REST success. The caps are limits, not tuning room, and no flag may move
    them (C-4.14), so no caller can build a monitor that holds an old heartbeat `healthy` or
    admits orders through a longer silence."""

    heartbeat_s: float = ACCOUNT_HEARTBEAT_MAX_S
    down_s: float = ACCOUNT_DOWN_MAX_S

    def __post_init__(self) -> None:
        if not 0 < self.heartbeat_s < self.down_s:
            raise ValueError("health thresholds need 0 < heartbeat_s < down_s")
        if self.heartbeat_s > ACCOUNT_HEARTBEAT_MAX_S or self.down_s > ACCOUNT_DOWN_MAX_S:
            raise ValueError(
                f"health thresholds are capped at heartbeat_s <= {ACCOUNT_HEARTBEAT_MAX_S:g} and "
                f"down_s <= {ACCOUNT_DOWN_MAX_S:g} (US-ACCT-010)"
            )

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
    that raises or times out is logged and made again by the account's first evaluation after a
    jittered retry delay, its backoff `DMS_RETRY_MIN_S` doubling per failure up to the down
    window, until one returns. So the hook must be idempotent, and a retry may land after the
    account recovered (`transition.at` dates the episode). An account id has at most one call in
    flight, a re-tracked id included, and one owed: a newer transition into `down` replaces an
    older one whose call never succeeded, and does not wait out the older one's retry delay. The
    replaced episode is logged as `account.dms_hook_dropped` once this process will not deliver
    it: at once, or when its call in flight fails; an untracked account's owed episode likewise.
    A call still owed at shutdown is logged and listed by `owed()`.

    The hook must not suppress `CancelledError`. A call that has not returned after the timeout
    is cancelled and gets the same time again to unwind; one that still has not returned is
    abandoned: logged as `account.dms_hook_stuck` and counted as failed, so it holds neither its
    account's next call nor `drain()`. The monitor keeps the abandoned task referenced until it
    ends and never awaits it.

    A restarted monitor starts every account `down` owing nothing, so an outage that spans a
    restart, or an account that never reconnects after boot, owes this monitor no call. Closing
    that gap is the #837 wiring's obligation: persist `owed()` at `drain()` and replay it after a
    restart, and owe a call for an account still `down`, with no evidence, `down_s` after
    startup."""

    async def account_down(self, transition: HealthTransition) -> None: ...


@dataclass(slots=True)
class _Account:
    changed_at: datetime
    since: float  # `changed_at` on the monotonic clock
    state: HealthState = HealthState.DOWN
    ws_at: float | None = None
    ws_live: bool = False
    rest_at: float | None = None
    dms_owed: HealthTransition | None = None  # no hook call for it has returned yet
    dms_calling: HealthTransition | None = None  # the episode this tracking's last call delivers
    dms_delay: float = 0.0  # the last backoff for `dms_owed`; 0 until a call for it fails
    dms_retry_at: float = -math.inf  # monotonic; no call for `dms_owed` starts before it

    def last_success(self) -> float | None:
        return max((t for t in (self.ws_at, self.rest_at) if t is not None), default=None)


def _log_dropped(owed: HealthTransition) -> None:
    """An owed hook call this process will not make: its account was untracked, a newer episode
    replaced it, or shutdown."""
    structlog.get_logger(__name__).warning(
        "account.dms_hook_dropped", account_id=str(owed.account_id), reason=owed.reason
    )


class AccountHealthMonitor:
    """Health for every tracked account. Feed it evidence as it arrives and call `tick()` at
    least once a second to commit transitions and retry owed dead-man's-switch calls; `current()`
    and `view()` derive on every read. Meant for one event loop, the one that runs the hook calls:
    no locks and no I/O of its own, so not thread-safe. `drain()` waits for the calls at shutdown
    and logs the calls still owed.

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
        rng: random.Random | None = None,
    ) -> None:
        if not (math.isfinite(dms_timeout_s) and dms_timeout_s > 0):
            raise ValueError("dms_timeout_s must be finite and greater than 0")
        self._clock = clock
        self._dms = dms
        self._th = thresholds or HealthThresholds()
        self._dms_timeout_s = dms_timeout_s
        self._rng = rng if rng is not None else random.SystemRandom()  # retry jitter only
        self._accounts: dict[UUID, _Account] = {}
        self._calls: dict[UUID, asyncio.Task[None]] = {}  # the latest call per account id
        self._watchers: set[asyncio.Task[None]] = set()  # one per call: ends with it or abandons it
        self._stuck: set[asyncio.Task[None]] = set()  # abandoned calls: running, never awaited

    def track(self, account_id: UUID) -> None:
        """Start monitoring an account; it is `down` until the first success."""
        if account_id not in self._accounts:
            self._accounts[account_id] = _Account(self._clock.now(), self._clock.monotonic())

    def untrack(self, account_id: UUID) -> None:
        """Stop monitoring an account. A call in flight finishes, and a later `track()` of the
        same id starts none until it has. An owed call is not retried: its drop is logged at once,
        or, if that call is in flight, when it fails."""
        acc = self._accounts.pop(account_id, None)
        if acc is None or acc.dms_owed is None:
            return
        owed, acc.dms_owed = acc.dms_owed, None
        if not (self._in_flight(account_id) and owed is acc.dms_calling):
            _log_dropped(owed)

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
        lapse = self._evaluate(account_id, acc)
        acc.ws_at, acc.ws_live = self._clock.monotonic(), True
        return self._evaluate(account_id, acc) or lapse

    def ws_dropped(self, account_id: UUID) -> HealthTransition | None:
        """Call when the account's authenticated private socket closes. The client must not feed
        `ws_heartbeat` for that socket afterwards: a straggler message would re-arm `healthy` for
        up to `heartbeat_s`."""
        if (acc := self._accounts.get(account_id)) is None:
            return None
        lapse = self._evaluate(account_id, acc)
        acc.ws_live = False
        return self._evaluate(account_id, acc) or lapse

    def rest_ok(self, account_id: UUID) -> HealthTransition | None:
        """Evidence of a successful authenticated REST response for this account: a signed private
        call that the exchange accepted. Never a public endpoint, a 4xx or a 5xx, so a rejected
        key cannot count as health."""
        if (acc := self._accounts.get(account_id)) is None:
            return None
        lapse = self._evaluate(account_id, acc)
        acc.rest_at = self._clock.monotonic()
        return self._evaluate(account_id, acc) or lapse

    def tick(self) -> list[HealthTransition]:
        moved = (self._evaluate(aid, acc) for aid, acc in list(self._accounts.items()))
        return [t for t in moved if t is not None]

    async def drain(self) -> None:
        """Shutdown: wait until no dead-man's-switch call is in flight; each ends within twice the
        hook timeout, whatever its hook does with the cancellation. This process makes no call
        still owed afterwards, so each is logged as `account.dms_hook_dropped`; `owed()` lists
        them for the #837 wiring to persist and replay after a restart."""
        while self._watchers:
            await asyncio.wait(set(self._watchers))
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
        in flight for the account id (an earlier tracking's included) or its retry delay is still
        running. A new transition into `down` replaces the owed episode, logged as dropped unless
        its call is in flight (that call's outcome decides), and starts with no delay. The call
        is a task bound to the account's correlation context, on top of the caller's: nothing
        here waits for the hook or sees it raise."""
        moved = self._commit(account_id, acc)
        busy = self._in_flight(account_id)
        if moved is not None and moved.to_state is HealthState.DOWN:
            replaced = acc.dms_owed
            if replaced is not None and not (busy and replaced is acc.dms_calling):
                _log_dropped(replaced)
            acc.dms_owed, acc.dms_delay, acc.dms_retry_at = moved, 0.0, -math.inf
        if acc.dms_owed is None or busy or self._clock.monotonic() < acc.dms_retry_at:
            return moved
        owed = acc.dms_owed
        with bind_context(account_id=account_id):
            call = spawn(self._call_dms(acc, owed), name=f"account-dms:{account_id}")
            watcher = spawn(
                self._watch(account_id, acc, owed, call), name=f"account-dms-watch:{account_id}"
            )
        acc.dms_calling = owed
        self._calls[account_id] = call
        self._watchers.add(watcher)
        watcher.add_done_callback(self._watchers.discard)
        return moved

    def _in_flight(self, account_id: UUID) -> bool:
        """The id's latest call is still running and not abandoned."""
        call = self._calls.get(account_id)
        return call is not None and not call.done() and call not in self._stuck

    def _commit(self, account_id: UUID, acc: _Account) -> HealthTransition | None:
        state, reason, began, at = self._project(acc, self._clock.monotonic())
        if state is acc.state:
            return None
        moved = HealthTransition(account_id, acc.state, state, reason, at)
        acc.state, acc.since, acc.changed_at = state, began, at
        log = structlog.get_logger(__name__).bind(account_id=str(account_id), reason=reason)
        log.info("account.health_changed", from_state=moved.from_state.value, to_state=state.value)
        return moved

    async def _call_dms(self, acc: _Account, owed: HealthTransition) -> None:
        try:
            async with asyncio.timeout(self._dms_timeout_s):
                await self._dms.account_down(owed)
        except Exception as exc:  # incl. TimeoutError; CancelledError still propagates
            if asyncio.current_task() not in self._stuck:  # else its watcher counted it failed
                self._failed(acc, owed, type(exc).__name__)
        else:
            if acc.dms_owed is owed:
                acc.dms_owed = None

    def _failed(self, acc: _Account, owed: HealthTransition, error: str) -> None:
        # Still owed: the first evaluation after the jittered delay makes it again. A newer
        # episode that replaced it meanwhile is not delayed, and this one is dropped. Log the
        # type only: a message may echo an exchange response (C-12.6).
        if acc.dms_owed is owed:
            acc.dms_delay = min(self._th.down_s, max(DMS_RETRY_MIN_S, 2 * acc.dms_delay))
            wait = self._rng.uniform(acc.dms_delay / 2, acc.dms_delay)
            acc.dms_retry_at = self._clock.monotonic() + wait
        log = structlog.get_logger(__name__)
        log.error(
            "account.dms_hook_failed",
            account_id=str(owed.account_id),
            reason=owed.reason,
            error=error,
        )
        if acc.dms_owed is not owed:
            _log_dropped(owed)

    async def _watch(
        self, account_id: UUID, acc: _Account, owed: HealthTransition, call: asyncio.Task[None]
    ) -> None:
        """Ends with its call, or abandons it: a call still running after the hook timeout and as
        long again for the cancellation to unwind has a hook that swallowed it. It is logged and
        counted as failed, so it holds neither the account's next call nor `drain()`; the task
        stays referenced in `_stuck` until it ends, and is never awaited."""
        done, _ = await asyncio.wait({call}, timeout=2 * self._dms_timeout_s)
        if done:
            return
        self._stuck.add(call)
        call.add_done_callback(self._stuck.discard)
        structlog.get_logger(__name__).error(
            "account.dms_hook_stuck", account_id=str(account_id), reason=owed.reason
        )
        self._failed(acc, owed, TimeoutError.__name__)

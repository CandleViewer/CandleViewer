"""Composition-root wiring (not a module) for account health and the wallet cache (E27-T04, #837).

`wire_account_health` builds the health monitor, the wallet cache and its REST reconciler from the
settings; `AccountHealthRuntime` runs them in two loops that the lifespan starts once the modules
are up and stops, draining the dead-man's-switch calls, before they stop. `create_app` attaches the
runtime's `feed` to `ctx.accounts`, which serves the private-WS consumer (E29-T05, #848) its
evidence calls and wallet feed, so no module imports this file. The monitor and the cache read the
boot-time clock, and the loops sleep on the event loop's: a wall-clock step moves nothing.

- `account-health-tick` calls `tick()` every `TICK_S` (at least once a second), so a lapsed account
  commits its transition and calls the dead-man's switch with or without evidence. It does no I/O,
  and the wallet reads run on their own loop, so a hung read cannot delay it.
- `account-health-reconcile` reads what the wallet reconciler finds due, every `TICK_S`.

Nothing is tracked yet, so both loops are idle in production: the next slice of #837 tracks the
enabled accounts that hold a signable key. An untracked account reads `None`; the gate refuses it.

A pass that raises is logged by its error type (a message may echo exchange text, C-12.6) and the
next one runs. A loop that ends, or whose passes keep failing, is a fault: `AccountsService`
reports it as a degraded `accounts` check (AGENTS.md §5.2), and an ended loop is logged critical.
Three bindings are stand-ins that fail closed until their owners land: the exchange's wallet read
is unavailable (E29), so sizing is off once a snapshot is stale after a failed attempt, or a period
old; the dead-man's-switch hook (E39) logs the episode; a credential rejection (the key standing, a
later slice of #837) is logged.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import structlog

from candleviewer.accounts.health import (
    DMS_HOOK_TIMEOUT_S,
    AccountHealthMonitor,
    Clock,
    DeadMansSwitch,
    HealthState,
    HealthThresholds,
    HealthTransition,
    SystemClock,
)
from candleviewer.accounts.verification import Refusal
from candleviewer.accounts.wallet import (
    CredentialRejections,
    WalletCache,
    WalletReconciler,
    WalletRestPort,
    WalletSnapshot,
    WalletThresholds,
    WalletUnavailable,
)
from candleviewer.observability import spawn
from candleviewer.observability.metrics_catalogue import register_r0

if TYPE_CHECKING:
    from candleviewer.accounts.service import AccountHealthFeed
    from candleviewer.observability.metrics import Metrics
    from candleviewer.settings import Settings

#: `tick()` and the reconciler's `run_due()` run this often: at least once a second (`health.py`),
#: and a wallet read that is due waits no longer than this for its pass.
TICK_S: Final = 0.5
#: The bound on each step of a stop. `AccountHealthMonitor.drain()` ends within twice the hook
#: timeout, so this only cuts a monitor that breaks that guarantee, or a loop that will not end.
STOP_TIMEOUT_S: Final = 2 * DMS_HOOK_TIMEOUT_S + 1.0
#: How long a loop's passes may keep failing before it is a fault (`fault`, so a degraded
#: `accounts` check). The health tick is what calls the dead-man's switch, and a pass that always
#: fails never does: 5 s, ten passes at `TICK_S`.
FAULT_AFTER_S: Final = 5.0
#: A failing loop logs its first failure and then once in this long, not every pass: the failures
#: are still counted, and `fault` still reports them.
LOG_EVERY_S: Final = 60.0
#: The catalogue's counter of sizing decisions taken on a snapshot older than the period.
OLD_SNAPSHOT_DECISIONS: Final = "cv_wallet_sizing_old_snapshot_total"


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class LoggingDeadMansSwitch:
    """The dead-man's-switch hook until E39 binds its policy: the episode is logged and the call
    returns, so the monitor counts it as delivered. The native stop-losses at the exchange hold
    meanwhile (C-2.6)."""

    async def account_down(self, transition: HealthTransition) -> None:
        logger().error(
            "account.dms_policy_unbound",
            account_id=str(transition.account_id),
            reason=transition.reason,
            down_at=transition.at.isoformat(),
        )


class LoggingCredentialRejections:
    """Where a rejected credential goes until the key standing takes the 24-internal-schemas
    section 8.6 reaction (a later slice of #837): it is logged, and the account is not marked or
    disabled."""

    def credential_rejected(self, account_id: UUID, refusal: Refusal) -> None:
        logger().error(
            "account.credential_rejection_unbound", account_id=str(account_id), reason=refusal.value
        )


class UnavailableWalletRest:
    """The REST wallet port until E29 implements `TradingPort.wallet()`: every read is unavailable,
    so every reconciliation attempt fails. With the wallet stream (#848) the only refresh, sizing
    is off once a snapshot is stale after a failed attempt, or a period old: fail closed. The
    reconciler logs each failed attempt (`wallet.reconcile_failed`, a warning), one per tracked
    account that is not healthy every `CV_ACCOUNT_HEARTBEAT_S`: expected, until E29 binds this."""

    async def wallet(self, account_id: UUID) -> WalletSnapshot:
        raise WalletUnavailable("no exchange adapter implements TradingPort.wallet yet")


def _passes(span_s: float, every_s: float) -> int:
    """How many passes of a loop that runs every `every_s` make `span_s`: at least one."""
    return max(1, math.ceil(span_s / every_s))


@dataclass(frozen=True, slots=True)
class _Loop:
    name: str
    step: Callable[[], Awaitable[object]]
    every_s: float
    fault_after_s: float

    @property
    def fault_after(self) -> int:
        """Failed passes in a row that make the loop a fault."""
        return _passes(self.fault_after_s, self.every_s)

    @property
    def log_every(self) -> int:
        """The failed passes between two log lines, after the first."""
        return _passes(LOG_EVERY_S, self.every_s)


class AccountHealthRuntime:
    """The running monitor, wallet cache and reconciler, with the loops that drive them. `monitor`
    and `wallets` are for the readers (the order-entry gate, the read models); the private-WS
    consumer gets `feed` through `ctx.accounts.account_health` (`AccountHealthFeed`): the evidence
    calls of the monitor, and the wallet cache's `apply` as `wallet_pushed`. `wallet_pushed` does
    not bound a frame's `updated_at`: the consumer refuses a frame dated ahead of the host clock
    before it gets here (a dated-ahead snapshot would block every later refresh). Meant for one
    event loop, the one that runs the loops and the hook calls."""

    def __init__(
        self,
        monitor: AccountHealthMonitor,
        wallets: WalletCache,
        rest: WalletRestPort,
        rejections: CredentialRejections,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.monitor, self.wallets = monitor, wallets
        self._sleep = sleep
        self._tasks: list[asyncio.Task[None]] = []
        self._loops: dict[str, _Loop] = {}
        self._failures: dict[str, int] = {}  # passes failed in a row, by loop
        self._stopping = False
        # the reconciler gives its evidence through this runtime, so a stop gates it as the feed
        self._reconciler = WalletReconciler(wallets, rest, self, rejections)
        self.feed: AccountHealthFeed = _Feed(self)

    # -- the evidence of the private-WS consumer (`AccountHealthFeed`, through `feed`) and of the
    # wallet reconciler (`HealthEvidence`). Once a stop has begun it gives nothing: evidence could
    # commit a transition and start a dead-man's-switch call that nothing drains, and a read that
    # outlives a cut-off stop is such evidence.

    def current(self, account_id: UUID) -> HealthState | None:
        return self.monitor.current(account_id)

    def ws_heartbeat(self, account_id: UUID) -> HealthTransition | None:
        return None if self._stopping else self.monitor.ws_heartbeat(account_id)

    def ws_dropped(self, account_id: UUID) -> HealthTransition | None:
        return None if self._stopping else self.monitor.ws_dropped(account_id)

    def rest_ok(self, account_id: UUID) -> HealthTransition | None:
        return None if self._stopping else self.monitor.rest_ok(account_id)

    def wallet_pushed(self, account_id: UUID, snapshot: WalletSnapshot) -> bool:
        return not self._stopping and self.wallets.apply(account_id, snapshot)

    @property
    def fault(self) -> str | None:
        """Why the runtime is not doing its job, `None` while it is, or while it is stopped: a loop
        that has ended, or whose passes keep failing."""
        for task in self._tasks:
            if task.done():
                return f"the {task.get_name()} loop ended"
        # a snapshot: `/readyz` reads this from a worker thread, while the loops update the streaks
        for name, streak in tuple(self._failures.items()):
            if streak >= self._loops[name].fault_after:
                return f"the {name} loop fails: {streak} passes in a row"
        return None

    # -- lifecycle

    def start(self) -> None:
        """Start the loops, inside the running event loop. A second call, or one after a stop,
        changes nothing: a stopped runtime is not restarted."""
        if self._tasks or self._stopping:
            return
        loops = [
            _Loop("account-health-tick", self._tick, TICK_S, FAULT_AFTER_S),
            _Loop("account-health-reconcile", self._reconcile, TICK_S, FAULT_AFTER_S),
        ]
        for loop in loops:
            self._loops[loop.name] = loop
            task = spawn(self._loop(loop), name=loop.name)
            task.add_done_callback(self._ended)
            self._tasks.append(task)

    async def stop(self) -> None:
        """Stop the loops, then wait for the dead-man's-switch calls in flight (the monitor logs
        the ones still owed). Each step is bounded by `STOP_TIMEOUT_S` and logged when it fails, and
        nothing is raised: a loop that swallows its cancellation does not keep the drain from
        running."""
        self._stopping = True
        tasks, self._tasks = self._tasks, []
        self._failures.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await self._within("loops", STOP_TIMEOUT_S, lambda: asyncio.wait(tasks))
        await self._within("drain", STOP_TIMEOUT_S, self.monitor.drain)

    @staticmethod
    async def _within(step: str, timeout_s: float, wait: Callable[[], Awaitable[object]]) -> None:
        try:
            async with asyncio.timeout(timeout_s):
                await wait()
        except Exception as exc:  # TimeoutError included; cancellation propagates
            logger().error("account_health.stop_step_failed", step=step, error=type(exc).__name__)

    # -- the loops

    async def _tick(self) -> None:
        self.monitor.tick()  # the monitor logs each transition and owes the hook its call

    async def _reconcile(self) -> None:
        await self._reconciler.run_due()

    async def _loop(self, loop: _Loop) -> None:
        while not self._stopping:  # a loop that a cut-off stop abandoned ends with its pass
            try:
                await loop.step()
            except Exception as exc:  # a bug in one pass must not end the loop; cancel propagates
                streak = self._failures[loop.name] = self._failures.get(loop.name, 0) + 1
                if streak == 1 or streak % loop.log_every == 0:
                    logger().error(
                        "account_health.step_failed",
                        task=loop.name,
                        error=type(exc).__name__,
                        consecutive=streak,
                    )
            else:
                self._failures.pop(loop.name, None)
            await self._sleep(loop.every_s)

    def _ended(self, task: asyncio.Task[None]) -> None:
        """Done-callback: a loop ends only when `stop()` cancels it, so any other end is critical,
        and a fault that `fault` reports. It also retrieves the error, so none goes unretrieved."""
        error = None if task.cancelled() else task.exception()
        if not self._stopping:
            logger().critical(
                "account_health.loop_ended",
                task=task.get_name(),
                error=None if error is None else type(error).__name__,
            )


@dataclass(frozen=True, slots=True)
class _Feed:
    """What `ctx.accounts.account_health` serves the private-WS consumer (`AccountHealthFeed`): the
    runtime's four evidence calls and its `fault`, and nothing else of it. A holder of the context
    reaches neither the monitor, nor the cache, nor the lifecycle through it."""

    _runtime: AccountHealthRuntime

    @property
    def fault(self) -> str | None:
        return self._runtime.fault

    def ws_heartbeat(self, account_id: UUID) -> HealthTransition | None:
        return self._runtime.ws_heartbeat(account_id)

    def ws_dropped(self, account_id: UUID) -> HealthTransition | None:
        return self._runtime.ws_dropped(account_id)

    def rest_ok(self, account_id: UUID) -> HealthTransition | None:
        return self._runtime.rest_ok(account_id)

    def wallet_pushed(self, account_id: UUID, snapshot: WalletSnapshot) -> bool:
        return self._runtime.wallet_pushed(account_id, snapshot)


def wire_account_health(
    settings: Settings,
    metrics: Metrics,
    *,
    clock: Clock | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rest: WalletRestPort | None = None,
    dms: DeadMansSwitch | None = None,
    rejections: CredentialRejections | None = None,
) -> AccountHealthRuntime:
    """Build the runtime; `create_app` calls it with nothing but the settings and its metrics. The
    rest are the seams of the bindings that land later and of the tests: the clock, the loops'
    sleep, the exchange's wallet read (E29), the dead-man's-switch hook (E39) and the place a
    credential rejection goes (the key standing). No I/O."""
    clock = clock or SystemClock()
    monitor = AccountHealthMonitor(
        clock, dms or LoggingDeadMansSwitch(), HealthThresholds.from_settings(settings)
    )
    wallets = WalletCache(
        clock,
        WalletThresholds.from_settings(settings),
        old_snapshot_decisions=register_r0(metrics)[OLD_SNAPSHOT_DECISIONS],
    )
    return AccountHealthRuntime(
        monitor,
        wallets,
        rest or UnavailableWalletRest(),
        rejections or LoggingCredentialRejections(),
        sleep=sleep,
    )

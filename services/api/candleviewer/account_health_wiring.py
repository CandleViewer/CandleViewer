"""Composition-root wiring (not a module) for account health and the wallet cache (E27-T04, #837).

`wire_account_health` builds the health monitor, the wallet cache and its REST reconciler from the
settings; `AccountHealthRuntime` runs them in two or three loops that the lifespan starts once the
modules are up and stops, draining the dead-man's-switch calls, before they stop. `create_app`
attaches the runtime's `feed` to `ctx.accounts`, which serves the private-WS consumer (E29-T05,
#848) its evidence calls and wallet feed, so no module imports this file. The monitor and the cache
read the boot-time clock, and the loops sleep on the event loop's: a wall-clock step moves nothing.

- `account-health-tick` calls `tick()` every `TICK_S` (at least once a second), so a lapsed account
  commits its transition and calls the dead-man's switch with or without evidence. It does no I/O,
  and the wallet reads run on their own loop, so a hung read cannot delay it.
- `account-health-reconcile` reads what the wallet reconciler finds due, every `TICK_S`.
- `account-health-tracking` makes the tracked accounts those the repository reports, every
  `TRACKING_REFRESH_S`: the enabled accounts of the process environment that hold a signable key.
  A read that fails keeps the set and is a failed pass. An untracked account has no state
  (`current()` is `None`, which the order-entry gate refuses). The same read feeds the key
  standing. The fake backend has no repository, so it runs no such loop and tracks none.
- Dead-man's-switch episodes outlive the process (#837 W5): the monitor journals each before its
  hook call (`system_events`). The tracking loop's first pass that works is the boot: it replays the
  open ones once and tracks `at_boot`, so an account with no evidence for `down_s` is owed one.

A pass that raises is logged by its error type (a message may echo exchange text, C-12.6) and the
next one runs. A loop that ends, or whose passes keep failing, is a fault: `AccountsService`
reports it as a degraded `accounts` check (AGENTS.md §5.2), and an ended loop is logged critical.
Two bindings are stand-ins that fail closed until their owners land: the exchange's wallet read is
unavailable (E29), so sizing is off once a snapshot is stale after a failed attempt, or a period
old; the dead-man's-switch hook (E39) logs the episode.

The runtime serves health and balances on the WS `wallet` topic (`accounts/wallet_topic.py`), which
`create_app` builds on the gateway's hub and hands in: the topic's snapshots read the monitor and
the cache, and the runtime publishes a health delta when an account's monitoring starts and on each
transition it commits, whichever call commits it (the tick, the feed or the reconciler's `rest_ok`),
and a balance delta on each refresh, pushed or read, and when the tick finds a refreshed balance
turned stale.

`order_entry_check` is the account check of the app's one gate, `OrderEntryGate(maintenance,
order_entry_check)` (#837 W3), over the monitor, the key standing (`accounts.key_standing`) and the
cache; the reconciler reports a rejected credential to the standing, never as health evidence.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, cast, get_args
from uuid import UUID

import structlog

from candleviewer.accounts.health import (
    DMS_HOOK_TIMEOUT_S,
    AccountHealth,
    AccountHealthMonitor,
    Clock,
    DeadMansSwitch,
    EpisodeJournal,
    HealthReason,
    HealthState,
    HealthThresholds,
    HealthTransition,
    SystemClock,
)
from candleviewer.accounts.key_standing import KeyStandings, SelfCheckResults
from candleviewer.accounts.order_gate import AccountHealthCheck
from candleviewer.accounts.wallet import (
    WalletCache,
    WalletReconciler,
    WalletRestPort,
    WalletSnapshot,
    WalletThresholds,
    WalletUnavailable,
)
from candleviewer.accounts.wallet_topic import WalletTopic
from candleviewer.observability import spawn
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.storage.repositories.accounts import SelfCheckTargetRow
from candleviewer.storage.repositories.dms_episodes_sqlalchemy import (
    DmsEpisodeRow,
    SqlAlchemyDmsEpisodeJournal,
)
from candleviewer.storage.repositories.key_selfcheck_sqlalchemy import SqlAlchemyKeySelfCheckStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

if TYPE_CHECKING:
    from candleviewer.accounts.service import AccountHealthFeed
    from candleviewer.observability.metrics import Metrics
    from candleviewer.settings import Settings
    from candleviewer.ws.sequencing import SnapshotBody

#: `tick()` and the reconciler's `run_due()` run this often: at least once a second (`health.py`),
#: and a wallet read that is due waits no longer than this for its pass.
TICK_S: Final = 0.5
#: How often the tracked accounts are read from the repository: a new account is monitored within
#: one interval, and a failed read is retried after one.
TRACKING_REFRESH_S: Final = 15.0
#: The bound on one repository read.
READ_TIMEOUT_S: Final = 10.0
#: The bound on each of the first two steps of a stop, the loops and the drain.
#: `AccountHealthMonitor.drain()` ends within twice the hook timeout, so this only cuts a monitor
#: that breaks that guarantee, or a loop that will not end.
STOP_TIMEOUT_S: Final = 2 * DMS_HOOK_TIMEOUT_S + 1.0
#: The bound on the third, releasing the repository's pool: a dispose takes well under a second,
#: and the three steps together stay inside the default stop budget (`api_stop_budget_s`).
RELEASE_TIMEOUT_S: Final = 3.0
#: How long a loop's passes may keep failing before it is a fault (`fault`, so a degraded
#: `accounts` check). The health tick is what calls the dead-man's switch, and a pass that always
#: fails never does: 5 s, ten passes at `TICK_S`.
FAULT_AFTER_S: Final = 5.0
#: The tracking loop's: a repository that cannot be read leaves a new account untracked (the gate
#: refuses it) and a removed one tracked. A minute is four reads, long enough that a restart of the
#: database is no fault. It also bounds the key standing: the gate refuses every account from the
#: last good read plus this, while `/readyz` reports the loop degraded only at its fourth failed
#: pass in a row, later when reads hang to `READ_TIMEOUT_S` (up to about 100 s after the last good
#: read). The gate refuses first, the safe direction.
TRACKING_FAULT_AFTER_S: Final = 60.0
#: A failing loop logs its first failure and then once in this long, not every pass: the failures
#: are still counted, and `fault` still reports them.
LOG_EVERY_S: Final = 60.0
#: The catalogue's counter of sizing decisions taken on a snapshot older than the period.
OLD_SNAPSHOT_DECISIONS: Final = "cv_wallet_sizing_old_snapshot_total"
#: The open episodes the boot replays, at most (C-2.18; the latest per account): more stay open.
REPLAY_BATCH: Final = 100

MonitoredAccounts = Callable[[], Awaitable[frozenset[UUID]]]
Release = Callable[[], Awaitable[None]]
_STATES: Final = {state.value: state for state in HealthState}
_REASONS: Final = frozenset(get_args(HealthReason))


class EpisodeStore(EpisodeJournal, Protocol):
    """The journal the monitor writes, and the replay read the boot makes of it."""

    async def open_episodes(self, limit: int) -> tuple[DmsEpisodeRow, ...]: ...


def _episode(row: DmsEpisodeRow) -> HealthTransition:
    """An open row's episode; one with codes this version does not know replays as a lapse."""
    reason = cast(HealthReason, row.reason) if row.reason in _REASONS else "no_success"
    state = _STATES.get(row.from_state or "", HealthState.DOWN)
    return HealthTransition(row.account_id, state, HealthState.DOWN, reason, row.at)


def _retrieved(task: asyncio.Task[Any]) -> None:
    """Done-callback of a replay read: its outcome is retrieved, so one left to unwind is never
    reported as unretrieved (its message could echo the driver's text, C-12.6)."""
    if not task.cancelled():
        task.exception()


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
    before it gets here (a dated-ahead snapshot would block every later refresh).

    `monitored` reads the ids of the accounts to track (`None`: the fake backend, nothing is
    tracked and no tracking loop runs); `release` frees what it holds once the runtime has stopped;
    `episodes` is the journal the boot replays (the monitor writes it). `standings` is the key
    standing: the reconciler reports a rejected credential to it, and `order_entry_check`, the
    account check of the app's order-entry gate, reads it with the monitor and the cache. `topic`
    is the `wallet` topic it publishes on. Meant for one event loop, the one that runs the loops and
    the hook calls."""

    def __init__(
        self,
        monitor: AccountHealthMonitor,
        wallets: WalletCache,
        rest: WalletRestPort,
        standings: KeyStandings,
        monitored: MonitoredAccounts | None,
        *,
        topic: WalletTopic[SnapshotBody],
        release: Release | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        episodes: EpisodeStore | None = None,
    ) -> None:
        self.monitor, self.wallets, self.standings = monitor, wallets, standings
        self.topic = topic
        self.order_entry_check = AccountHealthCheck(monitor, standings, wallets)
        self._monitored, self._release, self._episodes = monitored, release, episodes
        self._sleep = sleep
        self._tracked: set[UUID] = set()
        self._booted = False  # a tracking pass has worked: the boot's replay is done
        self._replay: asyncio.Task[tuple[DmsEpisodeRow, ...]] | None = None  # the last replay read
        self._replay_only: set[UUID] = set()  # tracked for a replayed call alone: the monitor's
        self._tasks: list[asyncio.Task[None]] = []
        self._loops: dict[str, _Loop] = {}
        self._failures: dict[str, int] = {}  # passes failed in a row, by loop
        self._stopping = False
        # the reconciler gives its evidence through this runtime, so a stop gates it as the feed
        self._reconciler = WalletReconciler(wallets, rest, self, standings)
        self.feed: AccountHealthFeed = _Feed(self)

    def view(self, account_id: UUID) -> AccountHealth | None:
        """The health the `wallet` topic shows (`HealthViews`): the monitor's, but none for an
        account it tracks for a replayed call alone."""
        return None if account_id in self._replay_only else self.monitor.view(account_id)

    # -- the evidence of the private-WS consumer (`AccountHealthFeed`, through `feed`) and of the
    # wallet reconciler (`HealthEvidence`). Once a stop has begun it gives nothing: evidence could
    # commit a transition and start a dead-man's-switch call that nothing drains, and a read that
    # outlives a cut-off stop is such evidence.

    def current(self, account_id: UUID) -> HealthState | None:
        return self.monitor.current(account_id)

    def ws_heartbeat(self, account_id: UUID) -> HealthTransition | None:
        return None if self._stopping else self._moved(self.monitor.ws_heartbeat(account_id))

    def ws_dropped(self, account_id: UUID) -> HealthTransition | None:
        return None if self._stopping else self._moved(self.monitor.ws_dropped(account_id))

    def rest_ok(self, account_id: UUID) -> HealthTransition | None:
        return None if self._stopping else self._moved(self.monitor.rest_ok(account_id))

    def wallet_pushed(self, account_id: UUID, snapshot: WalletSnapshot) -> bool:
        refreshed = not self._stopping and self.wallets.apply(account_id, snapshot)
        if refreshed:
            self.topic.balance_refreshed(account_id)
        return refreshed

    def _moved(self, transition: HealthTransition | None) -> HealthTransition | None:
        """Publish the health of an account whose state a call just committed, on `wallet`."""
        if transition is not None:
            self.topic.health_changed(transition.account_id)
        return transition

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
        if self._monitored is not None:
            tracking = _Loop(
                "account-health-tracking",
                self.refresh_tracking,
                TRACKING_REFRESH_S,
                TRACKING_FAULT_AFTER_S,
            )
            loops.append(tracking)
        for loop in loops:
            self._loops[loop.name] = loop
            task = spawn(self._loop(loop), name=loop.name)
            task.add_done_callback(self._ended)
            self._tasks.append(task)

    async def stop(self) -> None:
        """Stop the loops, then wait for the dead-man's-switch calls in flight (the monitor logs
        the ones still owed), then release the repository's pool. Each step is bounded (the first
        two by `STOP_TIMEOUT_S`, the third by `RELEASE_TIMEOUT_S`) and logged when it fails, and
        nothing is raised: a loop that swallows its cancellation does not keep the drain from
        running, nor a drain that hangs the release."""
        self._stopping = True
        tasks, self._tasks = self._tasks, []
        self._failures.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await self._within("loops", STOP_TIMEOUT_S, lambda: asyncio.wait(tasks))
        await self._within("drain", STOP_TIMEOUT_S, self.monitor.drain)
        release, self._release = self._release, None
        if release is not None:
            await self._within("release", RELEASE_TIMEOUT_S, release)

    @staticmethod
    async def _within(step: str, timeout_s: float, wait: Callable[[], Awaitable[object]]) -> None:
        try:
            async with asyncio.timeout(timeout_s):
                await wait()
        except Exception as exc:  # TimeoutError included; cancellation propagates
            logger().error("account_health.stop_step_failed", step=step, error=type(exc).__name__)

    async def refresh_tracking(self) -> None:
        """Make the tracked accounts the ones the repository reports; with no repository, do
        nothing. A read that fails or times out raises, and the set stays as it was: an account is
        never untracked on a failed read, and the loop counts the pass as failed. An account that
        leaves the set while a dead-man's-switch call is still owed for it stays tracked until the
        call has returned, so that its episode is not dropped.

        The first pass that works is the boot: it also reads the journal's open episodes, before
        anything is tracked (a failed read fails the pass), tracks its accounts `at_boot` and each
        episode's account too, owed that episode until its call has returned; once only. The wallet
        cache and topic hold the reported accounts, not one tracked for its replay alone."""
        if self._monitored is None:
            return
        async with asyncio.timeout(READ_TIMEOUT_S):
            wanted = await self._monitored()
        replayed = [] if self._booted else await self._replayed()
        owed = {episode.account_id for episode in self.monitor.owed()}
        kept = wanted | {episode.account_id for episode, _ in replayed}
        added = kept - self._tracked
        removed = {account_id for account_id in self._tracked - kept if account_id not in owed}
        shown = wanted & (added | self._replay_only)  # their monitoring starts, for the topic
        self._replay_only = (self._replay_only | added) - wanted - removed
        for account_id in added:
            self.monitor.track(account_id, at_boot=not self._booted)
        for account_id in removed:
            self.monitor.untrack(account_id)
            self.wallets.untrack(account_id)
        for account_id in wanted:  # a replayed account alone is the monitor's, for its call
            self.wallets.track(account_id)
        for account_id in shown:
            self.topic.health_changed(account_id)  # its monitoring starts (§15.4)
        for episode, row in replayed:
            self.monitor.replay(episode, row)
        self._tracked = (self._tracked - removed) | added
        self._booted = True
        if added or removed:
            logger().info(
                "account_health.tracking_changed",
                tracked=len(self._tracked),
                added=len(added),
                removed=len(removed),
            )

    async def _replayed(self) -> list[tuple[HealthTransition, int]]:
        """The open episodes, read as the monitor writes them: as a task of its own that the pass
        waits for, `READ_TIMEOUT_S` at most. One still running then fails the pass and is cancelled
        but never awaited (a driver's cleanup can wait on a stuck server); until it has ended, a
        pass starts no other and fails at once."""
        if self._episodes is None:
            return []
        if self._replay is not None and not self._replay.done():
            raise TimeoutError
        read = self._replay = spawn(
            self._episodes.open_episodes(REPLAY_BATCH + 1), name="account-health-replay"
        )
        read.add_done_callback(_retrieved)
        try:
            await asyncio.wait({read}, timeout=READ_TIMEOUT_S)
        finally:
            read.cancel()  # a no-op once it is done; else it was cut off, or the pass cancelled
        if not read.done() or read.cancelled():  # cut off, or cancelled by its driver
            raise TimeoutError
        rows = read.result()
        if len(rows) > REPLAY_BATCH:
            logger().error("account_health.replay_truncated", replayed=REPLAY_BATCH)
        return [(_episode(row), row.row) for row in rows[:REPLAY_BATCH]]

    # -- the loops

    async def _tick(self) -> None:
        for transition in self.monitor.tick():  # the monitor logs each one and owes the hook
            self._moved(transition)
        self.topic.stale_check()

    async def _reconcile(self) -> None:
        polls = await self._reconciler.run_due()  # a read's `rest_ok` went through `rest_ok` above
        for poll in polls:
            if poll.refreshed:
                self.topic.balance_refreshed(poll.account_id)

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


class _UsableKeys(Protocol):
    """The one call of the stored-key self-check's port that the runtime makes. Typing the store
    as this lets mypy refuse a write; the pin in
    `tests/unit/architecture/test_key_selfcheck_store_callers.py` refuses any mention of one."""

    async def targets(self) -> tuple[SelfCheckTargetRow, ...]: ...


def _repository_source(
    settings: Settings, standings: KeyStandings
) -> tuple[MonitoredAccounts | None, Release | None, EpisodeStore | None]:
    """The real backend's tracking source: the usable-key read of the stored-key self-check, on a
    store of its own bound to the process environment (C-2.11), reduced to the ids of the enabled
    accounts. The key standing takes the same read's rows of that environment and keeps none of
    them; the runtime never holds a row, and the store is typed as the read alone. The fake
    backend has none. The dead-man's-switch episode journal shares its pool and environment."""
    if settings.storage_backend != "real":
        return None, None, None
    env = settings.environment.value
    relational = SqlAlchemyRelationalRepository(
        settings.pg_dsn.get_secret_value(), "account-health"
    )
    store: _UsableKeys = SqlAlchemyKeySelfCheckStore(relational, env=env)
    foreign_said = 0  # the rows of another environment the last read said it found

    async def monitored() -> frozenset[UUID]:
        nonlocal foreign_said
        rows = await store.targets()
        foreign = sum(row.account.env != env for row in rows)
        if foreign and foreign != foreign_said:
            # the store filters on `env`: a row of another environment is a bug, said once per
            # change, not at every read
            logger().error("account_health.env_mismatch", rows=foreign)
        foreign_said = foreign
        own = [row for row in rows if row.account.env == env]
        standings.observe(own)
        return frozenset(row.account.id for row in own if row.account.is_enabled)

    return monitored, relational.dispose, SqlAlchemyDmsEpisodeJournal(relational, env=env)


def wire_account_health(
    settings: Settings,
    metrics: Metrics,
    topic: WalletTopic[SnapshotBody],
    *,
    selfcheck: SelfCheckResults | None = None,
    clock: Clock | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rest: WalletRestPort | None = None,
    dms: DeadMansSwitch | None = None,
    monitored: MonitoredAccounts | None = None,
    release: Release | None = None,
    journal: EpisodeStore | None = None,
) -> AccountHealthRuntime:
    """Build the runtime; `create_app` calls it with the settings, its metrics, the `wallet` topic,
    which this attaches to the runtime and the cache, and the stored-key self-check whose results
    the key standing reads (`None` on the fake backend, which has none). The rest are the seams of
    the bindings that land later and of the tests: the clock (the standing reads its wall time, the
    one the self-check dates passes on, and ages its last good read on the monotonic one), the
    loops' sleep, the exchange's wallet read (E29), the dead-man's-switch hook (E39), and the
    tracking source with the release of its pool and the episode journal on its database
    (`monitored` is the repository read; with none of the three given, the real backend's, which
    also feeds the standing). A `release` or a `journal` without the `monitored` it goes with is
    refused. No I/O."""
    clock = clock or SystemClock()
    standings = KeyStandings(
        selfcheck,
        interval_s=settings.selfcheck_interval_s,
        stale_after_s=TRACKING_FAULT_AFTER_S,
        clock=clock,
    )
    if monitored is None:
        if release is not None or journal is not None:
            raise ValueError("a release or a journal goes with the `monitored` read: pass it too")
        monitored, release, journal = _repository_source(settings, standings)
    thresholds = HealthThresholds.from_settings(settings)
    monitor = AccountHealthMonitor(
        clock, dms or LoggingDeadMansSwitch(), thresholds, journal=journal
    )
    wallets = WalletCache(
        clock,
        WalletThresholds.from_settings(settings),
        old_snapshot_decisions=register_r0(metrics)[OLD_SNAPSHOT_DECISIONS],
    )
    runtime = AccountHealthRuntime(
        monitor,
        wallets,
        rest or UnavailableWalletRest(),
        standings,
        monitored,
        topic=topic,
        release=release,
        sleep=sleep,
        episodes=journal,
    )
    topic.attach(runtime, wallets)
    return runtime

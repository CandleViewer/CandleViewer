"""Lifecycle contract for the storage module (M10).

Wires the in-memory fakes when `Settings.storage_backend == "fake"` (the CI/dev default — no
database containers required, ticket acceptance criterion 1). On `"real"` (#3874) it builds the
E07-T02/T03/T04 tier clients (`storage.real_tiers`) and probes each one in start order
(postgres, questdb, cold), each within `probe_timeout_s`. A tier that cannot answer fails the
start closed: every client is closed again and `StorageTierUnavailable` names the tier and the
probe error's type, never a DSN (C-12.6). Nothing is written by a start, failed or not. Once every
tier answers, the start checks the runtime role's guarded privileges (`storage.guarded_privileges`,
#3998) within `probe_timeout_s`: in `live` a held one, a pinned table missing from `public` or a
check that cannot run fails the start closed the same way (`GuardedPrivilegesHeld`). Elsewhere
its held and missing counts stay in `tier_health()`, and `/readyz` is degraded while either is
above 0.

Once started, the real tiers are probed again every `probe_interval_s` by one task the service
owns; `tier_health()` reports the latest probe of each, for `/readyz` and the health screen. A
postgres that cannot answer is `down` (readiness-blocking); a questdb or cold tier that cannot is
`degraded`, the serving-but-impaired state `StorageTierUnavailable` describes.

`stop(grace_s)` stops that task and gives tracked writes up to half of `grace_s`, cancelling the
ones still running; then it closes the tiers in reverse start order within the rest, each close
told its share of what is left, so a hung QuestDB drain cannot starve the Postgres pool's
dispose. A cancellation of `stop()` interrupts the close in flight and still runs every later
one, then propagates (as `Supervisor._stop_each`, #3361). It is idempotent: calling it twice, or
before `start()`, never raises. The real backend has no `RetentionRepository`: retention runs
through the recorder's wiring (`retention_wiring`, E16).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Final

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.settings import Environment
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.guarded_privileges import check_guarded_privileges
from candleviewer.storage.health import (
    GuardedPrivilegesHealth,
    StorageHealthReport,
    TierHealth,
    TierState,
)
from candleviewer.storage.models import StorageTier
from candleviewer.storage.real_tiers import RealTier, RealTiers, build_real_tiers
from candleviewer.storage.repositories import (
    ColdTierRepository,
    MarketDataRepository,
    RelationalRepository,
    RetentionRepository,
)
from candleviewer.storage.testing import (
    FakeColdTierRepository,
    FakeMarketDataRepository,
    FakeRelationalRepository,
    FakeRetentionRepository,
)

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.observability.metrics import MetricChild
    from candleviewer.settings import Settings

#: Bound on one tier's probe, at start and on every later round.
PROBE_TIMEOUT_S: Final = 5.0
#: Pause between two probe rounds of a started real backend.
PROBE_INTERVAL_S: Final = 15.0
#: Bound on closing the tiers again after a failed start (its `stop()` never runs).
START_FAILURE_CLOSE_S: Final = 5.0
#: The most of the tracked writes' window kept for the cancelled ones to unwind (a fifth of it,
#: up to this).
UNWIND_MAX_S: Final = 1.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _left(until: float) -> float:
    return max(0.0, until - asyncio.get_running_loop().time())


class StorageService:
    """M10 `storage` module lifecycle: constructs and owns the three tier
    clients (market data, relational, cold) plus retention, per
    `docs/plan/20-architecture.md` Sec.6.1 ("no module constructs its own
    dependencies" — this *is* that construction site, injected into
    `AppContext` by `candleviewer.app.build_app_context`)."""

    def __init__(
        self,
        backend: str = "fake",
        *,
        real_tiers: Callable[[Settings], RealTiers] = build_real_tiers,
        probe_timeout_s: float = PROBE_TIMEOUT_S,
        probe_interval_s: float = PROBE_INTERVAL_S,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._backend = backend
        self._started = False
        self._market_data: MarketDataRepository | None = None
        self._relational: RelationalRepository | None = None
        self._cold: ColdTierRepository | None = None
        self._retention: RetentionRepository | None = None
        self._pending_writes: set[asyncio.Task[None]] = set()
        self._build_real = real_tiers
        self._probe_timeout_s = probe_timeout_s
        self._probe_interval_s = probe_interval_s
        self._clock = clock
        #: The started real tiers, in start order; empty on the fake backend.
        self._tiers: tuple[RealTier, ...] = ()
        self._tier_health: dict[StorageTier, TierHealth] = {}
        self._prober: asyncio.Task[None] | None = None
        #: Serialises `start()`: a second call waits, then finds the service started.
        self._start_lock = asyncio.Lock()
        self._privileges_gauge: MetricChild | None = None
        #: What the start's guarded-privilege check counted (#3998); None until one has run.
        self._privileges: GuardedPrivilegesHealth | None = None

    @property
    def market_data(self) -> MarketDataRepository:
        if self._market_data is None:
            raise StorageTierUnavailable("storage.start() has not been called")
        return self._market_data

    @property
    def relational(self) -> RelationalRepository:
        if self._relational is None:
            raise StorageTierUnavailable("storage.start() has not been called")
        return self._relational

    @property
    def cold(self) -> ColdTierRepository:
        if self._cold is None:
            raise StorageTierUnavailable("storage.start() has not been called")
        return self._cold

    @property
    def retention(self) -> RetentionRepository:
        if self._retention is None:
            raise StorageTierUnavailable(
                "the real storage backend has no RetentionRepository: retention runs through "
                "retention_wiring (E16)"
                if self._started
                else "storage.start() has not been called"
            )
        return self._retention

    def attach_privileges_gauge(self, gauge: MetricChild) -> None:
        """Wire `cv_db_guarded_privileges_held` (`create_app`), which the start's check sets."""
        self._privileges_gauge = gauge

    async def start(self, ctx: AppContext) -> None:
        """Construct and connect the configured tier clients; a second call before `stop()`,
        concurrent or not, changes nothing.

        On the `fake` backend this performs no I/O by construction — the fakes hold everything
        in memory. On `real` it probes each tier in start order and raises
        `StorageTierUnavailable` naming the first one that cannot answer, after closing every
        client again, so a misconfigured environment fails loudly at boot instead of serving
        with a missing tier. Then it checks the runtime role's guarded privileges (#3998): in
        `live` a held pair, a pinned table missing from `public` or a check that cannot run
        raises `GuardedPrivilegesHeld`, after closing every client again too.
        """
        async with self._start_lock:
            await self._start(ctx)

    async def _start(self, ctx: AppContext) -> None:
        if self._started:
            return
        if self._backend == "fake":
            self._market_data = FakeMarketDataRepository()
            self._relational = FakeRelationalRepository()
            self._cold = FakeColdTierRepository()
            self._retention = FakeRetentionRepository()
            self._started = True
            return
        if self._backend != "real":
            raise StorageTierUnavailable(f"unknown storage_backend {self._backend!r}")
        built = self._build_real(ctx.settings)
        privileges: GuardedPrivilegesHealth | None = None
        try:
            for tier in built.tiers:
                health = await self._probe(tier)
                if health.state is not TierState.OK:
                    _log().error("storage_tier_unreachable_at_start", tier=tier.tier)
                    raise StorageTierUnavailable(
                        f"storage tier {tier.tier!r} is unreachable at start ({health.detail})"
                    )
                self._tier_health[tier.tier] = health
            if built.guarded_privileges is not None:  # #3998: on the relational tier's login
                privileges = await check_guarded_privileges(
                    built.guarded_privileges,
                    live=ctx.settings.environment is Environment.LIVE,
                    gauge=self._privileges_gauge,
                    timeout_s=self._probe_timeout_s,
                )
        except BaseException:
            self._tier_health.clear()
            loop = asyncio.get_running_loop()
            await self._close(built.tiers, loop.time() + START_FAILURE_CLOSE_S)
            raise
        self._privileges = privileges
        self._tiers = built.tiers
        self._market_data = built.market_data
        self._relational = built.relational
        self._cold = built.cold
        self._started = True
        self._prober = spawn(self._probe_loop(), name="storage-tier-probes")

    async def refresh(self) -> StorageHealthReport:
        """Probe every started real tier once (each within `probe_timeout_s`) and keep the
        results for `tier_health()`. The probe task runs this every `probe_interval_s`."""
        for tier in self._tiers:
            health = await self._probe(tier)
            previous = self._tier_health.get(tier.tier)
            if previous is not None and previous.state is not health.state:
                _log().warning(
                    "storage_tier_state_changed",
                    tier=tier.tier,
                    state=health.state.value,
                    previous=previous.state.value,
                )
            self._tier_health[tier.tier] = health
        return self.tier_health()

    async def _probe_loop(self) -> None:
        """Re-probe every `probe_interval_s` until `stop()`. A round that fails outside a probe
        is logged and the next one still runs, so readiness never freezes at an old state."""
        while True:
            await asyncio.sleep(self._probe_interval_s)
            try:
                await self.refresh()
            except Exception as exc:  # a cancellation is `stop()`'s and propagates
                _log().error("storage_tier_probe_round_failed", error=type(exc).__name__)

    async def _probe(self, tier: RealTier) -> TierHealth:
        """One bounded probe of `tier`. Its failure is a state, never an exception; only a
        cancellation propagates. The detail names the error's type, never its message, which
        may carry a host or a user name (C-12.6)."""
        started = self._clock()
        try:
            async with asyncio.timeout(self._probe_timeout_s):
                await tier.probe()
        except Exception as exc:  # incl. the bound's TimeoutError; CancelledError propagates
            failed = TierState.DOWN if tier.tier == "postgres" else TierState.DEGRADED
            return TierHealth(
                tier=tier.tier,
                state=failed,
                latency_ms=(self._clock() - started) * 1000,
                detail=type(exc).__name__,
            )
        return TierHealth(
            tier=tier.tier, state=TierState.OK, latency_ms=(self._clock() - started) * 1000
        )

    async def stop(self, grace_s: float) -> None:
        """Stop the probe task, give tracked writes up to half of `grace_s`, then close the tiers
        in reverse start order within the rest.

        Deterministic drain, never leaves an "Event loop is closed" warning (ticket acceptance
        criterion 4): a tracked write still running at its bound is cancelled, and the
        cancellation is awaited within the same bound, so a task that ignores it cannot hold the
        stop. A cancellation of this coroutine interrupts the close in flight and still runs every
        later one, then propagates.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + grace_s
        interrupted: BaseException | None = None
        try:
            await self._quiesce(loop.time() + grace_s / 2)
        except BaseException as exc:  # a cancellation: the tiers still close, then it propagates
            interrupted = exc
        tiers, self._tiers = self._tiers, ()
        try:
            await self._close(tiers, deadline)
        finally:
            self._tier_health.clear()
            self._market_data = None
            self._relational = None
            self._cold = None
            self._retention = None
            self._started = False
        if interrupted is not None:
            raise interrupted

    async def _quiesce(self, until: float) -> None:
        """Cancel the probe task and give tracked writes until `until`, less the last fifth of
        that window (at most `UNWIND_MAX_S`); every write still running then is cancelled and
        gets that last part to unwind, even when this is cancelled. One that is still unwinding
        at `until` ends on its own."""
        prober, self._prober = self._prober, None
        pending = list(self._pending_writes)
        self._pending_writes.clear()
        if prober is not None:
            prober.cancel()
        unwind = min(UNWIND_MAX_S, _left(until) / 5)
        try:
            if pending:
                await asyncio.wait(pending, timeout=max(0.0, _left(until) - unwind))
        finally:
            for task in pending:
                task.cancel()  # a finished task ignores it
            owned = pending if prober is None else [prober, *pending]
            if owned:
                await asyncio.wait(owned, timeout=_left(until))

    async def _close(self, tiers: Iterable[RealTier], deadline: float) -> None:
        """Close `tiers` in reverse order, each within an equal share of what is left until
        `deadline`, and told that share. A close that fails or overruns is logged and the next
        one still runs. So does one a cancellation interrupts: the first such exception is
        re-raised once the last close has run, as `Supervisor._stop_each` does (#3361), so no
        pool is left open."""
        interrupted: BaseException | None = None
        remaining = list(reversed(tuple(tiers)))
        while remaining:
            tier = remaining.pop(0)
            share = _left(deadline) / (len(remaining) + 1)
            try:
                async with asyncio.timeout(share):
                    await tier.close(share)
            except BaseException as exc:  # incl. the share's TimeoutError and a cancellation
                _log().warning(
                    "storage_tier_close_failed", tier=tier.tier, error=type(exc).__name__
                )
                if interrupted is None and not isinstance(exc, Exception):
                    interrupted = exc
        if interrupted is not None:
            raise interrupted

    def track_write(self, task: asyncio.Task[None]) -> None:
        """Register an in-flight write task so `stop()` can drain it
        deterministically. Callers issuing fire-and-forget writes must use
        this instead of a bare `create_task` (C-2.18: every task is owned)."""
        self._pending_writes.add(task)
        task.add_done_callback(self._pending_writes.discard)

    def health(self) -> HealthReport:
        """Module-wide health for the supervisor (`HealthReport`).

        `ok` only once started with every configured tier healthy; a
        `postgres` tier reporting `down` degrades the whole module (ticket:
        "readiness requires postgres=ok"). See `tier_health()` for the
        finer-grained per-tier report `/readyz` and the health screen use.
        """
        report = self.tier_health()
        pg = report.tier("postgres")
        if not self._started:
            status = HealthStatus.STOPPED
        elif pg is not None and pg.state != TierState.DOWN:
            status = HealthStatus.OK
        else:
            status = HealthStatus.DEGRADED
        return HealthReport(module="storage", status=status, detail="")

    def tier_health(self) -> StorageHealthReport:
        """Per-tier health (`{tier, state, latency_ms, detail}`, ticket
        "Technical notes / design"). On the `fake` backend all three tiers
        (`postgres`, `questdb`, `cold`) report `ok`/`"fake/healthy"` — the
        ticket's acceptance criterion 1 wording exactly — with `latency_ms`
        ~0 since no I/O occurs. On `real`, each tier's latest probe (#3874), read once per
        tier: the sync `/readyz` handler calls this from a worker thread; and what the start's
        guarded-privilege check counted (#3998), which only a start outside `live` can leave
        above 0."""
        if not self._started:
            return StorageHealthReport(tiers=())
        if self._backend == "fake":
            started = time.perf_counter()
            latency_ms = (time.perf_counter() - started) * 1000
            return StorageHealthReport(
                tiers=tuple(
                    TierHealth(
                        tier=tier,
                        state=TierState.OK,
                        latency_ms=latency_ms,
                        detail="fake/healthy",
                    )
                    for tier in ("postgres", "questdb", "cold")
                )
            )
        health = self._tier_health
        return StorageHealthReport(
            tiers=tuple(h for t in self._tiers if (h := health.get(t.tier)) is not None),
            guarded_privileges=self._privileges,
        )

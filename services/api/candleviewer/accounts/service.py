"""Lifecycle contract for the accounts module (M13) and its row gauges (#2314).

Every module implements the lifecycle contract from `docs/plan/20-architecture.md` Sec.3:
`start`, `stop`, `health`. On the real backend `create_app()` attaches the M10 aggregate counts
and the two catalogue gauges, and `start()` runs ONE supervised loop that refreshes
`cv_accounts_rows{env,kind}` and `cv_api_keys_rows{env,state}` every `REFRESH_INTERVAL_S`.

- The reads are scoped to the process environment (20 §7.1: queries never cross environments),
  which is also the metrics facade's `env` label, so demo rows never show as live (C-2.11).
- Every value of the closed `account_kind` / `key_status` enums is set on each refresh, zero when
  absent, so a vanished category reads 0, never its stale count.
- A failed or timed-out read, or a failed publish, keeps the last values, counts the failure
  (consecutive, reset on success) and degrades `health()`; it never stops the loop or the app.
- A loop that still dies is logged by its done-callback and reads DEGRADED at once
  (AGENTS.md §5.2 async hygiene: no silent task).
- The fake backend attaches nothing: no loop runs and the gauges stay unset.

`attach_key_selfcheck()` takes the stored-key self-check (E27-T03, `accounts.selfcheck`). Nothing
attaches it yet: its Postgres adapter, exchange calls and wiring are #836 slice 2b. Once attached,
`start()` awaits its boot assertion, so it ends before the app serves, `stop()` stops its loop,
and `health()` reads DEGRADED while any key fails it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Final

import structlog

from candleviewer.accounts.models import AccountKind, KeyStatus
from candleviewer.observability import spawn
from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.accounts.selfcheck import KeySelfCheck
    from candleviewer.app import AppContext
    from candleviewer.observability.metrics import BoundedMetric
    from candleviewer.storage.repositories.accounts import AccountsRowCounts

#: The tables change only on owner actions, so one read a minute is fresh enough.
REFRESH_INTERVAL_S: Final = 60.0
#: Bound on each aggregate read (every external await has a timeout).
READ_TIMEOUT_S: Final = 10.0
#: A last good refresh older than this many intervals reads DEGRADED (a wedged loop).
STALE_AFTER_INTERVALS: Final = 3
_KINDS: Final = tuple(k.value for k in AccountKind)
_STATES: Final = tuple(s.value for s in KeyStatus)
_MODULE: Final = "accounts"


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _log_loop_exit(task: asyncio.Task[None]) -> None:
    """Done-callback (AGENTS.md §5.2): logs, and so retrieves, the error that ended the loop."""
    error = None if task.cancelled() else task.exception()
    if error is not None:
        logger().error("accounts_row_gauges_loop_died", error=type(error).__name__)


class AccountsService:
    """M13 lifecycle; publishes the account and API-key row gauges and, once one is attached,
    runs the stored-key self-check."""

    def __init__(
        self,
        *,
        interval_s: float = REFRESH_INTERVAL_S,
        timeout_s: float = READ_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval_s = interval_s
        self._timeout_s = timeout_s
        self._clock = clock
        self._sleep = sleep
        self._counts: AccountsRowCounts | None = None
        self._gauges: tuple[BoundedMetric, BoundedMetric] | None = None
        self._env = ""
        self._task: asyncio.Task[None] | None = None
        self._started = False
        self._last_ok: float | None = None
        self._failures = 0
        self._selfcheck: KeySelfCheck | None = None

    def attach_row_gauges(
        self,
        counts: AccountsRowCounts,
        accounts_rows: BoundedMetric,
        api_keys_rows: BoundedMetric,
        *,
        env: str,
    ) -> None:
        """Wire the store and the catalogue gauges (`create_app`, real backend only)."""
        self._counts = counts
        self._gauges = (accounts_rows, api_keys_rows)
        self._env = env

    def attach_key_selfcheck(self, selfcheck: KeySelfCheck) -> None:
        """Wire the stored-key self-check (the wiring of #836 slice 2b; nothing calls it yet)."""
        self._selfcheck = selfcheck

    async def start(self, ctx: AppContext) -> None:
        """Run the key self-check's boot assertion, then start the loops that are wired."""
        self._started = True
        if self._selfcheck is not None:
            await self._selfcheck.start()
        if self._counts is not None and self._task is None:
            self._task = spawn(self._loop(), name="accounts-row-gauges")
            self._task.add_done_callback(_log_loop_exit)

    async def stop(self, grace_s: float) -> None:
        """Stop the key self-check's loop, then cancel the refresh loop and wait for it (it only
        awaits a read or the sleep)."""
        self._started = False
        if self._selfcheck is not None:
            await self._selfcheck.stop()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def refresh_once(self) -> bool:
        """Publish one refresh; on a read, timeout or publish error keep the last values and
        count it (never raised, so the loop survives)."""
        if self._counts is None or self._gauges is None:
            return False
        rows, key_rows = self._gauges
        try:
            async with asyncio.timeout(self._timeout_s):
                accounts = await self._counts.count_accounts_by_kind(self._env)
            async with asyncio.timeout(self._timeout_s):
                keys = await self._counts.count_api_keys_by_status(self._env)
            for kind in _KINDS:
                rows.labels(kind).set(accounts.get(kind, 0))
            for state in _STATES:
                key_rows.labels(state).set(keys.get(state, 0))
        except Exception as exc:  # TimeoutError included; cancellation still propagates
            self._failures += 1
            logger().warning(
                "accounts_row_gauges_refresh_failed",
                error=type(exc).__name__,  # the type only: driver text can name hosts
                consecutive_failures=self._failures,
            )
            return False
        self._failures = 0
        self._last_ok = self._clock()
        return True

    async def _loop(self) -> None:
        while True:
            await self.refresh_once()
            await self._sleep(self._interval_s)

    def health(self) -> HealthReport:
        """Synchronous; reports the last refresh age, never touches the store."""
        status, detail = self._health()
        return HealthReport(module=_MODULE, status=status, detail=detail)

    def _health(self) -> tuple[HealthStatus, str]:
        if not self._started:
            return HealthStatus.STOPPED, "stopped"
        if self._selfcheck is not None and self._selfcheck.failing:
            return (
                HealthStatus.DEGRADED,
                f"{self._selfcheck.failing} stored key(s) fail the self-check",
            )
        if self._counts is None:
            return HealthStatus.OK, "no accounts store (fake backend): row gauges unset"
        if self._task is not None and self._task.done():  # before a first success, too
            return HealthStatus.DEGRADED, "row gauge loop exited"
        age = None if self._last_ok is None else self._clock() - self._last_ok
        since = "never" if age is None else f"{age:.0f}s ago"
        if self._failures:
            failing = f"row gauges: {self._failures} consecutive refresh failures, last ok {since}"
            return HealthStatus.DEGRADED, failing
        if age is None:
            return HealthStatus.OK, "row gauges: first refresh pending"
        if age > STALE_AFTER_INTERVALS * self._interval_s:
            return HealthStatus.DEGRADED, f"row gauges stale: last refresh {since}"
        return HealthStatus.OK, f"row gauges refreshed {since}"

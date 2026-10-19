"""The bars heal driver (#2787 D2-H1, decision D-H1 = A; `23-ws-protocol.md` §7.4).

One supervised task re-reads the held WS bars series that the series store lists as not complete
(`SeriesStore.due`: not `hydrated`, or `gapped`). `BarsRuntime` builds and owns it only when
`bars_enabled` is on (C-4.13), so with the flag off no driver or task exists.

- **Each tick** (every `interval_s`, through the injected `sleep`) takes at most `CONCURRENCY`
  keys, the earliest due first, and refreshes them at once (`SeriesStore.refresh`). That is half the
  read slots (`MAX_CONCURRENT_TAIL_READS`), so a subscriber's first read still finds one. The store
  spaces the reads: none sooner than the series' re-read interval after its last read
  (`retry_after_s`, more for a gap or misses that stay), and one read per series.
- **Each refresh** is bounded by the store's `timeout_s` (a read and its wait for a slot) plus
  `HEAL_REFRESH_MARGIN_S`: a cut read's unwind, and slack. A read whose deadline passes before its
  reader has unwound is a failed read with its next read time set, whoever cancelled it first (its
  waiters keep that result); one that unwinds before its deadline sets none. A refresh that
  raises, or outlives the bound (a defect either way), is counted and logged; the loop goes on.
- **Repairs** reach subscribers through the store's repair hook, which follows the read's fold with
  no await between (§7.4); nothing here reads or compares a snapshot.
- **Owned (C-2.18):** `start` spawns the one task (`spawn`); `stop` cancels it and waits for it, so
  the refreshes in flight end first. A cancellation is never swallowed, `stop`'s own included. A
  tick's `gather` returns only once each refresh has ended, however it ends; a task that ends
  other than through `stop` is logged (`bars_heal_driver_ended`).

`bars_heal_refresh_total{result}` counts each refresh: `repaired`, `unchanged` (no repair, a failed
read included: the store counts that), `timeout` and `error`; and each `tick_error`, a tick that
raised before any refresh. A fault logs once a streak: a series' first failed refresh since one
that ended, or the first of failing ticks in a row. The counter counts every one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Final, Literal

import structlog

from candleviewer.bars.leases import Key
from candleviewer.bars.limits import HEAL_REFRESH_MARGIN_S, MAX_CONCURRENT_TAIL_READS
from candleviewer.bars.metrics import bars_heal_refresh_total
from candleviewer.bars.series_store import MAX_SERIES, SeriesStore
from candleviewer.observability.context import spawn

#: Refreshes at once, at most: half the read slots, so subscribers' first reads keep the rest.
CONCURRENCY: Final = MAX_CONCURRENT_TAIL_READS // 2
#: How often the driver asks the store what is due.
INTERVAL_S: Final = 1.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class HealDriver:
    """The heal driver described in the module docstring."""

    def __init__(
        self,
        store: SeriesStore,
        *,
        interval_s: float = INTERVAL_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._store, self._interval_s, self._sleep = store, interval_s, sleep
        self._task: asyncio.Task[None] | None = None
        #: Series whose last refresh failed: the next failure logs nothing. Bounded by `MAX_SERIES`.
        self._failing: set[Key] = set()

    def start(self) -> None:
        """Spawn the driver's one task; a second call while it runs does nothing."""
        if self._task is None:
            self._task = spawn(self._run(), name="bars-heal-driver")
            self._task.add_done_callback(self._ended)

    async def stop(self) -> None:
        """Cancel the task and wait for it, and so for the refreshes in flight. A cancellation of
        this caller propagates: `gather` passes it on."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _ended(self, task: asyncio.Task[None]) -> None:
        """Done-callback: `stop` lets go of the task first, so one still held here ended otherwise
        (it raised, or a cancellation not `stop`'s): a defect, logged."""
        if task is self._task:
            error = "CancelledError" if task.cancelled() else type(task.exception()).__name__
            _log().error("bars_heal_driver_ended", error_type=error)

    async def _run(self) -> None:
        failing = False  # the last tick raised: a streak's later ticks count, and log nothing
        while True:
            await self._sleep(self._interval_s)
            try:
                await self.tick()
            except Exception as exc:  # broad on purpose: the loop outlives a bad tick
                bars_heal_refresh_total.labels(result="tick_error").inc()
                if not failing:
                    _log().error(
                        "bars_heal_tick_failed", error_type=type(exc).__name__, error=str(exc)[:120]
                    )
                failing = True
            else:
                failing = False

    async def tick(self) -> None:
        """One pass: refresh what the store lists as due, at most `CONCURRENCY` at once. `gather`
        returns once every refresh has ended, and one that raised (a cancellation that is not the
        driver's included) counts as `error`: one series' fault never ends the tick."""
        keys = self._store.due(self._store.now(), limit=CONCURRENCY)
        ends = await asyncio.gather(*map(self._refresh, keys), return_exceptions=True)
        for key, end in zip(keys, ends, strict=True):
            if isinstance(end, BaseException):
                self._failed(key, "error", end)

    async def _refresh(self, key: Key) -> None:
        try:
            async with asyncio.timeout(self._store.timeout_s + HEAL_REFRESH_MARGIN_S):
                repaired = await self._store.refresh(*key)
        except TimeoutError as exc:
            self._failed(key, "timeout", exc)
        else:
            self._failing.discard(key)  # ends the series' streak of failed refreshes
            bars_heal_refresh_total.labels(result="repaired" if repaired else "unchanged").inc()

    def _failed(self, key: Key, result: Literal["timeout", "error"], exc: BaseException) -> None:
        """Count a refresh that timed out or raised; log it only as its series' first in a row."""
        bars_heal_refresh_total.labels(result=result).inc()
        if key in self._failing:
            return
        if len(self._failing) >= MAX_SERIES:  # series freed since: their streaks are forgotten
            self._failing.clear()
        self._failing.add(key)
        symbol, spec_hash = key
        _log().error(
            "bars_heal_refresh_failed", spec_hash=spec_hash, symbol=symbol, result=result,
            error_type=type(exc).__name__, error=str(exc)[:120],
        )  # fmt: skip

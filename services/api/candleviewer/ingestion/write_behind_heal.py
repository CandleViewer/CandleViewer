"""Write-behind healer: re-ingest the hot-tier holes `WriteBehindBuffer` records (#1944).

One supervised task per buffer, after the `bars/heal_driver.py` pattern and the
`TradeStream._retry_unrecovered` template (#2715). Rules (the #1944 BQ rulings):

* **Trigger** — every `interval_s` (injected `sleep`), once the buffer's writer has stayed
  recovered (`degraded` false, `failed_writes` unchanged) for `HEAL_SETTLE_S`: `degraded` clears
  on any one success, so a flapping store is debounced, a flap between two passes included.
  Only *closed* runs are worked; the open one is still growing.
* **Trades** — one REST recent-trade page per symbol (`fetch_recent`, the one `TradeStream`
  backfills with: its REST client's governor owns the 10006 / 10018 backoff, so there is no
  second limiter here). The page's prints inside a run are written straight through the
  `TradeWriter` port, real `trade_id` / `ts`, never via the live topic or `TradeStream`'s dedupe
  ring; re-ingest is idempotent through the `trades` DEDUP key `(ts, symbol, trade_id)`.
* **Covered** — the page-spans-the-run rule of `TradeStream._retry_unrecovered`, made strict at
  the start: oldest print *before* the run's start, newest past its end. Prints share a
  millisecond (`ts` is ms x 1000) and the page can cut through its oldest one, so a run starting
  in that millisecond may have lost prints the page never shows. A run the page no longer reaches
  back past never will (pages only move forward): it is *unrecoverable*. A covered run is then
  *verified* by
  reading its range back (`HotTradeReader`): every page print inside it must be there, re-read
  once after `WAL_LAG_RETRY_S` on a short read (QuestDB WAL lag). Verified runs are dropped
  with `WriteBehindBuffer.clear` against the pre-heal snapshot (a run that changed meanwhile
  stays whole). Anything else is *partial* and retried on a capped, jittered per-symbol backoff.
* **Horizon** — a run still unhealed `HEAL_HORIZON_S` after this task first saw it (in any pass,
  worked or not) is *unrecoverable*. An unrecoverable run is counted and logged once and leaves
  the work set only: it stays in `lost_ranges()` (lost rows are never hidden). A run the buffer's
  run cap merged out of an unrecoverable one inherits that status uncounted.
* **Book buffers** (`fetch_recent=None`) — L2 history cannot be re-fetched: each closed run is
  unrecoverable at once (metric + log). No book-gap surface exists yet: a new one is
  contract-first (TODO #1944, the `24` §19 follow-up).
* **Bounds (C-2.18)** — one task, one fetch in flight (symbols are healed in turn), at most
  `MAX_WORK_RUNS` runs per pass, and every external await under a timeout.

`write_behind_heal_ranges_total{table,result}` counts runs per attempt (`healed`, `partial`,
`error`; `unrecoverable` once per run); `write_behind_heal_rows_total{table}` the prints written.
Plain code, never a statechart (catalogue §1.2).
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.ingestion._logging import get_logger
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.metrics import (
    write_behind_heal_ranges_total,
    write_behind_heal_rows_total,
)
from candleviewer.ingestion.trade_stream import (
    BACKFILL_TIMEOUT_S,
    GAP_RETRY_MAX_S,
    GAP_RETRY_MIN_S,
    UNRECOVERED_RETENTION_S,
    TradeWriter,
)
from candleviewer.observability.context import spawn

#: How often the healer looks at its buffer.
INTERVAL_S: Final = 1.0
#: PROPOSED (#1944 BQ-5): how long `degraded` must stay false before a heal starts.
HEAL_SETTLE_S: Final = 30.0
#: PROPOSED (#1944 BQ-6): a run unhealed this long after first seen is unrecoverable; the
#: precedent is `UNRECOVERED_RETENTION_S` (900 s, 15 retries at the 60 s cap).
HEAL_HORIZON_S: Final = UNRECOVERED_RETENTION_S
#: Runs worked per pass, symbols in `lost_symbols()` (name) order (C-2.18); the rest wait for a
#: later pass, their horizon running.
MAX_WORK_RUNS: Final = 512
#: The one re-read after a short read-back (QuestDB applies WAL commits asynchronously).
WAL_LAG_RETRY_S: Final = 1.0
FETCH_TIMEOUT_S: Final = BACKFILL_TIMEOUT_S
WRITE_TIMEOUT_S: Final = 10.0
READ_TIMEOUT_S: Final = 10.0
_JITTER = random.SystemRandom().random


class HotTradeReader(Protocol):
    """The hot tier's `trade_id`s for `symbol` in `[start_us, end_us)` (M6 cannot import
    storage: the composition root adapts `MarketDataRepository.read_trades`)."""

    async def read_trade_ids(self, symbol: str, start_us: int, end_us: int) -> Collection[str]: ...


class LostRunIndex(Protocol):
    """The `WriteBehindBuffer` surface the healer reads and clears."""

    @property
    def degraded(self) -> bool: ...
    @property
    def failed_writes(self) -> int: ...
    def lost_symbols(self) -> list[str]: ...
    def closed_ranges(self, symbol: str) -> list[Range]: ...
    def clear(self, symbol: str, healed: Iterable[Range]) -> int: ...


@dataclass(frozen=True, slots=True)
class TradeHealPorts:
    """What a trades healer needs; a book healer has none (never re-fetched)."""

    fetch_recent: Callable[[str], Awaitable[Sequence[TradePrint]]]
    to_event: Callable[[TradePrint], TradeEvent]
    writer: TradeWriter
    reader: HotTradeReader


Run = tuple[str, Range]


class WriteBehindHealer:
    """The healer described in the module docstring, for one buffer."""

    def __init__(
        self,
        buffer: LostRunIndex,
        *,
        table: str,
        trades: TradeHealPorts | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] = _JITTER,
        interval_s: float = INTERVAL_S,
        max_work: int = MAX_WORK_RUNS,
    ) -> None:
        self._buf, self._table, self._ports = buffer, table, trades
        self._clock, self._sleep, self._rand = clock, sleep, rand
        self._interval_s, self._max_work = interval_s, max_work
        self._ranges = {
            r: write_behind_heal_ranges_total.labels(table=table, result=r)
            for r in ("healed", "partial", "unrecoverable", "error")
        }
        self._rows = write_behind_heal_rows_total.labels(table=table)
        self._healthy_since: float | None = None
        self._failed_writes: int | None = None  # the buffer's count when last sampled
        #: Bounded by the buffer's run cap: pruned each pass to its closed runs not yet dead.
        self._first_seen: dict[Run, float] = {}
        #: symbol -> (attempt, monotonic due): the per-symbol retry backoff.
        self._retry: dict[str, tuple[int, float]] = {}
        #: Counted unrecoverable; out of the work set, still in `lost_ranges()`. Pruned each
        #: pass to the buffer's closed runs, so bounded by the buffer's own run cap.
        self._dead: set[Run] = set()
        self._task: asyncio.Task[None] | None = None

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        """Spawn the healer's one task; a second call while it runs does nothing."""
        if self._task is None:
            self._task = spawn(self._run(), name=f"write-behind-heal:{self._table}")
            self._task.add_done_callback(self._ended)

    async def stop(self) -> None:
        """Cancel the task and wait for it; a cancellation of this caller propagates."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _ended(self, task: asyncio.Task[None]) -> None:
        if task is self._task:  # `stop` lets go first: one still held ended otherwise
            error = "CancelledError" if task.cancelled() else type(task.exception()).__name__
            get_logger(__name__).error("write_behind_heal_ended", table=self._table, error=error)

    async def _run(self) -> None:
        failing = False
        while True:
            await self._sleep(self._interval_s)
            try:
                await self.tick()
            except Exception as exc:  # broad on purpose: the loop outlives a bad pass
                if not failing:
                    get_logger(__name__).error(
                        "write_behind_heal_tick_failed", table=self._table, exc_info=exc
                    )
                failing = True
            else:
                failing = False

    # ---- one pass ----------------------------------------------------------
    def _settled(self, now: float) -> bool:
        failed = self._buf.failed_writes
        flapped, self._failed_writes = failed != self._failed_writes, failed
        if self._buf.degraded:
            self._healthy_since = None
            return False
        if self._healthy_since is None or flapped:  # a failure since the last pass restarts it
            self._healthy_since = now
        return now - self._healthy_since >= HEAL_SETTLE_S

    def _work(self, now: float) -> dict[str, list[Range]]:
        """The pre-heal snapshot: closed runs not yet unrecoverable, at most `max_work`."""
        closed = {s: self._buf.closed_ranges(s) for s in self._buf.lost_symbols()}
        gone: dict[str, list[Range]] = {}
        for s, r in self._dead:
            gone.setdefault(s, []).append(r)
        # A dead run stays dead; one the cap merged out of a dead run inherits it uncounted
        # (counted once per original run). Pruned to live runs: bounded by the buffer's cap.
        self._dead = {
            (s, r)
            for s, runs in closed.items()
            for r in runs
            if any(r.start_us <= d.start_us and d.end_us <= r.end_us for d in gone.get(s, ()))
        }
        work: dict[str, list[Range]] = {}
        budget = self._max_work
        for sym, all_runs in closed.items():
            runs = [r for r in all_runs if (sym, r) not in self._dead]
            if runs and budget > 0:
                work[sym] = runs[:budget]
                budget -= len(work[sym])
        # Every live run, worked this pass or not: one left out keeps its horizon running.
        live = {(s, r) for s, runs in closed.items() for r in runs} - self._dead
        self._first_seen = {k: self._first_seen.get(k, now) for k in live}
        self._retry = {s: v for s, v in self._retry.items() if s in work}
        return work

    async def tick(self) -> None:
        now = self._clock()
        if not self._settled(now):
            return
        for sym, runs in self._work(now).items():
            if self._ports is None:  # book: never re-fetched
                self._unrecoverable(sym, runs, "not_refetchable")
                continue
            old = [r for r in runs if now - self._first_seen[(sym, r)] >= HEAL_HORIZON_S]
            self._unrecoverable(sym, old, "horizon")
            runs = [r for r in runs if r not in old]
            due = self._retry.get(sym, (0, now))[1]
            if runs and now >= due:
                await self._heal(self._ports, sym, runs)

    def _unrecoverable(self, sym: str, runs: Sequence[Range], why: str) -> None:
        for r in runs:
            self._dead.add((sym, r))
            self._ranges["unrecoverable"].inc()
            get_logger(__name__).warning(
                "write-behind run unrecoverable", table=self._table, symbol=sym,
                start_us=r.start_us, end_us=r.end_us, reason=why,
            )  # fmt: skip

    def _again(self, sym: str) -> None:
        attempt = self._retry.get(sym, (0, 0.0))[0] + 1
        step = min(GAP_RETRY_MAX_S, GAP_RETRY_MIN_S * 2.0 ** min(attempt - 1, 16))
        self._retry[sym] = (attempt, self._clock() + step / 2 + step / 2 * self._rand())

    def _failed(self, sym: str, runs: Sequence[Range], what: str, exc: Exception) -> None:
        self._ranges["error"].inc(len(runs))
        self._again(sym)
        get_logger(__name__).warning(
            "write-behind heal failed", step=what, table=self._table, symbol=sym,
            error_type=type(exc).__name__,
        )  # fmt: skip

    async def _heal(self, ports: TradeHealPorts, sym: str, runs: list[Range]) -> None:
        try:
            async with asyncio.timeout(FETCH_TIMEOUT_S):
                page = [p for p in await ports.fetch_recent(sym) if p.symbol == sym]
        except Exception as exc:  # rate-limited (governed upstream) / network / malformed
            self._failed(sym, runs, "fetch", exc)
            return
        if not page:  # no evidence yet
            self._ranges["partial"].inc(len(runs))
            self._again(sym)
            return
        rows = [p for p in page if any(r.start_us <= p.ts_event_us < r.end_us for r in runs)]
        if rows:
            try:
                async with asyncio.timeout(WRITE_TIMEOUT_S):
                    await ports.writer.write_trades([ports.to_event(p) for p in rows])
            except Exception as exc:  # the store fell over again: retried later
                self._failed(sym, runs, "write", exc)
                return
            self._rows.inc(len(rows))
        oldest = min(p.ts_event_us for p in page)
        newest = max(p.ts_event_us for p in page)
        # Strict: the page may hold only part of its oldest millisecond, so a run starting in it
        # is past the page too (BQ-6: a lost print there would be cleared unseen).
        self._unrecoverable(sym, [r for r in runs if r.start_us <= oldest], "past_page")
        healed: list[Range] = []
        left = 0  # runs still to retry: partial or a failed read-back
        for r in (r for r in runs if r.start_us > oldest):
            ids = {p.trade_id for p in rows if r.start_us <= p.ts_event_us < r.end_us}
            try:
                ok = r.end_us <= newest and bool(ids) and await self._verified(ports, sym, r, ids)
            except Exception as exc:  # the read-back failed: retried later
                self._ranges["error"].inc()
                get_logger(__name__).warning(
                    "write-behind heal failed", step="read-back", table=self._table, symbol=sym,
                    error_type=type(exc).__name__,
                )  # fmt: skip
                left += 1
                continue
            if ok:
                healed.append(r)
            else:  # REST lags the run's end, or the read-back stayed short
                self._ranges["partial"].inc()
                left += 1
        if healed:  # snapshot runs: one that changed during the awaits is not covered, stays
            self._buf.clear(sym, healed)
            self._ranges["healed"].inc(len(healed))
        if left:
            self._again(sym)
        else:
            self._retry.pop(sym, None)

    async def _verified(self, ports: TradeHealPorts, sym: str, r: Range, ids: set[str]) -> bool:
        """Every page print inside `r` is in the hot tier; one re-read on a short read."""
        for attempt in range(2):
            if attempt:
                await self._sleep(WAL_LAG_RETRY_S)
            async with asyncio.timeout(READ_TIMEOUT_S):
                stored = await ports.reader.read_trade_ids(sym, r.start_us, r.end_us)
            if ids <= set(stored):
                return True
        return False


__all__ = [
    "HEAL_HORIZON_S",
    "HEAL_SETTLE_S",
    "MAX_WORK_RUNS",
    "HotTradeReader",
    "LostRunIndex",
    "TradeHealPorts",
    "WriteBehindHealer",
]

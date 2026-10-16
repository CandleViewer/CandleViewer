"""Live trade tape: subscribe once, normalise, dedupe by trade id, gap-backfill (E08-S04).

Every derived view (bars, footprint, CVD, bubbles) is a cache over this stream
(`24-internal-schemas.md` §13), so a duplicate or a hole changes delta. Rules:

* **Exactly once** — a bounded per-symbol `DedupeRing` (deque + set) drops any
  trade id already published; memory never grows with uptime.
* **Gaps are never hidden** — on reconnect (`resubscribing`/`degraded`) or a
  lost raw frame the window opens at the last published print. The first live
  batch after it closes the window: a REST recent-trade backfill is merged with
  that batch in `(ts_event, trade_id)` order, deduped, and published *before*
  any later print (no consumer sees time move backwards). A `GapEvent` with
  explicit bounds and a text label is published either way; `recovered=False`
  when the backfill failed or did not reach back to the gap start.
* **An unrecovered window stays visible (#2715)** — it is kept per symbol
  (bounded) and reported by `unrecovered_gaps()` (health `trade_gap_unrecovered`)
  until a later backfill covers it, the symbol leaves demand, or
  `UNRECOVERED_RETENTION_S` after it closed (then only its `GapEvent` remains,
  so a hole no page can reach never pins health for good). A failed (or
  empty) backfill is retried on a capped, jittered backoff through the same
  REST path and rate governor (C-12.7). A covering page sends the missing
  prints to the hot tier only: the live tape moved on, so publishing them
  would move time backwards, and the window's `GapEvent` stays as published.
  Each window is judged on its own: one a page no longer reaches back to is
  not retried again (later recent-trade pages only move forward).
* **Off the dispatch path (#1905)** — the backfill runs in a tracked,
  single-flight task per symbol; live batches for that symbol are held
  (bounded) and published after the merge, so other symbols/streams never wait.
* **Never drop** — prints go to the bus with `NEVER_DROP` subscribers, so a slow
  consumer back-pressures this reader (`ingest_queue_full_total{class}`).

Plain code, never a statechart (catalogue §1.2 hot-path exclusion). Venue
parsing and REST are injected (C-2.2): this module sees only `TradePrint`s.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic, TopicPattern
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.ingestion._logging import get_logger
from candleviewer.ingestion.metrics import (
    count_event,
    ingest_dispatch_overflow_total,
    ingest_lag_seconds,
    symbol_label,
    trade_backfill_rows_total,
    trade_duplicates_suppressed_total,
    trade_gaps_total,
    trade_prints_rejected_total,
    trade_writes_dropped_total,
)
from candleviewer.ingestion.planner import DEFAULT_GRACE_S, DemandTracker
from candleviewer.ingestion.rejection import RejectionLog
from candleviewer.ingestion.ticker_stream import UnknownSymbolError, uuid7
from candleviewer.ingestion.watchdog import FeedHealthEvent, prune_unlisted
from candleviewer.ingestion.write_behind import WriteBehindBuffer
from candleviewer.observability.context import spawn

#: Per-symbol recent-id capacity: 5 000 prints/s x a 10 s reconnect window,
#: rounded up; well past a 1 000-row backfill page.
DEDUPE_CAPACITY = 50_000
WRITE_QUEUE_MAXSIZE = 8192
BACKFILL_TIMEOUT_S = 5.0
#: #1905: live prints parked per symbol while its backfill is in flight
#: (5 000 prints/s x the 5 s backfill timeout, x2). Overflow: drop newest,
#: counted, and the gap is reopened so the next batch backfills again.
HOLD_CAPACITY = 50_000
#: #2715: an unrecovered window is re-backfilled after GAP_RETRY_MIN_S doubling to
#: GAP_RETRY_MAX_S, equal jitter: at most one recent-trade page per symbol per 30-60 s
#: once capped, on the same REST client and rate governor as the first backfill (C-12.7).
GAP_RETRY_MIN_S = 2.0
GAP_RETRY_MAX_S = 60.0
#: #2715: unrecovered windows kept per symbol; past it the newest folds into the last.
UNRECOVERED_WINDOWS_CAP = 16
#: #2715 review: a window is reported for at most this long after it closed (15 retries
#: at the 60 s cap fit inside); a hole no page can reach would otherwise pin health for good.
UNRECOVERED_RETENTION_S = 15 * GAP_RETRY_MAX_S
_JITTER = random.SystemRandom().random


class TradeWriter(Protocol):
    async def write_trades(self, events: Sequence[TradeEvent]) -> None: ...


@dataclass(frozen=True, slots=True)
class GapEvent:
    """A tape window with possibly missing prints, published on `{env}.md.{sym}.gap`."""

    symbol: str
    start_us: int
    end_us: int
    recovered: bool
    reason: str  # "reconnect" | "frame_loss"

    def label(self) -> str:
        """Words, not a colour band (a11y note): `No data 12:03:11-12:03:19`."""

        def hms(us: int) -> str:
            return datetime.fromtimestamp(us / 1e6, tz=UTC).strftime("%H:%M:%S")

        prefix = "Backfilled" if self.recovered else "No data"
        return f"{prefix} {hms(self.start_us)}-{hms(self.end_us)}"


@dataclass(slots=True, eq=False)  # identity, not value: two holes may share bounds
class _Hole:
    """#2715: a window that closed `recovered=False`, kept for the health signal."""

    start_us: int
    end_us: int
    expires: float  # `clock` s: reported until then unless a page covers it first
    retry: bool  # False once a page no longer reached back to `start_us`


class DedupeRing:
    """Fixed-capacity recent-id set: O(1) lookup, oldest evicted first."""

    def __init__(self, capacity: int = DEDUPE_CAPACITY) -> None:
        self._order: deque[str] = deque()
        self._ids: set[str] = set()
        self._cap = capacity

    def __len__(self) -> int:
        return len(self._ids)

    def add(self, trade_id: str) -> bool:
        """True if new (and now remembered); False for a duplicate."""
        if trade_id in self._ids:
            return False
        if len(self._order) >= self._cap:
            self._ids.discard(self._order.popleft())
        self._order.append(trade_id)
        self._ids.add(trade_id)
        return True


def merge_ordered(*batches: Iterable[TradePrint]) -> list[TradePrint]:
    """Union by trade id, ordered by `(ts_event, trade_id)` (§2.1, C4)."""
    seen: dict[str, TradePrint] = {}
    for batch in batches:
        for p in batch:
            seen.setdefault(p.trade_id, p)
    return sorted(seen.values(), key=lambda p: (p.ts_event_us, p.trade_id))


def _now_us() -> int:
    return time.time_ns() // 1000


class TradeStream:
    """Refcounted per-symbol public-trade stream demand + dedupe + gap backfill + publish."""

    def __init__(
        self,
        *,
        bus: Bus,
        env: str,
        set_desired: Callable[[set[str]], None],
        parse_frame: Callable[[str], list[TradePrint] | None],
        topic_for: Callable[[str], str],
        is_listed: Callable[[str], bool],
        touch: Callable[[str], None],
        fetch_recent: Callable[[str], Awaitable[Sequence[TradePrint]]] | None = None,
        tick_size: Callable[[str], Decimal | None] = lambda _s: None,
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _now_us,
        event_window: Callable[[str, int], None] | None = None,
        grace_s: float = DEFAULT_GRACE_S,
        writer: TradeWriter | None = None,
        dedupe_capacity: int = DEDUPE_CAPACITY,
        backfill_timeout_s: float = BACKFILL_TIMEOUT_S,
        write_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        write_rand: Callable[[], float] | None = None,
        hold_capacity: int = HOLD_CAPACITY,
        retry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_rand: Callable[[], float] = _JITTER,
    ) -> None:
        self._bus, self._env = bus, env
        self._set_desired, self._parse = set_desired, parse_frame
        self._topic_for, self._is_listed, self._touch = topic_for, is_listed, touch
        self._fetch, self._tick_size = fetch_recent, tick_size
        self._clock, self._now_us = clock, now_us
        self._demand = DemandTracker(clock, grace_s)
        self._rejects = RejectionLog("trade", clock)
        #: #1892: clock/listing-relative plausibility (`ingestion.rejection.EventWindow`).
        self._window = event_window
        self._writer, self._cap, self._bf_timeout = writer, dedupe_capacity, backfill_timeout_s
        self._rings: dict[str, DedupeRing] = {}
        self._last_ts: dict[str, int] = {}  # last published ts_event per symbol
        self._seq: dict[str, int] = {}
        self._gap_open: dict[str, tuple[int, str]] = {}  # symbol -> (start_us, reason)
        self._recent: dict[str, deque[TradeEvent]] = {}
        self._gaps: dict[str, deque[GapEvent]] = {}
        #: #1918: a failed batch is requeued with backoff, never discarded.
        self._writes: WriteBehindBuffer[TradeEvent] = WriteBehindBuffer(
            table="trades",
            maxsize=WRITE_QUEUE_MAXSIZE,
            dropped=trade_writes_dropped_total,
            key=lambda e: (e.symbol, e.ts_event),
            sleep=write_sleep,
            rand=write_rand,
        )
        self._tasks: list[asyncio.Task[None]] = []
        #: #1905: single-flight backfill per symbol + the live batches held meanwhile.
        self._bf_tasks: dict[str, asyncio.Task[None]] = {}
        self._hold: dict[str, list[TradePrint]] = {}
        self._hold_overflow: set[str] = set()
        self._hold_cap = hold_capacity
        #: #2715: windows that closed `recovered=False`, oldest first, + one retry per symbol.
        self._unrecovered: dict[str, list[_Hole]] = {}
        self._retry_tasks: dict[str, asyncio.Task[None]] = {}
        self._retry_sleep, self._retry_rand = retry_sleep, retry_rand
        self._health = bus.subscribe(
            "trade-stream-health",
            TopicPattern(env=env, domain="health", detail="feed"),
            QueuePolicy.NEVER_DROP,
            maxsize=1024,
        )

    # ---- demand ---------------------------------------------------------
    def acquire(self, consumer: str, symbol: str) -> None:
        if not self._is_listed(symbol):
            raise UnknownSymbolError(symbol)
        self._demand.acquire(consumer, symbol)
        self.sync()

    def release(self, consumer: str, symbol: str) -> None:
        self._demand.release(consumer, symbol)
        self.sync()

    def sync(self) -> None:
        wanted = self._demand.desired()
        self._set_desired({self._topic_for(s) for s in wanted})
        for gone in (set(self._rings) | set(self._unrecovered)) - wanted:
            for d in (self._rings, self._last_ts, self._gap_open, self._unrecovered):
                d.pop(gone, None)  # a pending retry sees no windows and ends (#2715)

    async def prune_unlisted(self) -> list[str]:
        """#1913: drop + unsubscribe symbols that left the catalogue."""
        health = Topic(env=self._env, domain="health", detail="feed")

        async def publish(ev: FeedHealthEvent) -> None:
            await self._bus.publish(health, ev)

        return await prune_unlisted(
            self._demand, self._is_listed, self.sync, publish, self._topic_for
        )

    # ---- reads (GET /market/trades) --------------------------------------
    def is_listed(self, symbol: str) -> bool:
        return self._is_listed(symbol)

    def tick_size(self, symbol: str) -> Decimal | None:
        return self._tick_size(symbol)

    def recent(self, symbol: str) -> list[TradeEvent]:
        return list(self._recent.get(symbol, ()))

    def gaps(self, symbol: str) -> list[GapEvent]:
        return list(self._gaps.get(symbol, ()))

    def open_gaps(self) -> dict[str, tuple[int, str]]:
        return dict(self._gap_open)

    def unrecovered_gaps(self) -> dict[str, tuple[int, int]]:
        """#2715: symbol -> (oldest start_us, newest end_us) over `unrecovered_windows`."""
        wanted = self._demand.desired()
        gaps = {s: self._reported(s, wanted) for s in self._unrecovered}
        return {s: (w[0][0], w[-1][1]) for s, w in gaps.items() if w}

    def unrecovered_windows(self, symbol: str) -> list[tuple[int, int]]:
        """#2715: `symbol`'s windows that closed `recovered=False`, oldest first, as
        (start_us, end_us): none covered by a later backfill, none past the retention
        horizon, and none once the symbol left demand."""
        return self._reported(symbol, self._demand.desired())

    def _reported(self, symbol: str, wanted: set[str]) -> list[tuple[int, int]]:
        now = self._clock()
        holes = self._unrecovered.get(symbol, ()) if symbol in wanted else ()
        return [(h.start_us, h.end_us) for h in holes if h.expires > now]

    # ---- gaps -----------------------------------------------------------
    def mark_gap(self, reason: str, symbol: str | None = None) -> None:
        """Open a gap window at the last published print (reconnect / frame loss)."""
        for sym in [symbol] if symbol else list(self._last_ts):
            if sym in self._last_ts and sym not in self._gap_open:
                self._gap_open[sym] = (self._last_ts[sym], reason)

    async def _backfill(self, symbol: str) -> list[TradePrint] | None:
        if self._fetch is None:
            trade_backfill_rows_total.labels(result="unavailable").inc()
            return None
        try:
            async with asyncio.timeout(self._bf_timeout):
                rows = list(await self._fetch(symbol))
        except asyncio.CancelledError:
            raise
        except Exception:  # rate-limited / network / malformed: gap stays unrecovered
            trade_backfill_rows_total.labels(result="error").inc()
            get_logger(__name__).warning("trade backfill failed", symbol=symbol)
            return None
        trade_backfill_rows_total.labels(result="ok").inc(len(rows))
        return rows

    # ---- frames ---------------------------------------------------------
    async def handle_frame(self, frame: str) -> None:
        try:
            prints = self._parse(frame)
            if prints and self._window is not None:
                for p in prints:
                    self._window(p.symbol, p.ts_event_us)
        except (ValueError, RecursionError) as exc:
            trade_prints_rejected_total.inc()
            self._rejects.record(exc)
            sym = getattr(exc, "symbol", None)
            if isinstance(sym, str):  # the frame held prints we dropped: backfill heals it
                self.mark_gap("rejected_frame", sym)
            return
        if not prints:
            return
        sym = prints[0].symbol
        if sym not in self._demand.desired():
            return
        self._touch(self._topic_for(sym))
        ts_ingest = self._now_us()
        live = sorted(prints, key=lambda p: (p.ts_event_us, p.trade_id))
        if sym in self._hold:
            self._hold_batch(sym, live)
            return
        gap = self._gap_open.pop(sym, None)
        if gap is None:
            await self._publish_all(sym, [(p, "live") for p in live], ts_ingest)
            return
        self._hold[sym] = list(live)
        task = spawn(self._backfill_and_merge(sym, gap, ts_ingest), name=f"trade-backfill:{sym}")
        self._bf_tasks[sym] = task
        task.add_done_callback(self._backfill_done)

    def _hold_batch(self, sym: str, live: list[TradePrint]) -> None:
        """#1905: a backfill is in flight for `sym`; park the batch (bounded)."""
        held = self._hold[sym]
        if len(held) + len(live) > self._hold_cap:  # drop newest; reopen the gap after
            ingest_dispatch_overflow_total.labels(stream="trade").inc()
            self._hold_overflow.add(sym)
            return
        held.extend(live)

    async def _backfill_and_merge(self, sym: str, gap: tuple[int, str], ts_ingest: int) -> None:
        """#1905: runs in its own task, so a slow/failing REST backfill never
        blocks frame dispatch. Live batches arriving meanwhile are held and
        published after the merge, in arrival order (never backwards)."""
        start_us, reason = gap
        backfill = await self._backfill(sym)
        live = self._hold[sym]
        self._hold[sym] = []
        end_us = live[0].ts_event_us
        rows = [p for p in (backfill or ()) if p.symbol == sym]
        recovered = bool(rows) and min(p.ts_event_us for p in rows) <= start_us
        live_ids = {p.trade_id for p in live}
        merged = merge_ordered(live, rows)
        gev = GapEvent(sym, start_us, end_us, recovered, reason)
        self._gaps.setdefault(sym, deque(maxlen=256)).append(gev)
        trade_gaps_total.labels(symbol=symbol_label(sym), recovered=str(recovered).lower()).inc()
        if not recovered:  # health keeps it; only a missing/empty page is worth a retry
            self._keep_unrecovered(gev, retry=not rows)
        await self._bus.publish(Topic(env=self._env, domain="md", symbol=sym, detail="gap"), gev)
        tagged = [(p, "live" if p.trade_id in live_ids else "backfill") for p in merged]
        await self._publish_all(sym, tagged, ts_ingest)
        while self._hold[sym]:  # batches that arrived during the backfill/publish
            more = sorted(self._hold[sym], key=lambda p: (p.ts_event_us, p.trade_id))
            self._hold[sym] = []
            await self._publish_all(sym, [(p, "live") for p in more], self._now_us())
        # No await between the drained check and here: handle_frame sees a
        # consistent "not backfilling" state from now on.
        self._hold.pop(sym, None)
        if sym in self._hold_overflow:
            self._hold_overflow.discard(sym)
            self.mark_gap("backfill_hold_full", sym)

    def _backfill_done(self, task: asyncio.Task[None]) -> None:
        for sym, t in list(self._bf_tasks.items()):
            if t is task:
                del self._bf_tasks[sym]
                if sym in self._hold:  # cancelled/failed mid-merge: never hide the hole
                    self._hold.pop(sym, None)
                    self._hold_overflow.discard(sym)
                    if sym in self._last_ts:
                        self._gap_open.setdefault(sym, (self._last_ts[sym], "backfill_failed"))
        if not task.cancelled() and task.exception() is not None:
            get_logger(__name__).error("trade backfill task failed", exc_info=task.exception())

    # ---- unrecovered windows (#2715) ------------------------------------------
    def _holes(self, sym: str) -> list[_Hole]:
        """`sym`'s holes inside the retention horizon; expired ones are dropped."""
        now = self._clock()
        holes = [h for h in self._unrecovered.pop(sym, ()) if h.expires > now]
        if holes:
            self._unrecovered[sym] = holes
        return holes

    def _keep_unrecovered(self, gev: GapEvent, *, retry: bool) -> None:
        sym = gev.symbol
        hole = _Hole(gev.start_us, gev.end_us, self._clock() + UNRECOVERED_RETENTION_S, retry)
        holes = self._holes(sym)
        if len(holes) >= UNRECOVERED_WINDOWS_CAP:  # bounded: the newest folds into the last
            last = holes.pop()  # the fold spans both: worth a retry only if both still are
            hole.start_us, hole.retry = last.start_us, last.retry and retry
        self._unrecovered[sym] = [*holes, hole]
        task = self._retry_tasks.get(sym)  # a done one waits for `_retry_done`: not running
        if hole.retry and self._fetch is not None and (task is None or task.done()):
            task = spawn(self._retry_unrecovered(sym), name=f"trade-gap-retry:{sym}")
            self._retry_tasks[sym] = task
            task.add_done_callback(self._retry_done)

    async def _retry_unrecovered(self, sym: str) -> None:
        """Re-run the backfill for `sym`'s holes until each is covered, expired, or past
        the backfill horizon (later pages only move forward), or `sym` leaves demand."""
        attempt = 0
        while any(h.retry for h in self._holes(sym)):
            attempt += 1
            step = min(GAP_RETRY_MAX_S, GAP_RETRY_MIN_S * 2.0 ** min(attempt - 1, 16))
            await self._retry_sleep(step / 2 + step / 2 * self._retry_rand())
            if sym not in self._demand.desired():  # its grace ran out with no sync() since
                self._unrecovered.pop(sym, None)
            if not any(h.retry for h in self._holes(sym)):  # nothing left: no REST call
                return
            page = [p for p in (await self._backfill(sym) or ()) if p.symbol == sym]
            if not page:
                continue  # failed or empty page: no evidence yet, try again later
            oldest = min(p.ts_event_us for p in page)
            newest = max(p.ts_event_us for p in page)
            healed: list[_Hole] = []
            for h in self._holes(sym):
                if h.retry and h.start_us < oldest:  # reported until it expires; no retries
                    h.retry = False
                    get_logger(__name__).warning(
                        "trade gap past the backfill horizon", symbol=sym, start_us=h.start_us
                    )
                elif h.retry and h.end_us <= newest:  # else REST lags the window end: retry
                    healed.append(h)
            if healed:
                self._heal(sym, healed, page)

    def _heal(self, sym: str, healed: list[_Hole], page: list[TradePrint]) -> None:
        """Write the holes' missing prints to the hot tier (never the live topic) and
        drop the holes from the health signal."""
        ring = self._rings.setdefault(sym, DedupeRing(self._cap))
        ts_ingest, written = self._now_us(), 0
        for p in sorted(page, key=lambda p: (p.ts_event_us, p.trade_id)):
            # Inclusive: one ms can stamp several prints, so a lost one may share a bound. A
            # bound print already out of the ring is written again: the hot tier's dedup
            # upsert keys (ts, symbol, trade_id) make that a no-op, so `written` is an upper bound.
            inside = any(h.start_us <= p.ts_event_us <= h.end_us for h in healed)
            if inside and ring.add(p.trade_id):
                self._enqueue_write(self._event(p, "backfill", ts_ingest))
                written += 1
        left = [h for h in self._unrecovered.get(sym, ()) if h not in healed]
        if left:
            self._unrecovered[sym] = left
        else:
            self._unrecovered.pop(sym, None)
        get_logger(__name__).info(
            "trade gap healed", symbol=sym, windows=len(healed), rows_written=written
        )

    def _retry_done(self, task: asyncio.Task[None]) -> None:
        for sym, t in list(self._retry_tasks.items()):
            if t is task:
                del self._retry_tasks[sym]
        if not task.cancelled() and task.exception() is not None:
            get_logger(__name__).error("trade gap retry failed", exc_info=task.exception())

    async def wait_backfills(self) -> None:
        """Await every in-flight backfill (tests, orderly shutdown)."""
        while self._bf_tasks:
            await asyncio.gather(*list(self._bf_tasks.values()), return_exceptions=True)

    async def _publish_all(
        self, sym: str, prints: list[tuple[TradePrint, str]], ts_ingest: int
    ) -> None:
        ring = self._rings.setdefault(sym, DedupeRing(self._cap))
        topic = Topic(env=self._env, domain="md", symbol=sym, detail="trade")
        floor = self._last_ts.get(sym)
        for p, source in prints:
            if not ring.add(p.trade_id):
                trade_duplicates_suppressed_total.labels(symbol=symbol_label(sym)).inc()
                continue
            if source == "backfill" and floor is not None and p.ts_event_us < floor:
                continue  # pre-gap history: publishing it would move time backwards
            event = self._event(p, source, ts_ingest)
            count_event("trade", sym)
            await self._bus.publish(topic, event)  # NEVER_DROP subscribers back-pressure us
            self._last_ts[sym] = max(self._last_ts.get(sym, 0), p.ts_event_us)
            recent = self._recent.setdefault(sym, deque(maxlen=1000))
            recent.append(event)
            self._enqueue_write(event)
        if prints:
            ingest_lag_seconds.labels(stream="trade").set(
                max(0.0, (ts_ingest - prints[-1][0].ts_event_us) / 1e6)
            )

    def _event(self, p: TradePrint, source: str, ts_ingest: int) -> TradeEvent:
        # `seq` is monotonic, not contiguous (§2.1): a hot-tier-only heal row (#2715) takes one.
        seq = self._seq.get(p.symbol, 0) + 1
        self._seq[p.symbol] = seq
        tick = self._tick_size(p.symbol)
        ticks = int((p.price / tick).to_integral_value()) if tick else 0
        return TradeEvent.model_validate(
            {
                "event_id": EventId(uuid7(p.ts_event_us // 1000)),
                "ts_event": p.ts_event_us,
                "ts_ingest": ts_ingest,
                "source": source,
                "symbol": p.symbol,
                "trade_id": p.trade_id,
                "price": p.price,
                "qty": p.qty,
                "side": p.side,
                "is_block_trade": p.is_block_trade,
                "price_ticks": ticks,
                "notional": p.price * p.qty,
                "seq": seq,
            }
        )

    def _enqueue_write(self, event: TradeEvent) -> None:
        if self._writer is None:
            return
        self._writes.put(event)  # never blocks the reader; full -> drop-oldest, counted

    # ---- loops / lifecycle -------------------------------------------------
    async def process_health(self, event: FeedHealthEvent) -> None:
        if event.state in ("resubscribing", "degraded"):
            self.mark_gap("reconnect")

    async def _health_loop(self) -> None:
        while True:
            ev = await self._health.get()
            if isinstance(ev, FeedHealthEvent):
                await self.process_health(ev)

    async def drain_writes(self, max_batch: int = 500) -> int:
        """Write one batch (blocks for the first row); returns rows written.

        On failure the batch goes back to the head of the buffer and the loop
        backs off (#1918); 0 is returned and nothing counts as persisted."""
        batch = await self._writes.take(max_batch)
        try:
            if self._writer is not None:
                await self._writer.write_trades(batch)
        except asyncio.CancelledError:
            self._writes.restore(batch)  # stop(): nothing taken is lost
            raise
        except Exception:  # write-behind must never take ingest down
            self._writes.requeue(batch)
            get_logger(__name__).warning(
                "trade write-behind failed; requeued",
                rows=len(batch),
                failures=self._writes.failures,
            )
            await self._writes.backoff()
            return 0
        self._writes.succeeded(batch)
        return len(batch)

    @property
    def write_behind(self) -> WriteBehindBuffer[TradeEvent]:
        """Hot-tier write-behind state (health probe + lost-range index)."""
        return self._writes

    async def _write_loop(self) -> None:
        while True:
            await self.drain_writes()

    async def start(self) -> None:
        self._tasks = [
            spawn(self._health_loop(), name="trade-health"),
            spawn(self._write_loop(), name="trade-write-behind"),
        ]

    async def stop(self) -> None:
        tasks = self._tasks + list(self._bf_tasks.values()) + list(self._retry_tasks.values())
        self._tasks = []
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._writes.flush_metrics()  # pending batched drop counts (#1918)
        self._bus.unsubscribe(self._health)


__all__ = [
    "DEDUPE_CAPACITY",
    "GAP_RETRY_MAX_S",
    "GAP_RETRY_MIN_S",
    "UNRECOVERED_RETENTION_S",
    "UNRECOVERED_WINDOWS_CAP",
    "DedupeRing",
    "GapEvent",
    "TradeStream",
    "TradeWriter",
    "merge_ordered",
]

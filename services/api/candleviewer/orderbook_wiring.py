"""Composition-root wiring (not a module): live order book (E08-S05).

Demand, per-symbol `TieredBook`, bus publish and write-behind.

Wires the venue-neutral `book` module to ingestion. Rules:

* A symbol's `BookEngine` publishes **only while LIVE** (the engine enforces it
  synchronously; the B14 chart supervises). Consumers on
  `{env}.md.{symbol}.book` therefore never see a delta before the snapshot.
* Resync = unsubscribe + subscribe of that one topic through the connection
  manager's shaped `resubscribe` (E08-T04 budget), never a fire-all burst.
* `SNAPSHOT_TIMEOUT`: a snapshot pending longer than `snapshot_timeout_s`
  re-enters `snapshot_pending` (chart) / re-requests (unsupervised).
* Write-behind to QuestDB is a bounded queue that drops oldest, never
  blocking the reader.
* A released symbol's grace (US-MKT-005) ends on the stream's own tick or its
  next frame, whichever comes first: the topic is dropped and the book
  forgotten, so a later acquire is served from a fresh snapshot (#3807).
* Tiers (E21-T01, BQ-1): one active tier per symbol, 200 by default. Demand is
  kept per (symbol, depth); a 500 demand moves the tier to 500 only with
  `heatmap_depth_500` on (C-4.13, default off), and the tier returns to the
  default once no 500 demand is left (the WS references' grace has run by then).
  The stream's tick applies a tier change, built muted and swapped in whole.
* E21-T01: `BestQuoteEvent` on `{env}.md.{symbol}.quote` after each event the
  active tier applied, only on change (`book.quote`); each resync incident's
  `BookDesyncEvent` on `{env}.health.{symbol}.book_desync` with its structured
  log; `book_apply_latency_ms`, `book_crossed_total` and the resync counter's
  `depth` (the active tier).

Plain code on the hot path (catalogue 1.2, C-2.20): this module never imports
the statechart package. B14 health supervision is an injected
`HealthSupervisor` (`ingestion.book_supervisor.B14BookSupervisor`, built in
`create_app`) that receives lifecycle edges fire-and-forget.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

import structlog

from candleviewer.book.models import BestQuoteEvent, BookDesyncEvent, BookPhase, BookStatus
from candleviewer.book.quote import QuoteTracker
from candleviewer.book.resync import BookEngine, HealthSink, Published
from candleviewer.book.tiers import DEFAULT_DEPTH, TieredBook
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, Topic, TopicPattern
from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from candleviewer.ingestion.metrics import (
    book_apply_latency_ms,
    book_crossed_total,
    book_writes_dropped_total,
    ingest_book_live,
    ingest_book_resyncs_total,
    symbol_label,
)
from candleviewer.ingestion.planner import DEFAULT_GRACE_S, DemandTracker
from candleviewer.ingestion.rejection import RejectionLog
from candleviewer.ingestion.ticker_stream import UnknownSymbolError
from candleviewer.ingestion.watchdog import STALENESS_S, FeedHealthEvent, prune_unlisted
from candleviewer.ingestion.write_behind import WriteBehindBuffer
from candleviewer.observability.context import spawn
from candleviewer.storage.repositories.rows import BookDeltaRow, BookSnapshotRow


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


WRITE_QUEUE_MAXSIZE = 8192
SNAPSHOT_TIMEOUT_S = 10.0
#: Per-symbol snapshot-request backoff (#1898 review r2): 250 ms doubling to 30 s,
#: x[1, 1.25) jitter. A good snapshot resets it; suppressed requests are counted
#: as `ingest_book_resyncs_total{reason="backoff"}` and the book stays out of LIVE.
RESYNC_BACKOFF_BASE_S = 0.25
RESYNC_BACKOFF_CAP_S = 30.0
#: A book LIVE this long without another resync is healthy: the backoff resets.
RESYNC_STABLE_S = 5.0
#: #3807, #2487 F4: a LIVE book that has applied no frame for this long is served `stale`.
#: The watchdog's book limit, which `25-market-data-trust-contract.md` section 3 applies to
#: the age of the last applied book update.
BOOK_STALE_AFTER_S = STALENESS_S["book"]
_TICK_S = 0.25
_JITTER = random.SystemRandom().random


class _ResyncBackoff:
    """Cooldown gate for one symbol's snapshot requests (clock-injected)."""

    __slots__ = ("fails", "live_at", "next_ok")

    def __init__(self) -> None:
        self.fails = 0
        self.next_ok = 0.0
        self.live_at: float | None = None

    def allow(self, now: float, rand: float) -> bool:
        if self.live_at is not None and now - self.live_at >= RESYNC_STABLE_S:
            self.fails, self.next_ok = 0, 0.0  # was stable: this is a fresh incident
        self.live_at = None
        if now < self.next_ok:
            return False
        delay = min(RESYNC_BACKOFF_CAP_S, RESYNC_BACKOFF_BASE_S * (2**self.fails))
        self.fails = min(self.fails + 1, 16)
        self.next_ok = now + delay * (1.0 + 0.25 * rand)
        return True


#: Closed set of resync reasons (book/resync.py + ingestion); anything else -> "other".
_RESYNC_REASONS = frozenset(
    {
        "buffer_overflow",
        "sequence_gap",
        "server_reset",
        "bad_snapshot",
        "bad_replay",
        "frame_loss",
        "reconnect",
        "snapshot_timeout",
        "rejected_frame",
        "backoff",
        "grid",  # #3806: a tick-size change under a LIVE book, or a level off the book's grid
    }
)


def _observe_book_status(status: BookStatus) -> None:
    """E08-T06: book LIVE gauge + resync counter, from the published status."""
    sym = symbol_label(status.symbol)
    live = status.state is BookPhase.LIVE
    ingest_book_live.labels(symbol=sym).set(1.0 if live else 0.0)
    if status.state is BookPhase.DESYNCED:
        reason = status.reason if status.reason in _RESYNC_REASONS else "other"
        ingest_book_resyncs_total.labels(symbol=sym, reason=reason, depth=str(status.depth)).inc()


#: The tier a 500 demand moves a symbol to, with `heatmap_depth_500` on (BQ-1).
DEEP_TIER = 500


def _observe_desync(ev: BookDesyncEvent) -> None:
    """E21-T01: the incident's structured log (no level, no price) and `book_crossed_total`."""
    logger().warning(
        "book_desync",
        symbol=ev.symbol,
        depth=ev.depth,
        reason=ev.reason,
        prev_update_id=ev.prev_update_id,
        got_update_id=ev.got_update_id,
        resync_count=ev.resync_count,
    )
    if ev.reason == "crossed":
        book_crossed_total.labels(symbol=symbol_label(ev.symbol)).inc()


class BookWriter(Protocol):
    async def write_book_deltas(self, rows: Sequence[BookDeltaRow]) -> None: ...
    async def write_book_snapshot(self, row: BookSnapshotRow) -> None: ...


@dataclass(frozen=True, slots=True)
class BookView:
    """A LIVE book as served by `GET /market/orderbook`."""

    snapshot: BookSnapshot
    stale: bool


def _now_us() -> int:
    return time.time_ns() // 1000


class HealthSupervisor(Protocol):
    """Non-hot B14 supervision, injected by the composition root."""

    async def attach(self, key: str, symbol: str) -> HealthSink: ...
    def detach(self, key: str) -> None: ...


class BookStream:
    def __init__(
        self,
        *,
        bus: Bus,
        env: str,
        set_desired: Callable[[set[str]], None],
        parse_frame: Callable[[str], BookSnapshot | BookDelta | None],
        topic_for: Callable[[str, int], str],
        resubscribe: Callable[[str], Awaitable[None]],
        is_listed: Callable[[str], bool],
        touch: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _now_us,
        grace_s: float = DEFAULT_GRACE_S,
        writer: BookWriter | None = None,
        snapshot_timeout_s: float = SNAPSHOT_TIMEOUT_S,
        default_depth: int = DEFAULT_DEPTH,
        supervisor: HealthSupervisor | None = None,
        rand: Callable[[], float] = _JITTER,
        write_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        tick_size: Callable[[str], Decimal | None] | None = None,
        depth_500: bool = False,
        perf: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._clock, self._rand = clock, rand
        #: E21-T01: whether a 500 demand may move a symbol's tier (`heatmap_depth_500`), the
        #: depth each consumer of a symbol asked for, the quotes last published and the timer
        #: `book_apply_latency_ms` reads.
        self._depth_500, self._wants, self._perf = depth_500, dict[str, dict[str, int]](), perf
        self._quotes = QuoteTracker()
        #: #3806: the catalogue's tick size (the one `parse_frame` reads), and the grid each
        #: (symbol, depth) book was last snapshotted on. Without it the grid check is off.
        self._tick_size = tick_size
        self._grids: dict[tuple[str, int], Decimal | None] = {}
        #: #1975: the SNAPSHOT_TIMEOUT tick's sleep (a virtual clock in the chaos rig).
        self._sleep = sleep
        self._backoff: dict[str, _ResyncBackoff] = {}
        self._deferred: set[str] = set()
        #: #1919: symbol -> clock() reading when its book last left LIVE.
        self._not_live_since: dict[str, float] = {}
        #: #3807: symbol -> clock() reading when its active book last applied a frame.
        self._applied_at: dict[str, float] = {}
        self._bus, self._env = bus, env
        self._set_desired, self._parse = set_desired, parse_frame
        self._topic_for, self._resub = topic_for, resubscribe
        self._is_listed, self._touch = is_listed, touch
        self._now_us, self._writer = now_us, writer
        self._timeout_us = int(snapshot_timeout_s * 1_000_000)
        self._depth = default_depth
        self._demand = DemandTracker(clock, grace_s)
        self._rejects = RejectionLog("book", clock)
        self._books: dict[str, TieredBook] = {}
        self._first_sub: set[tuple[str, int]] = set()
        self._supervisor = supervisor
        self._keys: dict[str, list[str]] = {}
        #: #1918: a failed batch is requeued with backoff, never discarded.
        self._writes: WriteBehindBuffer[BookDeltaRow | BookSnapshotRow] = WriteBehindBuffer(
            table="orderbook",
            maxsize=WRITE_QUEUE_MAXSIZE,
            dropped=book_writes_dropped_total,
            key=lambda r: (r.symbol, r.ts_us),
            sleep=write_sleep,
            rand=rand,
        )
        self._tasks: list[asyncio.Task[None]] = []
        self._health = bus.subscribe(
            "book-stream-health",
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

    def acquire_depth(self, consumer: str, symbol: str, depth: int) -> None:
        """`acquire`, naming the topic depth the consumer reads (E21-T01): the tier's demand."""
        if not self._is_listed(symbol):
            raise UnknownSymbolError(symbol)
        self._wants.setdefault(symbol, {})[consumer] = depth
        self.acquire(consumer, symbol)

    def release(self, consumer: str, symbol: str) -> None:
        self._demand.release(consumer, symbol)
        wants = self._wants.get(symbol)
        if wants is not None:
            wants.pop(consumer, None)
            if not wants:
                del self._wants[symbol]
        self.sync()

    def tier(self, symbol: str) -> int:
        """The tier `symbol`'s demand asks for (BQ-1): 500 while a consumer reads 500 and
        `heatmap_depth_500` is on, else the default."""
        wants = self._wants.get(symbol, {})
        deep = self._depth_500 and any(d >= DEEP_TIER for d in wants.values())
        return DEEP_TIER if deep else self._depth

    async def apply_tiers(self) -> int:
        """Start the tier change of each symbol whose active tier is not the one its demand asks
        for and that is not already warming one; the changes started."""
        n = 0
        for symbol, tb in list(self._books.items()):
            want = self.tier(symbol)
            if tb.warming is None and tb.active.depth != want:
                await tb.change_depth(want)
                n += 1
        if n:
            self.sync()
        return n

    def is_listed(self, symbol: str) -> bool:
        return self._is_listed(symbol)

    def sync(self) -> None:
        wanted = self._demand.desired()
        topics: set[str] = set()
        for sym in wanted:
            tb = self._books.get(sym)
            depths = {self.tier(sym)} if tb is None else {tb.active.depth}
            if tb is not None and tb.warming is not None:
                depths.add(tb.warming.depth)
            topics |= {self._topic_for(sym, d) for d in depths}
        self._set_desired(topics)
        for gone in set(self._books) - wanted:
            self._drop(gone)

    async def prune_unlisted(self) -> list[str]:
        """#1913: drop + unsubscribe symbols that left the catalogue."""
        health = Topic(env=self._env, domain="health", detail="feed")

        async def publish(ev: FeedHealthEvent) -> None:
            await self._bus.publish(health, ev)

        return await prune_unlisted(
            self._demand,
            self._is_listed,
            self.sync,
            publish,
            lambda s: self._topic_for(s, self._depth),
            now_us=self._now_us,
        )

    def _drop(self, symbol: str) -> None:
        self._books.pop(symbol, None)
        for key in self._keys.pop(symbol, []):
            if self._supervisor is not None:
                self._supervisor.detach(key)
        self._first_sub = {k for k in self._first_sub if k[0] != symbol}
        self._grids = {k: v for k, v in self._grids.items() if k[0] != symbol}
        self._backoff.pop(symbol, None)
        self._deferred.discard(symbol)
        self._not_live_since.pop(symbol, None)
        self._applied_at.pop(symbol, None)
        self._quotes.forget(symbol)
        ingest_book_live.labels(symbol=symbol_label(symbol)).set(0.0)  # forgotten: not LIVE

    def out_of_live(self, slo_s: float = RESYNC_BACKOFF_CAP_S) -> tuple[str, ...]:
        """#1919: desired symbols whose book has been out of LIVE longer than `slo_s`
        (default: the resync backoff cap). Plain bookkeeping, no engine query."""
        now = self._clock()
        return tuple(sorted(s for s, t in self._not_live_since.items() if now - t > slo_s))

    # ---- reads (GET /market/orderbook) -----------------------------------
    def view(self, symbol: str, depth: int) -> BookView | None:
        """The maintained book, only while LIVE at `depth` (else `None`); `stale` per `is_stale`."""
        tb = self._books.get(symbol)
        if tb is None or depth > tb.active.depth:
            return None
        snap = tb.active.live_snapshot(depth)
        return None if snap is None else BookView(snap, stale=self.is_stale(symbol))

    def is_stale(self, symbol: str) -> bool:
        """#3807, #2487 F4: True unless `symbol`'s book is LIVE and applied a frame within
        `BOOK_STALE_AFTER_S`. Read from the last applied frame, never from the subscription:
        no book, or a book not LIVE, is stale. It covers the watchdog's `stale` too: that
        watchdog has the same limit and is touched on every routed frame, applied or not."""
        tb = self._books.get(symbol)
        at = self._applied_at.get(symbol)
        if tb is None or at is None or tb.active.phase is not BookPhase.LIVE:
            return True
        return self._clock() - at >= BOOK_STALE_AFTER_S

    def anchor(self, symbol: str) -> BookSnapshot | Literal["no_book", "not_live"]:
        """#2223: the recorder's periodic seek anchor, the active tier's full book stamped with
        its last applied frame, or why there is none. Gated on LIVE, not on frame age: the
        exchange sends nothing while a book does not change, so a quiet LIVE book is still valid."""
        tb = self._books.get(symbol)
        if tb is None:
            return "no_book"
        snap = tb.active.anchor_snapshot()
        return "not_live" if snap is None else snap

    def phase(self, symbol: str) -> BookPhase | None:
        tb = self._books.get(symbol)
        return None if tb is None else tb.active.phase

    def engine(self, symbol: str) -> BookEngine | None:
        """The symbol's active engine, which the WS book snapshot reads (#2196)."""
        tb = self._books.get(symbol)
        return None if tb is None else tb.active

    # ---- tier change -------------------------------------------------------
    async def change_depth(self, symbol: str, depth: int) -> None:
        tb = self._books.get(symbol)
        if tb is None:
            self._depth = depth
            return
        await tb.change_depth(depth)
        self.sync()

    # ---- engines ----------------------------------------------------------
    def _make_engine(self, symbol: str) -> Callable[[int, bool], BookEngine]:
        def make(depth: int, muted: bool) -> BookEngine:
            async def publish(obj: Published) -> None:
                await self._publish(symbol, obj)

            async def resub() -> None:
                key = (symbol, depth)
                if key not in self._first_sub:  # first subscribe is the demand sync itself
                    self._first_sub.add(key)
                    return
                bo = self._backoff.setdefault(symbol, _ResyncBackoff())
                if not bo.allow(self._clock(), self._rand()):
                    # Cooling down: stay desynced/stale, retry from the tick loop.
                    self._deferred.add(symbol)
                    ingest_book_resyncs_total.labels(
                        symbol=symbol_label(symbol), reason="backoff", depth=str(depth)
                    ).inc()
                    return
                self._deferred.discard(symbol)
                await self._resub(self._topic_for(symbol, depth))

            eng = BookEngine(
                symbol=symbol,
                depth=depth,
                publish=publish,
                resubscribe=resub,
                now_us=self._now_us,
                incidents=True,  # E21-T01: each incident's `BookDesyncEvent`
            )
            eng.muted = muted
            return eng

        return make

    async def _ensure(self, symbol: str) -> TieredBook:
        tb = self._books.get(symbol)
        if tb is not None:
            return tb
        tb = TieredBook(self._make_engine(symbol), self.tier(symbol))
        self._books[symbol] = tb
        self._not_live_since[symbol] = self._clock()
        if self._supervisor is not None:
            key = f"{self._env}:{symbol}:{tb.active.depth}"
            self._keys.setdefault(symbol, []).append(key)
            tb.active.health_sink = await self._supervisor.attach(key, symbol)
        await tb.start()
        return tb

    async def _publish(self, symbol: str, obj: Published) -> None:
        if isinstance(obj, BookDesyncEvent):
            await self._publish_desync(symbol, obj)
        else:
            await self._publish_book(symbol, obj)

    async def _publish_desync(self, symbol: str, ev: BookDesyncEvent) -> None:
        """24 §2.9 (E21-T01): the incident on `{env}.health.{symbol}.book_desync`, logged."""
        _observe_desync(ev)
        health = Topic(env=self._env, domain="health", symbol=symbol, detail="book_desync")
        await self._bus.publish(health, ev)

    async def _publish_book(self, symbol: str, obj: BookSnapshot | BookDelta | BookStatus) -> None:
        topic = Topic(env=self._env, domain="md", symbol=symbol, detail="book")
        await self._bus.publish(topic, obj)
        if isinstance(obj, BookStatus):
            _observe_book_status(obj)
            if obj.state is BookPhase.LIVE:
                self._not_live_since.pop(symbol, None)
            else:
                self._quotes.forget(symbol)
            if obj.state is not BookPhase.LIVE and symbol in self._books:
                self._not_live_since.setdefault(symbol, self._clock())
            if obj.state is BookPhase.LIVE:  # stable-LIVE for RESYNC_STABLE_S resets it
                bo = self._backoff.get(symbol)
                if bo is not None:
                    bo.live_at = self._clock()
                self._deferred.discard(symbol)
        if isinstance(obj, BookSnapshot):
            self._enqueue(
                BookSnapshotRow(
                    ts_us=obj.ts_event,
                    symbol=symbol,
                    seq=obj.update_id,
                    bids=tuple((str(x.price), str(x.qty)) for x in obj.bids),
                    asks=tuple((str(x.price), str(x.qty)) for x in obj.asks),
                )
            )
        elif isinstance(obj, BookDelta):
            for side, levels in (("bid", obj.bids), ("ask", obj.asks)):
                for lv in levels:
                    self._enqueue(
                        BookDeltaRow(
                            obj.ts_event, symbol, obj.update_id, side, str(lv.price), str(lv.qty)
                        )
                    )

    def _enqueue(self, row: BookDeltaRow | BookSnapshotRow) -> None:
        if self._writer is None:
            return
        self._writes.put(row)  # never blocks the reader; full -> drop-oldest, counted

    # ---- frames -----------------------------------------------------------
    async def handle_frame(self, frame: str) -> None:
        received = self._perf()
        try:
            ev = self._parse(frame)
        except (ValueError, RecursionError) as exc:
            self._rejects.record(exc)
            sym = getattr(exc, "symbol", None)
            tb = self._books.get(sym) if isinstance(sym, str) else None
            if tb is not None:  # C-2.5: a rejected book frame is a gap -> resync, never patch
                await tb.active.invalidate("rejected_frame")
            return
        if ev is None:
            return
        if ev.symbol not in self._demand.desired():
            if ev.symbol in self._books:  # #3807: its grace ran out unsynced: forget it now
                self.sync()
            return
        # #3806: the grid `ev` was parsed on. No await lies between the parse and this read, so
        # both read the same catalogue tick size.
        grid = None if self._tick_size is None else self._tick_size(ev.symbol)
        self._touch(self._topic_for(ev.symbol, ev.depth))
        tb = await self._ensure(ev.symbol)
        key = (ev.symbol, ev.depth)
        if isinstance(ev, BookSnapshot):
            self._grids[key] = grid  # the grid this tier's book is (re)built on
        elif ev.depth == tb.active.depth and self._grids.get(key, grid) != grid:
            # C-2.5: a delta is never applied across two grids. Leave LIVE and rebuild from a
            # snapshot on the new grid; deltas until then are dropped. A warming tier has no
            # LIVE book yet, and a retired tier's frames are dropped by `TieredBook`.
            await tb.active.invalidate("grid")
            return
        await tb.on_event(ev)
        active = tb.active
        if ev.depth == active.depth and active.phase is BookPhase.LIVE and active.book is not None:
            self._applied_at[ev.symbol] = self._clock()  # applied: what `is_stale` ages
            if isinstance(ev, BookDelta):
                book_apply_latency_ms.labels(symbol=symbol_label(ev.symbol)).observe(
                    (self._perf() - received) * 1000.0
                )
            quote: BestQuoteEvent | None = self._quotes.update(active.book, ev)
            if quote is not None:
                await self._bus.publish(
                    Topic(env=self._env, domain="md", symbol=ev.symbol, detail="quote"), quote
                )
        if tb.warming is None:
            self.sync()  # a completed tier swap retires the old topic

    async def invalidate(self, reason: str) -> None:
        for tb in list(self._books.values()):
            await tb.active.invalidate(reason)

    async def invalidate_symbol(self, symbol: str, reason: str) -> None:
        """#1916: one symbol's dispatch lane dropped frames: resync only it."""
        tb = self._books.get(symbol)
        if tb is not None:
            await tb.active.invalidate(reason)

    async def check_timeouts(self) -> int:
        """SNAPSHOT_TIMEOUT: re-request every snapshot pending too long."""
        n = 0
        for tb in list(self._books.values()):
            e = tb.active
            if e.check_timeout(self._timeout_us):
                n += 1
                await e.on_snapshot_timeout()
        now = self._clock()
        for sym in list(self._deferred):  # cooldown elapsed: the deferred snapshot request
            dtb = self._books.get(sym)
            bo = self._backoff.get(sym)
            if dtb is None or bo is None:
                self._deferred.discard(sym)
            elif now >= bo.next_ok and dtb.active.phase is not BookPhase.LIVE:
                n += 1
                await dtb.active.request_snapshot()
        return n

    async def drain_writes(self, max_batch: int = 500) -> int:
        """Write one batch in row order; on failure requeue the unwritten
        suffix at the head and back off (#1918). Returns rows written."""
        batch = await self._writes.take(max_batch)
        if self._writer is None:
            return len(batch)
        done = 0  # persisted prefix of `batch`: never resent
        try:
            while done < len(batch):
                head = batch[done]
                if isinstance(head, BookSnapshotRow):
                    await self._writer.write_book_snapshot(head)
                    done += 1
                    continue
                run: list[BookDeltaRow] = []
                for r in batch[done:]:
                    if not isinstance(r, BookDeltaRow):
                        break
                    run.append(r)
                await self._writer.write_book_deltas(run)
                done += len(run)
        except asyncio.CancelledError:
            self._writes.restore(batch[done:])  # stop(): nothing taken is lost
            raise
        except Exception:  # write-behind must never take ingest down
            self._writes.requeue(batch[done:])
            logger().warning(
                "book write-behind failed; requeued",
                rows=len(batch) - done,
                failures=self._writes.failures,
            )
            await self._writes.backoff()
            return done
        self._writes.succeeded(batch)
        return done

    @property
    def write_behind(self) -> WriteBehindBuffer[BookDeltaRow | BookSnapshotRow]:
        """Hot-tier write-behind state (health probe + lost-range index)."""
        return self._writes

    async def _health_loop(self) -> None:
        while True:
            ev = await self._health.get()
            if isinstance(ev, FeedHealthEvent) and ev.state in ("resubscribing", "degraded"):
                await self.invalidate("reconnect")  # the socket re-sends snapshots

    async def _write_loop(self) -> None:
        while True:
            await self.drain_writes()

    async def _timeout_loop(self) -> None:
        while True:
            await self._sleep(_TICK_S)
            self.sync()  # #3807: a released symbol's grace ends here, demand change or not
            await self.apply_tiers()
            await self.check_timeouts()

    async def start(self) -> None:
        self._tasks = [
            spawn(self._health_loop(), name="book-health"),
            spawn(self._write_loop(), name="book-write-behind"),
            spawn(self._timeout_loop(), name="book-snapshot-timeout"),
        ]

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._writes.flush_metrics()  # pending batched drop counts (#1918)
        for sym in list(self._books):
            self._drop(sym)
        self._bus.unsubscribe(self._health)


__all__ = ["BookStream", "BookView", "BookWriter", "HealthSupervisor"]

"""`BarBuilderSet`: one bus subscription per symbol, fanned to every builder in one pass (E12-T03).

`24-internal-schemas.md` §3.5. Hot path (C-2.20): plain code, no statechart. Bar series have
no catalogue lifecycle (B1-B20), so lease state is plain bookkeeping in `leases.py`.

- **Fan-out.** The first registered spec on a symbol subscribes `{env}.md.{symbol}.trade` with
  `NEVER_DROP` (trades are never dropped: a full queue backpressures `TradeStream`, §4.2).
  One owned task per symbol pops each trade and folds it into every builder of the symbol in
  registration order. It loops over a tuple that is rebuilt only on (un)register, so the
  per-trade loop builds no list. Builders never touch the bus.
- **Runtime (un)register.** The lane lock serialises the trade loop, registration, the clock
  tick and teardown. A spec added mid-stream sees every trade the lane processes after it joins
  (a restored spec also sees the tape after its watermark, below). No trade is dropped.
- **Lifecycle.** `register(spec, symbol, consumer, user)` takes a lease, `release` drops it, and
  the last release starts the 30 s grace (US-MKT-005). `tick()` (every `tick_s`, driven by the
  injected clock) closes time bars on the clock, tears down expired series after writing their
  final blob, and persists every series each `persist_every_us` (60 s). Caps: see `leases.py`.
- **Restart.** A new series loads its blob (`state_store.py`). If the blob is usable it
  restores (keeping the generation the blob recorded), then replays from the tape only the
  trades after the watermark, then goes live. Live trades the watermark covers are skipped once,
  so nothing is applied twice (BI-5). A missing or refused blob cold-starts the series (fresh
  builder, partial first bar, new generation). A refused blob is also deleted, counted and
  logged with its `spec_hash`, and it sets `health_reasons()`. A refused blob never raises. A
  blob with no watermark has no replay point, so bars emitted after it could not be reproduced:
  it cold-starts the series too (quietly) and only sets the generation floor.
- **Generation (#2662).** A fresh builder restarts `index` at 0, so a cold start begins a new
  generation (epoch): `max(now_ms, floor + 1)`. `now_ms` is the set's injected UTC wall clock
  (`now_us // 1000`). `floor` is the highest generation known for the series: the one a blob
  that still parsed recorded (a refused or watermark-less blob), or the last one this process
  issued or restored for it (a bounded LRU, so a teardown followed by a re-register after a
  failed final save cannot fall back); else -1. A cold start writes its blob at once, so the
  floor survives a crash before the first 60 s persist. The new value is never below the
  cold-start time nor at or below a generation the process or a readable blob knew, so no two
  bars of a series share `(generation, index)`. Residual, accepted: a crash with no readable
  blob and a wall clock that stepped back can give a generation at or below an earlier one. The
  failure is a lower generation, so a consumer treats any change of generation, in either
  direction, as a swap and compares it for equality only, never as a time.
- **Emit.** Live and replayed emissions both go through `EmitRouter` (`emit.py`), stamped with
  the series' generation (`_Entry.generation`), which `WriterSink` stores on every row. An
  ADR-0033 rebuild (E12-S12, not implemented) would write under a generation of its own and
  swap a pointer; it must allocate above the live epoch.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Final, Protocol

import structlog

from candleviewer.bars.activity_builders import TickBarBuilder, VolumeBarBuilder
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.errors import BarsError, BarSpecError
from candleviewer.bars.leases import DEFAULT_CAPS, SpecCaps, SpecLeases
from candleviewer.bars.metrics import (
    bar_builder_cold_start_seconds,
    bar_builder_cold_starts_total,
    bar_builder_fanout_latency_seconds,
    bar_builder_quarantined_total,
    bar_builder_specs_in_use,
    bar_state_snapshots_written_total,
    bars_blob_discarded_total,
    bars_restore_gap_total,
)
from candleviewer.bars.models import BarBuilder, BarSpec, BarUpdate
from candleviewer.bars.renko_builder import RenkoBarBuilder
from candleviewer.bars.state_store import StateStore, StoredState, Watermark
from candleviewer.bars.threshold_builders import DeltaBarBuilder, RangeBarBuilder
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.bus.bus import Bus, Subscription
from candleviewer.bus.models import QueuePolicy, Topic
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.observability.context import spawn

PERSIST_EVERY_US: Final = 60_000_000
TICK_S: Final = 1.0
LANE_QUEUE: Final = 4096
#: Trades a lane remembers after applying them, so a series restored mid-stream can catch up
#: on trades the lane applied that the (asynchronously written) tape does not hold yet.
RECENT_RING: Final = 8192
#: Series whose last generation the set remembers (an LRU): a floor for a re-register after a
#: teardown whose final blob could not be written. Bounded, as every structure here is (C-2.18).
ISSUED_FLOOR_CAP: Final = 4096


class BarsHealthReason(StrEnum):
    """Stable `HealthReport.detail` tokens for the bars module (#1950 `HealthReason` pattern)."""

    #: A state blob was refused and its series cold-started (sticky until restart; SR-E12-12).
    STATE_BLOB_COLD_STARTED = "bar_state_blob_cold_started"
    #: A builder raised; its series was quarantined (removed) and the lane kept draining.
    BUILDER_QUARANTINED = "bar_builder_quarantined"
    #: A lane or the ticker task died unexpectedly; its subscription was removed so the
    #: trade publisher can never block on it.
    TASK_FAILED = "bar_task_failed"
    #: A restored series could not be caught up: the tape lagged by more than the lane's
    #: recent-trade ring, so trades between the tape head and the ring were missed.
    RESTORE_GAP = "bar_restore_gap"
    #: An emit sink missed its `SINK_TIMEOUT_S` bound (emit.py).
    SINK_TIMEOUT = "bar_emit_sink_timeout"


STATE_COLD_STARTED: Final = BarsHealthReason.STATE_BLOB_COLD_STARTED
_RESTORE_ERRORS = (BarsError, ValueError, KeyError, TypeError, IndexError, ArithmeticError)
#: Load outcomes that cold-start a series without a discard (not counted, no health reason).
_QUIET_REASONS: Final = ("ok", "missing", "no_watermark")
BuilderFactory = Callable[[BarSpec, str], BarBuilder]


def _log() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


def default_factory(spec: BarSpec, symbol: str) -> BarBuilder:
    """time/tick/volume/delta: builders that need no instrument data. range and renko need
    the tick size and are composed by `production_factory`."""
    kinds: dict[str, BuilderFactory] = {
        "time": TimeBarBuilder,
        "tick": TickBarBuilder,
        "volume": VolumeBarBuilder,
        "delta": DeltaBarBuilder,
    }
    make = kinds.get(spec.kind)
    if make is None:
        raise BarSpecError(f"Bar series of kind '{spec.kind}' are not available yet.")
    return make(spec, symbol)


def renko_factory(
    tick_size_of: Callable[[str], Decimal | None], base: BuilderFactory = default_factory
) -> BuilderFactory:
    """`base` plus renko (E12-S04), composed only when the `bars_renko_enabled` flag is on."""

    def make(spec: BarSpec, symbol: str) -> BarBuilder:
        if spec.kind == "renko":
            return RenkoBarBuilder(spec, symbol, tick_size_of)
        return base(spec, symbol)

    return make


def production_factory(
    tick_size_of: Callable[[str], Decimal | None], *, renko_enabled: bool
) -> BuilderFactory:
    """The factory the app composes: `default_factory` + range (E12-S03, needs `tick_size_of`),
    plus renko (E12-S04) only when the `bars_renko_enabled` flag is on (#2191)."""

    def with_range(spec: BarSpec, symbol: str) -> BarBuilder:
        if spec.kind == "range":
            return RangeBarBuilder(spec, symbol, tick_size_of)
        return default_factory(spec, symbol)

    return renko_factory(tick_size_of, with_range) if renko_enabled else with_range


class TapeSource(Protocol):
    """Recorded trades of a symbol (E12-T02 trades table / recorder), oldest first."""

    async def head_us(self, symbol: str) -> int | None: ...

    def since(self, symbol: str, ts_us: int) -> AsyncIterator[TradeEvent]: ...


class _Mark:
    """Mutable watermark: newest `ts_event` applied and the trade ids applied at it."""

    __slots__ = ("ids", "ts")

    def __init__(self, ts: int = -(2**63), ids: frozenset[str] = frozenset()) -> None:
        self.ts, self.ids = ts, set(ids)

    def advance(self, ts: int, trade_id: str) -> None:
        if ts > self.ts:
            self.ts = ts
            self.ids.clear()
        if ts == self.ts:
            self.ids.add(trade_id)

    def covers(self, ts: int, trade_id: str) -> bool:
        return ts < self.ts or (ts == self.ts and trade_id in self.ids)

    def frozen(self) -> Watermark:
        return Watermark(self.ts, frozenset(self.ids))


@dataclass(slots=True)
class _Entry:
    spec: BarSpec
    builder: BarBuilder
    saved_at: int
    generation: int
    skip: _Mark | None = None  # restored/replayed watermark; cleared once live passes it


@dataclass(slots=True)
class _Lane:
    symbol: str
    sub: Subscription
    entries: tuple[_Entry, ...] = ()
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    mark: _Mark = field(default_factory=_Mark)
    task: asyncio.Task[None] | None = None
    recent: deque[TradeEvent] = field(default_factory=lambda: deque(maxlen=RECENT_RING))


class BarBuilderSet:
    def __init__(
        self,
        bus: Bus,
        env: str,
        router: EmitRouter,
        store: StateStore,
        *,
        tape: TapeSource | None = None,
        now_us: Callable[[], int],
        caps: SpecCaps = DEFAULT_CAPS,
        factory: BuilderFactory = default_factory,
        persist_every_us: int = PERSIST_EVERY_US,
        tick_s: float = TICK_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._bus, self._env, self._router, self._store = bus, env, router, store
        self._tape, self._now, self._factory = tape, now_us, factory
        self._persist_every, self._tick_s, self._sleep = persist_every_us, tick_s, sleep
        self._leases = SpecLeases(caps)
        self._lanes: dict[str, _Lane] = {}
        self._issued: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._ticker: asyncio.Task[None] | None = None
        self._reasons: set[BarsHealthReason] = set()
        self._drains: set[asyncio.Task[None]] = set()
        self._stopping = False

    def health_reasons(self) -> tuple[BarsHealthReason, ...]:
        """Sticky degraded reasons, sorted (`BarsService.health()` reports them)."""
        reasons = set(self._reasons)
        if self._router.timed_out:
            reasons.add(BarsHealthReason.SINK_TIMEOUT)
        return tuple(sorted(reasons))

    def _supervise(self, task: asyncio.Task[None], on_death: Callable[[], None]) -> None:
        """A task that ends other than by cancellation is a defect: log, mark health, clean up."""

        def done(t: asyncio.Task[None]) -> None:
            if t.cancelled() or t.exception() is None:
                return
            exc = t.exception()
            self._reasons.add(BarsHealthReason.TASK_FAILED)
            bar_builder_quarantined_total.labels(reason="task_failed").inc()
            _log().error("bars_task_failed", task=t.get_name(), error_type=type(exc).__name__)
            on_death()

        task.add_done_callback(done)

    # -- lifecycle -------------------------------------------------------------------------
    async def start(self) -> None:
        """Clear crash-leftover temp blobs, then start the clock/persistence ticker."""
        if self._ticker is None:
            await self._store.sweep_tmp()
            self._ticker = spawn(self._tick_loop(), name="bars-set-tick")
            self._supervise(self._ticker, lambda: None)

    async def stop(self) -> None:
        """Refuse new registrations, cancel the ticker, then per lane: unsubscribe (no new
        deliveries), cancel the loop, apply everything still queued (including publishers
        that were blocked on a full queue and wake as it drains), write final blobs.

        Bounded loss: none for trades delivered before the unsubscribe. A publish that starts
        after it never reaches the set; the restart replays it from the tape."""
        self._stopping = True
        if self._ticker is not None:
            self._ticker.cancel()
            await asyncio.gather(self._ticker, return_exceptions=True)
            self._ticker = None
        if self._drains:
            await asyncio.gather(*self._drains, return_exceptions=True)
        for symbol in list(self._lanes):
            lane = self._lanes.pop(symbol)
            await self._stop_lane(lane)
            async with lane.lock:
                idle = 0
                while idle < 2:  # two empty passes: woken blocked putters have landed
                    if lane.sub.qsize():
                        idle = 0
                        await self._apply(lane, lane.sub.get_nowait())
                    else:
                        idle += 1
                        await asyncio.sleep(0)
                saves = [self._stored(lane, e) for e in lane.entries]
            for stored in saves:
                await self._save(stored)
            bar_builder_specs_in_use.labels(symbol=symbol).set(0)

    async def _maybe_close_lane(self, symbol: str) -> None:
        """Drop the symbol's subscription once it has no series and no pending lease."""
        lane = self._lanes.get(symbol)
        if lane is not None and not lane.entries and not self._leases.on_symbol(symbol):
            del self._lanes[symbol]
            await self._stop_lane(lane)

    async def _stop_lane(self, lane: _Lane) -> None:
        self._unsubscribe(lane)
        if lane.task is not None:
            lane.task.cancel()
            await asyncio.gather(lane.task, return_exceptions=True)

    def _on_lane_death(self, lane: _Lane) -> None:
        """Unsubscribe (no new deliveries), then drain the orphaned queue in a tracked task so
        a publisher already blocked in `queue.put` on it is released (#2030 review)."""
        self._unsubscribe(lane)
        self._lanes.pop(lane.symbol, None)
        task = spawn(self._drain_dead(lane), name=f"bars-drain-{lane.symbol}")
        self._drains.add(task)
        task.add_done_callback(self._drains.discard)

    @staticmethod
    async def _drain_dead(lane: _Lane) -> None:
        """Each `get_nowait` wakes one blocked putter, which then lands its item; loop until two
        passes in a row find the queue empty, so every blocked publisher has completed. No new
        putter can arrive (unsubscribed), so this ends. The drained trades are lost for this
        lane only; the series are quarantined and health reports `bar_task_failed`."""
        idle = 0
        while idle < 2:
            if lane.sub.qsize():
                idle = 0
                while lane.sub.qsize():
                    lane.sub.get_nowait()
            else:
                idle += 1
            await asyncio.sleep(0)

    def _unsubscribe(self, lane: _Lane) -> None:
        if lane.sub in self._bus._subscriptions:
            self._bus.unsubscribe(lane.sub)

    async def _tick_loop(self) -> None:
        while True:
            await self._sleep(self._tick_s)
            try:
                await self.tick()
            except Exception as exc:  # the ticker must outlive one bad tick
                self._reasons.add(BarsHealthReason.TASK_FAILED)
                _log().error("bars_tick_failed", error_type=type(exc).__name__)

    # -- leases ----------------------------------------------------------------------------
    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        """Lease `(symbol, spec)` for `consumer`; builds the series on first lease.

        `user` MUST be the authenticated principal id resolved server-side (never a client
        string), or the per-user cap is meaningless. `None` is reserved for system consumers
        (recorder, rules) and skips only the per-user cap.

        Raises `SpecCapExceeded` (nothing changed) or `BarSpecError` for an unbuildable kind.
        """
        if self._stopping:
            raise BarsError("The bar service is shutting down; open the series again later.")
        key = (symbol, spec.spec_hash)
        if not self._leases.acquire(key, consumer, user):
            return
        try:
            builder = self._factory(spec, symbol)
            lane = self._lane(symbol)
            async with lane.lock:
                # A series still in teardown (expired, lock not yet taken) is re-adopted.
                if all(e.spec.spec_hash != key[1] for e in lane.entries):
                    entry = await self._build(spec, symbol, builder, lane)
                    lane.entries = (*lane.entries, entry)
        except BaseException:
            self._leases.drop(key)
            await self._maybe_close_lane(symbol)
            raise
        bar_builder_specs_in_use.labels(symbol=symbol).set(len(lane.entries))

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        self._leases.release((symbol, spec_hash), consumer, self._now())

    def release_consumer(self, consumer: str) -> None:
        """Liveness sweep: a client that vanished without releasing loses all its leases."""
        self._leases.release_consumer(consumer, self._now())

    def active(self, symbol: str) -> tuple[str, ...]:
        lane = self._lanes.get(symbol)
        return () if lane is None else tuple(e.spec.spec_hash for e in lane.entries)

    def _lane(self, symbol: str) -> _Lane:
        lane = self._lanes.get(symbol)
        if lane is None:
            topic = Topic(env=self._env, domain="md", symbol=symbol, detail="trade")
            sub = self._bus.subscribe(
                f"bars.{symbol}", topic.key, QueuePolicy.NEVER_DROP, maxsize=LANE_QUEUE
            )
            lane = self._lanes[symbol] = _Lane(symbol, sub)
            lane.task = spawn(self._run(lane), name=f"bars-lane-{symbol}")
            # A dead lane must never leave a NEVER_DROP queue for the publisher to block on.
            self._supervise(lane.task, lambda: self._on_lane_death(lane))
        return lane

    # -- restore / replay ------------------------------------------------------------------
    async def _build(self, spec: BarSpec, symbol: str, builder: BarBuilder, lane: _Lane) -> _Entry:
        """Restore or cold-start a series. Runs under `lane.lock`, so no live trade is applied
        meanwhile. A restored series replays the tape after its watermark, then the lane's
        recent ring: trades the lane already applied that the async tape writer may not have
        landed yet. Both are deduped by the advancing watermark, so the series is exactly
        caught up to `lane.mark` before it joins (BI-5). The replay holds the lane lock; moving
        it to a staged entry outside the lock is a follow-up."""
        t0 = time.perf_counter()
        h = spec.spec_hash
        key = (symbol, h)
        stored, reason = await self._store.load(symbol, h)
        recorded = -1 if stored is None else stored.generation  # -1: no blob parsed
        wm = None if stored is None else stored.watermark
        if stored is not None and wm is None:
            # No replay point: bars emitted after this blob could not be reproduced, so its
            # epoch must not continue. It still sets the floor (`recorded`).
            stored, reason = None, "no_watermark"
        if wm is not None and self._tape is not None:
            head = await self._tape.head_us(symbol)
            if head is not None and wm.ts_us > head:
                stored, reason = None, "ahead_of_tape"
        if stored is not None:
            try:
                builder.restore(stored.state)
            except _RESTORE_ERRORS:
                stored, reason, builder = None, "restore_failed", self._factory(spec, symbol)
        if reason not in _QUIET_REASONS:
            bars_blob_discarded_total.labels(reason=reason).inc()
            _log().warning("bars_state_blob_discarded", symbol=symbol, spec_hash=h, reason=reason)
            await self._store.delete(symbol, h)
            self._reasons.add(STATE_COLD_STARTED)
        now = self._now()
        if stored is not None:
            generation = stored.generation  # a restored series keeps its epoch
        else:
            # A cold start begins a new generation (`index` restarts at 0 in the fresh builder):
            # the wall time in ms, above every generation known for the series, so a clock that
            # stepped back cannot reuse one: the blob that parsed (`recorded`) and the last one
            # this process issued or restored for it.
            floor = max(recorded, self._issued.get(key, -1))
            generation = max(now // 1000, floor + 1)
        self._remember(key, generation)
        entry = _Entry(spec, builder, saved_at=now, generation=generation)
        if stored is None:
            bar_builder_cold_starts_total.inc()
            _log().info(
                "bars_series_cold_started",
                symbol=symbol,
                spec_hash=h,
                reason=reason,
                generation=generation,
            )
            # Write the new epoch now: the next periodic persist is a minute away, and a crash
            # plus a clock step-back before it would let the generation fall below this one.
            await self._save(self._stored(lane, entry))
        elif wm is not None:
            entry.skip = skip = _Mark(wm.ts_us, wm.ids)
            if self._tape is not None:
                async for t in self._tape.since(symbol, wm.ts_us):
                    await self._catch_up(entry, skip, t)
            ring = tuple(lane.recent)
            if (
                ring
                and len(ring) == RECENT_RING
                and ring[0].ts_event > skip.ts
                and not skip.covers(ring[0].ts_event, ring[0].trade_id)
            ):
                # The ring has evicted trades newer than everything replayed: a gap we cannot
                # fill. Fail loud; the series still joins (partial history) rather than block.
                bars_restore_gap_total.inc()
                self._reasons.add(BarsHealthReason.RESTORE_GAP)
                _log().warning(
                    "bars_restore_gap",
                    symbol=symbol,
                    spec_hash=h,
                    replayed_to_us=skip.ts,
                    ring_oldest_us=ring[0].ts_event,
                )
            for t in ring:
                await self._catch_up(entry, skip, t)
        bar_builder_cold_start_seconds.observe(time.perf_counter() - t0)
        return entry

    def _remember(self, key: tuple[str, str], generation: int) -> None:
        """Note the newest generation issued for a series; evict the least recently used."""
        issued = self._issued
        issued[key] = max(generation, issued.get(key, -1))
        issued.move_to_end(key)
        while len(issued) > ISSUED_FLOOR_CAP:
            issued.popitem(last=False)

    async def _catch_up(self, entry: _Entry, skip: _Mark, t: TradeEvent) -> None:
        if not skip.covers(t.ts_event, t.trade_id):
            await self._emit(entry, entry.builder.on_trade(t))
            skip.advance(t.ts_event, t.trade_id)

    # -- hot path --------------------------------------------------------------------------
    async def _run(self, lane: _Lane) -> None:
        sub = lane.sub
        while True:
            trade = await sub.get()
            async with lane.lock:
                await self._apply(lane, trade)

    async def _apply(self, lane: _Lane, t: TradeEvent) -> None:
        t0 = time.perf_counter()
        ts, tid = t.ts_event, t.trade_id
        for e in lane.entries:
            skip = e.skip
            if skip is not None:
                if skip.covers(ts, tid):
                    continue
                if ts > skip.ts:
                    e.skip = None
            try:
                ups = e.builder.on_trade(t)
            except Exception as exc:  # one bad builder must never stall the symbol's lane
                self._quarantine(lane, e, exc)
                continue
            if ups:
                await self._router.emit(e.spec, ups, e.generation)
        lane.mark.advance(ts, tid)
        lane.recent.append(t)
        bar_builder_fanout_latency_seconds.observe(time.perf_counter() - t0)

    def _quarantine(self, lane: _Lane, e: _Entry, exc: Exception) -> None:
        """Remove a failing series from its lane (the loop keeps draining for the others).
        Its leases stay, so it is not silently rebuilt; health reports the quarantine."""
        lane.entries = tuple(x for x in lane.entries if x is not e)
        self._reasons.add(BarsHealthReason.BUILDER_QUARANTINED)
        bar_builder_quarantined_total.labels(reason="builder_error").inc()
        _log().error(
            "bars_builder_quarantined",
            symbol=lane.symbol,
            spec_hash=e.spec.spec_hash,
            error_type=type(exc).__name__,
        )

    async def _emit(self, e: _Entry, ups: Sequence[BarUpdate]) -> None:
        if ups:
            await self._router.emit(e.spec, ups, e.generation)

    # -- clock, persistence, teardown ------------------------------------------------------
    async def tick(self) -> None:
        """Clock closes, 60 s persistence and grace-period teardown (driven by `start()`)."""
        now = self._now()
        saves: list[StoredState] = []
        for lane in list(self._lanes.values()):
            async with lane.lock:
                for e in lane.entries:
                    try:
                        ups = e.builder.on_clock(now)
                        if now - e.saved_at >= self._persist_every:
                            e.saved_at = now
                            saves.append(self._stored(lane, e))
                    except Exception as exc:  # one spec must not stop closes for all
                        self._quarantine(lane, e, exc)
                        continue
                    await self._emit(e, ups)
        for symbol, h in self._leases.expired(now):
            lane = self._lanes[symbol]
            async with lane.lock:
                if (symbol, h) in self._leases:
                    continue  # re-leased while we waited for the lock
                gone = [e for e in lane.entries if e.spec.spec_hash == h]
                lane.entries = tuple(e for e in lane.entries if e.spec.spec_hash != h)
                for e in gone:  # final blob, written before a re-register can read it
                    await self._save(self._stored(lane, e))
            bar_builder_specs_in_use.labels(symbol=symbol).set(len(lane.entries))
            await self._maybe_close_lane(symbol)
        for stored in saves:
            await self._save(stored)

    def _stored(self, lane: _Lane, e: _Entry) -> StoredState:
        mark = e.skip if e.skip is not None and e.skip.ts > lane.mark.ts else lane.mark
        wm = None if mark.ts == _Mark().ts else mark.frozen()
        return StoredState(e.builder.snapshot(), wm, e.generation)

    async def _save(self, stored: StoredState) -> None:
        try:
            await self._store.save(stored)
        except (OSError, BarsError) as exc:
            _log().warning(
                "bars_state_write_failed",
                spec_hash=stored.state.spec_hash,
                error_type=type(exc).__name__,
            )
            return
        bar_state_snapshots_written_total.inc()

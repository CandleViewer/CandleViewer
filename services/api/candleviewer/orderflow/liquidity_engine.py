"""The wired `LiquidityTracker` (E21-T04 PR 2, #710; 24 §2.11): one tracker per pinned symbol,
fed by the `HeatmapTopic`'s native sampler and the trade bus, publishing `LiquidityReload` and
`LiquidityPulled` on `{env}.md.{symbol}.liquidity`.

- **One sampler (carry e).** The heatmap engine reads the book; at every native 100 ms deadline of
  a pinned symbol it hands `on_deadline` the levels it last read (instantaneous, never an averaged
  column). Nothing here walks a book. The levels' float sizes are quantised back to the
  instrument's `qty_step` as `Decimal`, PR 1's exact semantics.
- **Grid (carry d).** A sample's time is its deadline, on the epoch 100 ms grid, so a replay of
  the same book and tape derives the same samples. `None` levels (the book not LIVE, the resync
  hold, or a deadline the engine closed late) are an estimated gap: no events, pending state
  reset, the next live sample re-baselines. A deadline the engine skipped (a stall) shows as a
  jump of more than one column: a gap sample is recorded one column before the live one, which
  then re-baselines. A trade-queue overflow (`StreamInvalidated`) makes the symbol's next sample a
  gap too, as the tape it would judge by is incomplete.
- **Pins.** `liquidity_pinned_symbols` (at most `liquidity_pin_max`) are pinned at `start` and
  released at `stop`: the configured set stands in for the rule engine's tracked symbols until
  that API exists (24 §2.11). Each pin holds the symbol's book at `PIN_DEPTH` itself (the
  heatmap's `heatmap:pin` demand), so detection runs with no WS viewer. The heatmap engine runs
  only with the public WS wired, so detection does too.
- **Bounds (C-2.18).** At most `max_events` events a sample (the rest counted as `sample_cap`),
  an outbound queue of `OUT_MAX` (oldest shed and counted as `publish_queue`), each publish
  bounded by `PUBLISH_TIMEOUT_S`, the trade subscription bounded at `TRADE_QUEUE_MAX`.
- **Tasks.** One owned task runs a `TaskGroup` of the trade reader and the publisher; `stop`
  releases the pins and the sampler, cancels it and waits for it, and unsubscribes; a `start`
  that fails part-way releases what it took. The sample path is plain
  synchronous code (C-2.20): no statechart, no await, no wall clock beyond `perf_counter` for its
  own histogram.
- **Call-once (carry b).** `distance_to_liquidity_cluster` reads the tracker's per-sample cache.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog

from candleviewer.book.models import BookPhase
from candleviewer.bus import Bus, QueuePolicy, StreamInvalidated, Topic, TopicPattern
from candleviewer.bus import Subscription as BusSubscription
from candleviewer.bus.models import WILDCARD
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.observability.context import spawn, spawn_child
from candleviewer.orderflow import liquidity_metrics as lm
from candleviewer.orderflow.heatmap import COLUMN_MS, NativeLevels, Sampler
from candleviewer.orderflow.liquidity import LiquidityTracker
from candleviewer.orderflow.liquidity_models import (
    LiquidityConfig,
    LiquidityPulled,
    LiquidityReload,
    LiquiditySample,
)

#: The depth a pin reads: the ticket's 200-level budget (below the heatmap's deep tier).
PIN_DEPTH: Final = 200
#: Liquidity events waiting for the bus; past it the oldest are shed (counted).
OUT_MAX: Final = 1_024
#: Bound on one bus publish (a NEVER_DROP subscriber that stalls costs that event, counted).
PUBLISH_TIMEOUT_S: Final = 1.0
#: The trade subscription (INVALIDATE_ON_FULL: an overflow is a tape gap, never a stall upstream).
TRADE_QUEUE_MAX: Final = 16_384
DETAIL: Final = "liquidity"
#: Quantised sizes remembered per symbol (a size in steps -> its `Decimal`): a sample reads at
#: most 2 x `PIN_DEPTH` sizes, so 4 096 holds about ten samples' worth, under 1 MB a symbol.
DECIMALS_MAX: Final = 4_096

Event = LiquidityReload | LiquidityPulled
Steps = Callable[[str], tuple[Decimal, Decimal] | None]


def _log() -> Any:
    return structlog.get_logger(__name__)


def _causes(exc: BaseException) -> list[str]:
    """The exception types inside `exc` (a `TaskGroup` raises a group), names only: a message
    may carry what must never be logged."""
    if isinstance(exc, BaseExceptionGroup):
        return sorted({name for sub in exc.exceptions for name in _causes(sub)})
    return [type(exc).__name__]


def _stopped(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _log().error("liquidity_tracker_stopped", error=type(exc).__name__, causes=_causes(exc))


class Pins(Protocol):
    """What the engine needs of `HeatmapTopic`."""

    def set_sampler(self, sampler: Sampler | None) -> None: ...
    def pin_native(self, symbol: str, depth: int) -> None: ...
    def unpin_native(self, symbol: str) -> None: ...


class _Quantised:
    """A `BookView` over instantaneous float levels, sizes quantised to `qty_step` (`Decimal`).
    A level that quantises to zero is skipped. `cache` maps a size in steps to its `Decimal`
    (the symbol's, bounded at `DECIMALS_MAX`: cleared when full)."""

    __slots__ = ("_asks", "_bids", "_cache", "_step", "_unit")

    def __init__(
        self, levels: NativeLevels, qty_step: Decimal, cache: dict[int, Decimal] | None = None
    ) -> None:
        self._bids, self._asks, self._step = levels.bids, levels.asks, qty_step
        self._unit = float(qty_step)
        self._cache: dict[int, Decimal] = {} if cache is None else cache

    def walk(self, *, bids: bool) -> Iterator[tuple[int, Decimal]]:
        step, unit, cache = self._step, self._unit, self._cache
        out: list[tuple[int, Decimal]] = []
        for tick, size in (self._bids if bids else self._asks).items():
            units = round(size / unit)
            if units > 0:
                exact = cache.get(units)
                if exact is None:
                    if len(cache) >= DECIMALS_MAX:
                        cache.clear()
                    exact = cache[units] = step * units
                out.append((tick, exact))
        return iter(out)


class _Empty:
    def walk(self, *, bids: bool) -> Iterator[tuple[int, Decimal]]:
        return iter(())


_EMPTY: Final = _Empty()


class _Symbol:
    __slots__ = ("decimals", "label", "last_ms", "qty_step", "tape_gap", "topic", "tracker")

    def __init__(self, tracker: LiquidityTracker, qty_step: Decimal, topic: Topic) -> None:
        self.tracker, self.qty_step, self.topic = tracker, qty_step, topic
        self.label = lm.symbol_label(tracker.symbol)
        self.last_ms: int | None = None
        self.tape_gap = False
        self.decimals: dict[int, Decimal] = {}


class LiquidityEngine:
    def __init__(
        self,
        bus: Bus,
        env: str,
        *,
        pins: Pins,
        steps: Steps,
        symbols: Sequence[str],
        config: LiquidityConfig | None = None,
    ) -> None:
        self._bus, self._env, self._pins, self._steps = bus, env, pins, steps
        self._config = (config or LiquidityConfig()).validated()
        self._wanted = tuple(dict.fromkeys(symbols))
        self._symbols: dict[str, _Symbol] = {}
        self._out: deque[tuple[_Symbol, Event]] = deque()
        self._wake = asyncio.Event()
        self._sub: BusSubscription | None = None
        self._task: asyncio.Task[None] | None = None

    # -- lifecycle (`WsRuntime` feed) ------------------------------------------------------------

    def start(self) -> None:
        """Pin the configured symbols, subscribe the tape, run the reader and the publisher."""
        if self._task is not None or not self._wanted:
            return
        pattern = TopicPattern(env=self._env, domain="md", symbol=WILDCARD, detail="trade")
        self._sub = self._bus.subscribe(
            "liquidity-tracker", pattern, QueuePolicy.INVALIDATE_ON_FULL, maxsize=TRADE_QUEUE_MAX
        )
        try:
            self._pins.set_sampler(self.on_deadline)
            for symbol in self._wanted:
                self._pins.pin_native(symbol, PIN_DEPTH)
            self._task = spawn(self._main(), name="liquidity-tracker")
        except BaseException:  # a partial start holds nothing: the pins and the tape go
            self._unpin()
            self._unsubscribe()
            raise
        self._task.add_done_callback(_stopped)

    async def stop(self) -> None:
        """Release the sampler and the pins, cancel the task, unsubscribe; queued events go.
        The task is waited, never awaited: the caller's own cancellation is not swallowed."""
        task, self._task = self._task, None
        try:
            self._unpin()
        finally:  # a failed release still cancels the task and lets the tape go
            await self._halt(task)

    async def _halt(self, task: asyncio.Task[None] | None) -> None:
        try:
            if task is not None:
                task.cancel()
                await asyncio.wait({task})
        finally:  # a cancelled `stop` still lets the tape go
            self._unsubscribe()
            self._out.clear()
            self._symbols.clear()

    def _unpin(self) -> None:
        self._pins.set_sampler(None)
        for symbol in self._wanted:
            self._pins.unpin_native(symbol)  # idempotent: a symbol never pinned is a no-op

    def _unsubscribe(self) -> None:
        sub, self._sub = self._sub, None
        if sub is not None:
            self._bus.unsubscribe(sub)

    async def _main(self) -> None:
        async with asyncio.TaskGroup() as group:
            spawn_child(group, self._read(), name="liquidity-trades")
            spawn_child(group, self._publish(), name="liquidity-publish")

    # -- inputs ----------------------------------------------------------------------------------

    def _offer(self, item: object) -> None:
        if isinstance(item, TradeEvent):
            sym = self._symbols.get(item.symbol)
            if sym is not None:
                sym.tracker.on_trade(item)  # dedup by trade_id inside
        elif isinstance(item, StreamInvalidated):
            for sym in self._symbols.values():  # the wildcard queue lost prints of any symbol
                sym.tape_gap = True
            _log().warning("liquidity_tape_invalidated", topic=item.topic)

    def _pump(self) -> None:
        """Drain the tape without waiting, so a sample judges by every print queued before it."""
        sub = self._sub
        while sub is not None:
            try:
                item = sub.get_nowait()
            except asyncio.QueueEmpty:
                return
            self._offer(item)

    async def _read(self) -> None:
        while (sub := self._sub) is not None:
            item = await sub.get()
            try:
                self._offer(item)
            except Exception as exc:  # one bad print never stops the tape
                _log().error("liquidity_trade_failed", error=type(exc).__name__)

    def _tracker(self, symbol: str) -> _Symbol | None:
        sym = self._symbols.get(symbol)
        if sym is None and symbol in self._wanted:
            steps = self._steps(symbol)
            if steps is None:
                return None  # the instrument is not known yet: no tracker, no sample
            tick, qty_step = steps
            tracker = LiquidityTracker(symbol, tick, qty_step, self._config)
            # `DETAIL`, spelt out: the E08 handshake scan reads a literal detail (24 §2.9).
            topic = Topic(env=self._env, domain="md", symbol=symbol, detail="liquidity")
            sym = self._symbols[symbol] = _Symbol(tracker, qty_step, topic)
            lm.liquidity_tracker_memory_bytes.labels(symbol=sym.label).set(tracker.memory_bytes)
        return sym

    def on_deadline(self, symbol: str, t_ms: int, levels: NativeLevels | None) -> None:
        """The heatmap's native sampler (module doc): one sample on the 100 ms grid."""
        sym = self._tracker(symbol)
        if sym is None:
            return
        began = time.perf_counter()
        self._pump()
        tracker, ts_us = sym.tracker, t_ms * 1000
        if sym.last_ms is not None and t_ms - sym.last_ms > COLUMN_MS:
            tracker.on_sample(ts_us - COLUMN_MS * 1000, BookPhase.DESYNCED, _EMPTY)  # skipped
        sym.last_ms = t_ms
        if levels is None or sym.tape_gap:
            sym.tape_gap = False
            result = tracker.on_sample(ts_us, BookPhase.DESYNCED, _EMPTY)
        else:
            result = tracker.on_sample(
                ts_us, BookPhase.LIVE, _Quantised(levels, sym.qty_step, sym.decimals)
            )
        self._emit(sym, result)
        lm.liquidity_band_compute_ms.observe((time.perf_counter() - began) * 1000.0)

    def _emit(self, sym: _Symbol, result: LiquiditySample) -> None:
        if result.overflow:
            lm.liquidity_events_overflow_total.labels(sym.label, "sample_cap").inc(result.overflow)
        for ev in result.events:
            if len(self._out) >= OUT_MAX:
                shed, _ = self._out.popleft()
                lm.liquidity_events_overflow_total.labels(shed.label, "publish_queue").inc()
            self._out.append((sym, ev))
        if result.events:
            self._wake.set()

    # -- outputs ---------------------------------------------------------------------------------

    async def _publish(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._out:
                sym, ev = self._out.popleft()
                try:
                    async with asyncio.timeout(PUBLISH_TIMEOUT_S):
                        await self._bus.publish(sym.topic, ev)
                except Exception as exc:  # that event is lost (counted), the next goes on
                    lm.liquidity_events_overflow_total.labels(sym.label, "publish_queue").inc()
                    _log().warning("liquidity_publish_failed", error=type(exc).__name__)
                    continue
                kind = lm.liquidity_reload_events_total
                if isinstance(ev, LiquidityPulled):
                    kind = lm.liquidity_pulled_events_total
                kind.labels(symbol=sym.label).inc()

    def tracker(self, symbol: str) -> LiquidityTracker | None:
        sym = self._symbols.get(symbol)
        return None if sym is None else sym.tracker

    def distance_to_liquidity_cluster(self, symbol: str) -> int | None:
        """24 §7's accessor at its defaults, from the tracker's per-sample cache (call-once)."""
        tracker = self.tracker(symbol)
        return None if tracker is None else tracker.distance_to_liquidity_cluster()

    @property
    def queued(self) -> int:
        return len(self._out)


__all__ = ["DETAIL", "OUT_MAX", "PIN_DEPTH", "LiquidityEngine", "Pins"]

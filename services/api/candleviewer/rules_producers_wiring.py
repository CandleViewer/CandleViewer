"""Composition-root wiring (not a module): the rules' metric producers (E35-T15, #5745).

Only the composition root sees the bars, the book, the bus and the rules together (C-3.1); each
producer here reads one shipped market path and writes through its own `PushSink` (the bridge,
`rules/producers.py`), never the source. Market-scope metrics only (#1204 Part B's binding rule).

* Quotes and the ticker: `QuoteProducer` (``{env}.md.*.quote``) and `TickerProducer`
  (``{env}.md.*.ticker``) are wildcard bus consumers built as `ingestion/ticker_topic.py` is:
  `INVALIDATE_ON_FULL` on a bounded queue (the bus's `CONFLATE_LATEST` keeps one event across
  every symbol of a wildcard subscription), one tracked task, a keyed dict of each symbol's
  latest event capped at `MAX_SYMBOLS`; an invalidation marker clears it, so each symbol's next
  event re-pushes. They push at most once per symbol per window (100 ms and 250 ms), then tick
  ``on_book_update`` / ``on_price_update`` for the symbol. Only the process's own live ``env`` is
  subscribed and only ``source == "live"`` events are taken: a replay session never feeds the
  source (C-2.11).
* The book: `BookDepthProducer` reads the demanded symbols' books every 100 ms (never per delta,
  C-2.20) through `BookStream.view` at the deepest demanded ``n`` the book holds; a want deeper
  than the book, or a book not LIVE, pushes nothing and stays ``warmup`` without holding back
  the shallower wants; `book_staleness_ms` needs no view. It holds no book tier.
  `BookTicks` keeps ``on_book_update`` to one tick per symbol per window across both producers.

The bar producer, the lost-feed watch and the composition (`build_bridge`) are E35-T15's next
slice; nothing here is composed by the app yet, so nothing is built, spliced or subscribed.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections.abc import Awaitable, Callable, Iterable
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog

from candleviewer.book.models import BestQuoteEvent
from candleviewer.book.ws_topic import WINDOW_S as BOOK_WINDOWS_S
from candleviewer.bus import Bus, QueuePolicy, StreamInvalidated, Subscription, TopicPattern
from candleviewer.bus.models import LIVE_ENVS, WILDCARD
from candleviewer.domain.events import MarketEvent
from candleviewer.exchange.base.models import BookLevel, TickerEvent
from candleviewer.ingestion.ticker_topic import BUS_QUEUE_MAX, MAX_SYMBOLS
from candleviewer.ingestion.ticker_topic import WINDOW_S as TICKER_WINDOW_S
from candleviewer.observability import spawn
from candleviewer.orderbook_wiring import BookView
from candleviewer.rules.evaluator.snapshot import Value
from candleviewer.rules.producers import LOST_AFTER_S, PushSink, Want

#: 24 §11.6 ``on_book_update`` at 10 Hz: the book publisher's window at depth 200.
BOOK_WINDOW_S: Final = BOOK_WINDOWS_S[200]
BOOK_CADENCE_MS: Final = round(BOOK_WINDOW_S * 1000)
#: The ticker family's window (23 §6.1), the `price` cadence.
TICKER_CADENCE_MS: Final = round(TICKER_WINDOW_S * 1000)
QUOTE_METRICS: Final = ("spread_ticks", "spread_bps", "mid", "microprice")
DEPTH_METRICS: Final = ("dom_imbalance_ratio", "book_pressure", "book_staleness_ms")
#: The registry's default ``n`` (`rules/vocabulary/metrics.py`); ``n`` past `MAX_BOOK_N` (the
#: deepest tier) or not a positive integer (an int, or up to 3 ASCII digits) is never served: the
#: want stays ``warmup``, counted as a ``params`` refusal.
DEPTH_N_DEFAULT: Final = {"dom_imbalance_ratio": 10, "book_pressure": 20}
MAX_BOOK_N: Final = 500
#: `price`'s ``source`` parameter (registry default ``last``) -> the `TickerEvent` field.
PRICE_SOURCES: Final = {"last": "last_price", "mark": "mark_price", "index": "index_price"}


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


# --- quotes, the ticker, the book -------------------------------------------------------------


def microprice(bid: Decimal, bid_qty: Decimal, ask: Decimal, ask_qty: Decimal) -> Decimal | None:
    """``(bid x ask_qty + ask x bid_qty) / (bid_qty + ask_qty)``; None (not pushed) for an empty
    top, never a defaulted 0 (E3). Pure."""
    total = bid_qty + ask_qty
    return None if total <= 0 else (bid * ask_qty + ask * bid_qty) / total


def depth_sums(levels: Iterable[BookLevel], n: int) -> Decimal:
    total = Decimal(0)
    for i, level in enumerate(levels):
        if i >= n:
            break
        total += level.qty
    return total


def depth_n(want: Want) -> int | None:
    """The book depth `want` reads: its ``n`` as authored (a key is the params as written, so
    nothing is canonicalised), else the registry default; 1 for `book_staleness_ms`. Strict, and
    never raises: a string is read only as at most 3 ASCII digits (no superscript, Arabic-Indic or
    full-width digit, which `str.isdigit` accepts and `int` may not)."""
    default = DEPTH_N_DEFAULT.get(want.metric)
    if default is None:
        return 1
    n = want.params.get("n", default)
    if isinstance(n, str):
        n = int(n) if len(n) <= 3 and n.isascii() and n.isdecimal() else None
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_BOOK_N:
        return None
    return n


class BookTicks:
    """One ``on_book_update`` tick per symbol per book window, whichever producer pushed first
    (quotes or depth): windows are clock buckets, so a late timer never doubles a window. One
    entry per symbol, cleared whole at `MAX_SYMBOLS` (a cleared entry costs one extra tick)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._at: dict[str, int] = {}

    def allow(self, symbol: str) -> bool:
        bucket = round(self._clock() * 1000) // BOOK_CADENCE_MS  # whole ms: no float drift
        last = self._at.get(symbol)
        if last == bucket:
            return False
        if last is None and len(self._at) >= MAX_SYMBOLS:
            self._at.clear()
        self._at[symbol] = bucket
        return True


class _KeyedConsumer[E: MarketEvent]:
    """A wildcard ``{env}.md.*.{detail}`` consumer pushing each symbol's latest event at most once
    per window (`ingestion/ticker_topic.py`'s pattern). Subclasses name the producer and `_push`
    one event, returning whether anything was written (then the symbol's tick is submitted)."""

    name: str
    metrics: frozenset[str]
    feeds: frozenset[str]

    def __init__(
        self,
        bus: Bus,
        env: str,
        detail: str,
        kind: type[E],
        window_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_symbols: int = MAX_SYMBOLS,
    ) -> None:
        if env not in LIVE_ENVS:  # a replay session's env never feeds the live source (C-2.11)
            raise ValueError("a metric producer subscribes a live env only")
        self._bus, self._env, self._detail, self._kind = bus, env, detail, kind
        self._window_s, self._clock, self._sleep, self._max = window_s, clock, sleep, max_symbols
        self._latest: dict[str, E] = {}
        self._seen: dict[str, float] = {}  # symbol -> when its latest event was received
        self._changed: set[str] = set()
        self._last_flush = -math.inf
        self._full = False
        self._sink: PushSink | None = None
        self._sub: Subscription | None = None
        self._task: asyncio.Task[None] | None = None

    # -- the bridge's side ---------------------------------------------------------------------
    def attach(self, sink: PushSink) -> None:
        self._sink = sink
        self.start()

    async def detach(self) -> None:
        self._sink = None
        await self.stop()
        self._latest.clear()
        self._seen.clear()
        self._changed.clear()

    def holds(self, symbol: str) -> bool:
        """Attached, subscribed, and `symbol`'s latest event received less than `LOST_AFTER_S`
        ago on this consumer's monotonic clock: a quiet symbol, not a lost one
        (`ProducerBridge.watch`). Fail closed: a feed that stops with no health event (a book
        dropped, a ticker unsubscribed) is marked once the bound passes, held event or not. A
        feed that publishes only on a change says more (`QuoteProducer.holds`: the book's
        frames)."""
        seen = self._seen.get(symbol)
        return (
            self._sink is not None and self._sub is not None and seen is not None
            and self._clock() - seen < LOST_AFTER_S
        )  # fmt: skip

    # -- the bus -------------------------------------------------------------------------------
    def offer(self, item: object) -> None:
        """One item from the bus: a symbol's new event, or the bus's overflow marker."""
        if isinstance(item, StreamInvalidated):
            _log().warning("rules.producer_stream_invalidated", producer=self.name)
            self._latest.clear()  # the next event of each symbol re-pushes
            self._seen.clear()
            self._changed.clear()
            self._full = False
        elif isinstance(item, self._kind) and item.source == "live":
            self._take(item)

    def _take(self, event: E) -> None:
        symbol = event.symbol
        held = self._latest.get(symbol)
        if held is None and len(self._latest) >= self._max:
            if not self._full:
                self._full = True
                _log().warning("rules.producer_symbols_full", producer=self.name)
            return
        if held is not None and event.ts_event < held.ts_event:
            return  # never a symbol back in time
        self._latest[symbol] = event
        self._seen[symbol] = self._clock()
        self._changed.add(symbol)

    def pump(self) -> int:
        """Drain the bus subscription without waiting; the items taken."""
        taken = 0
        while self._sub is not None and taken < BUS_QUEUE_MAX:
            try:
                item = self._sub.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.offer(item)
            taken += 1
        return taken

    def flush(self) -> int:
        """Once the window allows, push each changed symbol's latest event, then tick it (push,
        then tick: E2); the symbols ticked."""
        sink = self._sink
        if sink is None or not self._changed or self._clock() < self._last_flush + self._window_s:
            return 0
        self._last_flush = self._clock()
        changed, self._changed = self._changed, set()
        ticked = 0
        with sink.window():
            for symbol in sorted(changed):
                event = self._latest.get(symbol)
                if event is None or not sink.guard(self._push, sink, event):
                    continue
                if self._tick(symbol):
                    sink.tick(self._trigger, symbol)
                    ticked += 1
        return ticked

    _trigger: str

    def _push(self, sink: PushSink, event: E) -> bool:
        raise NotImplementedError

    def _tick(self, symbol: str) -> bool:
        return True

    # -- lifecycle -----------------------------------------------------------------------------
    def open(self) -> None:
        if self._sub is None:
            pattern = TopicPattern(env=self._env, domain="md", symbol=WILDCARD, detail=self._detail)
            self._sub = self._bus.subscribe(
                f"rule-producers-{self._detail}", pattern, QueuePolicy.INVALIDATE_ON_FULL,
                maxsize=BUS_QUEUE_MAX,
            )  # fmt: skip

    def start(self) -> None:
        self.open()
        if self._task is None:
            self._task = spawn(self._run(), name=f"rule-producers-{self._detail}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})
        sub, self._sub = self._sub, None
        if sub is not None:
            self._bus.unsubscribe(sub)

    async def _run(self) -> None:
        while (sub := self._sub) is not None:
            wait = self._window_s
            if self._changed and self._sink is not None:  # the window's end, or the next event
                wait = max(0.0, self._last_flush + self._window_s - self._clock())
            try:
                if wait > 0:
                    with contextlib.suppress(TimeoutError):
                        async with asyncio.timeout(wait):
                            self.offer(await sub.get())
                else:  # a late turn still yields: it never starves the loop
                    await asyncio.sleep(0)
                self.pump()
                self.flush()
            except Exception as exc:  # one bad turn never stops the consumer
                if (sink := self._sink) is not None:
                    sink.failed(exc)
                await self._sleep(self._window_s)


class QuoteProducer(_KeyedConsumer[BestQuoteEvent]):
    """`spread_ticks`, `spread_bps`, `mid` (as the quote carries them) and `microprice` from the
    best quote, at most once per symbol per 100 ms, cadence 100 ms, then ``on_book_update``.

    The book publishes a quote only when the top changes, so a quiet top is no lost feed: `books`
    (the stream the quotes come from; None: not composed) says whether frames still apply."""

    _trigger = "on_book_update"

    def __init__(
        self,
        bus: Bus,
        env: str,
        ticks: BookTicks,
        *,
        books: Callable[[], BookReader | None] | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(bus, env, "quote", BestQuoteEvent, BOOK_WINDOW_S, **kw)
        self.name = "quote"
        self.metrics = frozenset(QUOTE_METRICS)
        self.feeds = frozenset({"book"})
        self._ticks, self._books = ticks, books

    def holds(self, symbol: str) -> bool:
        """`_KeyedConsumer.holds`, or, attached and subscribed, `symbol`'s book applied a frame
        less than `LOST_AFTER_S` ago (`BookReader.applied_age_ms`): its top is quiet, the feed is
        live. A book with no frame for the bound, or none at all, is marked (fail closed)."""
        if super().holds(symbol):
            return True
        books = None if self._books is None else self._books()
        if self._sink is None or self._sub is None or books is None:
            return False
        age = books.applied_age_ms(symbol)
        return age is not None and age < LOST_AFTER_S * 1000

    def _push(self, sink: PushSink, event: BestQuoteEvent) -> bool:
        symbol, ts_ms = event.symbol, event.ts_event // 1000
        values: tuple[tuple[str, Value], ...] = (
            ("spread_ticks", Decimal(event.spread_ticks)), ("spread_bps", event.spread_bps),
            ("mid", event.mid),
            ("microprice", microprice(event.bid, event.bid_qty, event.ask, event.ask_qty)),
        )  # fmt: skip
        hit = False
        for metric, value in values:
            if value is None:
                continue
            for want in sink.wanted(metric, symbol):
                hit = sink.push(want, symbol, value, ts_ms, BOOK_CADENCE_MS) or hit
        return hit

    def _tick(self, symbol: str) -> bool:
        return self._ticks.allow(symbol)


class TickerProducer(_KeyedConsumer[TickerEvent]):
    """`price` by its ``source`` parameter (last, mark, index) from the ticker, at most once per
    symbol per 250 ms, cadence 250 ms, then ``on_price_update``. A None field is not pushed."""

    _trigger = "on_price_update"

    def __init__(self, bus: Bus, env: str, **kw: Any) -> None:
        super().__init__(bus, env, "ticker", TickerEvent, TICKER_WINDOW_S, **kw)
        self.name = "ticker"
        self.metrics = frozenset({"price"})
        self.feeds = frozenset({"ticker"})

    def _push(self, sink: PushSink, event: TickerEvent) -> bool:
        symbol, ts_ms = event.symbol, event.ts_event // 1000
        hit = False
        for want in sink.wanted("price", symbol):
            source = want.params.get("source", "last")
            field = PRICE_SOURCES.get(source) if isinstance(source, str) else None
            value = None if field is None else getattr(event, field)
            if value is not None:
                hit = sink.push(want, symbol, value, ts_ms, TICKER_CADENCE_MS) or hit
        return hit


class _Stamped(Protocol):
    @property
    def ts_event(self) -> int: ...


class _Engine(Protocol):
    @property
    def last_applied(self) -> _Stamped | None: ...


class BookReader(Protocol):
    """The slice of `BookStream` (``ctx.ingestion.books``) the depth producer reads."""

    def view(self, symbol: str, depth: int) -> BookView | None: ...

    def applied_age_ms(self, symbol: str) -> int | None: ...

    def engine(self, symbol: str) -> _Engine | None: ...


class BookDepthProducer:
    """`dom_imbalance_ratio` (bid qty over ask qty, top ``n``), `book_pressure` (``(bids - asks)
    / (bids + asks)``, top ``n``) and `book_staleness_ms` of each demanded symbol, every 100 ms.

    Values are as of the last applied frame (its exchange time); `book_staleness_ms` is its age
    on the stream's monotonic clock, stamped at that frame's time plus the age (a deviation from
    the exchange-time stamp: stamped at the frame's time, the staleness value would itself read
    stale exactly when it matters), pushed whenever a frame was applied, at any depth, and on
    through a desync (the book keeps no frame then; the last one seen is kept per symbol), so
    the age grows while the book resyncs. A stale book, or a want deeper than the book, pushes no
    depth value; a zero denominator pushes nothing. A rule that lists no symbol gets no depth
    value (no book tier is held for it: it stays ``warmup``). At most one pass per book window
    (a clock bucket), however often `poll` runs."""

    def __init__(
        self,
        books: Callable[[], BookReader | None],
        ticks: BookTicks,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.name = "book_depth"
        self.metrics = frozenset(DEPTH_METRICS)
        self.feeds = frozenset({"book"})
        self._books, self._ticks, self._clock, self._sleep = books, ticks, clock, sleep
        self._bucket = -1  # the book window `poll` last ran in
        self._last_ts: dict[str, int] = {}  # symbol -> the last applied frame's time (ms)
        self._sink: PushSink | None = None
        self._task: asyncio.Task[None] | None = None
        self._by_symbol: dict[str, tuple[tuple[Want, int], ...]] = {}
        self._by_symbol_of: tuple[PushSink, int] | None = None

    def attach(self, sink: PushSink) -> None:
        self._sink = sink
        if self._task is None:
            self._task = spawn(self._polling(), name="rule-producers-book-depth")

    async def detach(self) -> None:
        self._sink = None
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})
        self._last_ts.clear()

    def poll(self) -> int:
        """One window: read each demanded symbol's book once; the symbols ticked. A second pass
        in the same window does nothing."""
        sink, books = self._sink, self._books()
        bucket = round(self._clock() * 1000) // BOOK_CADENCE_MS  # whole ms: no float drift
        if sink is None or books is None or bucket == self._bucket:
            return 0
        self._bucket = bucket
        ticked = 0
        with sink.window():
            for symbol, wants in self._demand(sink).items():
                if not sink.guard(self._read, sink, books, symbol, wants):
                    continue
                if self._ticks.allow(symbol):
                    sink.tick("on_book_update", symbol)
                    ticked += 1
        return ticked

    def _read(
        self, sink: PushSink, books: BookReader, symbol: str, wants: tuple[tuple[Want, int], ...]
    ) -> bool:
        age = books.applied_age_ms(symbol)
        engine = books.engine(symbol)
        last = None if engine is None else engine.last_applied
        if last is not None:
            self._last_ts[symbol] = last.ts_event // 1000
        ts_ms = self._last_ts.get(symbol)
        if age is None or ts_ms is None:
            return False  # no frame applied: warmup
        hit = False
        depth: list[tuple[Want, int]] = []
        for want, n in wants:
            if want.metric == "book_staleness_ms":  # the frame's age needs no view
                hit = sink.push(want, symbol, Decimal(age), ts_ms + age, BOOK_CADENCE_MS) or hit
            else:
                depth.append((want, n))
        view, held = None, 0
        for n in sorted({n for _, n in depth}, reverse=True):  # the deepest the book holds
            if (view := books.view(symbol, n)) is not None:
                held = n
                break
        if view is None or view.stale:
            return hit  # deeper than the book, not LIVE, or old: never pushed as fresh
        bids, asks = view.snapshot.bids, view.snapshot.asks
        for want, n in depth:
            if n > held:
                continue  # deeper than the book: this want alone stays warmup
            b, a = depth_sums(bids, n), depth_sums(asks, n)
            value: Decimal | None
            if want.metric == "dom_imbalance_ratio":
                value = None if a <= 0 else b / a
            else:
                value = None if b + a <= 0 else (b - a) / (b + a)
            if value is not None:
                hit = sink.push(want, symbol, value, ts_ms, BOOK_CADENCE_MS) or hit
        return hit

    def _demand(self, sink: PushSink) -> dict[str, tuple[tuple[Want, int], ...]]:
        """symbol -> its demanded ``(want, n)``, rebuilt on a demand change; an invalid ``n`` is
        never read (``warmup``) and is counted once per demand, without holding back another."""
        if self._by_symbol_of != (sink, sink.demand_version):
            by_symbol: dict[str, list[tuple[Want, int]]] = {}
            for want in sink.demanded():
                n = sink.guard(depth_n, want)
                if n is None:
                    sink.params_refused()
                    continue
                for symbol in want.symbols:
                    if symbol is not None:
                        by_symbol.setdefault(symbol, []).append((want, n))
            self._by_symbol = {s: tuple(w) for s, w in sorted(by_symbol.items())}
            self._by_symbol_of = (sink, sink.demand_version)
            self._last_ts = {s: t for s, t in self._last_ts.items() if s in self._by_symbol}
        return self._by_symbol

    async def _polling(self) -> None:
        while True:
            await self._sleep(BOOK_WINDOW_S)
            try:
                self.poll()
            except Exception as exc:  # the timer outlives one bad pass
                if (sink := self._sink) is not None:
                    sink.failed(exc)

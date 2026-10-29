"""The `book.{symbol}.{depth}` WS topic (E21-T01, #604; 23 §6.1, §7.3, §7.7, §8.2): the book
module's snapshot source and the publisher of its `d` frames.

`book` may not import `ws` (CONSTITUTION §3), so the gateway is met structurally, as the ticker
topic meets it (`ingestion/ticker_topic.py`): `sub` is typed by the fields read here, and the hub's
`subscriptions`, `publish`, `upstream_desync` and `flush_pending`, the gateway's body constructor
(through `BookSnapshotSource`) and its kind-2 part constructor are injected
(`ws_wiring.book_topic`). Plain asyncio code on the hot path, never a statechart (C-2.20): every
read is of the engine's plain published state (`phase`, `resync_count`, `last_u`, its book).

- **Windows.** One per (symbol, topic depth) with a live subscription: the levels its clients
  hold, the best `min(depth, tier)` per side of the symbol's one active tier (BQ-1), with the `u`,
  the scales and a version. A snapshot is that window (seeded from the live book when no
  subscription that already took its `snap` holds it), so every `d` applies to exactly what its
  client holds. Depths 1, 50 and 200 are windows of the same tier; 500 is one only while the tier
  is 500: a 500 `sub` while the tier is still 200 stays pending and takes its snapshot after the
  swap (with `heatmap_depth_500` off the `sub` was refused).
- **Deltas.** Each window has its own cadence (BQ-4, 23 §8.2): 20 ms for depth 1, 50 ms for 50,
  100 ms for 200 and 500, whatever the pacer. An upstream change goes out at once when the window
  sent nothing in its last period, else at the period's close, as one `d` holding every level that
  differs from the window: per-level last-write-wins over every upstream delta since, so the final
  state is never lost. A level that leaves the window (deleted, or pushed past the depth) is sent
  once with size `"0"` (§7.3). Each `d` is structured plus kind 2 at the window's snapshot scales;
  a level those scales cannot carry exactly re-snapshots the symbol instead.
- **Lifecycle.** A desync of the book, a tier swap (a new engine) or a resync (a new
  `resync_count`) makes the held windows a book that is gone: they are dropped and every live
  `book` subscription of the symbol re-snaps (`upstream_desync`, §7.4), pending until the book is
  live again. The book going live flushes the subscriptions awaiting their `snap`
  (`flush_pending`). Nothing is published while the book is not live, and no window is ever taken
  from a crossed book (24 §2.2: a crossed book is a desync, never clamped).
- **Isolation.** A symbol whose turn raises is re-snapped alone (`upstream_desync`) and the other
  symbols' windows go on, so one symbol's fault or burst cannot stall another's frames.
- **Bounds (C-2.18).** The bus queue holds `BUS_QUEUE_MAX` items. Its overflow marker loses only
  wake-ups, never state (a flush diffs the live book), so it marks every window dirty and every
  symbol for a lifecycle check. Windows: one per (symbol, depth) subscribed, at most `MAX_SYMBOLS`
  symbols; past it a new symbol's subscription stays pending (logged once per episode).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import math
import time
import weakref
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.book.resync import BookEngine
from candleviewer.book.snapshot_source import (
    BookSnapshotSource,
    Record,
    book_scales,
    scaled_records,
)
from candleviewer.bus import Bus, QueuePolicy, StreamInvalidated, TopicPattern
from candleviewer.bus import Subscription as BusSubscription
from candleviewer.bus.models import WILDCARD
from candleviewer.exchange.base.models import BookDelta, BookLevel, BookSnapshot
from candleviewer.observability.context import spawn

FAMILY: Final = "book"
#: BQ-4 (23 §6.1, §8.2): the publisher's own window per topic depth, in seconds.
WINDOW_S: Final[Mapping[int, float]] = {1: 0.02, 50: 0.05, 200: 0.1, 500: 0.1}
#: The bus queue, drained at every wake: only a stuck loop fills it.
BUS_QUEUE_MAX: Final = 16_384
#: Symbols with windows at once (the catalogue lists some 600).
MAX_SYMBOLS: Final = 2048
#: How often the active-subscription gauge is recounted.
COUNT_EVERY_S: Final = 1.0
_ZERO: Final = Decimal(0)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Topic(Protocol):
    @property
    def symbol(self) -> str | None: ...

    @property
    def depth(self) -> int | None: ...


class BookSub(Protocol):
    """The fields of a WS `Subscription` read here."""

    @property
    def ch(self) -> str: ...
    @property
    def topic(self) -> _Topic: ...
    @property
    def replay_session_id(self) -> str | None: ...
    @property
    def snapshot_pending(self) -> bool: ...
    @property
    def ended(self) -> bool: ...


Match = Callable[[BookSub], bool]


class Subscriptions(Protocol):
    """`SequencingHub.subscriptions`: the live subscriptions of `ch`."""

    def __call__(self, ch: str) -> Sequence[BookSub]: ...


class Publish[P](Protocol):
    """`SequencingHub.publish`: one delta to the live subscriptions of `ch`."""

    def __call__(
        self,
        ch: str,
        body: Mapping[str, Any] | None = ...,
        *,
        part: P | None = ...,
        coalesced_count: int = ...,
    ) -> int: ...


class FlushPending(Protocol):
    """`SequencingHub.flush_pending`: the pending snapshots of what `match` accepts."""

    def __call__(self, match: Match | None = ...) -> int: ...


#: The gateway's kind-2 part from its records and scales (`ws.binary.Frame`).
PartFactory = Callable[[tuple[Record, ...], int, int], Any]


@dataclass(slots=True)
class _Window:
    """What the clients of one (symbol, topic depth) hold."""

    served: int
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    xu: int
    xseq: int  # the cross sequence the window was seeded with, rendered with its `xu`
    scales: tuple[int, int]
    version: int
    dirty_since: float | None = None  # the clock at the first change not yet sent
    merged: int = 0  # upstream events since the last frame
    last_flush: float = -math.inf


@dataclass(slots=True)
class _Symbol:
    """The windows of one symbol, all of one book: its engine and that engine's resync count."""

    engine: weakref.ref[BookEngine]
    resync_count: int
    windows: dict[int, _Window] = field(default_factory=dict)
    check: bool = False  # a lifecycle edge arrived: look at the engine in the next turn
    resnap: bool = False  # built over windows of a book that is gone: their holders re-snap

    def of(self, eng: BookEngine) -> bool:
        return self.engine() is eng and self.resync_count == eng.resync_count


def _live(eng: BookEngine | None) -> bool:
    return eng is not None and eng.phase is BookPhase.LIVE and eng.book is not None


def _uncrossed(bids: tuple[BookLevel, ...], asks: tuple[BookLevel, ...]) -> bool:
    return not bids or not asks or bids[0].price < asks[0].price


def _changes(
    held: tuple[BookLevel, ...], new: tuple[BookLevel, ...]
) -> list[tuple[Decimal, Decimal]]:
    """The `(price, size)` that take a client from `held` to `new`, best first: changed or added
    levels at their size, and each level that left with size 0 (§7.3)."""
    before = {lv.price_ticks: lv for lv in held}
    out: list[tuple[int, Decimal, Decimal]] = []
    for lv in new:
        old = before.pop(lv.price_ticks, None)
        if old is None or old.qty != lv.qty:
            out.append((lv.price_ticks, lv.price, lv.qty))
    out.extend((lv.price_ticks, lv.price, _ZERO) for lv in before.values())
    return [(p, q) for _, p, q in sorted(out)]


def _rows(levels: list[tuple[Decimal, Decimal]]) -> list[list[str]]:
    return [[format(p, "f"), "0" if q == 0 else format(q, "f")] for p, q in levels]


def _stopped(task: asyncio.Task[None]) -> None:
    """A loop that ends other than by `stop` says so: from then on no book `d` goes out."""
    if not task.cancelled() and (exc := task.exception()) is not None:
        _log().error("book_topic_stopped", error=type(exc).__name__)


class BookTopic[B]:
    """The `book` family's snapshot source and publisher (see the module docstring), for the event
    loop that runs the gateway and the book stream: no locks."""

    def __init__(
        self,
        source: BookSnapshotSource[B],
        subscriptions: Subscriptions,
        publish: Publish[Any],
        upstream_desync: Callable[[str], int],
        flush_pending: FlushPending,
        part: PartFactory,
        *,
        bus: Bus,
        env: str,
        clock: Callable[[], float] = time.monotonic,
        windows: Mapping[int, float] = WINDOW_S,
        max_symbols: int = MAX_SYMBOLS,
        publish_latency: Callable[[str, int, float], None] | None = None,
        active: Callable[[int, int], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._source, self._subscriptions, self._publish = source, subscriptions, publish
        self._desync, self._flush_pending, self._part = upstream_desync, flush_pending, part
        self._bus, self._env, self._clock, self._windows = bus, env, clock, windows
        self._max, self._sleep = max_symbols, sleep
        self._publish_latency, self._active = publish_latency, active
        self._symbols: dict[str, _Symbol] = {}
        self._dirty: set[str] = set()  # symbols with a change or an edge not yet handled
        self._known: dict[tuple[str, int], None] = {}  # (symbol, depth) asked about: the gauge
        self._counted: dict[int, int] = {}
        self._last_count = -math.inf
        self._full = False
        self._versions = itertools.count(1)
        #: Per (symbol, depth), the state its generation names and that generation.
        self._seen: dict[tuple[str, int], tuple[tuple[object, ...], int]] = {}
        self._generations = itertools.count(1)
        self._sub: BusSubscription | None = None
        self._task: asyncio.Task[None] | None = None

    # -- SnapshotSource

    def build(self, sub: BookSub) -> B | None:
        key = self._key(sub)
        eng = None if key is None else self._source.engine(key[0])
        if key is None or eng is None or not _live(eng):
            return None
        symbol, depth = key
        st = self._symbol(symbol, eng)
        if st is None:
            return None
        w = st.windows.get(depth)
        if w is None or not self._held(sub):
            w = self._seed(eng, depth)
            if w is None:
                return None
            st.windows[depth] = w
        return self._source.render(eng, w.served, w.bids, w.asks, w.xu, w.xseq, w.scales)

    def generation(self, sub: BookSub) -> int:
        key = self._key(sub)
        eng = None if key is None else self._source.engine(key[0])
        if key is None or eng is None:
            return 0
        if key not in self._known and len(self._known) < 4 * self._max:
            self._known[key] = None
        st = self._symbols.get(key[0])
        w = st.windows.get(key[1]) if st is not None and st.of(eng) else None
        # a held window moves with its frames; tagged, so a version never reads as a live `u`
        moving = ("u", eng.last_u) if w is None else ("w", w.version)
        state = (id(eng), eng.resync_count, eng.phase, moving, self._source.is_stale(eng))
        seen = self._seen.get(key)
        if seen is None or seen[0] != state:
            if seen is None and len(self._seen) >= 4 * self._max:
                self._seen.clear()  # safe: generations only grow, so none repeats
            seen = self._seen[key] = (state, next(self._generations))
        return seen[1]

    def continuity(self, sub: BookSub, from_ts_ms: int | None) -> bool:
        return False  # no delta history: `snapshot: false` is always `snapshot_forced` (§7.7)

    # -- deltas

    def offer(self, item: object) -> None:
        """One bus item: a book event of a symbol, its status edge, or the overflow marker."""
        if isinstance(item, StreamInvalidated):
            _log().warning("book_topic_stream_invalidated")
            for symbol, held in self._symbols.items():
                held.check = True
                self._touch(symbol, held)
        elif isinstance(item, BookStatus):
            if (st := self._symbols.get(item.symbol)) is not None:
                st.check = True
            self._dirty.add(item.symbol)
        elif isinstance(item, BookDelta | BookSnapshot):
            if (st := self._symbols.get(item.symbol)) is not None:
                self._touch(item.symbol, st)

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

    def tick(self) -> int:
        """Each symbol's edges, then each window whose period allows; the frames sent."""
        now, sent = self._clock(), 0
        for symbol in sorted(self._dirty):
            try:
                n, more = self._turn(symbol, now)
            except Exception as exc:  # contained to its symbol: the others go on
                _log().error("book_topic_symbol_failed", symbol=symbol, error=type(exc).__name__)
                self._resync(symbol)
                n, more = 0, False
            sent += n
            if not more:
                self._dirty.discard(symbol)
        if now >= self._last_count + COUNT_EVERY_S:
            self._last_count = now
            self._count()
        return sent

    def next_due(self) -> float | None:
        """The clock at which the earliest held change may go out; `None` with nothing held."""
        due = [
            w.last_flush + self._windows.get(depth, 0.1)
            for symbol in self._dirty
            if (st := self._symbols.get(symbol)) is not None
            for depth, w in st.windows.items()
            if w.dirty_since is not None
        ]
        return min(due) if due else None

    def _turn(self, symbol: str, now: float) -> tuple[int, bool]:
        """One symbol: its lifecycle edge, then its due windows; (frames sent, still dirty)."""
        eng = self._source.engine(symbol)
        st = self._symbols.get(symbol)
        if st is None:  # no window: only a book going live matters, for pending subscriptions
            if _live(eng):
                self._flush_pending(self._match(symbol))
            return 0, False
        if not _live(eng) or eng is None or not st.of(eng) or st.resnap:
            self._resync(symbol)
            return 0, False
        if st.check:
            st.check = False
            self._flush_pending(self._match(symbol))
        sent, more = 0, False
        for depth, w in list(st.windows.items()):
            if w.dirty_since is None:
                continue
            if now < w.last_flush + self._windows.get(depth, 0.1):
                more = True
                continue
            n = self._flush(symbol, depth, w, eng, now)
            if n < 0:  # the window cannot go out as a delta: the symbol re-snaps
                self._resync(symbol)
                return sent, False
            sent += n
        return sent, more

    def _flush(self, symbol: str, depth: int, w: _Window, eng: BookEngine, now: float) -> int:
        ch = f"{FAMILY}.{symbol}.{depth}"
        if not self._subscriptions(ch):
            st = self._symbols[symbol]
            del st.windows[depth]
            if not st.windows:
                del self._symbols[symbol]
            return 0
        book = eng.book
        if book is None:  # pragma: no cover - `_live` was checked by the caller
            return -1
        bids, asks = book.top(w.served)
        if not _uncrossed(bids, asks):
            return -1  # never a window of a crossed book (24 §2.2): the engine resyncs it
        bid_changes, ask_changes = _changes(w.bids, bids), _changes(w.asks, asks)
        since, merged = w.dirty_since, w.merged
        w.dirty_since, w.merged = None, 0
        if not bid_changes and not ask_changes:
            return 0
        bid_changes.reverse()  # bids best (highest) first, asks ascending (§14.1)
        bid_rec = scaled_records(0, bid_changes, w.scales)
        ask_rec = scaled_records(1, ask_changes, w.scales)
        if bid_rec is None or ask_rec is None:
            return -1  # finer than the snapshot's scales: a resnapshot carries it
        body = {"symbol": symbol, "depth": w.served, "xu": eng.last_u,
                "bids": _rows(bid_changes), "asks": _rows(ask_changes)}  # fmt: skip
        sent = self._publish(
            ch, body, part=self._part(bid_rec + ask_rec, *w.scales), coalesced_count=max(1, merged)
        )
        w.bids, w.asks, w.xu, w.version = bids, asks, eng.last_u, next(self._versions)
        w.last_flush = now
        if self._publish_latency is not None and since is not None:
            self._publish_latency(symbol, depth, (self._clock() - since) * 1000.0)
        return sent

    def _seed(self, eng: BookEngine, depth: int) -> _Window | None:
        """`None` (the `sub` stays pending) while the tier is shallower than `depth`: a 500 window
        is never a 200 tier's book under the `.500` topic; it is seeded after the swap."""
        book, xseq = eng.book, eng.snapshot_cross_seq
        steps = self._source.steps(eng.symbol)
        if book is None or steps is None or xseq is None or eng.depth < depth:
            return None
        bids, asks = book.top(depth)
        scales = book_scales(steps, bids, asks)
        if scales is None or not _uncrossed(bids, asks):
            return None
        return _Window(depth, bids, asks, eng.last_u, xseq, scales, next(self._versions))

    def _symbol(self, symbol: str, eng: BookEngine) -> _Symbol | None:
        """The symbol's windows of `eng`'s book: a book that is gone is replaced, and the next
        turn re-snaps whoever held it."""
        st = self._symbols.get(symbol)
        if st is not None and st.of(eng):
            return st
        if st is None and len(self._symbols) >= self._max:
            if not self._full:
                self._full = True
                _log().warning("book_topic_symbols_full", symbols=len(self._symbols))
            return None
        self._full = False
        resnap = st is not None and bool(st.windows)
        if resnap:
            self._dirty.add(symbol)  # held windows of the old book: re-snapped next turn
        fresh = _Symbol(weakref.ref(eng), eng.resync_count, resnap=resnap)
        self._symbols[symbol] = fresh
        return fresh

    def _held(self, sub: BookSub) -> bool:
        """Some other subscription of `sub`'s topic took its `snap` and holds the window."""
        return any(
            s is not sub and not s.snapshot_pending and not s.ended
            for s in self._subscriptions(sub.ch)
        )

    def _touch(self, symbol: str, st: _Symbol) -> None:
        now = self._clock()
        for w in st.windows.values():
            if w.dirty_since is None:
                w.dirty_since = now
            w.merged += 1
        self._dirty.add(symbol)

    def _resync(self, symbol: str) -> None:
        """The symbol's windows are of a book that is gone: drop them and re-snap (§7.4)."""
        self._symbols.pop(symbol, None)
        try:
            self._desync(symbol)
        except Exception as exc:
            _log().error("book_topic_resync_failed", symbol=symbol, error=type(exc).__name__)

    def _count(self) -> None:
        """`book_subscriptions_active{depth}`: the live subscriptions per topic depth."""
        counts: dict[int, int] = dict.fromkeys(self._counted, 0)
        for key in list(self._known):
            n = len(self._subscriptions(f"{FAMILY}.{key[0]}.{key[1]}"))
            if n == 0:
                del self._known[key]
            counts[key[1]] = counts.get(key[1], 0) + n
        self._counted = {d: n for d, n in counts.items() if n}
        if self._active is not None:
            for depth, n in counts.items():
                self._active(depth, n)

    @staticmethod
    def _key(sub: BookSub) -> tuple[str, int] | None:
        symbol, depth = sub.topic.symbol, sub.topic.depth
        if sub.replay_session_id is not None or symbol is None or depth is None:
            return None  # the live book is no replay state
        return symbol, depth

    @staticmethod
    def _match(symbol: str) -> Match:
        prefix = f"{FAMILY}.{symbol}."

        def match(sub: BookSub) -> bool:
            return sub.replay_session_id is None and sub.ch.startswith(prefix)

        return match

    # -- lifecycle (`WsRuntime`)

    def open(self) -> None:
        """Hold the bus topic (idempotent); `pump` drains it."""
        if self._sub is None:
            pattern = TopicPattern(env=self._env, domain="md", symbol=WILDCARD, detail=FAMILY)
            self._sub = self._bus.subscribe(
                "ws-book-topic", pattern, QueuePolicy.INVALIDATE_ON_FULL, maxsize=BUS_QUEUE_MAX
            )

    def start(self) -> None:
        self.open()
        if self._task is None:
            self._task = spawn(self._run(), name="ws-book-topic")
            self._task.add_done_callback(_stopped)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})
        sub, self._sub = self._sub, None
        if sub is not None:
            self._bus.unsubscribe(sub)

    async def _run(self) -> None:
        idle = max(self._windows.values(), default=0.1)
        while (sub := self._sub) is not None:
            due = self.next_due()
            wait = idle if due is None else max(0.0, due - self._clock())
            try:
                if wait > 0:
                    with contextlib.suppress(TimeoutError):
                        async with asyncio.timeout(wait):
                            self.offer(await sub.get())
                else:  # a turn that runs late still yields: it never starves the event loop
                    await asyncio.sleep(0)
                self.pump()
                self.tick()
            except Exception as exc:  # never let one bad turn stop every book `d`
                _log().error("book_topic_turn_failed", error=type(exc).__name__)
                await self._sleep(idle)


__all__ = ["BUS_QUEUE_MAX", "FAMILY", "MAX_SYMBOLS", "WINDOW_S", "BookSub", "BookTopic"]

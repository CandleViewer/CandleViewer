"""The bench feeder: stand-ins for the WS producers main does not have yet (E17-Q03).

Main publishes no book `d` (#604) and no trades, ticker or liquidations (no producer, no snapshot
source), so a load run on main as it is would measure almost nothing. The feeder replays the
recorded corpus into the real `SequencingHub`, as the E17-Q02 chaos `Stack` does, on wall time and
at N symbols: `book.{symbol}.{depth}` window deltas and `trades.{symbol}` batches, each with its
CVWB part beside the structured body, and the same prints as `TradeEvent`s on the private `Bus`,
which the real `BarBuilderSet` consumes, so `bars.*` is real end to end. Sequencing, pacing,
encoding, the writer and the socket are the gateway's own.

- **Parse in the backend process.** Each recorded frame goes through the production parser
  (`tests._corpus.normalize`) when its turn comes, so the feeder's work (parse, book upkeep, window
  deltas) is in the backend CPU numbers, as ingestion's would be; a fed-but-unsubscribed phase
  measures it.
- **Symbols.** The corpus holds one usable book (BTCUSDT) and three trade tapes. A symbol of rank r
  replays the BTCUSDT book from a seeded offset and tape `r % 3`, so clones are not in lockstep.
- **Schedule.** Drift-free from t0: stream k fires at `t0 + phase + n * interval`. A stream more
  than `MAX_LATE_S` behind skips ahead and counts what it missed, so `published / scheduled` (a
  validity guard) shows a feeder that fell behind instead of hiding it in a burst.
- **Book.** The server book applies corpus deltas for good and never resets (a wrap keeps applying
  from the first delta). A delta that moves no level inside the subscribed window is applied and
  skipped, so the published rate is the tier's rate, not the share of the corpus that touches it.
- **Trades.** A print's `ts_ms` is the wall clock at publish (the reference of budget #3) and its
  id `<recorded id>.<round>`, unique across replays of the tape.
- **Determinism.** The seed fixes offsets, phases and content; only wall timing varies.
- **Two seams** (#571): `live(ch)` says whether a topic has a subscriber and a `Sink` takes what a
  step produced. In process (the default) they are the hub's `subscriptions` and `HubSink`, which
  publishes into the hub and the bus as before; `feed_proc` runs the same schedule in a child
  process with every topic live and a sink that writes lines to the backend.
"""

from __future__ import annotations

import asyncio
import heapq
import random
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.exchange.base.models import BookDelta, BookLevel, BookSnapshot, TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.ingestion.ticker_stream import uuid7
from candleviewer.ws.binary import BOOK_DELTA, TRADES, Frame
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody, window_delta
from candleviewer.ws_wiring import book_snapshot_body
from tests import _corpus

#: The recorded tapes, replayed round-robin by symbol rank.
TAPES: Final = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
#: The recorded book is BTCUSDT's; its price and size places are fixed by the corpus (a value that
#: needs more raises in `scale_int`, never rounds).
BOOK_PRICE_SCALE, BOOK_QTY_SCALE = 1, 3
#: §6.1: a trades snapshot is the last 200 prints.
TRADES_SNAPSHOT = 200
#: A stream this far behind skips ahead instead of replaying the gap in a burst.
MAX_LATE_S: Final = 1.0
#: A corpus delta that moves no window level is skipped; this many in a row is a corpus fault.
MAX_SKIPS: Final = 256
_ENV: Final = "demo"


@dataclass(frozen=True, slots=True)
class Tier:
    book_per_s: int
    batches_per_s: int
    prints_per_batch: int


def scale_int(value: str | Decimal, scale: int) -> int:
    """`value` as the integer CVWB carries (`real = int / 10**scale`); a value that does not fit
    the scale exactly is a harness fault, never rounded."""
    scaled = Decimal(value).scaleb(scale)
    whole = int(scaled)
    if whole != scaled:
        raise ValueError(f"{value} needs more than {scale} decimal places")
    return whole


def _places(value: Decimal) -> int:
    exp = value.as_tuple().exponent
    return max(0, -exp) if isinstance(exp, int) else 0


def _delta(frame: str) -> BookDelta:
    """A recorded book frame through the production parser (a non-delta is a corpus fault)."""
    ev = _corpus.normalize(frame)[0]
    if not isinstance(ev, BookDelta):
        raise TypeError(f"recorded book frame is a {type(ev).__name__}, not a delta")
    return ev


class Book:
    """The server-side book of one symbol: price -> (price text, size text)."""

    def __init__(self) -> None:
        self.bids: dict[Decimal, tuple[str, str]] = {}
        self.asks: dict[Decimal, tuple[str, str]] = {}

    def copy(self) -> Book:
        out = Book()
        out.bids, out.asks = dict(self.bids), dict(self.asks)
        return out

    def apply(self, bids: Sequence[BookLevel], asks: Sequence[BookLevel]) -> None:
        for side, levels in ((self.bids, bids), (self.asks, asks)):
            for lv in levels:
                if lv.qty == 0:
                    side.pop(lv.price, None)
                else:
                    side[lv.price] = (str(lv.price), str(lv.qty))

    def apply_rows(self, bids: Sequence[Sequence[str]], asks: Sequence[Sequence[str]]) -> None:
        """Rows as the wire states them, `[price text, size text]`: size `"0"` deletes the level,
        as `window_delta` writes a level that left the window."""
        for side, rows in ((self.bids, bids), (self.asks, asks)):
            for price, size in rows:
                if size == "0":
                    side.pop(Decimal(price), None)
                else:
                    side[Decimal(price)] = (price, size)

    def top(self, depth: int) -> tuple[dict[str, str], dict[str, str]]:
        """The `depth` best levels per side as the wire states them (price text -> size text)."""
        bids = sorted(self.bids, reverse=True)[:depth]
        asks = sorted(self.asks)[:depth]
        return dict(self.bids[p] for p in bids), dict(self.asks[p] for p in asks)


class Corpus:
    """The recorded frames, raw, and what the feeder needs from them once: the opening book, and
    each tape's decimal places and tick size (a symbol's bars scales)."""

    def __init__(self) -> None:
        book = _corpus.frames("ws/orderbook_BTCUSDT.jsonl")
        self.deltas = [f for f in book[1:] if '"type":"delta"' in f]
        first = _corpus.normalize(book[0])[0]
        if not isinstance(first, BookSnapshot):
            raise TypeError("the recorded book opens with a snapshot")
        self.opening = Book()
        self.opening.apply(first.bids, first.asks)
        self.tapes = {s: _corpus.frames(f"ws/clean_publicTrade_{s}.jsonl") for s in TAPES}
        self.scales: dict[str, tuple[int, int]] = {}
        for sym, frames in self.tapes.items():
            prints = [p for f in frames for p in _corpus.normalize(f) if isinstance(p, TradePrint)]
            self.scales[sym] = (
                max(_places(p.price) for p in prints),
                max(_places(p.qty) for p in prints),
            )

    def book_at(self, offsets: Sequence[int]) -> list[Book]:
        """The book after `offset` corpus deltas, for each offset, in one pass over the corpus."""
        books: dict[int, Book] = {}
        book = self.opening.copy()
        done = 0
        for want in sorted(set(offsets)):
            while done < want:
                ev = _delta(self.deltas[done])
                book.apply(ev.bids, ev.asks)
                done += 1
            books[want] = book.copy()
        return [books[o].copy() for o in offsets]


class _Feed:
    """One symbol: its book, tape cursor and the numbers its snapshots and frames are built from."""

    def __init__(self, name: str, rank: int, tier: Tier, corpus: Corpus, book: Book, at: int):
        self.name, self.tier, self.corpus = name, tier, corpus
        self.tape = TAPES[rank % len(TAPES)]
        self.price_scale, self.qty_scale = corpus.scales[self.tape]
        self.tick = _corpus.TICKS[self.tape]
        self.book, self.cursor = book, at
        self.pos, self.round, self.buffer = 0, 0, deque[TradePrint]()
        self.xu = self.cursor  # the book's update counter; `generation` moves with it
        self.trades_gen = 0
        self.seq = 0  # the TradeEvent sequence on the bus
        self.ring: deque[dict[str, str | int]] = deque(maxlen=TRADES_SNAPSHOT)

    def next_delta(self) -> BookDelta:
        ev = _delta(self.corpus.deltas[self.cursor % len(self.corpus.deltas)])
        self.cursor += 1
        return ev

    def next_print(self) -> tuple[TradePrint, int]:
        """The next print of the tape and the replay round it belongs to."""
        frames = self.corpus.tapes[self.tape]
        while not self.buffer:
            batch = [p for p in _corpus.normalize(frames[self.pos]) if isinstance(p, TradePrint)]
            self.buffer.extend(batch)
            self.pos += 1
            if self.pos == len(frames):
                self.pos, self.round = 0, self.round + 1
        return self.buffer.popleft(), self.round


class SnapshotFeed(Protocol):
    """What the snapshot sources read of a symbol: a `_Feed`, or `feed_proc`'s mirror of one."""

    @property
    def name(self) -> str: ...
    @property
    def book(self) -> Book: ...
    @property
    def xu(self) -> int: ...
    @property
    def ring(self) -> deque[dict[str, str | int]]: ...
    @property
    def trades_gen(self) -> int: ...
    @property
    def price_scale(self) -> int: ...
    @property
    def qty_scale(self) -> int: ...


class BookSource:
    """`SnapshotSource` of `book.*` over the feeder's server books, shaped as the production
    `BookSnapshotSource` shapes it (§14.1: `xu`, `xseq`, both encodings)."""

    def __init__(self, feeds: Mapping[str, SnapshotFeed]) -> None:
        self._feeds = feeds

    def build(self, sub: Subscription) -> SnapshotBody | None:
        feed = self._feeds.get(sub.topic.symbol or "")
        if feed is None or sub.replay_session_id is not None:
            return None
        bids, asks = feed.book.top(sub.topic.depth or 50)
        ps, qs = BOOK_PRICE_SCALE, BOOK_QTY_SCALE
        records = tuple((0, scale_int(p, ps), scale_int(s, qs)) for p, s in bids.items()) + tuple(
            (1, scale_int(p, ps), scale_int(s, qs)) for p, s in asks.items()
        )
        structured = {
            "symbol": feed.name,
            "depth": sub.topic.depth or 50,
            "xu": feed.xu,
            "xseq": feed.xu,
            "bids": [[p, s] for p, s in bids.items()],
            "asks": [[p, s] for p, s in asks.items()],
        }
        return book_snapshot_body(
            structured, records, (feed.xu, feed.xu), price_scale=ps, qty_scale=qs
        )

    def generation(self, sub: Subscription) -> int:
        feed = self._feeds.get(sub.topic.symbol or "")
        return 0 if feed is None else feed.xu

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        return False  # the feeder keeps no delta history (as the production adapter, §7.6)


class TradesSource:
    """`SnapshotSource` of `trades.*`: the last 200 prints of the symbol (§6.1)."""

    def __init__(self, feeds: Mapping[str, SnapshotFeed]) -> None:
        self._feeds = feeds

    def build(self, sub: Subscription) -> SnapshotBody | None:
        feed = self._feeds.get(sub.topic.symbol or "")
        if feed is None or sub.replay_session_id is not None:
            return None
        ring = list(feed.ring)
        base = int(ring[0]["ts_ms"]) if ring else 0
        ps, qs = feed.price_scale, feed.qty_scale
        records = tuple(
            (
                int(t["ts_ms"]) - base,
                scale_int(str(t["price"]), ps),
                scale_int(str(t["size"]), qs),
                0 if t["side"] == "buy" else 1,
                0,
            )
            for t in ring
        )
        part = Frame(TRADES, records, price_scale=ps, qty_scale=qs, ts_base_ms=base)
        return SnapshotBody(
            {"symbol": feed.name, "trades": ring}, (part,), price_scale=ps, qty_scale=qs
        )

    def generation(self, sub: Subscription) -> int:
        feed = self._feeds.get(sub.topic.symbol or "")
        return 0 if feed is None else feed.trades_gen

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        return False


@dataclass(slots=True)
class _Stream:
    feed: _Feed
    kind: str  # "book" | "trades"
    interval: float
    start: float
    missed: int = 0
    published: int = 0


class Slot(Protocol):
    """A stream as the schedule counts it."""

    @property
    def kind(self) -> str: ...
    @property
    def interval(self) -> float: ...
    @property
    def start(self) -> float: ...
    @property
    def published(self) -> int: ...


def schedule_stats(streams: Sequence[Slot], now: float) -> dict[str, tuple[int, int]]:
    """Per kind, `(scheduled by `now` seconds after t0, published)`."""
    out = {"book": (0, 0), "trades": (0, 0)}
    for s in streams:
        due = max(0, int((now - s.start) / s.interval) + 1) if now >= s.start else 0
        sched, pub = out[s.kind]
        out[s.kind] = (sched + due, pub + s.published)
    return out


#: One depth's window delta of a book step: `(depth, bids, asks, CVWB records)`.
BookMove = tuple[int, list[list[str]], list[list[str]], tuple[tuple[int, int, int], ...]]


class Sink(Protocol):
    """Where a step's output goes (module docstring, "Two seams")."""

    def book(self, feed: _Feed, moves: Sequence[BookMove]) -> None: ...

    async def trades(
        self,
        feed: _Feed,
        prints: Sequence[tuple[TradePrint, str]],
        items: list[dict[str, str | int]],
        now_ms: int,
        live: bool,
    ) -> None: ...


def print_fields(p: TradePrint, tick: Decimal) -> tuple[int, Decimal]:
    """A print's `price_ticks` and `notional`, as its `TradeEvent` carries them."""
    return int((p.price / tick).to_integral_value()), p.price * p.qty


def trade_event(
    symbol: str,
    seq: int,
    tid: str,
    p: tuple[Decimal, Decimal, str, int, Decimal],
    ts_us: int,
) -> TradeEvent:
    """The bus event of one print, `p` = `(price, qty, side, price_ticks, notional)`: one builder
    for both feeder modes, so the bars lanes get equal events from either."""
    price, qty, side, ticks, notional = p
    return TradeEvent.model_validate(
        {
            "event_id": uuid7(ts_us // 1000),
            "ts_event": ts_us,
            "ts_ingest": ts_us,
            "source": "live",
            "symbol": symbol,
            "trade_id": tid,
            "price": price,
            "qty": qty,
            "side": side,
            "is_block_trade": False,
            "price_ticks": ticks,
            "notional": notional,
            "seq": seq,
        }
    )


class HubSink:
    """The in-process sink: the hub's frames and the bus's `TradeEvent`s, as the feeder has always
    published them."""

    def __init__(self, hub: SequencingHub, bus: Bus) -> None:
        self._hub, self._bus = hub, bus

    def book(self, feed: _Feed, moves: Sequence[BookMove]) -> None:
        for d, bids, asks, records in moves:
            part = Frame(
                BOOK_DELTA, records, price_scale=BOOK_PRICE_SCALE, qty_scale=BOOK_QTY_SCALE
            )
            body = {"symbol": feed.name, "xu": feed.xu, "xseq": feed.xu, "bids": bids, "asks": asks}
            self._hub.publish(f"book.{feed.name}.{d}", body, part=part)

    async def trades(
        self,
        feed: _Feed,
        prints: Sequence[tuple[TradePrint, str]],
        items: list[dict[str, str | int]],
        now_ms: int,
        live: bool,
    ) -> None:
        events: list[TradeEvent] = []
        for k, (p, tid) in enumerate(prints):
            feed.seq += 1
            fields = (p.price, p.qty, p.side, *print_fields(p, feed.tick))
            events.append(trade_event(feed.name, feed.seq, tid, fields, now_ms * 1000 + k))
        ch = f"trades.{feed.name}"
        if live:
            ps, qs = feed.price_scale, feed.qty_scale
            records = tuple(
                (
                    0,
                    scale_int(str(i["price"]), ps),
                    scale_int(str(i["size"]), qs),
                    0 if i["side"] == "buy" else 1,
                    0,
                )
                for i in items
            )
            part = Frame(TRADES, records, price_scale=ps, qty_scale=qs, ts_base_ms=now_ms)
            self._hub.publish(ch, {"symbol": feed.name, "trades": items}, part=part)
        topic = Topic(env=_ENV, domain="md", symbol=feed.name, detail="trade")
        for ev in events:  # the bars lanes: a NEVER_DROP queue, so a slow lane slows the feeder
            await self._bus.publish(topic, ev)


class Feeder:
    """Publishes the symbols' streams into `hub` and `bus` on the schedule (module docstring)."""

    def __init__(
        self,
        hub: SequencingHub | None,
        bus: Bus | None,
        symbols: Sequence[str],
        tiers: Sequence[Tier],
        *,
        seed: int,
        depths: Sequence[int] = (50,),
        corpus: Corpus | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        live: Callable[[str], bool] | None = None,
        sink: Sink | None = None,
    ) -> None:
        """`live` and `sink` default to `hub` and `bus` (the in-process feeder); a feeder given both
        needs neither (`feed_proc`'s child)."""
        if len(symbols) != len(tiers):
            raise ValueError("one tier per symbol")
        if live is None or sink is None:
            if hub is None or bus is None:
                raise ValueError(
                    "a feeder without `live` and `sink` publishes into a hub and a bus"
                )
            on_hub = hub
            live = live or (lambda ch: bool(on_hub.subscriptions(ch)))
            sink = sink or HubSink(hub, bus)
        self._live, self._sink, self._depths = live, sink, tuple(depths)
        self._clock, self._wall_ms = clock, wall_ms
        rng = random.Random(seed)  # noqa: S311 - seeded, reproducible feed; not security
        self.corpus = corpus or Corpus()
        offsets = [rng.randrange(len(self.corpus.deltas)) for _ in symbols]
        books = self.corpus.book_at(offsets)
        self.feeds: dict[str, _Feed] = {
            s: _Feed(s, r, tiers[r], self.corpus, books[r], offsets[r])
            for r, s in enumerate(symbols)
        }
        self.streams: list[_Stream] = []
        for feed in self.feeds.values():
            rates = (("book", feed.tier.book_per_s), ("trades", feed.tier.batches_per_s))
            for kind, per_s in rates:
                interval = 1.0 / per_s
                self.streams.append(_Stream(feed, kind, interval, rng.random() * interval))
        self.t0 = 0.0

    def scales(self, symbol: str) -> tuple[int, int] | None:
        """A symbol's bars scales: its tick's places and the qty places of its tape."""
        feed = self.feeds.get(symbol)
        return None if feed is None else (max(1, _places(feed.tick)), feed.qty_scale)

    def tick_size(self, symbol: str) -> Decimal | None:
        feed = self.feeds.get(symbol)
        return None if feed is None else feed.tick

    def schedule(self, n: int) -> list[tuple[float, int]]:
        """The first `n` `(offset from t0, stream index)` firings, in order: the plan, with no
        clock (the determinism test reads it)."""
        heap = [(s.start, i) for i, s in enumerate(self.streams)]
        heapq.heapify(heap)
        out: list[tuple[float, int]] = []
        while len(out) < n:
            due, i = heapq.heappop(heap)
            out.append((due, i))
            heapq.heappush(heap, (due + self.streams[i].interval, i))
        return out

    def stats(self) -> dict[str, tuple[int, int]]:
        """Per kind, `(scheduled so far, published)`: published short of scheduled is a feeder that
        fell behind (a validity guard of the run)."""
        return schedule_stats(self.streams, self._clock() - self.t0)

    async def run(self, t0: float | None = None) -> None:
        """The schedule from `t0` (now, unless the caller already told someone its t0)."""
        self.t0 = self._clock() if t0 is None else t0
        heap = [(self.t0 + s.start, i) for i, s in enumerate(self.streams)]
        heapq.heapify(heap)
        while True:
            wait = heap[0][0] - self._clock()
            if wait > 0:
                await asyncio.sleep(wait)
            while heap and heap[0][0] <= self._clock():
                due, i = heapq.heappop(heap)
                stream = self.streams[i]
                late = self._clock() - due
                if late > MAX_LATE_S:  # fell behind: skip the slots, count them, go on from now
                    skipped = int(late / stream.interval)
                    stream.missed, due = stream.missed + skipped, due + skipped * stream.interval
                await self.step(stream)
                heapq.heappush(heap, (due + stream.interval, i))
                # #4833: a step never suspends (the book's publish is synchronous, the bus's queue
                # is not full), so a backlog of due slots would otherwise run in one loop turn,
                # beside the gateway it feeds: each slot gives the loop a turn.
                await asyncio.sleep(0)

    async def step(self, stream: _Stream) -> None:
        if stream.kind == "book":
            self._book_step(stream.feed)
        else:
            await self._trades_step(stream.feed)
        stream.published += 1

    def _book_step(self, feed: _Feed) -> None:
        live = [d for d in self._depths if self._live(f"book.{feed.name}.{d}")]
        before = {d: feed.book.top(d) for d in live}
        moved: dict[int, tuple[list[list[str]], list[list[str]]]] = {}
        for _ in range(MAX_SKIPS):
            ev = feed.next_delta()
            feed.book.apply(ev.bids, ev.asks)
            feed.xu += 1
            moved = {d: self._windows(feed, d, before[d]) for d in live}
            if not live or any(b or a for b, a in moved.values()):
                break
        moves: list[BookMove] = []
        for d, (bids, asks) in moved.items():
            records = tuple(
                (side, *_scaled(p, s, BOOK_PRICE_SCALE, BOOK_QTY_SCALE))
                for side, rows in ((0, bids), (1, asks))
                for p, s in rows
            )
            moves.append((d, bids, asks, records))
        if moves:
            self._sink.book(feed, moves)

    @staticmethod
    def _windows(
        feed: _Feed, depth: int, before: tuple[dict[str, str], dict[str, str]]
    ) -> tuple[list[list[str]], list[list[str]]]:
        bids, asks = feed.book.top(depth)
        return window_delta(before[0], bids), window_delta(before[1], asks)

    async def _trades_step(self, feed: _Feed) -> None:
        now_ms = self._wall_ms()
        prints: list[tuple[TradePrint, str]] = []
        items: list[dict[str, str | int]] = []
        for _ in range(feed.tier.prints_per_batch):
            p, rnd = feed.next_print()
            tid = f"{p.trade_id}.{rnd}"
            prints.append((p, tid))
            item: dict[str, str | int] = {"id": tid, "ts_ms": now_ms, "price": str(p.price)}
            items.append(item | {"size": str(p.qty), "side": p.side})
        feed.ring.extend(items)
        feed.trades_gen += 1
        await self._sink.trades(feed, prints, items, now_ms, self._live(f"trades.{feed.name}"))


def _scaled(price: str, size: str, ps: int, qs: int) -> tuple[int, int]:
    return scale_int(price, ps), scale_int(size, qs)


def tier_plan(
    symbols: int, hot: int, warm: int, tiers: Mapping[str, Mapping[str, Any]]
) -> list[Tier]:
    """The tier of each symbol by rank: the first `hot`, then `warm`, the rest cold."""
    pick = [*(["hot"] * hot), *(["warm"] * warm)]
    pick += ["cold"] * (symbols - len(pick))
    return [Tier(**tiers[name]) for name in pick[:symbols]]

"""The `ticker` WS topics (E08-T08, #4707; 23 §6.1, §7.7, §8, §14.8): the ingestion module's
snapshot source for `ticker.{symbol}` and the batched `ticker`, and the publisher of their deltas.

`ingestion` may not import `ws` (CONSTITUTION §3), so the gateway is met structurally, as the
recorder topic meets it: `sub` is typed by the fields read here, and the hub's `subscriptions`,
`publish` and `resnapshot` and the gateway's body constructor are injected
(`ws_wiring.ticker_topic`). Plain asyncio code on the hot path, never a statechart (C-2.20).

- Snapshot: one §14.8 item per symbol the topic serves (the symbol in its name, else its `symbols`),
  sorted, from the ticker stream's merged state (24 §2.3). `None` while any of them has no complete
  merged state (warming, reconnecting or not ingested), so the subscription stays
  `snapshot_pending` and no frame carries a half-populated item (§7.7); live state only, so a
  replay subscription is never served. The generation moves whenever a served symbol's state or
  its `stale` flag changes. Continuity is never proven (no delta history), so every
  `snapshot: false` attach is forced (§7.6).
- Item: the §14.8 fields the merged state has, none `null`, and `stale`, true while that state is
  over `STALE_S` old (the stream's ticker threshold), in every frame.
- Deltas: from the bus topic `{env}.md.{symbol}.ticker`, the stream's one publication per push. One
  bus subscription spans every symbol, so the bus's `CONFLATE_LATEST`, which keeps one event across
  all of them, is not used: the queue is `INVALIDATE_ON_FULL`, and a keyed dict keeps each symbol's
  latest event.
- Throttle: one window of `WINDOW_S` (the family's 250 ms, §6.1) for every symbol. A change goes
  out at once when no frame went out in the last window, else at the window's close, so each
  `ticker.{symbol}` and each batched subscription gets at most one `d` per window, carrying each
  changed symbol's latest state, whole (§8.2). With `CV_WS_BACKPRESSURE_ENABLED` off this is the
  topics' only throttle; with it on, the pacer windows after it. A flush publishes each changed
  symbol's item to `ticker.{symbol}`, and to the batched `ticker` one frame per group of
  subscriptions naming the same symbols, grouped once per flush (`select` is a set lookup), with
  the group's changed items; a publish wakes a pending subscription, which gets its `snap` instead
  once every symbol it names is complete.
- Stale: a symbol whose state passes `STALE_S` with no push goes out once more, its last values and
  `stale: true` (§14.8); its next push clears the flag. A symbol the stream is rebuilding (no
  merged state) never goes out with its pre-drop values as fresh. The held symbols and the waits
  are swept at most once per window, so a bus wake between two sweeps walks neither.
- W11 (23 §16.6): a live subscription the merged state cannot snap is followed from its first
  refused build; one still pending past `STALE_S` stays pending, never an error, and counts once
  per wait (`overdue`, `cv_ws_snapshot_overdue_total{topic="ticker"}`).
- Bounds (C-2.18): the bus queue holds `BUS_QUEUE_MAX` events; a full one is invalidated by the
  bus, and its marker re-snaps every live ticker subscription from the merged state
  (`upstream_desync`, §7.4), so no client keeps what the queue lost; a publish that raises does the
  same, and so does a loop turn that raises, which then waits one window before the next, so a
  fault that persists re-snaps once per window, never in a spin. The keyed dict and its sets hold
  one entry per symbol the stream publishes (listed instruments only), capped at `max_symbols`:
  past it a new symbol's push is dropped, never a held symbol's, and logged once per episode. The
  waits hold one entry per waiting subscription, bounded by the registry's own caps. Logs carry
  counts and error classes, never a value.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import math
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.bus import Bus, QueuePolicy, StreamInvalidated, Subscription, TopicPattern
from candleviewer.bus.models import WILDCARD
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.ingestion.watchdog import STALENESS_S
from candleviewer.observability.context import spawn

TICKER: Final = "ticker"
#: The family's default throttle (23 §6.1): one window for every symbol.
WINDOW_S: Final = 0.25
#: 23 §14.8: an item is `stale` past the ingestion stream's ticker threshold.
STALE_S: Final = STALENESS_S["ticker"]
_STALE_US: Final = round(STALE_S * 1_000_000)
#: The bus queue: drained at every wake, so only a stuck loop fills it.
BUS_QUEUE_MAX: Final = 4096
#: Symbols held at once; the stream publishes listed instruments only, some 600.
MAX_SYMBOLS: Final = 2048
#: The §14.8 item's decimals, by the `TickerEvent` field each one is read from (24 §2.3).
_DECIMALS: Final = (
    ("last_price", "last_price"), ("mark_price", "mark_price"), ("index_price", "index_price"),
    ("bid1_price", "bid1_price"), ("bid1_size", "bid1_qty"), ("ask1_price", "ask1_price"),
    ("ask1_size", "ask1_qty"), ("price_change_pct_24h", "price_24h_pcnt"),
    ("high_24h", "high_24h"), ("low_24h", "low_24h"), ("volume_24h", "volume_24h"),
    ("turnover_24h", "turnover_24h"), ("open_interest", "open_interest"),
    ("open_interest_value", "open_interest_value"), ("funding_rate", "funding_rate"),
)  # fmt: skip


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _now_us() -> int:
    return time.time_ns() // 1000


class _Topic(Protocol):
    @property
    def symbol(self) -> str | None: ...


class TickerSub(Protocol):
    """The fields of a WS `Subscription` read here."""

    @property
    def ch(self) -> str: ...
    @property
    def topic(self) -> _Topic: ...
    @property
    def opts(self) -> Mapping[str, Any]: ...
    @property
    def replay_session_id(self) -> str | None: ...
    @property
    def snapshot_pending(self) -> bool: ...
    @property
    def ended(self) -> bool: ...


Match = Callable[[TickerSub], bool]


class Subscriptions(Protocol):
    """`SequencingHub.subscriptions`: the live subscriptions of `ch`."""

    def __call__(self, ch: str) -> Sequence[TickerSub]: ...


class Publish(Protocol):
    """`SequencingHub.publish`: one delta to the subscriptions `select` accepts."""

    def __call__(
        self,
        ch: str,
        body: Mapping[str, Any] | None = ...,
        *,
        select: Match | None = ...,
        wake: bool = ...,
    ) -> int: ...


class Resnapshot(Protocol):
    """`SequencingHub.resnapshot`: a server-initiated resync of what `match` accepts (§7.4)."""

    def __call__(self, match: Match, reason: Literal["upstream_desync"]) -> int: ...


class BodyFactory[B](Protocol):
    """The gateway's snapshot body from a §14.8 payload."""

    def __call__(self, structured: Mapping[str, Any]) -> B: ...


class TickerReader(Protocol):
    """The ticker stream's merged state (`TickerStream`)."""

    def latest(self, symbol: str) -> TickerEvent | None: ...

    def phase(self, symbol: str) -> str | None: ...


class _Counter(Protocol):
    def inc(self, amount: float = 1) -> None: ...


def served(sub: TickerSub) -> tuple[str, ...]:
    """The symbols a subscription is served: the one in its name, else its `symbols` (§6.1)."""
    symbol = sub.topic.symbol
    return (symbol,) if symbol is not None else tuple(sorted(set(sub.opts.get("symbols") or ())))


def ticker_item(event: TickerEvent, *, stale: bool) -> dict[str, Any]:
    """The §14.8 item of `event`: a field it lacks is left out, never `null`."""
    item: dict[str, Any] = {"symbol": event.symbol}
    for name, field in _DECIMALS:
        value = getattr(event, field)
        if value is not None:
            item[name] = format(value, "f")
    if event.next_funding_time is not None:
        item["next_funding_time_ms"] = event.next_funding_time // 1000
    item["ts_ms"] = event.ts_event // 1000
    item["stale"] = stale
    return item


def _live_ticker(sub: TickerSub) -> bool:
    return sub.replay_session_id is None and (sub.ch == TICKER or sub.ch.startswith("ticker."))


def _among(ids: set[int]) -> Match:
    """One group's subscriptions, by identity: the hub's test of each one is a set lookup."""

    def match(sub: TickerSub) -> bool:
        return id(sub) in ids

    return match


@dataclass(slots=True)
class _Wait:
    sub: TickerSub
    since: float
    counted: bool = False


def _stopped(task: asyncio.Task[None]) -> None:
    """A loop that ends other than by `stop` says so: from then on no ticker `d` goes out."""
    if not task.cancelled() and (exc := task.exception()) is not None:
        _log().error("ticker_topic_stopped", error=type(exc).__name__)


class TickerTopic[B]:
    """The `ticker` family's snapshot source and publisher (see the module docstring), for the
    event loop that runs the gateway and the stream: no locks."""

    def __init__(
        self,
        subscriptions: Subscriptions,
        publish: Publish,
        resnapshot: Resnapshot,
        body: BodyFactory[B],
        *,
        reader: Callable[[], TickerReader | None],
        bus: Bus,
        env: str,
        overdue: _Counter | None = None,
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _now_us,
        window_s: float = WINDOW_S,
        max_symbols: int = MAX_SYMBOLS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._subscriptions, self._publish, self._resnapshot = subscriptions, publish, resnapshot
        self._body, self._reader, self._bus, self._env = body, reader, bus, env
        self._overdue, self._clock, self._now_us = overdue, clock, now_us
        self._window_s, self._max, self._sleep = window_s, max_symbols, sleep
        self._latest: dict[str, TickerEvent] = {}  # the keyed latest dict
        self._changed: set[str] = set()  # symbols with a change not yet sent
        self._flagged: set[str] = set()  # symbols whose stale item went out
        self._full = False
        self._last_flush = self._last_sweep = -math.inf
        #: Per symbol, the state its generation names and that generation (identity + stale).
        self._seen: dict[str, tuple[tuple[TickerEvent, bool] | None, int]] = {}
        self._generations = itertools.count(1)
        self._waits: dict[int, _Wait] = {}
        self._sub: Subscription | None = None
        self._task: asyncio.Task[None] | None = None

    # -- SnapshotSource

    def build(self, sub: TickerSub) -> B | None:
        if sub.replay_session_id is not None:
            return None  # the merged state is live state, no replay's
        reader, now_us = self._reader(), self._now_us()
        items: list[dict[str, Any]] = []
        for symbol in served(sub):
            event = None if reader is None else reader.latest(symbol)
            if event is None:  # warming: the subscription stays pending, its wait followed
                self._waits.setdefault(id(sub), _Wait(sub, self._clock()))
                return None
            items.append(ticker_item(event, stale=self._stale(event, now_us)))
        self._waits.pop(id(sub), None)
        return self._body({"tickers": items})

    def generation(self, sub: TickerSub) -> int:
        reader, now_us, total = self._reader(), self._now_us(), 0
        for symbol in served(sub):
            event = None if reader is None else reader.latest(symbol)
            state = None if event is None else (event, self._stale(event, now_us))
            seen = self._seen.get(symbol)
            if seen is None or not _same(seen[0], state):
                if seen is None and len(self._seen) >= self._max:
                    self._seen.clear()  # safe: generations only grow, so none repeats
                seen = self._seen[symbol] = (state, next(self._generations))
            total += seen[1]
        return total

    def continuity(self, sub: TickerSub, from_ts_ms: int | None) -> bool:
        return False  # no delta history: `snapshot: false` is always `snapshot_forced`

    # -- deltas

    def offer(self, item: object) -> None:
        """One item from the bus: a symbol's new state, or the bus's overflow marker."""
        if isinstance(item, StreamInvalidated):
            _log().warning("ticker_topic_stream_invalidated")
            self._resync()
        elif isinstance(item, TickerEvent):
            self._take(item)

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
        """At most once per window, mark the symbols newly stale and count the overdue waits; flush
        once the window allows; the frames sent."""
        now, now_us, reader = self._clock(), self._now_us(), self._reader()
        if now >= self._last_sweep + self._window_s:
            self._last_sweep = now
            self._sweep(reader, now, now_us)
        if not self._changed or now < self._last_flush + self._window_s:
            return 0
        return self._flush(reader, now, now_us)

    def _take(self, event: TickerEvent) -> None:
        symbol = event.symbol
        held = self._latest.get(symbol)
        if held is None and len(self._latest) >= self._max:
            if not self._full:
                self._full = True
                _log().warning("ticker_topic_symbols_full", symbols=len(self._latest))
            return
        if held is not None and event.ts_event < held.ts_event:
            return  # never a symbol back in time
        self._latest[symbol] = event
        self._changed.add(symbol)
        self._flagged.discard(symbol)  # a fresh push clears `stale` (§14.8)

    def _sweep(self, reader: TickerReader | None, now: float, now_us: int) -> None:
        for symbol, held in list(self._latest.items()):
            current = None if reader is None else reader.latest(symbol)
            if current is None and (reader is None or reader.phase(symbol) is None):
                self._forget(symbol)  # the stream let it go
                continue
            if current is not None and current.ts_event > held.ts_event:
                held = self._latest[symbol] = current  # the bus is behind: age the newer one
            if symbol not in self._flagged and self._stale(held, now_us):
                self._flagged.add(symbol)
                self._changed.add(symbol)
        self._full = self._full and len(self._latest) >= self._max
        for key, wait in list(self._waits.items()):
            if wait.sub.ended or not wait.sub.snapshot_pending:
                del self._waits[key]
            elif not wait.counted and now - wait.since > STALE_S:
                wait.counted = True
                if self._overdue is not None:
                    self._overdue.inc()

    def _flush(self, reader: TickerReader | None, now: float, now_us: int) -> int:
        changed, self._changed = self._changed, set()
        items: dict[str, dict[str, Any]] = {}
        for symbol in sorted(changed):
            event = self._latest.get(symbol)
            if event is None:
                continue
            current = None if reader is None else reader.latest(symbol)
            if current is not None and current.ts_event >= event.ts_event:
                event = self._latest[symbol] = current  # never older than a snapshot built since
            stale = self._stale(event, now_us)
            if current is None and not stale:
                continue  # rebuilding: its pre-drop values never go out as fresh
            items[symbol] = ticker_item(event, stale=stale)
        if not items:
            return 0
        self._last_flush = now
        try:
            sent = 0
            for symbol, item in items.items():
                sent += self._publish(f"{TICKER}.{symbol}", {"tickers": [item]}, wake=True)
            subs = self._subscriptions(TICKER)  # held through the flush: no `id` in it is reused
            groups: dict[tuple[str, ...], set[int]] = {}
            for sub in subs:  # `served` once per subscription per flush, never once per group
                groups.setdefault(served(sub), set()).add(id(sub))
            for group, ids in groups.items():
                hit = [items[s] for s in group if s in items]
                if hit:
                    sent += self._publish(TICKER, {"tickers": hit}, select=_among(ids), wake=True)
        except Exception as exc:  # contained: the topic is a view, the stream goes on
            _log().error("ticker_topic_publish_failed", error=type(exc).__name__)
            self._resync()
            return 0
        return sent

    def _forget(self, symbol: str) -> None:
        self._latest.pop(symbol, None)
        self._seen.pop(symbol, None)
        self._changed.discard(symbol)
        self._flagged.discard(symbol)

    def _stale(self, event: TickerEvent, now_us: int) -> bool:
        return now_us - event.ts_ingest > _STALE_US

    def _resync(self) -> None:
        try:
            self._resnapshot(_live_ticker, "upstream_desync")
        except Exception as exc:
            _log().error("ticker_topic_resync_failed", error=type(exc).__name__)

    # -- lifecycle (`WsRuntime`)

    def open(self) -> None:
        """Hold the bus topic (idempotent); `pump` drains it."""
        if self._sub is None:
            pattern = TopicPattern(env=self._env, domain="md", symbol=WILDCARD, detail=TICKER)
            self._sub = self._bus.subscribe(
                "ws-ticker-topic", pattern, QueuePolicy.INVALIDATE_ON_FULL, maxsize=BUS_QUEUE_MAX
            )

    def start(self) -> None:
        self.open()
        if self._task is None:
            self._task = spawn(self._run(), name="ws-ticker-topic")
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
        while (sub := self._sub) is not None:
            wait = self._window_s
            if self._changed:  # wait for the window to close, or for the next push
                wait = max(0.0, self._last_flush + self._window_s - self._clock())
            try:
                if wait > 0:
                    with contextlib.suppress(TimeoutError):
                        async with asyncio.timeout(wait):
                            self.offer(await sub.get())
                self.pump()
                self.tick()
            except Exception as exc:  # never let one bad turn stop every ticker `d`
                _log().error("ticker_topic_turn_failed", error=type(exc).__name__)
                self._resync()
                await self._sleep(self._window_s)  # a fault that persists: one resync per window


def _same(seen: tuple[TickerEvent, bool] | None, state: tuple[TickerEvent, bool] | None) -> bool:
    if seen is None or state is None:
        return seen is state
    return seen[0] is state[0] and seen[1] == state[1]


__all__ = [
    "BUS_QUEUE_MAX",
    "MAX_SYMBOLS",
    "STALE_S",
    "TICKER",
    "WINDOW_S",
    "TickerReader",
    "TickerSub",
    "TickerTopic",
    "served",
    "ticker_item",
]

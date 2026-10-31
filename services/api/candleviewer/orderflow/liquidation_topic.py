"""The `liquidations` WS topics (E24-T03, #667; 23 §6.1, §8.2, §14.9): the order-flow module's
snapshot source for `liquidations.{symbol}` and the batched `liquidations`, and their publisher.

`orderflow` may not import `ws` (CONSTITUTION §3), so the gateway is met structurally, as the
ticker topic meets it: the hub's `subscriptions`, `publish` and `resnapshot` and the gateway's body
constructor are injected (`ws_wiring.liquidations_topic`). Plain asyncio on the hot path, never a
statechart (C-2.20).

- **Prints** come from the bus topic `{env}.md.{symbol}.liquidation` (the ingestion stream's one
  publication per print). A print already seen (a push the exchange replays after a reconnect) is
  dropped by its dedup key, so a client never counts it twice.
- **Items** are `orderflow.liquidations.LiqItem`s, clustered exactly as `/market/liquidations`
  clusters them (`Clusterer`), one clusterer per `(symbol, cluster_window_ms)` some subscription
  uses. A cluster goes out once closed: by a later print of its side at or past its end, or by the
  clock `LATE_GRACE_US` past it. `min_notional_usd` drops an item below it. No item is estimated.
- **Throttle** (§6.1, 500 ms): at most one `d` per subscription group per `WINDOW_S`, carrying every
  item closed since the last one, appended and never merged (§8.2: the pacer keeps `liquidations`
  an append family too). `note` is in every snapshot and `d`: the 23 §14.9 sentence, injected by
  the composition root from the adapter, which owns the venue's name (C-2.2).
- **Snapshot**: the last `SNAPSHOT_ITEMS` closed items of the symbols served (the one in the name,
  else `symbols`), oldest first, from the recent prints; live subscriptions only. Continuity is
  never proven (no delta history), so every `snapshot: false` attach is forced (§7.6).
- **Bounds** (C-2.18): the bus queue (`BUS_QUEUE_MAX`, invalidated when full: its marker
  re-snaps every live liquidations subscription, `upstream_desync`), the recent prints and the
  seen keys per symbol, the prints waiting for a flush per symbol (`PENDING_MAX`; past it the
  symbol re-snaps), and the symbols held (`MAX_SYMBOLS`; a new symbol past it is dropped, logged
  once). Clusterers live only while a subscription uses their window.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.bus import Bus, QueuePolicy, StreamInvalidated, TopicPattern
from candleviewer.bus import Subscription as BusSubscription
from candleviewer.bus.models import WILDCARD
from candleviewer.domain.liquidations import LiqPrint
from candleviewer.exchange.base.models import LiquidationEvent
from candleviewer.observability.context import spawn
from candleviewer.orderflow.deriv_metrics import deriv_sub_cap_rejected_total
from candleviewer.orderflow.liquidations import Clusterer, LiqItem, cluster_scan, print_of

FAMILY: Final = "liquidations"
#: The ingestion stream's bus detail: one publication per print.
DETAIL: Final = "liquidation"
#: §6.1: the family's throttle.
WINDOW_S: Final = 0.5
#: §6.1: "Last 100".
SNAPSHOT_ITEMS: Final = 100
#: A cluster closes on the clock this long after its end, so a late print still joins it.
LATE_GRACE_US: Final = 500_000
RECENT_PRINTS: Final = 1000
SEEN_KEYS: Final = 4000
PENDING_MAX: Final = 20_000
BUS_QUEUE_MAX: Final = 16_384
MAX_SYMBOLS: Final = 1024
#: §16.2: a subscription names at most this many symbols (`ws/topics.py` `_SYMBOLS`).
SYMBOLS_CAP: Final = 40


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _now_us() -> int:
    return time.time_ns() // 1000


class _Topic(Protocol):
    @property
    def symbol(self) -> str | None: ...


class LiqSub(Protocol):
    """The fields of a WS `Subscription` read here."""

    @property
    def ch(self) -> str: ...
    @property
    def topic(self) -> _Topic: ...
    @property
    def opts(self) -> Mapping[str, Any]: ...
    @property
    def replay_session_id(self) -> str | None: ...


Match = Callable[[LiqSub], bool]


class Subscriptions(Protocol):
    def __call__(self, ch: str) -> Sequence[LiqSub]: ...


class Publish(Protocol):
    def __call__(
        self,
        ch: str,
        body: Mapping[str, Any] | None = ...,
        *,
        select: Match | None = ...,
        wake: bool = ...,
    ) -> int: ...


class Resnapshot(Protocol):
    def __call__(self, match: Match, reason: Literal["upstream_desync"]) -> int: ...


class BodyFactory[B](Protocol):
    def __call__(self, structured: Mapping[str, Any]) -> B: ...


@dataclass(frozen=True, slots=True)
class Options:
    window_ms: int
    min_notional: Decimal | None


def options_of(opts: Mapping[str, Any]) -> Options:
    raw = opts.get("min_notional_usd")
    try:
        floor = None if raw is None else Decimal(str(raw))
    except InvalidOperation:
        floor = None  # the registry validated it; never reached
    return Options(int(opts.get("cluster_window_ms") or 0), floor)


def served(sub: LiqSub) -> tuple[str, ...]:
    """The symbols a subscription is served: the one in its name, else its `symbols` (§6.1)."""
    symbol = sub.topic.symbol
    return (symbol,) if symbol is not None else tuple(sorted(set(sub.opts.get("symbols") or ())))


def _passes(item: LiqItem, floor: Decimal | None) -> bool:
    return floor is None or item.notional >= floor


def _order(item: LiqItem) -> tuple[object, ...]:
    """Time order across symbols, the dedup key's order within one."""
    return (item.first.ts_us, item.first.symbol, *item.key()[1:])


_PREFIX: Final = f"{FAMILY}."


def _live(sub: LiqSub) -> bool:
    return sub.replay_session_id is None and (sub.ch == FAMILY or sub.ch.startswith(_PREFIX))


def _among(ids: set[int]) -> Match:
    def match(sub: LiqSub) -> bool:
        return id(sub) in ids

    return match


def note_cap_refusal(entry: object, ch: object, code: str, field_: str | None) -> None:
    """Count a `liquidations` subscription the registry refused for naming more than the
    protocol's symbol cap (`deriv_sub_cap_rejected_total`, E24 STRIDE model §9)."""
    if code != "invalid_options" or field_ != "symbols" or not isinstance(ch, str):
        return
    if ch != FAMILY and not ch.startswith("liquidations."):
        return
    opts = entry.get("opts") if isinstance(entry, dict) else None
    symbols = opts.get("symbols") if isinstance(opts, dict) else None
    if isinstance(symbols, list) and len(symbols) > SYMBOLS_CAP:
        deriv_sub_cap_rejected_total.inc()


@dataclass(slots=True)
class _Symbol:
    recent: deque[LiqPrint] = field(default_factory=lambda: deque(maxlen=RECENT_PRINTS))
    seen: dict[tuple[object, ...], None] = field(default_factory=dict)
    pending: list[LiqPrint] = field(default_factory=list)
    generation: int = 0


def _stopped(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        _log().error("liquidations_topic_stopped", error=type(exc).__name__)


class LiquidationsTopic[B]:
    """The `liquidations` family's snapshot source and publisher (module docstring), for the
    event loop that runs the gateway and the ingestion stream: no locks."""

    def __init__(
        self,
        subscriptions: Subscriptions,
        publish: Publish,
        resnapshot: Resnapshot,
        body: BodyFactory[B],
        *,
        bus: Bus,
        env: str,
        note: str,
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _now_us,
        window_s: float = WINDOW_S,
        max_symbols: int = MAX_SYMBOLS,
        pending_max: int = PENDING_MAX,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._subscriptions, self._publish, self._resnapshot = subscriptions, publish, resnapshot
        self._body, self._bus, self._env, self._note = body, bus, env, note
        self._clock, self._now_us, self._window_s = clock, now_us, window_s
        self._max, self._pending_max, self._sleep = max_symbols, pending_max, sleep
        self._symbols: dict[str, _Symbol] = {}
        self._clusterers: dict[tuple[str, int], Clusterer] = {}
        self._full = False
        self._last_flush = -math.inf
        self._sub: BusSubscription | None = None
        self._task: asyncio.Task[None] | None = None

    # -- SnapshotSource

    def build(self, sub: LiqSub) -> B:
        if sub.replay_session_id is not None:
            return self._body({"liquidations": [], "note": self._note})  # live prints only
        opts = options_of(sub.opts)
        items: list[LiqItem] = []
        for symbol in served(sub):
            state = self._symbols.get(symbol)
            if state is None:
                continue
            # What this subscription's `d` frames will send later is what the clusterer holds
            # open now: the snapshot is every other item of the recent prints.
            held = {i.key() for i in self._clusterer(symbol, opts.window_ms).open.values()}
            recent = sorted(state.recent, key=LiqPrint.key)
            items += [i for i in cluster_scan(recent, opts.window_ms, {}) if i.key() not in held]
        kept = [i for i in sorted(items, key=_order) if _passes(i, opts.min_notional)]
        body = {"liquidations": [i.wire() for i in kept[-SNAPSHOT_ITEMS:]], "note": self._note}
        return self._body(body)

    def generation(self, sub: LiqSub) -> int:
        return sum(s.generation for sym in served(sub) if (s := self._symbols.get(sym)) is not None)

    def continuity(self, sub: LiqSub, from_ts_ms: int | None) -> bool:
        return False

    def _clusterer(self, symbol: str, window_ms: int) -> Clusterer:
        """The `(symbol, window)` clusterer, made on first use from the recent prints: the
        clusters still open then are the first its frames send."""
        held = self._clusterers.get((symbol, window_ms))
        if held is None:
            held = self._clusterers[(symbol, window_ms)] = Clusterer(window_ms)
            state = self._symbols.get(symbol)
            now = self._now_us()
            for p in sorted(state.recent if state is not None else (), key=LiqPrint.key):
                held.add(p, now)
            held.expire(now - LATE_GRACE_US)
        return held

    # -- deltas

    def offer(self, item: object) -> None:
        if isinstance(item, StreamInvalidated):
            _log().warning("liquidations_topic_stream_invalidated")
            self._resync()
        elif isinstance(item, LiquidationEvent):
            self._take(print_of(item))

    def _take(self, p: LiqPrint) -> None:
        state = self._symbols.get(p.symbol)
        if state is None:
            if len(self._symbols) >= self._max:
                if not self._full:
                    self._full = True
                    _log().warning("liquidations_topic_symbols_full", symbols=len(self._symbols))
                return
            state = self._symbols[p.symbol] = _Symbol()
        key = p.key()
        if key in state.seen:
            return  # replayed by the exchange after a reconnect: already delivered
        state.seen[key] = None
        while len(state.seen) > SEEN_KEYS:
            del state.seen[next(iter(state.seen))]
        if len(state.pending) >= self._pending_max:
            _log().warning("liquidations_topic_pending_full", symbol=p.symbol)
            state.recent.extend(state.pending)
            state.pending.clear()
            self._resync()
        state.pending.append(p)

    def pump(self) -> int:
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
        """Flush once the window allows and something is pending or a cluster may close."""
        now = self._clock()
        if now < self._last_flush + self._window_s:
            return 0
        busy = any(s.pending for s in self._symbols.values()) or any(
            c.open for c in self._clusterers.values()
        )
        if not busy:
            return 0
        self._last_flush = now
        try:
            return self._flush()
        except Exception as exc:  # contained: the topic is a view, the stream goes on
            _log().error("liquidations_topic_publish_failed", error=type(exc).__name__)
            self._resync()
            return 0

    def _groups(self) -> dict[tuple[str, tuple[str, ...], Options], set[int]]:
        """Live subscriptions by channel, served symbols and options: one frame per group."""
        groups: dict[tuple[str, tuple[str, ...], Options], set[int]] = {}
        channels = [FAMILY, *(f"{FAMILY}.{s}" for s in self._symbols)]
        for ch in channels:
            for sub in self._subscriptions(ch):
                if _live(sub):
                    groups.setdefault((ch, served(sub), options_of(sub.opts)), set()).add(id(sub))
        return groups

    def _flush(self) -> int:
        groups = self._groups()
        wanted = {(sym, opts.window_ms) for (_, syms, opts) in groups for sym in syms}
        for key in [k for k in self._clusterers if k not in wanted]:
            del self._clusterers[key]
        now = self._now_us()
        horizon = now - LATE_GRACE_US
        closed: dict[tuple[str, int], list[LiqItem]] = {}
        for sym, window in wanted:
            state = self._symbols.get(sym)
            if state is None:
                continue
            clusterer = self._clusterer(sym, window)
            pending = sorted(state.pending, key=LiqPrint.key)
            out = [i for p in pending if (i := clusterer.add(p, now))]
            closed[(sym, window)] = out + clusterer.expire(horizon)
        for state in self._symbols.values():
            if state.pending:
                state.recent.extend(state.pending)
                state.pending.clear()
                state.generation += 1
        sent = 0
        for (ch, syms, opts), ids in groups.items():
            items = [
                i
                for sym in syms
                for i in closed.get((sym, opts.window_ms), ())
                if _passes(i, opts.min_notional)
            ]
            if items:
                items.sort(key=_order)
                body = {"liquidations": [i.wire() for i in items], "note": self._note}
                sent += self._publish(ch, body, select=_among(ids), wake=True)
        return sent

    def _resync(self) -> None:
        try:
            self._resnapshot(_live, "upstream_desync")
        except Exception as exc:
            _log().error("liquidations_topic_resync_failed", error=type(exc).__name__)

    # -- lifecycle (`WsRuntime`)

    def open(self) -> None:
        if self._sub is None:
            pattern = TopicPattern(env=self._env, domain="md", symbol=WILDCARD, detail=DETAIL)
            self._sub = self._bus.subscribe(
                "ws-liquidations-topic", pattern, QueuePolicy.INVALIDATE_ON_FULL,
                maxsize=BUS_QUEUE_MAX,
            )  # fmt: skip

    def start(self) -> None:
        self.open()
        if self._task is None:
            self._task = spawn(self._run(), name="ws-liquidations-topic")
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
            try:
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(self._window_s):
                        self.offer(await sub.get())
                self.pump()
                self.tick()
            except Exception as exc:  # never let one bad turn stop every liquidations `d`
                _log().error("liquidations_topic_turn_failed", error=type(exc).__name__)
                self._resync()
                await self._sleep(self._window_s)


__all__ = [
    "FAMILY",
    "SNAPSHOT_ITEMS",
    "WINDOW_S",
    "LiquidationsTopic",
    "Options",
    "note_cap_refusal",
    "options_of",
    "served",
]

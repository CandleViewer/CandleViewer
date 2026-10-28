"""The big-trade tape: what `trades.{symbol}` (23 §6.1) and `GET /market/trades` (22) both serve
(E22-T02, #654). Plain synchronous code (C-2.20: per-print work is never a statechart).

One `SymbolTape` per symbol reads every print in `(ts_event, trade_id)` order:

* **Flags.** One `BigTradeEngine` with the symbol's config (24 §2.10, server defaults:
  `BigTradeConfig()`) and clustering off flags prints (`BigTradeEvent`) and reports the effective
  threshold (`BigTradeThresholdEvent`). The subscription options never reach it, so `min_size` and
  the cluster options never move the threshold (23 §6.1).
* **Tick direction.** Derived over the symbol's prints in order, as the exchange defines it; the
  first print the tape reads has none.

One `OptionTape` per option set (`min_size`, `cluster_window_ms`, `cluster_tolerance_ticks`) reads
the annotated prints: `min_size` drops a print whose own size is below it, counted (`dropped`),
before the engine's `Clusterer` (`bigtrade_cluster.py`) groups the rest. A cluster leaves once it
closes, as one item: its first print's `id`, `ts` and `price` (and side, block flag and tick
direction), the members' total size, their count as `cluster_size` and `is_big_trade` when any
member is flagged (the engine flags prints, never a cluster's total). With clustering off every
print is its own item. A cluster's members are tracked per key in arrival order, so membership
never depends on the engine's bounded id list (`CLUSTER_IDS_MAX`).

`tape_page` is the same path over stored prints, ending with a flush: REST and WS agree on the
flagged prints and on cluster membership for the same prints and options."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow.bigtrade import BigTradeEngine
from candleviewer.orderflow.bigtrade_cluster import Clusterer, Key, OpenCluster
from candleviewer.orderflow.bigtrade_models import (
    BigTradeConfig,
    BigTradeEvent,
    BigTradeThresholdEvent,
    Mode,
)

TickDirection = Literal["PlusTick", "ZeroPlusTick", "MinusTick", "ZeroMinusTick"]
_ZERO: dict[str, TickDirection] = {"PlusTick": "ZeroPlusTick", "MinusTick": "ZeroMinusTick"}


@dataclass(frozen=True, slots=True)
class TapePrint:
    """A print as the tape reads it: the engine's flag and its tick direction."""

    event: TradeEvent
    big: bool
    tick_direction: TickDirection | None


@dataclass(frozen=True, slots=True)
class TapeItem:
    """One tape row (23 §14.2 item, 22 `PublicTrade`): a print, or a closed cluster."""

    first: TapePrint
    size: Decimal
    cluster_size: int
    big: bool

    @property
    def key(self) -> tuple[int, str]:
        return self.first.event.ts_event, self.first.event.trade_id

    def wire(self) -> dict[str, object]:
        """The §14.2 item: decimals as plain strings, `ts_ms` in epoch milliseconds."""
        ev = self.first.event
        item: dict[str, object] = {
            "id": ev.trade_id,
            "ts_ms": ev.ts_event // 1000,
            "price": format(ev.price, "f"),
            "size": format(self.size, "f"),
            "side": ev.side,
            "is_block_trade": ev.is_block_trade,
            "is_liquidation": False,  # the public tape names no liquidation-origin print
            "cluster_size": self.cluster_size,
            "is_big_trade": self.big,
        }
        if self.first.tick_direction is not None:
            item["tick_direction"] = self.first.tick_direction
        return item


@dataclass(frozen=True, slots=True)
class Options:
    """One option set. `min_size` None means no extra filter."""

    min_size: Decimal | None = None
    cluster_window_ms: int = 0
    cluster_tolerance_ticks: int = 0


class SymbolTape:
    """Flags and tick directions for one symbol (module docstring)."""

    def __init__(self, symbol: str, tick_size: Decimal, config: BigTradeConfig) -> None:
        flags = BigTradeConfig(config.mode, config.value, config.percentile_window_ms)
        self.symbol, self.tick_size, self.mode = symbol, tick_size, config.mode
        self._engine = BigTradeEngine(symbol, tick_size, flags)
        self.threshold: Decimal = config.value if config.mode != "percentile" else Decimal(0)
        self._last: tuple[int, str] | None = None
        self._price: Decimal | None = None
        self._direction: TickDirection = "ZeroPlusTick"

    @property
    def last(self) -> tuple[int, str] | None:
        """The newest `(ts_event, trade_id)` read: an older or equal print is skipped."""
        return self._last

    def read(self, batch: Iterable[TradeEvent]) -> list[TapePrint]:
        """Annotate the prints of `batch` newer than every print read so far, in order."""
        fresh = sorted(
            (e for e in batch if self._last is None or (e.ts_event, e.trade_id) > self._last),
            key=lambda e: (e.ts_event, e.trade_id),
        )
        if not fresh:
            return []
        self._last = fresh[-1].ts_event, fresh[-1].trade_id
        flagged: set[str] = set()
        for out in self._engine.process(fresh):
            if isinstance(out, BigTradeEvent):
                flagged.add(out.trade_id)
            elif isinstance(out, BigTradeThresholdEvent):
                self.threshold = out.effective_threshold_abs
        return [TapePrint(e, e.trade_id in flagged, self._tick(e.price)) for e in fresh]

    def _tick(self, price: Decimal) -> TickDirection | None:
        prev, self._price = self._price, price
        if prev is None:
            return None
        if price > prev:
            self._direction = "PlusTick"
        elif price < prev:
            self._direction = "MinusTick"
        else:
            self._direction = _ZERO.get(self._direction, self._direction)
        return self._direction


@dataclass(slots=True)
class OptionTape:
    """`min_size`, then clustering, for one option set (module docstring)."""

    tick_size: Decimal
    options: Options
    dropped: int = 0
    _members: dict[Key, deque[TapePrint]] = field(default_factory=dict)
    _clusters: Clusterer | None = None

    def __post_init__(self) -> None:
        o = self.options
        if o.cluster_window_ms > 0:
            self._clusters = Clusterer(
                self.tick_size, o.cluster_window_ms, o.cluster_tolerance_ticks
            )

    def add(self, prints: Sequence[TapePrint]) -> list[TapeItem]:
        """The items that close with `prints`; the prints `min_size` drops add to `dropped`."""
        floor, out = self.options.min_size, []
        for p in prints:
            if floor is not None and p.event.qty < floor:
                self.dropped += 1
                continue
            clusters = self._clusters
            if clusters is None:
                out.append(TapeItem(p, p.event.qty, 1, p.big))
                continue
            key: Key = (p.event.side, clusters.bucket(p.event.price))
            self._members.setdefault(key, deque()).append(p)
            out.extend(self._item(c) for c, _ in clusters.add(p.event))
        return out

    def expire(self, now_us: int) -> list[TapeItem]:
        """The items of the clusters whose deadline is before `now_us` (a live reader's clock)."""
        if self._clusters is None:
            return []
        return [self._item(c) for c, _ in self._clusters.expire(now_us)]

    def flush(self) -> list[TapeItem]:
        """Close every open cluster (a page's end): their items, oldest first."""
        if self._clusters is None:
            return []
        return [self._item(c) for c, _ in self._clusters.flush()]

    def take_dropped(self) -> int:
        dropped, self.dropped = self.dropped, 0
        return dropped

    def _item(self, cluster: OpenCluster) -> TapeItem:
        """A closed cluster's item from its members, the oldest `count` prints of its key."""
        queue = self._members[cluster.key]
        members = [queue.popleft() for _ in range(cluster.count)]
        if not queue:
            del self._members[cluster.key]
        return TapeItem(members[0], cluster.qty, cluster.count, any(m.big for m in members))


def tape_page(
    events: Iterable[TradeEvent],
    symbol: str,
    tick_size: Decimal,
    config: BigTradeConfig,
    options: Options,
    *,
    side: str | None = None,
) -> tuple[list[TapeItem], Decimal, Mode]:
    """REST's read (22 `getTrades`): every stored print through a fresh `SymbolTape` (both sides:
    flags and tick directions never depend on the filter), then the prints of `side` (all when
    None) through one `OptionTape`, open clusters closed at the end. Returns the items in
    `(ts, id)` order of their first print, the effective threshold and its mode."""
    tape = SymbolTape(symbol, tick_size, config)
    option = OptionTape(tick_size, options)
    prints = [p for p in tape.read(events) if side is None or p.event.side == side]
    items = option.add(prints)
    items.extend(option.flush())
    items.sort(key=lambda i: i.key)
    return items, tape.threshold, tape.mode


__all__ = ["OptionTape", "Options", "SymbolTape", "TapeItem", "TapePrint", "tape_page"]

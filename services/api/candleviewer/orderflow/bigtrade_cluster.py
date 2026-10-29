"""Deterministic print clustering (24-internal-schemas §2.10 "Cluster key", US-BIG-004).

Plain synchronous code (C-2.20: per-print work is never a statechart). Rules:

* Key = `(side, price_bucket)` per symbol, `price_bucket = floor(price / (tick_size *
  max(1, tolerance_ticks)))`. There is no anchor-tolerance check; the anchor is display only.
* A print merges into its key's open cluster iff `ts_event <= first_ts_event +
  cluster_window_ms * 1000` (ms → µs). Every other open cluster whose deadline has passed is
  closed (`deadline`) **before** the print is placed, so closing depends only on print time
  and never on batch boundaries (determinism).
* Open clusters are kept in first-print order, so the deadline sweep is O(1) amortised (the
  front is always the oldest), never a window rescan (threat model D16).
* Bounds (SR-E22-05): at most `CLUSTER_KEYS_MAX` open keys and
  `prints_buffer_effective_max(window)` buffered prints; overflow evicts the oldest cluster
  (`evicted`) and calls `on_truncate` (-> `bigtrade_state_truncated_total`).
* The buffer holds the prints of the open clusters (bounded). A config change re-clusters them
  under the new config (`replay`, US-BIG-004 sc.2) without emitting any close for the
  never-published open clusters, so each print lands in exactly one emitted cluster;
  `config_change` closes appear only when clustering is turned off. `cluster_prints` is the
  same recompute over an arbitrary stored range (e.g. a REST window).
* Bar attribution: `TradeClusterEvent.bar_open_us` uses the FIRST print (US-BIG-004 sc.3)."""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal

from candleviewer.domain.primitives import Side
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow import limits as L
from candleviewer.orderflow.bigtrade_models import CloseReason

Key = tuple[Side, int]


@dataclass(slots=True)
class OpenCluster:
    key: Key
    first: TradeEvent
    last: TradeEvent
    ids: list[str]
    count: int = 0
    qty: Decimal = Decimal(0)
    notional: Decimal = Decimal(0)
    max_qty: Decimal = Decimal(0)

    def add(self, ev: TradeEvent) -> None:
        self.count += 1
        if len(self.ids) < L.CLUSTER_IDS_MAX:
            self.ids.append(ev.trade_id)
        self.last = ev
        self.qty += ev.qty
        self.notional += ev.notional
        self.max_qty = max(self.max_qty, ev.qty)


Closed = tuple[OpenCluster, CloseReason]


@dataclass(slots=True)
class Clusterer:
    tick_size: Decimal
    window_ms: int
    tolerance_ticks: int
    on_truncate: Callable[[], None] = lambda: None
    _open: OrderedDict[Key, OpenCluster] = field(default_factory=OrderedDict)
    _buffer: deque[TradeEvent] = field(default_factory=deque)

    @property
    def enabled(self) -> bool:
        return self.window_ms > 0

    def bucket(self, price: Decimal) -> int:
        width = self.tick_size * max(1, self.tolerance_ticks)
        return int((price / width).to_integral_value(rounding=ROUND_FLOOR))

    def add(self, ev: TradeEvent) -> list[Closed]:
        if not self.enabled:
            return []
        out = self._sweep(ev.ts_event)
        key: Key = (ev.side, self.bucket(ev.price))
        cluster = self._open.get(key)
        if cluster is None:
            if len(self._open) >= L.CLUSTER_KEYS_MAX:
                out.append(self._evict())
            cluster = OpenCluster(key, ev, ev, [])
            self._open[key] = cluster
        cluster.add(ev)
        self._buffer.append(ev)
        while len(self._buffer) > L.prints_buffer_effective_max(self.window_ms):
            out.append(self._evict())
        return out

    def expire(self, now_us: int) -> list[Closed]:
        """Close every open cluster whose deadline is before `now_us` with no print to place: a
        live reader's clock, so a quiet tape still closes its clusters (E22-T02, 23 §6.1)."""
        return self._sweep(now_us) if self.enabled else []

    def _sweep(self, now_us: int) -> list[Closed]:
        out: list[Closed] = []
        horizon = self.window_ms * 1000
        while self._open:
            first = next(iter(self._open.values()))
            if first.first.ts_event + horizon >= now_us:
                break
            self._open.popitem(last=False)
            out.append((first, "deadline"))
        self._prune()
        return out

    def _evict(self) -> Closed:
        self.on_truncate()
        _, cluster = self._open.popitem(last=False)
        self._prune()
        return cluster, "evicted"

    def _prune(self) -> None:
        if not self._open:
            self._buffer.clear()
            return
        oldest = next(iter(self._open.values())).first.ts_event
        while self._buffer and self._buffer[0].ts_event < oldest:
            self._buffer.popleft()

    def open_members(self) -> list[TradeEvent]:
        """Buffered prints that belong to a still-open cluster, in `(ts_event, trade_id)` order.
        The buffer can also hold late members of clusters that already closed (it is pruned by
        the oldest open first-print); those were emitted and must not be replayed."""
        out = []
        for ev in self._buffer:
            c = self._open.get((ev.side, self.bucket(ev.price)))
            if c is not None and ev.ts_event >= c.first.ts_event:
                out.append(ev)
        return sorted(out, key=lambda e: (e.ts_event, e.trade_id))

    def replay(self, window_ms: int, tolerance_ticks: int) -> list[Closed]:
        """§2.10 config change. Still-open clusters were never published, so **no close is
        emitted for them**: their buffered prints are re-clustered under the new config
        (US-BIG-004 sc.2), print-time deterministic and bounded by `PRINTS_BUFFER_EFFECTIVE_MAX`.
        Clusters closing during the recompute carry their normal reason; the rest stay open.
        Invariant: across a reconfigure every trade id ends up in exactly one emitted cluster.
        Only turning clustering off (`window_ms == 0`) closes them, with `config_change`."""
        if window_ms == 0:
            closed = self.flush("config_change")
            self.window_ms, self.tolerance_ticks = window_ms, tolerance_ticks
            return closed
        members = self.open_members()
        self._open.clear()
        self._buffer.clear()
        self.window_ms, self.tolerance_ticks = window_ms, tolerance_ticks
        out: list[Closed] = []
        for ev in members:
            out.extend(self.add(ev))
        return out

    def flush(self, reason: CloseReason = "flush") -> list[Closed]:
        out: list[Closed] = [(c, reason) for c in self._open.values()]
        self._open.clear()
        self._buffer.clear()
        return out


def cluster_prints(
    events: list[TradeEvent], tick_size: Decimal, window_ms: int, tolerance_ticks: int
) -> list[Closed]:
    """Pure recompute over stored prints (US-BIG-004 sc.2: "recomputes from stored prints
    immediately"); the same path as live, ending with a `flush`."""
    c = Clusterer(tick_size, window_ms, tolerance_ticks)
    out: list[Closed] = []
    for ev in sorted(events, key=lambda e: (e.ts_event, e.trade_id)):
        out.extend(c.add(ev))
    return out + c.flush()

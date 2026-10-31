"""LiquidityTracker - depth bands, a bounded per-bucket ring, reload / pulled detection (E21-T04).

Binding contract: 24-internal-schemas §2.11. Plain synchronous code (C-2.20): the caller samples
the book every `cadence_ms` (100 ms) and feeds prints; nothing here awaits, queries an
interpreter or reads the wall clock (every time is a caller-supplied `ts_us`).

Detection is L2-only inference, so every event is `estimated=True`. Per `(side, tick)`:
- the level's **baseline** is its highest size since the baseline was set; it is re-set to the
  current size after every consume or pull, and re-based on the previous sample once it is older
  than `reload_window_ms` (so a gradual consume 100 -> 70 -> 40 is one drop of 60 % from 100,
  never a later step measured from 40: the D6 carry of #4958);
- a size drop of at least `reload_consume_pct` of the baseline (the baseline at least
  `min_size`) is CONSUMED when the tape traded at or through that price within the window is at
  least `drop x tolerance_pct` (buys through an ask, sells through a bid), else PULLED;
- a consumed level that returns to at least `reload_replenish_pct` of its prior size within
  `reload_window_ms` is a RELOAD; `refill_count` counts the reload cycles at that price in the
  window. Window edges are inclusive.
- a sample while the book is not LIVE (or one-sided) is an estimated gap: pending state of every
  level is reset and nothing is emitted for the first live sample after it (BQ-4).
- one sample emits at most `max_events` events, nearest the mid first; the rest are reported as
  `LiquiditySample.overflow` for the caller to count (C-2.18), never published.

`distance_to_liquidity_cluster` (about 1.4 ms over the default 600-column window) is computed at
most once per sample and argument set: the first read after a sample computes and caches it, a
later read of the same sample returns the cache, and the next sample clears it (24 §7).

Memory: a preallocated ring, `buckets` rows x `ring_ms / cadence_ms` columns x (bid, ask)
float32, rows keyed by `bucket % buckets`; a row whose bucket changes is wiped. Default
200 x 6000 x 8 B = 9.6 MB. The ring is for series/clusters (float32); bands and detection use
the book's exact `Decimal` sizes."""

from __future__ import annotations

import hashlib
import uuid
from bisect import bisect_left, bisect_right
from collections import OrderedDict, deque
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from itertools import islice
from typing import Literal, Protocol, TypedDict

import numpy as np
import numpy.typing as npt

from candleviewer.book.models import BookPhase
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow.liquidity_models import (
    BandDepth,
    BookSide,
    LiquidityConfig,
    LiquidityPulled,
    LiquidityReload,
    LiquiditySample,
)

TAPE_MAX = 16_384  # prints kept per aggressor side (expiry queue); oldest dropped first
DEDUPE_MAX = 16_384  # trade ids remembered
_NONE_BUCKET = np.iinfo(np.int64).min

Level = tuple[int, Decimal]


class BookView(Protocol):
    """What the tracker reads of a book: `BookState.walk` (best first, `(price_ticks, qty)`)."""

    def walk(self, *, bids: bool) -> Iterator[Level]: ...


@dataclass(frozen=True, slots=True)
class LiquiditySeries:
    """One bucket's history, oldest first. NaN = not recorded (gap or before the bucket's row)."""

    ts_us: npt.NDArray[np.int64]
    bid: npt.NDArray[np.float32]
    ask: npt.NDArray[np.float32]
    estimated: npt.NDArray[np.bool_]


def _event_id(ts_us: int, *parts: str) -> EventId:
    """Deterministic UUIDv7-shaped id: sample-time ms + content hash (no randomness)."""
    rand = int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:10], "big")
    value = ((ts_us // 1000) & 0xFFFFFFFFFFFF) << 80 | rand
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    return EventId(uuid.UUID(int=(value & ~(0x3 << 62)) | (0x2 << 62)))


class _Envelope(TypedDict):
    event_id: EventId
    ts_event: int
    ts_ingest: int
    source: Literal["live", "replay"]
    symbol: str


class _Ring:
    """Preallocated `[column, row]` float32 matrices; one write head shared by every row."""

    def __init__(self, rows: int, cols: int) -> None:
        self.rows, self.cols = rows, cols
        self.bid = np.full((cols, rows), np.nan, dtype=np.float32)
        self.ask = np.full((cols, rows), np.nan, dtype=np.float32)
        self.ts = np.zeros(cols, dtype=np.int64)
        self.est = np.zeros(cols, dtype=np.bool_)
        self.row_bucket = np.full(rows, _NONE_BUCKET, dtype=np.int64)
        self.head = 0  # next column to write
        self.count = 0  # columns written, <= cols

    @property
    def nbytes(self) -> int:
        arrays = (self.bid, self.ask, self.ts, self.est, self.row_bucket)
        return sum(int(a.nbytes) for a in arrays)

    def assign_rows(self, lo: int) -> None:
        """Make rows own buckets `lo .. lo + rows`; a row that changes bucket is wiped."""
        buckets = np.arange(lo, lo + self.rows, dtype=np.int64)
        rows = buckets % self.rows
        stale = self.row_bucket[rows] != buckets
        if stale.any():
            idx = rows[stale]
            self.bid[:, idx] = np.nan
            self.ask[:, idx] = np.nan
            self.row_bucket[idx] = buckets[stale]

    def push(self, ts_us: int, estimated: bool) -> int:
        col = self.head
        self.ts[col], self.est[col] = ts_us, estimated
        self.head = (col + 1) % self.cols
        self.count = min(self.count + 1, self.cols)
        return col

    def last(self, n: int) -> npt.NDArray[np.intp]:
        """Column indices of the latest `n` samples, oldest first."""
        return (self.head - n + np.arange(n)) % self.cols


class LiquidityTracker:
    def __init__(
        self,
        symbol: str,
        tick_size: Decimal,
        qty_step: Decimal,
        config: LiquidityConfig | None = None,
        *,
        source: Literal["live", "replay"] = "live",
    ) -> None:
        self.config = (config or LiquidityConfig()).validated()
        self.symbol, self.tick_size, self.source = symbol, tick_size, source
        c = self.config
        self.min_size = c.min_size if c.min_size is not None else qty_step * 10
        self._window_us = c.reload_window_ms * 1000
        self._limits2 = [2 * b for b in c.bands_ticks]
        self._ring = _Ring(c.buckets, c.samples)
        self._prev: dict[BookSide, dict[int, Decimal]] = {"bid": {}, "ask": {}}
        self._pending: dict[tuple[BookSide, int], tuple[Decimal, int]] = {}
        self._cycles: dict[tuple[BookSide, int], list[int]] = {}
        # BQ-5: aggressor volume per (side, tick) inside the window, plus the FIFO that expires it
        self._tape_q: dict[str, deque[tuple[int, int, Decimal]]] = {"buy": deque(), "sell": deque()}
        self._tape_qty: dict[str, dict[int, Decimal]] = {"buy": {}, "sell": {}}
        self._tape_cum: dict[str, tuple[list[int], list[Decimal]]] = {}  # per-sample prefix sums
        # drops no print explains yet: held one sample for late prints (key -> prior, left, ts)
        self._suspect: dict[tuple[BookSide, int], tuple[Decimal, Decimal, int]] = {}
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._mid_bucket: int | None = None
        # D6: per-level drop baseline (highest size since it was set, and when it was set)
        self._base: dict[BookSide, dict[int, tuple[Decimal, int]]] = {"bid": {}, "ask": {}}
        self._distance: dict[tuple[BookSide | None, float, int], int | None] = {}
        self.distance_computes = 0  # cache misses (the call-once rule's evidence)

    # ---- inputs -----------------------------------------------------------------------

    def on_trade(self, ev: TradeEvent) -> None:
        """Record one print; a repeated `trade_id` counts once."""
        if ev.trade_id in self._seen:
            return
        self._seen[ev.trade_id] = None
        if len(self._seen) > DEDUPE_MAX:
            self._seen.popitem(last=False)
        side = ev.side
        self._expire_tape(side, ev.ts_event - self._window_us)
        q = self._tape_q[side]
        if len(q) >= TAPE_MAX:
            self._drop_oldest(side)
        q.append((ev.ts_event, ev.price_ticks, ev.qty))
        qty = self._tape_qty[side]
        qty[ev.price_ticks] = qty.get(ev.price_ticks, Decimal(0)) + ev.qty
        self._tape_cum.pop(side, None)

    def _drop_oldest(self, side: str) -> None:
        _, tick, q = self._tape_q[side].popleft()
        qty = self._tape_qty[side]
        left = qty[tick] - q
        if left > 0:
            qty[tick] = left
        else:
            del qty[tick]

    def _expire_tape(self, side: str, floor: int) -> None:
        q = self._tape_q[side]
        while q and q[0][0] < floor:
            self._drop_oldest(side)
            self._tape_cum.pop(side, None)

    def on_sample(self, ts_us: int, phase: BookPhase, book: BookView) -> LiquiditySample:
        """One book sample. Not LIVE (or a one-sided book) is an estimated gap, no events."""
        c = self.config
        self._distance.clear()
        bids = list(islice(book.walk(bids=True), c.max_levels)) if phase is BookPhase.LIVE else []
        asks = list(islice(book.walk(bids=False), c.max_levels)) if bids else []
        if not bids or not asks:
            self._reset()
            self._ring.push(ts_us, True)
            col = self._ring.last(1)[0]
            self._ring.bid[col, :] = np.nan
            self._ring.ask[col, :] = np.nan
            return LiquiditySample(ts_us, True, (), ())
        mid2 = bids[0][0] + asks[0][0]
        step, rows = c.bucket_ticks, c.buckets
        mid_bucket = (mid2 // 2) // step
        lo = mid_bucket - rows // 2
        self._ring.assign_rows(lo)
        col = self._ring.push(ts_us, False)
        bid_col = np.zeros(rows, dtype=np.float32)
        ask_col = np.zeros(rows, dtype=np.float32)
        bid_bins = self._scan(bids, mid2, -1, lo, bid_col)
        ask_bins = self._scan(asks, mid2, 1, lo, ask_col)
        self._ring.bid[col], self._ring.ask[col] = bid_col, ask_col
        self._mid_bucket = mid_bucket
        bands = self._bands(bid_bins, ask_bins)
        events: list[LiquidityReload | LiquidityPulled] = []
        had_state = bool(self._prev["bid"] or self._prev["ask"])
        self._expire(ts_us)
        self._tape_cum.clear()
        for tape_side in ("buy", "sell"):
            self._expire_tape(tape_side, ts_us - self._window_us)
        self._resolve_suspects(ts_us, events)
        self._detect("bid", bids, ts_us, events, had_state)
        self._detect("ask", asks, ts_us, events, had_state)
        overflow = len(events) - c.max_events
        if overflow > 0:  # keep the nearest the mid (C-2.18); the caller counts the rest
            dist = [abs(2 * ev.price_ticks - mid2) for ev in events]
            near = sorted(range(len(events)), key=lambda i: (dist[i], i))[: c.max_events]
            events = [events[i] for i in sorted(near)]
        return LiquiditySample(ts_us, False, bands, tuple(events), max(0, overflow))

    # ---- outputs ----------------------------------------------------------------------

    @property
    def memory_bytes(self) -> int:
        """Ring bytes (the gauge `liquidity_tracker_memory_bytes`); fixed at construction."""
        return self._ring.nbytes

    def series(self, price_bucket: int, window_ms: int | None = None) -> LiquiditySeries:
        """The bucket's samples within `window_ms` of the latest one (default: the whole ring).
        `price_bucket` = `price_ticks // bucket_ticks`. Empty if the bucket is not in the ring."""
        ring = self._ring
        empty = LiquiditySeries(
            np.zeros(0, np.int64),
            np.zeros(0, np.float32),
            np.zeros(0, np.float32),
            np.zeros(0, bool),
        )
        row = price_bucket % ring.rows
        if ring.count == 0 or ring.row_bucket[row] != price_bucket:
            return empty
        idx = ring.last(ring.count)
        ts = ring.ts[idx]
        if window_ms is not None:
            idx = idx[ts >= ts[-1] - window_ms * 1000]
        return LiquiditySeries(
            ring.ts[idx].copy(),
            ring.bid[idx, row].copy(),
            ring.ask[idx, row].copy(),
            ring.est[idx].copy(),
        )

    def distance_to_liquidity_cluster(
        self, side: BookSide | None = None, *, z: float = 2.0, window_columns: int = 600
    ) -> int | None:
        """Ticks from the mid to the nearest latest-sample cell with `heatmap_cluster_z >= z`
        (24 §7: size vs the non-zero distribution of the last `window_columns` samples).
        `None` when any of those samples is estimated (BQ-9), when there is no history,
        or when no cell qualifies. Call-once: cached per sample and argument set (module doc)."""
        key = (side, z, window_columns)
        if key in self._distance:
            return self._distance[key]
        if len(self._distance) >= 8:  # a bound on distinct argument sets per sample
            self._distance.clear()
        self.distance_computes += 1
        got = self._distance[key] = self._cluster_distance(side, z, window_columns)
        return got

    def _cluster_distance(self, side: BookSide | None, z: float, window_columns: int) -> int | None:
        ring = self._ring
        n = min(window_columns, ring.count)
        if n == 0 or self._mid_bucket is None:
            return None
        idx = ring.last(n)
        if ring.est[idx].any():
            return None
        mats = [m for s, m in (("bid", ring.bid), ("ask", ring.ask)) if side in (None, s)]
        window = np.concatenate([m[idx].ravel() for m in mats])
        nonzero = window[np.isfinite(window) & (window > 0)]
        if nonzero.size < 2:
            return None
        mean, std = float(nonzero.mean()), float(nonzero.std())
        if std == 0.0:
            return None
        best: int | None = None
        for m in mats:
            latest = m[idx[-1]]
            hit = np.isfinite(latest) & (latest > 0) & ((latest - mean) / std >= z)
            if hit.any():
                dist = int(np.abs(ring.row_bucket[hit] - self._mid_bucket).min())
                best = dist if best is None else min(best, dist)
        return None if best is None else best * self.config.bucket_ticks

    # ---- internals --------------------------------------------------------------------

    def _reset(self) -> None:
        self._prev = {"bid": {}, "ask": {}}
        self._pending.clear()
        self._suspect.clear()
        self._cycles.clear()
        self._base = {"bid": {}, "ask": {}}
        self._mid_bucket = None

    def _scan(
        self, levels: list[Level], mid2: int, sign: int, lo: int, col: npt.NDArray[np.float32]
    ) -> list[Decimal]:
        """Fill the ring column and bin sizes by band (distance to the mid, doubled: exact)."""
        step, rows, limits = self.config.bucket_ticks, self.config.buckets, self._limits2
        bins = [Decimal(0)] * (len(limits) + 1)
        for tick, qty in levels:
            bins[bisect_left(limits, sign * (2 * tick - mid2))] += qty
            bucket = tick // step
            if lo <= bucket < lo + rows:
                col[bucket % rows] += float(qty)
        return bins

    def _bands(self, bid_bins: list[Decimal], ask_bins: list[Decimal]) -> tuple[BandDepth, ...]:
        out: list[BandDepth] = []
        bid = ask = Decimal(0)
        for i, band in enumerate(self.config.bands_ticks):
            bid, ask = bid + bid_bins[i], ask + ask_bins[i]
            out.append(BandDepth(band, bid, ask, bid - ask))
        return tuple(out)

    def _expire(self, ts_us: int) -> None:
        w = self._window_us
        for key in [k for k, (_, t0) in self._pending.items() if ts_us - t0 > w]:
            del self._pending[key]
        for key in [k for k, v in self._cycles.items() if ts_us - v[-1] > w]:
            del self._cycles[key]

    def _detect(
        self,
        side: BookSide,
        levels: list[Level],
        ts_us: int,
        out: list[LiquidityReload | LiquidityPulled],
        had_state: bool,
    ) -> None:
        cur = dict(levels)
        prev = self._prev[side]
        far = levels[-1][0]
        if had_state:
            for tick, s0 in prev.items():
                in_range = tick >= far if side == "bid" else tick <= far
                if tick not in cur and in_range:
                    self._step(side, tick, s0, Decimal(0), ts_us, out)
            pending = self._pending
            for tick, s1 in cur.items():
                # a level consumed to zero and pending prior-size refill reappears from 0
                before = prev.get(tick, Decimal(0) if (side, tick) in pending else None)
                # an unchanged level outside a pending refill leaves its baseline as it was
                if before is not None and (s1 != before or (side, tick) in pending):
                    self._step(side, tick, before, s1, ts_us, out)
        base = self._base[side]
        for tick in [t for t in base if t not in cur]:
            del base[tick]  # a level that left the walked depth forgets its baseline
        self._prev[side] = cur

    def _step(
        self,
        side: BookSide,
        tick: int,
        s0: Decimal,
        s1: Decimal,
        ts_us: int,
        out: list[LiquidityReload | LiquidityPulled],
    ) -> None:
        c, key = self.config, (side, tick)
        pend = self._pending.get(key)
        if pend is not None:
            prior = pend[0]
            if s1 >= c.reload_replenish_pct * prior:
                del self._pending[key]
                cycles = [t for t in self._cycles.get(key, []) if ts_us - t <= self._window_us]
                cycles.append(ts_us)
                self._cycles[key] = cycles
                out.append(
                    LiquidityReload(
                        **self._envelope(ts_us, "reload", side, tick, len(cycles)),
                        side=side,
                        price=tick * self.tick_size,
                        price_ticks=tick,
                        prior_size=prior,
                        replenished_size=s1,
                        refill_count=len(cycles),
                    )
                )
            return
        bases = self._base[side]
        base = bases.get(tick)
        if base is None or ts_us - base[1] > self._window_us:
            base = (s0, ts_us)  # (re)based on the previous sample
        peak = max(base[0], s0)
        if s1 >= peak:
            bases[tick] = (s1, ts_us)
            return
        bases[tick] = (peak, base[1] if peak == base[0] else ts_us)
        drop = peak - s1
        if peak < self.min_size or drop < c.reload_consume_pct * peak:
            return
        bases[tick] = (s1, ts_us)  # an event re-sets the baseline
        traded = self._traded_through(side, tick)
        if traded >= drop * c.tolerance_pct:
            self._pending[key] = (peak, ts_us)
        else:
            # no print explains it yet: hold one sample for a late print (m1), then classify
            self._suspect[key] = (peak, s1, ts_us)

    def _resolve_suspects(self, ts_us: int, out: list[LiquidityReload | LiquidityPulled]) -> None:
        c = self.config
        for key, (prior, left, t0) in self._suspect.items():
            side, tick = key
            traded = self._traded_through(side, tick)
            if traded >= (prior - left) * c.tolerance_pct:
                self._pending[key] = (prior, t0)  # consumed after all: its window runs from t0
            else:
                out.append(
                    LiquidityPulled(
                        **self._envelope(t0, "pulled", side, tick, 0),
                        side=side,
                        price=tick * self.tick_size,
                        price_ticks=tick,
                        prior_size=prior,
                        remaining_size=left,
                        traded_qty=traded,
                    )
                )
        self._suspect.clear()

    def _traded_through(self, side: BookSide, tick: int) -> Decimal:
        """Aggressor volume at or through the level inside the window (buys lift an ask, sells
        hit a bid), from per-sample prefix sums over the tape's distinct ticks."""
        tape = "buy" if side == "ask" else "sell"
        cum = self._tape_cum.get(tape)
        if cum is None:
            ticks = sorted(self._tape_qty[tape])
            sums = [Decimal(0)]
            for t in ticks:
                sums.append(sums[-1] + self._tape_qty[tape][t])
            cum = self._tape_cum[tape] = (ticks, sums)
        ticks, sums = cum
        if side == "ask":
            return sums[-1] - sums[bisect_left(ticks, tick)]
        return sums[bisect_right(ticks, tick)]

    def _envelope(self, ts_us: int, kind: str, side: str, tick: int, n: int) -> _Envelope:
        return {
            "event_id": _event_id(ts_us, self.symbol, kind, side, str(tick), str(n)),
            "ts_event": ts_us,
            "ts_ingest": ts_us,
            "source": self.source,
            "symbol": self.symbol,
        }

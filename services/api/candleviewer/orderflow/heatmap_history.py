"""Recorded DOM heatmap history (E21-T03, #606): the engine behind `GET /market/heatmap`
(`22-api-openapi.yaml` `getHeatmap`, `24-internal-schemas.md` §6.3 "Read-time bucketing",
`21-database-schema.md` §4.12, §7).

`orderflow` may not import `storage` (CONSTITUTION §3), so the tiers are met structurally through
`HeatmapHistoryReader`: the composition root adapts QuestDB, the Parquet cold tier and the
recorded book readers to it. The engine never builds a path or SQL; it only asks the reader for
a symbol and a time range.

- **Cells.** Stored rows are native 100 ms columns, one tick a row (21 §4.12). A price reads back
  as `Decimal(str(x)).quantize(tick)` (24 §6.5) and is grouped to `price_grouping` ticks, sizes
  summed. A bucket's size is the sum over its native columns divided by their count, so a native
  column that was not stored counts 0; its `samples` sum theirs (NULL counts 1), and it is
  `estimated` if any is. A bucket with no row is `samples = 0` and empty, never interpolated.
- **Reconstruction.** Only when the window holds no stored cell: each minute of it seeks the
  newest recorded snapshot at or before the minute (the recorder forces one every 60 s) and rolls
  the deltas after it forward, sampling the book at every native deadline, windowed to `ROWS`
  around its mid. A snapshot whose stored checksum does not match is skipped for the one before
  it; one with none is used and its columns are `estimated`.
- **Range.** The response never starts before the bucket holding `first_available` (no empty
  leading columns); no recorded history is an empty answer with `history = "none"`.
- **Clamp and paging.** At most `MAX_COLUMNS` columns: the bucket is coarsened along `BUCKETS`
  (`clamped`); past 60 000 ms, or when the price span exceeds `ROWS` rows, the newest columns
  that fit are served and `remainder` names the older rest (newest first).
- **Downsample.** A span older than `DOWNSAMPLE_AGE_US` is 1 s data (21 §7): its segment states
  `max(bucket, 1000)` and its rows weigh the native columns they stand for.

The CPU folds run in a worker thread (`asyncio.to_thread`), one at a time, so the event loop
never aggregates; `checkpoint` is awaited between reads, so a caller can stop a read whose client
has gone, and a cancellation ends it at its next await.
"""

from __future__ import annotations

import asyncio
import zlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Literal, Protocol

import numpy as np
import numpy.typing as npt

from candleviewer.orderflow.heatmap import COLUMN_MS, HEATMAP_SNAPSHOT_MAX_COLUMNS, ROWS

type Normalize = Literal["none", "column", "window"]
type SegmentSource = Literal["hot", "cold", "reconstructed", "downsampled"]
type History = Literal["full", "partial", "none"]
type Level = tuple[Decimal, Decimal]

#: 22 `getHeatmap` `time_bucket_ms`, finest first: the clamp coarsens along it.
BUCKETS: Final = (100, 250, 500, 1000, 5000, 60000)
DEPTHS: Final = (50, 200, 500)
MAX_GROUPING: Final = 1000
#: 22 `getHeatmap` "Clamp and paging": the column cap is the snapshot's (23 §16.2).
MAX_COLUMNS: Final = HEATMAP_SNAPSHOT_MAX_COLUMNS
_US_PER_MS: Final = 1_000
#: 21 §7: `heatmap_cells` and `orderbook_deltas` older than this are 1 s data.
DOWNSAMPLE_AGE_US: Final = 180 * 86_400 * 1_000_000
DOWNSAMPLED_MS: Final = 1_000
#: The recorder forces a snapshot every 60 s (21 §4.3): reconstruction re-anchors a minute at a
#: time, and looks no further back than this for an anchor.
ANCHOR_STEP_US: Final = 60 * 1_000_000
ANCHOR_LOOKBACK_US: Final = 300 * 1_000_000
#: Snapshots skipped for a checksum mismatch before a minute is given up (left `samples = 0`).
MAX_ANCHOR_TRIES: Final = 4


class HeatmapQueryError(ValueError):
    """A query outside 22's parameter ranges; the HTTP edge validates first, so this is a bug."""


@dataclass(frozen=True, slots=True)
class CellRow:
    """One stored `heatmap_cells` row (21 §4.12); `samples`/`estimated` NULL before E21-T02."""

    ts_us: int
    price: float
    bid_size: float
    ask_size: float
    samples: int | None
    estimated: bool | None


@dataclass(frozen=True, slots=True)
class CellSpan:
    """The rows one tier served for `[lo_us, hi_us)`: a span with no row is still a span read."""

    lo_us: int
    hi_us: int
    tier: Literal["hot", "cold"]
    rows: Sequence[CellRow]


@dataclass(frozen=True, slots=True)
class BookAnchor:
    """A recorded `orderbook_snapshots` row (21 §4.3): levels best first, as stored."""

    ts_us: int
    update_id: int
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    checksum: int | None


@dataclass(frozen=True, slots=True)
class BookChange:
    """One recorded `orderbook_deltas` row (21 §4.2); `size == 0` removes the level."""

    ts_us: int
    update_id: int
    side: Literal["bid", "ask"]
    price: Decimal
    size: Decimal


class HeatmapHistoryReader(Protocol):
    """The tiers, as the engine reads them. Symbol and depth arrive validated."""

    async def first_available(self, symbol: str) -> int | None:
        """µs of the oldest recorded heatmap cell, book snapshot or delta; None if none (BQ-3)."""
        ...

    async def cells(self, symbol: str, lo_us: int, hi_us: int) -> Sequence[CellSpan]:
        """Stored cells in `[lo_us, hi_us)`, one span per tier read, oldest first."""
        ...

    async def book_anchor(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> BookAnchor | None:
        """The newest `depth` snapshot with `not_before_us <= ts <= at_us`."""
        ...

    async def book_changes(
        self, symbol: str, depth: int, lo_us: int, hi_us: int
    ) -> Sequence[BookChange]:
        """`depth` deltas in `[lo_us, hi_us)`, in recorded order."""
        ...


@dataclass(frozen=True, slots=True)
class HeatmapQuery:
    symbol: str
    from_us: int
    to_us: int
    time_bucket_ms: int = 1000
    price_grouping: int = 1
    depth: int = 200
    normalize: Normalize = "window"
    tick_size: Decimal = Decimal("0.1")


@dataclass(frozen=True, slots=True)
class Segment:
    lo_us: int
    hi_us: int
    source: SegmentSource
    resolution_ms: int


@dataclass(frozen=True, slots=True)
class HeatmapHistory:
    """A served page: `bid_matrix[i][j]` is `prices[i]` at `times_us[j]` (row-major)."""

    query: HeatmapQuery
    from_us: int
    to_us: int
    effective_bucket_ms: int
    times_us: tuple[int, ...]
    prices: tuple[Decimal, ...]
    bid_matrix: list[list[float]]
    ask_matrix: list[list[float]]
    max_value: float
    samples: tuple[int, ...]
    estimated_columns: tuple[bool, ...]
    first_available_us: int | None
    history: History
    segments: tuple[Segment, ...]
    clamped: bool
    #: The older rest of the window, `[lo, hi)`, that a cursor continues with; None when done.
    remainder: tuple[int, int] | None
    #: Snapshots used with no stored checksum (`heatmap_reconstruct_unverified_total`, BQ-4).
    unverified_anchors: int
    sources: frozenset[SegmentSource]

    @property
    def estimated(self) -> bool:
        return any(self.estimated_columns)


def book_checksum(bids: Sequence[Level], asks: Sequence[Level]) -> int:
    """24 §6.3: unsigned CRC32 of the stored `bids` text then the `asks` text, each the
    recorder's `[["price","size"],…]` in plain decimal text (`recorder/writer.py`)."""

    def side(levels: Sequence[Level]) -> str:
        return "[" + ",".join(f'["{p:f}","{q:f}"]' for p, q in levels) + "]"

    return zlib.crc32((side(bids) + side(asks)).encode())


def _validate(q: HeatmapQuery) -> None:
    if q.time_bucket_ms not in BUCKETS:
        raise HeatmapQueryError("time_bucket_ms is not one of 22's values")
    if not 1 <= q.price_grouping <= MAX_GROUPING:
        raise HeatmapQueryError("price_grouping is outside 1..1000")
    if q.depth not in DEPTHS:
        raise HeatmapQueryError("depth is not one of 22's values")
    if q.normalize not in ("none", "column", "window"):
        raise HeatmapQueryError("normalize is not one of 22's values")
    if q.to_us <= q.from_us:
        raise HeatmapQueryError("to must be after from")
    if not (q.tick_size.is_finite() and q.tick_size > 0):
        raise HeatmapQueryError("tick_size must be positive")


@dataclass(frozen=True, slots=True)
class _Plan:
    bucket_ms: int
    c0_us: int
    end_us: int
    clamped: bool
    remainder: tuple[int, int] | None


def _plan(q: HeatmapQuery, lo_us: int) -> _Plan:
    """The coarsest bucket needed to fit `MAX_COLUMNS`, and the newest page if none does."""
    for bucket in BUCKETS[BUCKETS.index(q.time_bucket_ms) :]:
        bus = bucket * _US_PER_MS
        c0, end = lo_us // bus * bus, -(-q.to_us // bus) * bus
        if (end - c0) // bus <= MAX_COLUMNS:
            return _Plan(bucket, c0, end, bucket != q.time_bucket_ms, None)
    start = end - MAX_COLUMNS * bus
    return _Plan(bucket, start, end, bucket != q.time_bucket_ms, (lo_us, start))


@dataclass(slots=True)
class _Page:
    first_col: int
    prices: tuple[Decimal, ...]
    bid: npt.NDArray[np.float64]
    ask: npt.NDArray[np.float64]


@dataclass(slots=True)
class _Grid:
    """Sizes by grouped tick and column; only ever touched by one worker thread at a time."""

    c0_us: int
    bucket_ms: int
    columns: int
    grouping: int
    tick: Decimal
    bid: dict[int, npt.NDArray[np.float64]] = field(default_factory=dict)
    ask: dict[int, npt.NDArray[np.float64]] = field(default_factory=dict)
    samples: list[int] = field(default_factory=list)
    estimated: list[bool] = field(default_factory=list)
    _seen: set[int] = field(default_factory=set)
    _ticks_f: dict[float, int] = field(default_factory=dict)
    _ticks_d: dict[Decimal, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.samples = [0] * self.columns
        self.estimated = [False] * self.columns

    @property
    def natives(self) -> int:
        return self.bucket_ms // COLUMN_MS

    def _col(self, ts_us: int) -> int:
        col = (ts_us - self.c0_us) // (self.bucket_ms * _US_PER_MS)
        return col if 0 <= col < self.columns else -1

    def _ticks_of_decimal(self, price: Decimal) -> int:
        ticks = self._ticks_d.get(price)
        if ticks is None:
            ticks = int(price.quantize(self.tick) / self.tick)
            self._ticks_d[price] = ticks
        return ticks

    def _ticks_of_float(self, price: float) -> int:
        """24 §6.5: a stored DOUBLE reads back as `Decimal(str(x)).quantize(tick)`."""
        ticks = self._ticks_f.get(price)
        if ticks is None:
            ticks = self._ticks_of_decimal(Decimal(str(price)))
            self._ticks_f[price] = ticks
        return ticks

    def _add(self, gticks: int, col: int, bid: float, ask: float) -> None:
        for side, size in ((self.bid, bid), (self.ask, ask)):
            if size:
                row = side.get(gticks)
                if row is None:
                    row = side[gticks] = np.zeros(self.columns)
                row[col] += size

    def fold_cells(self, rows: Sequence[CellRow], downsampled_before_us: int) -> None:
        natives, grouping = self.natives, self.grouping
        coarse = min(DOWNSAMPLED_MS, self.bucket_ms) // COLUMN_MS
        for r in rows:
            col = self._col(r.ts_us)
            if col < 0:
                continue
            if r.ts_us not in self._seen:  # a column's samples repeat on each of its rows
                self._seen.add(r.ts_us)
                held = 1 if r.samples is None else r.samples
                self.samples[col] = min(natives, self.samples[col] + held)
                self.estimated[col] = self.estimated[col] or bool(r.estimated)
            weight = (coarse if r.ts_us < downsampled_before_us else 1) / natives
            g = self._ticks_of_float(r.price) // grouping * grouping
            self._add(g, col, r.bid_size * weight, r.ask_size * weight)

    def fold_book(
        self, anchor: BookAnchor, changes: Sequence[BookChange], lo_us: int, hi_us: int
    ) -> None:
        """Roll `anchor` forward through `changes`, sampling the book at each native deadline of
        `[lo_us, hi_us)` (24 §6.3 "Read-time bucketing")."""
        books = {"bid": dict(anchor.bids), "ask": dict(anchor.asks)}
        later = [c for c in changes if c.update_id > anchor.update_id]
        step = COLUMN_MS * _US_PER_MS
        at, i = -(-lo_us // step) * step, 0
        while at < hi_us:
            while i < len(later) and later[i].ts_us <= at:
                c = later[i]
                if c.size:
                    books[c.side][c.price] = c.size
                else:
                    books[c.side].pop(c.price, None)
                i += 1
            self._sample(at, books["bid"], books["ask"], anchor.checksum is None)
            at += step

    def _sample(
        self, at_us: int, bids: dict[Decimal, Decimal], asks: dict[Decimal, Decimal], est: bool
    ) -> None:
        col = self._col(at_us)
        if col < 0 or not (bids or asks):
            return
        tops = (max(bids, default=None), min(asks, default=None))
        best = [self._ticks_of_decimal(p) for p in tops if p is not None]
        mid, half, g = sum(best) // len(best), ROWS // 2 * self.grouping, self.grouping
        for price, size in bids.items():
            t = self._ticks_of_decimal(price)
            if -half <= t - mid < half:  # the window of `ROWS` rows around the mid (24 §6.2)
                self._add(t // g * g, col, float(size) / self.natives, 0.0)
        for price, size in asks.items():
            t = self._ticks_of_decimal(price)
            if -half <= t - mid < half:
                self._add(t // g * g, col, 0.0, float(size) / self.natives)
        self.samples[col] = min(self.natives, self.samples[col] + 1)
        self.estimated[col] = self.estimated[col] or est

    def page(self) -> _Page:
        """The newest columns whose price span fits `ROWS` rows, as dense `[price][time]`."""
        ticks = sorted(set(self.bid) | set(self.ask))
        if not ticks:
            return _Page(0, (), np.zeros((0, self.columns)), np.zeros((0, self.columns)))
        zero = np.zeros(self.columns)
        bid = np.vstack([self.bid.get(t, zero) for t in ticks])
        ask = np.vstack([self.ask.get(t, zero) for t in ticks])
        held = (bid > 0) | (ask > 0)
        lo_g = hi_g = None
        first_col = 0
        for col in range(self.columns - 1, -1, -1):
            rows = np.flatnonzero(held[:, col])
            if not rows.size:
                continue
            new_lo, new_hi = ticks[rows[0]], ticks[rows[-1]]
            if lo_g is not None and hi_g is not None:
                new_lo, new_hi = min(lo_g, new_lo), max(hi_g, new_hi)
                if (new_hi - new_lo) // self.grouping + 1 > ROWS:
                    first_col = col + 1
                    break
            lo_g, hi_g = new_lo, new_hi
        if lo_g is None or hi_g is None:  # unreachable: `ticks` holds a level some column has
            lo_g = hi_g = ticks[0]
        if (hi_g - lo_g) // self.grouping + 1 > ROWS:  # one bucket wider than the cap: centre it
            centre = (lo_g + hi_g) // 2 // self.grouping * self.grouping
            lo_g = centre - ROWS // 2 * self.grouping
            hi_g = lo_g + (ROWS - 1) * self.grouping
        axis = range(lo_g, hi_g + self.grouping, self.grouping)
        index = {t: i for i, t in enumerate(ticks)}
        dense_bid = np.zeros((len(axis), self.columns - first_col))
        dense_ask = np.zeros_like(dense_bid)
        for r, t in enumerate(axis):
            i = index.get(t)
            if i is not None:
                dense_bid[r] = bid[i, first_col:]
                dense_ask[r] = ask[i, first_col:]
        prices = tuple((Decimal(t) * self.tick).quantize(self.tick) for t in axis)
        return _Page(first_col, prices, dense_bid, dense_ask)


def _normalize(
    page: _Page, mode: Normalize
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], float]:
    """22 `normalize`: `window` scales by the window's largest cell, `column` by each column's;
    `max_value` is always the largest raw cell."""
    bid, ask = page.bid, page.ask
    peak = float(max(bid.max(initial=0.0), ask.max(initial=0.0)))
    if mode == "window" and peak > 0:
        return bid / peak, ask / peak, peak
    if mode == "column" and bid.size:
        top = np.maximum(bid.max(axis=0), ask.max(axis=0))
        scale = np.where(top > 0, top, 1.0)
        return bid / scale, ask / scale, peak
    return bid, ask, peak


def _segments(
    pieces: Sequence[tuple[int, int, SegmentSource]],
    lo_us: int,
    hi_us: int,
    bucket_ms: int,
    downsampled_before_us: int,
) -> tuple[Segment, ...]:
    """The served range's spans, clipped, split at the downsample boundary, adjacent equals
    merged, oldest first."""
    out: list[Segment] = []
    for a, b, source in sorted(pieces):
        a, b = max(a, lo_us), min(b, hi_us)
        cut = min(max(downsampled_before_us, a), b)
        parts: list[tuple[int, int, SegmentSource, int]] = [
            (a, cut, "downsampled", max(bucket_ms, DOWNSAMPLED_MS)),
            (cut, b, source, bucket_ms),
        ]
        for lo, hi, src, res in parts:
            if hi <= lo:
                continue
            if out and out[-1].source == src and out[-1].hi_us == lo:
                out[-1] = Segment(out[-1].lo_us, hi, src, res)
            else:
                out.append(Segment(lo, hi, src, res))
    return tuple(out)


def _empty(q: HeatmapQuery, first_us: int | None) -> HeatmapHistory:
    """No recorded history in the window: empty axes and matrices, `history = "none"`."""
    return HeatmapHistory(
        q, q.from_us, q.to_us, q.time_bucket_ms, (), (), [], [], 0.0, (), (), first_us,
        "none", (), False, None, 0, frozenset(),
    )  # fmt: skip


async def _checkpoint(checkpoint: Callable[[], Awaitable[None]] | None) -> None:
    if checkpoint is not None:
        await checkpoint()


async def _anchor(reader: HeatmapHistoryReader, q: HeatmapQuery, at_us: int) -> BookAnchor | None:
    """The newest snapshot at or before `at_us` whose stored checksum, if any, matches (BQ-4)."""
    not_before = at_us - ANCHOR_LOOKBACK_US
    for _ in range(MAX_ANCHOR_TRIES):
        found = await reader.book_anchor(q.symbol, q.depth, at_us, not_before_us=not_before)
        if found is None:
            return None
        if found.checksum is None or found.checksum == book_checksum(found.bids, found.asks):
            return found
        at_us = found.ts_us - 1
        if at_us < not_before:
            return None
    return None


async def _reconstruct(
    reader: HeatmapHistoryReader,
    q: HeatmapQuery,
    grid: _Grid,
    checkpoint: Callable[[], Awaitable[None]] | None,
) -> int:
    """Rebuild the grid's window from the recorded book a minute at a time; the number of
    snapshots used with no stored checksum."""
    unverified = 0
    end = grid.c0_us + grid.columns * grid.bucket_ms * _US_PER_MS
    for lo in range(grid.c0_us, end, ANCHOR_STEP_US):
        hi = min(lo + ANCHOR_STEP_US, end)
        await _checkpoint(checkpoint)
        anchor = await _anchor(reader, q, lo)
        if anchor is None:
            continue  # no book recorded for this minute: its columns stay samples = 0
        changes = await reader.book_changes(q.symbol, q.depth, anchor.ts_us, hi)
        unverified += anchor.checksum is None
        await asyncio.to_thread(grid.fold_book, anchor, changes, lo, hi)
    return unverified


async def read_heatmap_history(
    reader: HeatmapHistoryReader,
    q: HeatmapQuery,
    *,
    now_us: int,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> HeatmapHistory:
    """One page of `GET /market/heatmap` (module docstring). `checkpoint` is awaited between
    storage reads (a disconnected client raises there); cancellation ends it at its next await."""
    _validate(q)
    first = await reader.first_available(q.symbol)
    lo = q.from_us if first is None else max(q.from_us, first)
    if first is None or lo >= q.to_us:
        return _empty(q, first)
    plan = _plan(q, lo)
    bus = plan.bucket_ms * _US_PER_MS
    columns = (plan.end_us - plan.c0_us) // bus
    grid = _Grid(plan.c0_us, plan.bucket_ms, columns, q.price_grouping, q.tick_size)
    downsampled_before = now_us - DOWNSAMPLE_AGE_US
    await _checkpoint(checkpoint)
    spans = await reader.cells(q.symbol, plan.c0_us, plan.end_us)
    pieces: list[tuple[int, int, SegmentSource]] = []
    unverified = 0
    if any(span.rows for span in spans):
        for span in spans:
            await _checkpoint(checkpoint)
            await asyncio.to_thread(grid.fold_cells, span.rows, downsampled_before)
            pieces.append((span.lo_us, span.hi_us, span.tier))
    else:  # BQ-3: the recorded book only where no cell was stored
        unverified = await _reconstruct(reader, q, grid, checkpoint)
        pieces.append((plan.c0_us, plan.end_us, "reconstructed"))
    page = await asyncio.to_thread(grid.page)
    bid, ask, peak = await asyncio.to_thread(_normalize, page, q.normalize)
    c0 = plan.c0_us + page.first_col * bus
    remainder = (lo, c0) if c0 > lo else None
    segments = _segments(pieces, c0, plan.end_us, plan.bucket_ms, downsampled_before)
    return HeatmapHistory(
        query=q,
        from_us=c0,
        to_us=plan.end_us,
        effective_bucket_ms=plan.bucket_ms,
        times_us=tuple(range(c0, plan.end_us, bus)),
        prices=page.prices,
        bid_matrix=bid.tolist(),
        ask_matrix=ask.tolist(),
        max_value=peak,
        samples=tuple(grid.samples[page.first_col :]),
        estimated_columns=tuple(grid.estimated[page.first_col :]),
        first_available_us=first,
        history="partial" if first > q.from_us else "full",
        segments=segments,
        clamped=plan.clamped,
        remainder=remainder,
        unverified_anchors=unverified,
        sources=frozenset(s.source for s in segments),
    )


__all__ = [
    "BUCKETS",
    "DOWNSAMPLE_AGE_US",
    "MAX_COLUMNS",
    "BookAnchor",
    "BookChange",
    "CellRow",
    "CellSpan",
    "HeatmapHistory",
    "HeatmapHistoryReader",
    "HeatmapQuery",
    "HeatmapQueryError",
    "Segment",
    "book_checksum",
    "read_heatmap_history",
]

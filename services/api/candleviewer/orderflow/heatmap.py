"""The DOM heatmap (E21-T02, #605; `24-internal-schemas.md` §6, `23-ws-protocol.md` §3.4 kind 6,
§3.6, §6.1, §8.2, §14.5, §16.2; `21-database-schema.md` §4.12): the `HeatmapEngine`'s columns
and the `heatmap.{symbol}` topic that publishes them.

`orderflow` may not import `ws` or `storage` (CONSTITUTION §3), so the hub, the gateway's
snapshot body and kind-6 part constructors, the book stream's depth demand and the
`heatmap_cells` store are met structurally and injected (`ws_wiring.heatmap_topic`). Plain
asyncio on the hot path, never a statechart (C-2.20): the book is read through the engine's plain
published state (`phase`, `depth`, `book`).

- **Time.** One clock in epoch milliseconds. Native deadlines fall every `COLUMN_MS` (100 ms) on
  the epoch grid; a spec's buckets fall every `time_bucket_ms` on the same grid. A deadline closed
  more than one native column late is missed (a stall): it counts no sample and
  `heatmap_missing_columns_total` (24 §6.3). A column's `samples` is the native deadlines of its
  bucket that the engine met with a book; its native count is the deadlines in the bucket,
  `time_bucket_ms / 100` (2 or 3 at 250 ms: the bucket's own deadlines, 23 §14.5).
- **Integration (24 §6.2, `time_weighted`).** Every interval between two observations is
  integrated level by level, size x ms, and divided by the column's length (`Σ size·dt /
  column_ms`), so a level that rested 5 ms of 100 weighs 5 %. Time the engine missed or had no
  book is not integrated, and reads as missing samples.
- **Window.** At its close a column is centred on the mid (`rows // 2` steps below it, on the
  spec's `price_grouping` grid), summing sizes into rows; what falls outside is the off-window
  totals. A price gap thus re-centres the next column, and the buckets the engine had no book for
  are empty `samples = 0` columns, never stretched (24 §6.3). Rows are trimmed to the populated
  span, never past `ROWS` (G-07a).
- **Resync.** While a book that was LIVE is not, the last levels read stand in for at most
  `RESYNC_ESTIMATE_MS`, and every column closed during the resync is `estimated` (24 §6.3), the
  ones past the hold too (empty). The phase is read at every deadline. Estimated columns never
  reach the `liquidity` consumer (the rules side).
- **Specs (G-02).** One state per (symbol, `depth`, `price_grouping`, `time_bucket_ms`), shared
  by its leases, a ring of at most `HEATMAP_SNAPSHOT_MAX_COLUMNS` columns; at most
  `HEATMAP_MAX_SPECS_PER_SYMBOL` a symbol and `HEATMAP_MAX_SPECS_PER_SERVER` a server
  (`subscription_limit`, `HeatmapSpecCapError`). A depth-500 spec demands the symbol's 500 tier
  (`DepthDemand`, as `book.X.500` does) and integrates nothing until the tier holds 500.
- **Ready.** A spec's subscriptions stay `snapshot_pending` until it is ready: the instrument
  steps known, the tier as deep as the spec, and its seed done; then they are flushed. A new spec
  whose grouping a held spec of the same depth and bucket divides is seeded from that spec's
  newest columns (at most the G-03 frame bound), re-bucketed a slice per loop turn
  (`SEED_TURN_S`), never inside the `sub` (24 §6.3); otherwise it starts empty and older columns
  come from REST (E21-T03).
- **Snapshot (G-03).** The newest columns that fit all of `window_seconds`, the column cap, half
  the queue's bytes (48 + 16 x rows a column) and half its frames, oldest first; kind 6 beside it
  only when every column is complete (23 §14.5) and its scales are known and fit. Each column's
  kind-6 part is built and packed (encoded once) at its close and cached on its ring entry, so a
  binary snapshot is a slice of cached parts that the gateway re-encodes header only.
- **Storage.** Each native column with a populated row is queued for the injected store, bounded
  by cells (`STORE_CELLS_MAX`, oldest dropped and logged); a size that is negative or not finite
  is never written (24 §6.5).
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import itertools
import math
import time
from array import array
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Context, Decimal
from typing import Any, Final, Protocol

import numpy as np
import structlog

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.book.resync import BookEngine
from candleviewer.bus import Bus, QueuePolicy, StreamInvalidated, TopicPattern
from candleviewer.bus import Subscription as BusSubscription
from candleviewer.bus.models import WILDCARD
from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from candleviewer.observability.context import spawn
from candleviewer.orderflow import heatmap_metrics as hm

FAMILY: Final = "heatmap"
#: 24 §6.1 `HeatmapGridSpec.column_ms`: the native column, the engine's sampling deadline.
COLUMN_MS: Final = 100
#: 24 §6.1 `rows`, 23 §16.2 (G-07a): the most rows a column carries.
ROWS: Final = 512
#: 23 §16.2 (G-02): live specs a symbol, and a server, may hold.
HEATMAP_MAX_SPECS_PER_SYMBOL: Final = 4
HEATMAP_MAX_SPECS_PER_SERVER: Final = 32
#: 23 §16.2 (G-03): the column cap of a snapshot, and of a spec's ring.
HEATMAP_SNAPSHOT_MAX_COLUMNS: Final = 2000
#: 23 §3.4: a kind-6 frame's header (24 B) and column prefix (24 B), and one row.
COLUMN_FRAME_BYTES: Final = 48
ROW_BYTES: Final = 16
#: 23 §6.1: the option defaults (`time_bucket_ms`: the server fallback, §6.1.1).
DEFAULT_BUCKET_MS: Final = 500
DEFAULT_DEPTH: Final = 200
DEFAULT_GROUPING: Final = 1
DEFAULT_WINDOW_S: Final = 900
#: A spec this deep demands the symbol's deep tier (E21-T01's 500, `heatmap_depth_500`).
DEEP_DEPTH: Final = 500
#: How long the last levels of a book that left LIVE stand in for it (estimated, 24 §6.3).
RESYNC_ESTIMATE_MS: Final = 5_000
#: The bus queue, drained at every wake: only a stuck loop fills it.
BUS_QUEUE_MAX: Final = 16_384
#: Cells waiting for the store: 262 144 is 512 full columns (~18 MiB of tuples), about a minute of
#: ten symbols; past it the oldest columns are shed and logged (C-2.18).
STORE_CELLS_MAX: Final = 262_144
#: Bound on one store write; a slower store loses that column (logged), never the loop.
STORE_TIMEOUT_S: Final = 5.0
#: Bound on draining the store queue at `stop`.
STOP_DRAIN_S: Final = 5.0
#: CPU a loop turn spends re-bucketing seeds, so a turn stays inside budget #6 (20 ms).
SEED_TURN_S: Final = 0.005
_U64_MAX: Final = 2**64 - 1
_I64_MIN: Final = -(2**63)
_I64_MAX: Final = 2**63 - 1
#: Enough digits for any float's exact value (at most 767 significant) after a scale shift.
_EXACT: Final = Context(prec=1100, rounding=ROUND_HALF_EVEN)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class HeatmapSpecCapError(Exception):
    """A spec past a G-02 cap (23 §16.2): refused `subscription_limit`, nothing held. The message
    names the cap, never another user's specs (HM-I04)."""


@dataclass(frozen=True, slots=True)
class HeatmapSpec:
    """23 §6.1 (G-02): what a spec's state is keyed by (not `window_seconds`, `throttle_ms`)."""

    symbol: str
    depth: int = DEFAULT_DEPTH
    price_grouping: int = DEFAULT_GROUPING
    time_bucket_ms: int = DEFAULT_BUCKET_MS


def spec_of(symbol: str, opts: Mapping[str, Any]) -> HeatmapSpec:
    """A subscription's spec from its validated options, the §6.1 defaults filled in."""
    return HeatmapSpec(
        symbol,
        int(opts.get("depth", DEFAULT_DEPTH)),
        int(opts.get("price_grouping", DEFAULT_GROUPING)),
        int(opts.get("time_bucket_ms", DEFAULT_BUCKET_MS)),
    )


@dataclass(frozen=True, slots=True)
class HeatmapLease:
    """What one live `heatmap.*` subscription holds."""

    consumer: str
    spec: HeatmapSpec


@dataclass(frozen=True, slots=True)
class HeatmapColumn:
    """24 §6.1 `HeatmapColumn`: row `i` is the price `price_origin_ticks + i * price_step_ticks`
    (in ticks) and its sizes are time-weighted averages (`float`, C3). `expected` is the bucket's
    native count, so the column is complete (23 §14.5) when `samples` reaches it."""

    ts_ms: int
    bucket_ms: int
    price_origin_ticks: int
    price_step_ticks: int
    bid_sizes: array[float]
    ask_sizes: array[float]
    best_bid_ticks: int | None
    best_ask_ticks: int | None
    off_window_bid_qty: float
    off_window_ask_qty: float
    estimated: bool
    samples: int
    expected: int

    @property
    def rows(self) -> int:
        return len(self.bid_sizes)

    @property
    def full(self) -> bool:
        """Every native deadline of the bucket was sampled."""
        return self.samples >= self.expected

    @property
    def binary_ok(self) -> bool:
        """Kind 6 can say everything about it (23 §3.4, §14.5): complete, no off-window total."""
        return self.full and self.off_window_bid_qty == 0 and self.off_window_ask_qty == 0

    @property
    def wire_bytes(self) -> int:
        """Its kind-6 frame's size (23 §6.1, G-03), whatever the encoding."""
        return COLUMN_FRAME_BYTES + ROW_BYTES * self.rows


def native_count(start_ms: int, end_ms: int) -> int:
    """The native deadlines in the bucket `[start, end)`: those in `(start, end]`."""
    return end_ms // COLUMN_MS - start_ms // COLUMN_MS


def _mid(best_bid: int | None, best_ask: int | None) -> int | None:
    if best_bid is not None and best_ask is not None:
        return (best_bid + best_ask) // 2
    return best_bid if best_bid is not None else best_ask


def _origin(mid: int, step: int) -> int:
    """24 §6.2 step 3, on the step's grid so a coarser step's rows hold whole finer rows."""
    return ((mid - (ROWS // 2) * step) // step) * step


def window_column(
    *,
    ts_ms: int,
    bucket_ms: int,
    step: int,
    bids: Mapping[int, float],
    asks: Mapping[int, float],
    best_bid: int | None,
    best_ask: int | None,
    estimated: bool,
    samples: int,
    expected: int,
    off_bid: float = 0.0,
    off_ask: float = 0.0,
    origin_hint: int = 0,
) -> HeatmapColumn:
    """One column from per-tick sizes (24 §6.2 steps 3-4): rows around the mid, sizes in a row
    summed, the rest in the off-window totals; trimmed to the populated rows. Without a sample
    the column is empty (24 §6.3). A column with no row never sits below price 0."""
    mid = _mid(best_bid, best_ask)
    origin = _origin(mid, step) if mid is not None else (origin_hint // step) * step
    if samples == 0:
        return HeatmapColumn(ts_ms, bucket_ms, max(0, origin), step, array("d"), array("d"),
                             best_bid, best_ask, 0.0, 0.0, estimated, 0, expected)  # fmt: skip
    rows_b, rows_a = array("d", bytes(8 * ROWS)), array("d", bytes(8 * ROWS))
    for levels, rows, side in ((bids, rows_b, 0), (asks, rows_a, 1)):
        off = 0.0
        for price, size in levels.items():
            i = (price - origin) // step
            if 0 <= i < ROWS:
                rows[i] += size
            else:
                off += size
        if side == 0:
            off_bid += off
        else:
            off_ask += off
    first = next((i for i in range(ROWS) if rows_b[i] or rows_a[i]), ROWS)
    last = next((i for i in range(ROWS - 1, -1, -1) if rows_b[i] or rows_a[i]), -1)
    lowest = origin + first * step if first <= last else max(0, origin)
    return HeatmapColumn(
        ts_ms, bucket_ms, lowest, step, rows_b[first : last + 1], rows_a[first : last + 1],
        best_bid, best_ask, off_bid, off_ask, estimated, samples, expected,
    )  # fmt: skip


def rebucket(column: HeatmapColumn, step: int) -> HeatmapColumn:
    """`column` on the coarser `step`, which its own step divides (24 §6.3): each row summed into
    the row of its price, re-centred on the column's mid; what leaves the window joins the
    off-window totals."""
    if step % column.price_step_ticks:
        raise ValueError("the column's step does not divide the new step")
    rows = range(column.rows)
    prices = [column.price_origin_ticks + i * column.price_step_ticks for i in rows]
    return window_column(
        ts_ms=column.ts_ms, bucket_ms=column.bucket_ms, step=step,
        bids=dict(zip(prices, column.bid_sizes, strict=True)),
        asks=dict(zip(prices, column.ask_sizes, strict=True)),
        best_bid=column.best_bid_ticks, best_ask=column.best_ask_ticks,
        estimated=column.estimated, samples=column.samples, expected=column.expected,
        off_bid=column.off_window_bid_qty, off_ask=column.off_window_ask_qty,
        origin_hint=column.price_origin_ticks,
    )  # fmt: skip


#: Below this a float product `size * 10^scale` is within one part in 2^52 of the exact one, so
#: its rounding equals the exact rounding unless it lies this close to a tie (relative).
_FAST_LIMIT: Final = 2.0**52
_TIE_MARGIN: Final = 1e-9


def _exact_scaled(size: float, qty_scale: int) -> int | None:
    n = int(Decimal(size).scaleb(qty_scale, _EXACT).to_integral_value(ROUND_HALF_EVEN, _EXACT))
    return n if n <= _U64_MAX else None


def scaled_size(size: float, qty_scale: int) -> int | None:
    """24 §6.5: `round(size * 10^qty_scale)`, ties to even, from the float's exact value; None
    when it is not a `u64` (negative, not finite, or too large). The float product decides
    unless it is near a tie or large, where the exact `Decimal` value does."""
    if not math.isfinite(size) or size < 0:
        return None
    scaled = size * 10.0**qty_scale
    if scaled < _FAST_LIMIT:
        fraction = scaled - math.floor(scaled)
        if abs(fraction - 0.5) > _TIE_MARGIN * max(1.0, scaled):
            return round(scaled)
    return _exact_scaled(size, qty_scale)


def scaled_sizes(sizes: Sequence[float], qty_scale: int) -> list[int] | None:
    """`scaled_size` of each of `sizes` (a column side: kind 6's hot path), or None when one is
    no `u64`; the same results, vectorised. `numpy.rint` rounds the float product half to even,
    as `round` does, and a value near a tie, large or not finite takes `scaled_size`'s exact
    path, one by one."""
    values = np.asarray(sizes, dtype=np.float64)
    if values.size == 0:
        return []
    with np.errstate(invalid="ignore", over="ignore"):
        scaled = values * 10.0**qty_scale
        fast = np.isfinite(scaled) & (scaled >= 0.0) & (scaled < _FAST_LIMIT)
        distance = np.abs(scaled - np.floor(scaled) - 0.5)
        fast &= distance > _TIE_MARGIN * np.maximum(1.0, scaled)
        out: list[int] = np.where(fast, np.rint(scaled), 0.0).astype(np.int64).tolist()
    for i in np.flatnonzero(~fast).tolist():
        n = scaled_size(float(values[i]), qty_scale)
        if n is None:
            return None
        out[i] = n
    return out


def places(step: Decimal) -> int:
    """Decimal places of an instrument step: `0.10` -> 1, `0.001` -> 3, `5` -> 0."""
    exponent = step.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


# -- the engine's state ---------------------------------------------------------------------------


class HeatmapSub(Protocol):
    """The fields of a WS `Subscription` read here."""

    @property
    def ch(self) -> str: ...
    @property
    def replay_session_id(self) -> str | None: ...
    @property
    def snapshot_pending(self) -> bool: ...
    @property
    def effective(self) -> Mapping[str, Any]: ...
    @property
    def heatmap_lease(self) -> HeatmapLease | None: ...


class Hub(Protocol):
    """`SequencingHub`'s calls the topic makes."""

    def publish(
        self,
        ch: str,
        body: Mapping[str, Any] | None = ...,
        *,
        part: Any = ...,
        coalesced_count: int = ...,
        select: Callable[[Any], bool] | None = ...,
    ) -> int: ...

    def flush_pending(self, match: Callable[[Any], bool] | None = ...) -> int: ...


class HeatmapStore(Protocol):
    """`heatmap_cells` (21 §4.12): one native column's populated rows, `(price, bid, ask)`."""

    async def write_column(
        self,
        symbol: str,
        ts_us: int,
        cells: Sequence[tuple[float, float, float]],
        *,
        estimated: bool,
        samples: int,
        off_window_bid_qty: float,
        off_window_ask_qty: float,
    ) -> None: ...

    async def close(self) -> None: ...


class DepthDemand(Protocol):
    """The book stream's per-depth demand (`BookStream.acquire_depth` / `release`, E21-T01)."""

    def acquire_depth(self, consumer: str, symbol: str, depth: int) -> None: ...

    def release(self, consumer: str, symbol: str) -> None: ...


#: The gateway's kind-6 part: `(ts_ms, price_min, price_step, rows, price_scale, qty_scale,
#: estimated)`, every value scaled (`ws.binary.Frame`).
PartFactory = Callable[[int, int, int, tuple[tuple[int, int], ...], int, int, bool], Any]
#: The gateway's snapshot body: `(structured, parts, price_scale=, qty_scale=, estimated=)`.
BodyFactory = Callable[..., Any]
#: A symbol's `(tick_size, qty_step)` from the instrument catalogue; None when unknown.
Steps = Callable[[str], tuple[Decimal, Decimal] | None]
#: The rules side's read of live liquidity: native columns that are not estimated, only.
Liquidity = Callable[[str, HeatmapColumn], None]
#: The consumer name a deep spec's tier demand is held under.
DEEP_CONSUMER: Final = "ws:heatmap:500"


@dataclass(slots=True)
class _Levels:
    """The top `depth` levels per side of the book as last read, sizes as floats (C3)."""

    bids: dict[int, float]
    asks: dict[int, float]
    best_bid: int | None
    best_ask: int | None


class _Integrator:
    """Σ size x ms per price over one bucket (24 §6.2 step 2)."""

    __slots__ = ("asks", "bids", "estimated", "t")

    def __init__(self, t: float) -> None:
        self.bids: dict[int, float] = {}
        self.asks: dict[int, float] = {}
        self.estimated = False
        self.t = t

    def run(self, levels: _Levels | None, to: float) -> None:
        """Integrate `levels` from the last time to `to`; None skips the interval (no sample)."""
        dt = to - self.t
        if dt <= 0:
            return
        self.t = to
        if levels is None:
            return
        for held, side in ((self.bids, levels.bids), (self.asks, levels.asks)):
            for price, size in side.items():
                held[price] = held.get(price, 0.0) + size * dt

    def averages(self, span_ms: int) -> tuple[dict[int, float], dict[int, float]]:
        """24 §6.2: `Σ size·dt / column_ms`, the column being `span_ms` long."""
        return (
            {p: v / span_ms for p, v in self.bids.items()},
            {p: v / span_ms for p, v in self.asks.items()},
        )


@dataclass(slots=True)
class _Entry:
    """A ring column with its kind-6 part, built (and packed: encoded once) per instrument steps.
    The §14.5 form is not kept: 1 024 floats a column as Python objects are ~32 KiB, four times the
    packed part, so it is built when a structured reader asks (23 §6.1, budget #8)."""

    column: HeatmapColumn
    steps: tuple[Decimal, Decimal] | None = None
    part: Any = None


@dataclass(slots=True)
class _SpecState:
    spec: HeatmapSpec
    start: int  # the open bucket's start, epoch ms
    acc: _Integrator
    ring: deque[_Entry]
    samples: int = 0
    consumers: set[str] = field(default_factory=set)
    version: int = 0
    origin: int = 0  # the last column's origin: an empty column keeps it
    waiting: bool = True  # leased subscriptions may be pending until it is ready
    seed: deque[HeatmapColumn] | None = None  # donor columns still to re-bucket, newest first

    @property
    def end(self) -> int:
        return self.start + self.spec.time_bucket_ms


def _spec_state(
    spec: HeatmapSpec, now: float, ring: int = HEATMAP_SNAPSHOT_MAX_COLUMNS
) -> _SpecState:
    start = int(now) // spec.time_bucket_ms * spec.time_bucket_ms
    return _SpecState(spec, start, _Integrator(now), deque(maxlen=ring))


@dataclass(slots=True)
class _SymbolState:
    symbol: str
    deadline: int  # the next native deadline, epoch ms
    native: _SpecState  # the stored column: 100 ms, one tick a row
    specs: dict[HeatmapSpec, _SpecState] = field(default_factory=dict)
    levels: dict[int, _Levels] = field(default_factory=dict)  # per depth, as last read
    live: bool = False
    seen_live: bool = False  # it was LIVE once: not LIVE now is a resync, not a cold start
    left_ms: float | None = None  # when the book left LIVE (levels then stand in for it)
    tier: int = 0  # the engine's depth when last LIVE

    def all(self) -> list[_SpecState]:
        return [self.native, *self.specs.values()]


def _read(eng: BookEngine, depth: int) -> _Levels | None:
    book = eng.book
    if book is None:
        return None
    bids = {p: float(q) for p, q in itertools.islice(book.walk(bids=True), depth)}
    asks = {p: float(q) for p, q in itertools.islice(book.walk(bids=False), depth)}
    return _Levels(bids, asks, max(bids, default=None), min(asks, default=None))


def _is_live(eng: BookEngine | None) -> bool:
    return eng is not None and eng.phase is BookPhase.LIVE and eng.book is not None


def _price(ticks: int, tick: Decimal) -> str:
    return format(Decimal(ticks) * tick, "f")


def wire_column(column: HeatmapColumn, tick: Decimal) -> dict[str, Any]:
    """23 §14.5's column: `samples` only below the native count and the off-window totals only
    when non-zero (BQ-8); `complete` is true, as a column is published once, at its close."""
    out: dict[str, Any] = {
        "t_ms": column.ts_ms,
        "price_min": _price(column.price_origin_ticks, tick),
        "price_step": _price(column.price_step_ticks, tick),
        "bids": column.bid_sizes.tolist(),
        "asks": column.ask_sizes.tolist(),
        "complete": True,
    }
    if not column.full:
        out["samples"] = column.samples
    if column.off_window_bid_qty > 0:
        out["off_window_bid_qty"] = column.off_window_bid_qty
    if column.off_window_ask_qty > 0:
        out["off_window_ask_qty"] = column.off_window_ask_qty
    return out


def _bounded[T](
    ring: Sequence[T],
    size: Callable[[T], int],
    *,
    window_seconds: int,
    bucket_ms: int,
    queue_bytes: int,
    queue_frames: int,
) -> list[T]:
    limit = min(
        math.ceil(window_seconds * 1000 / bucket_ms),
        HEATMAP_SNAPSHOT_MAX_COLUMNS,
        queue_frames // 2,
    )
    budget, used = queue_bytes // 2, 0
    out: list[T] = []
    for item in reversed(ring):
        cost = size(item)
        if len(out) >= limit or used + cost > budget:
            break
        used += cost
        out.append(item)
    out.reverse()
    return out


def snapshot_columns(
    ring: Sequence[HeatmapColumn],
    *,
    window_seconds: int,
    bucket_ms: int,
    queue_bytes: int,
    queue_frames: int,
) -> list[HeatmapColumn]:
    """G-03 (23 §6.1): the newest columns that fit `window_seconds` of buckets, the column cap,
    half the queue's bytes and half its frames, oldest first. The walk stops at the first bound,
    so no column is built that the frame would drop (HM-D02)."""
    return _bounded(ring, lambda c: c.wire_bytes, window_seconds=window_seconds,
                    bucket_ms=bucket_ms, queue_bytes=queue_bytes,
                    queue_frames=queue_frames)  # fmt: skip


def _leased(sub: Any, spec: HeatmapSpec) -> bool:
    lease = getattr(sub, "heatmap_lease", None)
    return lease is not None and lease.spec == spec


def _waiting(sub: Any, spec: HeatmapSpec) -> bool:
    return _leased(sub, spec) and bool(sub.snapshot_pending)


def _stopped(task: asyncio.Task[None]) -> None:
    """A loop that ends other than by `stop` says so: from then on no heatmap column goes out."""
    if not task.cancelled() and (exc := task.exception()) is not None:
        _log().error("heatmap_topic_stopped", error=type(exc).__name__)


@dataclass(frozen=True, slots=True)
class _Cells:
    """One native column as the store takes it."""

    symbol: str
    ts_us: int
    cells: tuple[tuple[float, float, float], ...]
    estimated: bool
    samples: int
    off_bid: float
    off_ask: float


class HeatmapTopic:
    """The `HeatmapEngine` and the `heatmap` family's leases, snapshot source and publisher
    (module docstring), for the event loop that runs the gateway and the book stream: no locks."""

    def __init__(
        self,
        hub: Hub,
        *,
        engine: Callable[[str], BookEngine | None],
        steps: Steps,
        part: PartFactory,
        body: BodyFactory,
        bus: Bus,
        env: str,
        queue_bytes: int,
        queue_frames: int,
        store: HeatmapStore | None = None,
        liquidity: Liquidity | None = None,
        demand: DepthDemand | None = None,
        clock_ms: Callable[[], float] = lambda: time.time() * 1000.0,
        max_specs_per_symbol: int = HEATMAP_MAX_SPECS_PER_SYMBOL,
        max_specs_per_server: int = HEATMAP_MAX_SPECS_PER_SERVER,
        seed_turn_s: float = SEED_TURN_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._hub, self._engine, self._steps, self._part, self._body = (
            hub,
            engine,
            steps,
            part,
            body,
        )
        self._bus, self._env, self._store, self._liquidity = bus, env, store, liquidity
        self._demand, self._seed_turn_s = demand, seed_turn_s
        self._queue_bytes, self._queue_frames = queue_bytes, queue_frames
        self._clock, self._sleep = clock_ms, sleep
        self._max_symbol, self._max_server = max_specs_per_symbol, max_specs_per_server
        self._symbols: dict[str, _SymbolState] = {}
        self._dirty: set[str] = set()
        self._consumers = 0
        self._stored: deque[_Cells] = deque()
        self._stored_cells = 0
        self._shed = 0  # store columns dropped since the last log
        self._wake = asyncio.Event()
        self._closing = False
        self._sub: BusSubscription | None = None
        self._task: asyncio.Task[None] | None = None
        self._writer: asyncio.Task[None] | None = None

    # -- leases (`ConnectionAuthz`) --------------------------------------------------------------

    def hold(self, consumer: str, spec: HeatmapSpec) -> HeatmapLease:
        """A lease on `spec` for a new subscription, or `HeatmapSpecCapError` with nothing held.
        O(levels) at most: a re-bucketing seed is only queued here (`_seed_turn`)."""
        self._check(spec, None)
        self._take(spec).consumers.add(consumer)
        self._count(+1)
        return HeatmapLease(consumer, spec)

    def check_retune(self, lease: HeatmapLease, spec: HeatmapSpec) -> None:
        """Whether a `ctl` may move `lease` to `spec` (23 §5.4), as `hold` checks a new one."""
        if spec != lease.spec:
            self._check(spec, lease)

    def retune(self, lease: HeatmapLease, spec: HeatmapSpec) -> HeatmapLease:
        """Move `lease` to `spec` once `check_retune` passed: the new spec is taken first, so a
        coarser grouping can be seeded from the old one's columns (24 §6.3)."""
        if spec == lease.spec:
            return lease
        self.check_retune(lease, spec)
        self._take(spec).consumers.add(lease.consumer)
        self._free(lease)
        return HeatmapLease(lease.consumer, spec)

    def release(self, lease: HeatmapLease) -> None:
        self._free(lease)
        self._count(-1)

    def _check(self, spec: HeatmapSpec, moving: HeatmapLease | None) -> None:
        st = self._symbols.get(spec.symbol)
        if st is not None and spec in st.specs:
            return
        freed = None
        if moving is not None:  # its spec goes if it is the last lease on it
            held = self._symbols.get(moving.spec.symbol)
            spec_state = None if held is None else held.specs.get(moving.spec)
            if spec_state is not None and spec_state.consumers == {moving.consumer}:
                freed = moving.spec
        on_symbol = 0 if st is None else len(st.specs)
        on_symbol -= 1 if freed is not None and freed.symbol == spec.symbol else 0
        total = sum(len(s.specs) for s in self._symbols.values()) - (freed is not None)
        if on_symbol >= self._max_symbol:
            raise HeatmapSpecCapError(
                f"At most {self._max_symbol} heatmap specs per symbol are served."
            )
        if total >= self._max_server:
            raise HeatmapSpecCapError(f"At most {self._max_server} heatmap specs are served.")

    def _take(self, spec: HeatmapSpec) -> _SpecState:
        now = self._clock()
        st = self._symbols.get(spec.symbol)
        if st is None:
            native = _spec_state(HeatmapSpec(spec.symbol, spec.depth, 1, COLUMN_MS), now, ring=0)
            st = _SymbolState(spec.symbol, int(now) // COLUMN_MS * COLUMN_MS + COLUMN_MS, native)
            self._symbols[spec.symbol] = st
            self._dirty.add(spec.symbol)
        state = st.specs.get(spec)
        if state is None:
            self._advance(st, now)  # close what is due first, as it was
            self._integrate(st, now, ok=True)  # the others' open buckets up to now
            deep = self._deep(st)
            state = st.specs[spec] = _spec_state(spec, now)
            if spec.depth >= DEEP_DEPTH and not deep:
                self._call_demand("acquire", spec.symbol)
            self._seed(st, state)
            self._native_depth(st)
            self._observe(st, now)
        return state

    def _seed(self, st: _SymbolState, state: _SpecState) -> None:
        """24 §6.3: a new spec is seeded from the newest columns (at most the G-03 frame bound)
        of a held one of its depth and bucket whose step divides its own; the re-bucketing runs a
        slice per loop turn (`_seed_turn`). Else it starts empty (older columns: REST, E21-T03)."""
        spec = state.spec
        alike = [
            s
            for s in st.specs.values()
            if s is not state
            and s.spec.depth == spec.depth
            and s.spec.time_bucket_ms == spec.time_bucket_ms
            and s.ring
        ]
        if not alike:
            return  # nothing held to re-bucket: a fresh spec, not a re-bucketing event
        donors = [s for s in alike if spec.price_grouping % s.spec.price_grouping == 0]
        if not donors:
            _log().info("heatmap_rebucket", symbol=spec.symbol, new_step=spec.price_grouping,
                        strategy="none", columns=0)  # fmt: skip
            return
        donor = max(donors, key=lambda s: s.spec.price_grouping)
        cap = min(HEATMAP_SNAPSHOT_MAX_COLUMNS, max(1, self._queue_frames // 2))
        state.seed = deque(e.column for e in itertools.islice(reversed(donor.ring), cap))
        _log().info("heatmap_rebucket", symbol=spec.symbol, old_step=donor.spec.price_grouping,
                    new_step=spec.price_grouping, strategy="native_columns",
                    columns=len(state.seed))  # fmt: skip

    def _seed_turn(self) -> int:
        """Re-bucket queued seeds, newest first, for at most `seed_turn_s` of CPU (at least one
        column); a spec whose seed is done becomes ready. The columns re-bucketed."""
        began, done = time.perf_counter(), 0
        for st in self._symbols.values():
            for state in st.specs.values():
                seed = state.seed
                if seed is None:
                    continue
                steps = self._steps(st.symbol)
                while seed and len(state.ring) < (state.ring.maxlen or 0):
                    if done and time.perf_counter() - began > self._seed_turn_s:
                        return done
                    entry = _Entry(rebucket(seed.popleft(), state.spec.price_grouping))
                    if steps is not None:
                        self._fill(entry, steps)
                    state.ring.appendleft(entry)
                    done += 1
                state.seed = None
                state.version += 1
        return done

    def _free(self, lease: HeatmapLease) -> None:
        st = self._symbols.get(lease.spec.symbol)
        state = None if st is None else st.specs.get(lease.spec)
        if st is None or state is None:
            return
        state.consumers.discard(lease.consumer)
        if not state.consumers:
            del st.specs[lease.spec]
            self._native_depth(st)
            if lease.spec.depth >= DEEP_DEPTH and not self._deep(st):
                self._call_demand("release", lease.spec.symbol)
        if not st.specs:
            del self._symbols[lease.spec.symbol]
            self._dirty.discard(lease.spec.symbol)

    @staticmethod
    def _deep(st: _SymbolState) -> bool:
        return any(s.depth >= DEEP_DEPTH for s in st.specs)

    def _call_demand(self, what: str, symbol: str) -> None:
        """A deep spec holds the symbol's deep tier (as `book.X.500` does); a refusal (an
        unlisted symbol) leaves its subscriptions pending, never the loop faulted."""
        if self._demand is None:
            return
        try:
            if what == "acquire":
                self._demand.acquire_depth(DEEP_CONSUMER, symbol, DEEP_DEPTH)
            else:
                self._demand.release(DEEP_CONSUMER, symbol)
        except Exception as exc:
            _log().warning("heatmap_depth_demand_failed", symbol=symbol, op=what,
                           error=type(exc).__name__)  # fmt: skip

    def _count(self, delta: int) -> None:
        self._consumers = max(0, self._consumers + delta)
        hm.heatmap_subscriptions_active.set(self._consumers)

    @staticmethod
    def _native_depth(st: _SymbolState) -> None:
        """The stored column holds the deepest depth any spec of the symbol reads."""
        depth = max((s.depth for s in st.specs), default=st.native.spec.depth)
        if depth != st.native.spec.depth:
            st.native.spec = HeatmapSpec(st.symbol, depth, 1, COLUMN_MS)

    # -- the engine ------------------------------------------------------------------------------

    def _usable(self, st: _SymbolState, t: float) -> bool:
        """A book (LIVE, or its last levels within `RESYNC_ESTIMATE_MS` of leaving LIVE)."""
        if st.live:
            return bool(st.levels)
        if st.left_ms is None or t - st.left_ms > RESYNC_ESTIMATE_MS:
            st.levels.clear()
            return False
        return bool(st.levels)

    @staticmethod
    def _deep_enough(st: _SymbolState, state: _SpecState) -> bool:
        """The tier holds the spec's depth (the stored column reads what the tier holds)."""
        return state is st.native or st.tier >= state.spec.depth

    def _integrate(self, st: _SymbolState, to: float, *, ok: bool) -> None:
        usable = ok and self._usable(st, to)
        resync = st.seen_live and not st.live
        for state in st.all():
            if resync and to > state.acc.t:
                state.acc.estimated = True  # closed during a resync: estimated, held or not
            fed = usable and self._deep_enough(st, state)
            state.acc.run(st.levels.get(state.spec.depth) if fed else None, to)

    def _observe(self, st: _SymbolState, now: float) -> None:
        """Integrate up to `now` on the levels held, then read the book: LIVE, its top levels
        per depth in use; else it is resyncing and the last levels stand in (estimated)."""
        self._integrate(st, now, ok=True)
        eng = self._engine(st.symbol)
        if eng is not None and _is_live(eng):
            st.live, st.seen_live, st.left_ms, st.tier = True, True, None, eng.depth
            for depth in {s.spec.depth for s in st.all()}:
                levels = _read(eng, depth)
                if levels is not None:
                    st.levels[depth] = levels
            return
        self._left(st, now)

    @staticmethod
    def _left(st: _SymbolState, at: float) -> None:
        if st.live or (st.left_ms is None and st.levels):
            st.left_ms = at
        st.live = False

    def _advance(self, st: _SymbolState, now: float) -> int:
        """Close every native deadline and bucket up to `now`, in time order; the columns sent.
        The book's phase is read at each step, so a resync is never integrated as live."""
        if now - st.deadline > HEATMAP_SNAPSHOT_MAX_COLUMNS * COLUMN_MS:
            self._skip(st, now)  # a clock jump or a very long stall: no catch-up per column
        sent = 0
        while True:
            states = st.all()
            t = min(st.deadline, *(s.end for s in states))
            if t > now:
                return sent
            if st.live and not _is_live(self._engine(st.symbol)):
                self._left(st, st.native.acc.t)
            deadline = st.deadline
            on_time = now < deadline + COLUMN_MS
            self._integrate(st, t, ok=on_time)
            if t == deadline:
                sampled = on_time and self._usable(st, t)
                if not on_time:
                    hm.missing(st.symbol)
                for state in states:
                    state.samples += sampled and self._deep_enough(st, state)
                st.deadline += COLUMN_MS
            for state in states:
                if state.end == t:
                    sent += self._close(st, state, now)

    def _skip(self, st: _SymbolState, now: float) -> None:
        """Jump the symbol to `now`: the deadlines between were missed (counted), and no column
        is built for them; the gap reads `samples = 0` (21 §4.12)."""
        missed = (int(now) - st.deadline) // COLUMN_MS + 1
        hm.missing(st.symbol, missed)
        _log().warning("heatmap_engine_skipped", symbol=st.symbol, missed=missed)
        st.deadline = int(now) // COLUMN_MS * COLUMN_MS + COLUMN_MS
        for state in st.all():
            state.start = int(now) // state.spec.time_bucket_ms * state.spec.time_bucket_ms
            state.acc, state.samples = _Integrator(now), 0

    def _close(self, st: _SymbolState, state: _SpecState, now: float) -> int:
        spec, end = state.spec, state.end
        bids, asks = state.acc.averages(spec.time_bucket_ms)
        levels = st.levels.get(spec.depth)
        column = window_column(
            ts_ms=state.start, bucket_ms=spec.time_bucket_ms, step=spec.price_grouping,
            bids=bids, asks=asks,
            best_bid=None if levels is None else levels.best_bid,
            best_ask=None if levels is None else levels.best_ask,
            estimated=state.acc.estimated, samples=state.samples,
            expected=native_count(state.start, end), origin_hint=state.origin,
        )  # fmt: skip
        state.start, state.acc, state.samples, state.origin = (
            end,
            _Integrator(end),
            0,
            column.price_origin_ticks,
        )
        if state is st.native:
            self._native(st.symbol, column)
            return 0
        entry = _Entry(column)
        state.ring.append(entry)
        state.version += 1
        return self._publish(st, state, entry, now)

    def _fill(self, entry: _Entry, steps: tuple[Decimal, Decimal]) -> None:
        """Build the entry's kind-6 part once for these steps (columns never change; an
        instrument revision changes the steps and rebuilds it)."""
        if entry.steps == steps:
            return
        column = entry.column
        entry.part = self._frame(column, steps) if column.binary_ok else None
        entry.steps = steps

    def _publish(self, st: _SymbolState, state: _SpecState, entry: _Entry, now: float) -> int:
        steps = self._steps(st.symbol)
        if steps is None or not state.consumers:
            return 0  # its subscriptions wait for the steps (`build`), then snap
        self._fill(entry, steps)
        spec, column = state.spec, entry.column
        body = {
            "symbol": spec.symbol, "time_bucket_ms": spec.time_bucket_ms,
            "price_grouping": spec.price_grouping, "depth": spec.depth,
            "columns": [wire_column(column, steps[0])], "estimated": column.estimated,
        }  # fmt: skip
        try:
            sent = self._hub.publish(
                f"{FAMILY}.{spec.symbol}", body, part=entry.part, coalesced_count=1,
                select=lambda sub: _leased(sub, spec),
            )  # fmt: skip
        except Exception as exc:  # contained: the other specs and symbols go on
            _log().error("heatmap_topic_publish_failed", error=type(exc).__name__)
            return 0
        hm.EMITTED["estimated" if column.estimated else "live"].inc()
        hm.heatmap_column_publish_latency_ms.observe(max(0.0, self._clock() - column.ts_ms
                                                         - column.bucket_ms))  # fmt: skip
        return sent

    def _frame(self, column: HeatmapColumn, steps: tuple[Decimal, Decimal]) -> Any | None:
        """The column's kind-6 part (23 §3.4, 24 §6.5), or None when a value does not fit."""
        tick, qty_step = steps
        ps, qs = places(tick), places(qty_step)
        unit = int(tick.scaleb(ps))
        price_min, price_step = column.price_origin_ticks * unit, column.price_step_ticks * unit
        if not (_I64_MIN <= price_min <= _I64_MAX and 0 < price_step <= _I64_MAX):
            return None
        bids, asks = scaled_sizes(column.bid_sizes, qs), scaled_sizes(column.ask_sizes, qs)
        if bids is None or asks is None:
            return None
        return self._part(column.ts_ms, price_min, price_step, tuple(zip(bids, asks, strict=True)),
                          ps, qs, column.estimated)  # fmt: skip

    def _native(self, symbol: str, column: HeatmapColumn) -> None:
        """The stored column: to the rules side when it is live data, to the store when a row is
        populated (21 §4.12: no empty column is stored)."""
        if column.samples == 0:
            return
        if not column.estimated and self._liquidity is not None:
            try:
                self._liquidity(symbol, column)
            except Exception as exc:  # the rules side's fault is its own
                _log().error("heatmap_liquidity_failed", error=type(exc).__name__)
        steps = self._steps(symbol)
        if self._store is None or steps is None or column.rows == 0:
            return
        cells: list[tuple[float, float, float]] = []
        faults = 0
        for i, (bid, ask) in enumerate(zip(column.bid_sizes, column.ask_sizes, strict=True)):
            if not (math.isfinite(bid) and math.isfinite(ask) and bid >= 0 and ask >= 0):
                faults += 1  # 24 §6.5: never written, a producer fault
                continue
            if bid or ask:
                price = column.price_origin_ticks + i * column.price_step_ticks
                cells.append((float(Decimal(price) * steps[0]), bid, ask))
        if faults:
            hm.heatmap_cell_faults_total.inc(faults)
        off_b, off_a = column.off_window_bid_qty, column.off_window_ask_qty
        if not (math.isfinite(off_b) and math.isfinite(off_a) and off_b >= 0 and off_a >= 0):
            hm.heatmap_cell_faults_total.inc()
            return
        if not cells:
            return
        self._stored.append(_Cells(symbol, column.ts_ms * 1000, tuple(cells), column.estimated,
                                   column.samples, off_b, off_a))  # fmt: skip
        self._stored_cells += len(cells)
        while self._stored_cells > STORE_CELLS_MAX and len(self._stored) > 1:
            self._stored_cells -= len(self._stored.popleft().cells)
            self._shed += 1
        self._wake.set()

    # -- SnapshotSource --------------------------------------------------------------------------

    def _held(
        self, sub: HeatmapSub
    ) -> tuple[_SymbolState, _SpecState, tuple[Decimal, Decimal]] | None:
        lease = sub.heatmap_lease
        st = None if lease is None else self._symbols.get(lease.spec.symbol)
        state = None if lease is None or st is None else st.specs.get(lease.spec)
        steps = None if lease is None else self._steps(lease.spec.symbol)
        if st is None or state is None or steps is None:
            return None
        return st, state, steps

    def _ready(self, st: _SymbolState, state: _SpecState) -> bool:
        """Its snapshot can be built: the steps known, the tier as deep as the spec, no seed."""
        return (
            state.seed is None
            and st.tier >= state.spec.depth
            and self._steps(st.symbol) is not None
        )

    def build(self, sub: HeatmapSub) -> Any | None:
        """The spec's columns that G-03 allows, a slice of cached entries; kind 6 beside them on
        a binary subscription when every one is complete and fits (23 §3.4, §14.5). None (the
        subscription stays pending, then is flushed) while the spec is not ready."""
        held = self._held(sub)
        if held is None:
            return None  # a replay one, not leased, or waiting for the steps: it stays pending
        st, state, steps = held
        if not self._ready(st, state):
            state.waiting = True
            return None
        spec = state.spec
        entries = _bounded(
            state.ring,
            lambda e: e.column.wire_bytes,
            window_seconds=int(sub.effective.get("window_seconds", DEFAULT_WINDOW_S)),
            bucket_ms=spec.time_bucket_ms,
            queue_bytes=self._queue_bytes,
            queue_frames=self._queue_frames,
        )
        for entry in entries:
            self._fill(entry, steps)  # a no-op but after a steps change
        parts: tuple[Any, ...] = ()
        if sub.effective.get("encoding") == "binary" and all(e.part is not None for e in entries):
            parts = tuple(e.part for e in entries)
        # A binary snapshot sends its parts only: its structured side carries what the gateway
        # reads of it (each column's bucket and that it is complete, §8.2), not 1 024 floats a
        # column it would never send. A structured one gets every §14.5 column.
        tick = steps[0]
        columns = (
            [{"t_ms": e.column.ts_ms, "complete": True} for e in entries]
            if parts
            else [wire_column(e.column, tick) for e in entries]
        )
        structured = {
            "symbol": spec.symbol, "time_bucket_ms": spec.time_bucket_ms,
            "price_grouping": spec.price_grouping, "depth": spec.depth, "columns": columns,
        }  # fmt: skip
        return self._body(structured, parts, price_scale=places(steps[0]),
                          qty_scale=places(steps[1]),
                          estimated=any(e.column.estimated for e in entries))  # fmt: skip

    def generation(self, sub: HeatmapSub) -> int:
        held = self._held(sub)
        return 0 if held is None else held[1].version

    def continuity(self, sub: HeatmapSub, from_ts_ms: int | None) -> bool:
        return False  # the ring is no delta history the hub can prove (§7.6)

    # -- the book's events -----------------------------------------------------------------------

    def offer(self, item: object) -> None:
        """One bus item: a book event or status of a symbol, or the overflow marker."""
        if isinstance(item, StreamInvalidated):
            self._dirty.update(self._symbols)  # a flush reads the live book: no state is lost
        elif isinstance(item, BookDelta | BookSnapshot | BookStatus):
            if item.symbol in self._symbols:
                self._dirty.add(item.symbol)

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
        """A slice of the seeds, then close what is due on the clock, read the books that
        changed and flush the subscriptions of the specs that became ready; the frames sent."""
        self._seed_turn()
        now, sent = self._clock(), 0
        for symbol, st in list(self._symbols.items()):
            try:
                sent += self._advance(st, now)
                if symbol in self._dirty:
                    self._observe(st, now)
                for state in list(st.specs.values()):
                    if state.waiting and self._ready(st, state):
                        state.waiting = False
                        match = functools.partial(_waiting, spec=state.spec)
                        sent += self._hub.flush_pending(match)
            except Exception as exc:  # contained to its symbol: the others go on
                _log().error("heatmap_topic_symbol_failed", symbol=symbol,
                             error=type(exc).__name__)  # fmt: skip
        self._dirty.clear()
        if self._shed:
            _log().warning("heatmap_store_queue_full", dropped=self._shed)
            self._shed = 0
        return sent

    def next_due(self) -> float | None:
        """The clock (epoch ms) of the earliest deadline or bucket end, now while a seed is
        queued; None with no symbol."""
        due: list[float] = [
            min(st.deadline, *(s.end for s in st.all())) for st in self._symbols.values()
        ]
        if any(s.seed for st in self._symbols.values() for s in st.specs.values()):
            due.append(self._clock())
        return min(due) if due else None

    # -- lifecycle (`WsRuntime`) -----------------------------------------------------------------

    def open(self) -> None:
        """Hold the bus topic of the books (idempotent); `pump` drains it."""
        if self._sub is None:
            pattern = TopicPattern(env=self._env, domain="md", symbol=WILDCARD, detail="book")
            self._sub = self._bus.subscribe(
                "ws-heatmap-topic", pattern, QueuePolicy.INVALIDATE_ON_FULL, maxsize=BUS_QUEUE_MAX
            )

    def start(self) -> None:
        self.open()
        self._closing = False
        if self._task is None:
            self._task = spawn(self._run(), name="ws-heatmap-topic")
            self._task.add_done_callback(_stopped)
        if self._writer is None and self._store is not None:
            self._writer = spawn(self._write(), name="heatmap-cells-writer")
            self._writer.add_done_callback(_stopped)

    async def stop(self) -> None:
        """Stop building columns, drain what the store has queued (bounded), close the store."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})
        writer, self._writer = self._writer, None
        if writer is not None:
            self._closing = True
            self._wake.set()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(STOP_DRAIN_S):
                    await asyncio.wait({writer})
            writer.cancel()
            await asyncio.wait({writer})
        if self._store is not None:
            try:
                async with asyncio.timeout(STOP_DRAIN_S):
                    await self._store.close()
            except Exception as exc:  # a store that cannot close never holds the shutdown
                _log().warning("heatmap_store_close_failed", error=type(exc).__name__)
        sub, self._sub = self._sub, None
        if sub is not None:
            self._bus.unsubscribe(sub)

    async def _run(self) -> None:
        while (sub := self._sub) is not None:
            due = self.next_due()
            wait = 0.1 if due is None else max(0.0, (due - self._clock()) / 1000.0)
            try:
                if wait > 0:
                    with contextlib.suppress(TimeoutError):
                        async with asyncio.timeout(wait):
                            self.offer(await sub.get())
                else:  # a turn that runs late still yields: it never starves the event loop
                    await asyncio.sleep(0)
                self.pump()
                self.tick()
            except Exception as exc:  # never let one bad turn stop every heatmap column
                _log().error("heatmap_topic_turn_failed", error=type(exc).__name__)
                await self._sleep(COLUMN_MS / 1000.0)

    async def _write(self) -> None:
        """The store's one writer: queued columns in order, each write bounded."""
        store = self._store
        while store is not None:
            await self._wake.wait()
            self._wake.clear()
            while self._stored:
                c = self._stored.popleft()
                self._stored_cells -= len(c.cells)
                try:
                    async with asyncio.timeout(STORE_TIMEOUT_S):
                        await store.write_column(
                            c.symbol, c.ts_us, c.cells, estimated=c.estimated,
                            samples=c.samples, off_window_bid_qty=c.off_bid,
                            off_window_ask_qty=c.off_ask,
                        )  # fmt: skip
                except Exception as exc:  # that column is lost (logged); the next is written
                    _log().warning("heatmap_store_write_failed", error=type(exc).__name__)
            if self._closing:
                return


__all__ = [
    "COLUMN_MS",
    "DEEP_DEPTH",
    "FAMILY",
    "HEATMAP_MAX_SPECS_PER_SERVER",
    "HEATMAP_MAX_SPECS_PER_SYMBOL",
    "HEATMAP_SNAPSHOT_MAX_COLUMNS",
    "ROWS",
    "DepthDemand",
    "HeatmapColumn",
    "HeatmapLease",
    "HeatmapSpec",
    "HeatmapSpecCapError",
    "HeatmapStore",
    "HeatmapSub",
    "HeatmapTopic",
    "native_count",
    "rebucket",
    "scaled_size",
    "scaled_sizes",
    "snapshot_columns",
    "spec_of",
    "window_column",
    "wire_column",
]

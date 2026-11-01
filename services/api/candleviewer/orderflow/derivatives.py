"""The derivatives engine (E24-T04): the one producer of the 24 §7.2 *Derivatives* metrics.

Pure: plain rows in (the bar grid, OI samples, ticker snapshots, settled funding, liquidation
prints, instrument metadata), per-bar `BarMetrics` out. No HTTP, socket or store code, and no
exchange knowledge (C-2.2). Every consumer reads a value through `metric_value`, so a pane, a
`/market/metrics` query and a rule condition read the same number.

Semantics (bars are half-open `[start_ms, end_ms)`, all times exchange ms UTC):
- OI resamples onto the grid last-value-at-or-before with `OI_STALENESS_MS`: `OI(close)` is the
  last sample inside the bar, `OI(open)` the last at or before its start within the bound, and
  `open_interest` is `OI(close)`, else `OI(open)` carried (never past the bound). No
  sample in the bar, or a stale open, is the None case: `open_interest_delta` and
  `oi_price_quadrant` are None, never 0 or a quadrant (US-DERIV-002 scenario 3). A lone sample
  at exactly `start_ms` is both the open and the close: delta 0, reason `flat`.
- The quadrant is the sign of the bar's price move (`close - open`) against the sign of the OI
  delta; a flat price or flat OI classifies nothing (None).
- Ticker values (funding, basis, premium) come from the last snapshot inside the bar. A bar with
  no snapshot falls back, for the funding rate only, to the settled row whose period covers it.
- `funding_rate` and `funding_annualized` are percent (the descriptors' unit); the
  annualisation is `domain.funding.annualised_pct`, the one formula.
- Liquidations bucket per bar by `liquidated_side`; half-open bars count every print once, and
  an identical print (same `ts_ms`, side, notional and `batch_index`) is counted once.

Bounded state (C-2.18): at most `max_bars` bars (the oldest drops on append), and the row stores
keep only what a bar in the window reads: per bar the last ticker snapshot, the last OI sample at
its start and the last inside it, and its liquidation prints; per gap the last OI sample; nothing
before the first bar except an OI sample within `OI_STALENESS_MS` of it. Rows past the last bar
wait for the next one, at most `MAX_PENDING_ROWS` per store. Overflow policy: refused, never
dropped (`DerivativesBackpressure`, a `DerivativesInputError` subclass, so a caller can tell a
stalled grid from a malformed row). A refused `load()` resets the engine to empty (it refuses the
whole load), so the caller (PR B) must reload; a refused `on_*` leaves the engine unchanged.

Incremental path: a row recomputes only the bars it can change (a ticker or liquidation its own
bar; OI its own bar plus the bars starting within `OI_STALENESS_MS` after it; a settlement at
`T` the bars whose last ms lies in `[T - interval, T)`), and the `on_*` methods return the bars
whose metrics changed, oldest first. The result always equals a full recompute.

Not thread-safe: one engine per symbol, driven from one event loop.
"""

from __future__ import annotations

import time
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalTuple,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from itertools import pairwise
from typing import Final, Literal, Protocol

from candleviewer.domain.funding import annualised_pct, resolve_funding_interval_minutes
from candleviewer.orderflow.derivatives_metrics import (
    deriv_engine_compute_seconds,
    deriv_engine_none_bars_total,
)
from candleviewer.orderflow.errors import OrderflowError

#: OI resampling staleness bound: twice the coarsest OI sampling the engine is fed (the 5-min
#: history interval). Past it the open sample is absent; never carried forward (BQ-5).
OI_STALENESS_MS: Final = 600_000
#: The visible window the ticket budgets (1 500 bars); the oldest bar drops past it.
MAX_BARS: Final = 1_500
#: Rows per store waiting past the last bar for the next one; a stalled grid refuses more.
MAX_PENDING_ROWS: Final = 65_536
#: Inputs are refused outside `1e-30 < |x| < 1e30` (or zero), so no arithmetic can overflow.
_MAX_ADJUSTED: Final = 30
#: The engine's arithmetic context: fixed, so results never depend on the thread's context.
_CTX: Final = Context(
    prec=28,
    rounding=ROUND_HALF_EVEN,
    Emax=999_999,
    Emin=-999_999,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)
_MS_PER_MIN: Final = 60_000
_HUNDRED: Final = Decimal(100)
_ZERO: Final = Decimal(0)
_LOW: Final = -(1 << 63)
_HIGH: Final = 1 << 63

LiquidatedSide = Literal["long", "short"]
Quadrant = Literal["long_buildup", "short_covering", "short_buildup", "long_unwind"]
Value = Decimal | int | str | None


class DerivativesInputError(OrderflowError, ValueError):
    """An input row is malformed: a NaN/infinite/out-of-range number, a negative quantity, an
    unordered grid or a bad param."""


class DerivativesBackpressure(DerivativesInputError):
    """The `MAX_PENDING_ROWS` refusal: rows are piling up past a stalled bar grid. Not a
    malformed row; the row is refused, never dropped (C-2.18)."""


def _finite(v: Decimal | None, what: str) -> None:
    if v is None:
        return
    if not v.is_finite() or (v != 0 and not -_MAX_ADJUSTED < v.adjusted() < _MAX_ADJUSTED):
        raise DerivativesInputError(f"{what} is not a finite number in range")


def _non_negative(v: Decimal, what: str) -> None:
    _finite(v, what)
    if v < 0:
        raise DerivativesInputError(f"{what} is negative")


@dataclass(frozen=True, slots=True)
class DerivBar:
    """One bar of the grid the bar builders supply (E12); the engine never builds bars."""

    start_ms: int
    end_ms: int
    open: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        if self.end_ms <= self.start_ms:
            raise DerivativesInputError("bar end_ms must be after start_ms")
        _finite(self.open, "bar open")
        _finite(self.close, "bar close")


@dataclass(frozen=True, slots=True)
class OiSample:
    ts_ms: int
    open_interest: Decimal
    open_interest_value: Decimal
    source: str  # kept so a displayed value is attributable (ticket security note R)

    def __post_init__(self) -> None:
        _non_negative(self.open_interest, "open_interest")
        _non_negative(self.open_interest_value, "open_interest_value")


@dataclass(frozen=True, slots=True)
class TickerSnapshot:
    ts_ms: int
    last_price: Decimal | None = None
    mark_price: Decimal | None = None
    index_price: Decimal | None = None
    funding_rate: Decimal | None = None  # a fraction per interval, as the exchange gives it
    next_funding_time_ms: int | None = None

    def __post_init__(self) -> None:
        for name in ("last_price", "mark_price", "index_price", "funding_rate"):
            _finite(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class FundingRow:
    """A settled funding print: `funding_rate` (a fraction) applied at `ts_ms`."""

    ts_ms: int
    funding_rate: Decimal

    def __post_init__(self) -> None:
        _finite(self.funding_rate, "funding_rate")


@dataclass(frozen=True, slots=True)
class LiquidationPrint:
    """`batch_index` is the print's index in its exchange push (the store's dedup key leg), so
    two real prints with equal `ts_ms`, side and notional stay distinct."""

    ts_ms: int
    liquidated_side: LiquidatedSide
    notional: Decimal
    batch_index: int = 0

    def __post_init__(self) -> None:
        _non_negative(self.notional, "notional")
        if self.liquidated_side not in ("long", "short"):
            raise DerivativesInputError("liquidated_side must be long or short")


@dataclass(frozen=True, slots=True)
class InstrumentMeta:
    funding_interval_min: int


@dataclass(frozen=True, slots=True)
class BarMetrics:
    start_ms: int
    open_interest: Decimal | None
    open_interest_value: Decimal | None
    oi_source: str | None
    open_interest_delta: Decimal | None
    oi_price_quadrant: Quadrant | None
    funding_rate: Decimal | None
    funding_annualized: Decimal | None
    time_to_funding_ms: int | None
    basis_last: Decimal | None
    basis_mark: Decimal | None
    premium_pct_last: Decimal | None
    premium_pct_mark: Decimal | None
    liquidation_long: Decimal
    liquidation_short: Decimal


#: The ten 24 §7.2 descriptors and their params (name -> allowed values; first is the default).
DESCRIPTORS: Final[Mapping[str, Mapping[str, tuple[str, ...]]]] = {
    "open_interest": {},
    "open_interest_value": {},
    "open_interest_delta": {},
    "oi_price_quadrant": {},
    "funding_rate": {},
    "funding_annualized": {},
    "time_to_funding_ms": {},
    "basis": {"source": ("last", "mark")},
    "premium_pct": {"source": ("last", "mark")},
    "liquidation_notional": {"side": ("both", "long", "short")},
}


def metric_value(m: BarMetrics, name: str, params: Mapping[str, str] | None = None) -> Value:
    """The one read path: a descriptor's value for a bar, with its params validated."""
    allowed = DESCRIPTORS.get(name)
    if allowed is None:
        raise DerivativesInputError(f"{name!r} is not a derivatives metric")
    given = dict(params or {})
    if set(given) - set(allowed):
        raise DerivativesInputError(f"{name}: unknown param")
    p = {k: given.get(k, v[0]) for k, v in allowed.items()}
    if any(p[k] not in v for k, v in allowed.items()):
        raise DerivativesInputError(f"{name}: param value outside {dict(allowed)}")
    mark = p.get("source") == "mark"
    side = p.get("side")
    with localcontext(_CTX):
        both = m.liquidation_long + m.liquidation_short
    values: dict[str, Value] = {
        "open_interest": m.open_interest,
        "open_interest_value": m.open_interest_value,
        "open_interest_delta": m.open_interest_delta,
        "oi_price_quadrant": m.oi_price_quadrant,
        "funding_rate": m.funding_rate,
        "funding_annualized": m.funding_annualized,
        "time_to_funding_ms": m.time_to_funding_ms,
        "basis": m.basis_mark if mark else m.basis_last,
        "premium_pct": m.premium_pct_mark if mark else m.premium_pct_last,
        "liquidation_notional": (
            m.liquidation_long if side == "long"
            else m.liquidation_short if side == "short"
            else both
        ),
    }  # fmt: skip
    return values[name]


def classify_quadrant(price_move: Decimal, oi_delta: Decimal | None) -> Quadrant | None:
    """24 §7.2 truth table; a missing or flat OI change, or a flat price, classifies nothing."""
    if oi_delta is None or oi_delta == 0 or price_move == 0:
        return None
    if price_move > 0:
        return "long_buildup" if oi_delta > 0 else "short_covering"
    return "short_buildup" if oi_delta > 0 else "long_unwind"


_Row = OiSample | TickerSnapshot | FundingRow | LiquidationPrint
#: Where a timestamp falls on the grid: before the first bar, in a bar, between two bars, or
#: past the last bar (pending: the next bar is not known yet).
_Seg = Literal["head", "bar", "gap", "tail"]
Update = tuple["BarMetrics", ...]


class _Store(Protocol):
    def __len__(self) -> int: ...
    def span(self, start: int, end: int) -> tuple[int, int]: ...
    def keep(self, lo: int, hi: int, idx: Sequence[int]) -> None: ...


class _Sorted[R: _Row]:
    """Rows ordered by `ts_ms`, ties in arrival order (so incremental == full recompute)."""

    __slots__ = ("rows", "ts")

    def __init__(self, rows: Iterable[R] = ()) -> None:
        self.rows: list[R] = sorted(rows, key=lambda r: r.ts_ms)
        self.ts: list[int] = [r.ts_ms for r in self.rows]

    def add(self, row: R) -> None:
        i = bisect_right(self.ts, row.ts_ms)
        self.ts.insert(i, row.ts_ms)
        self.rows.insert(i, row)

    def __len__(self) -> int:
        return len(self.rows)

    def span(self, start: int, end: int) -> tuple[int, int]:
        """Indices `[lo, hi)` of the rows with `start <= ts_ms < end`."""
        return bisect_left(self.ts, start), bisect_left(self.ts, end)

    def keep(self, lo: int, hi: int, idx: Sequence[int]) -> None:
        """Keep, of the rows `[lo, hi)`, only those at the (absolute, ascending) `idx`."""
        if len(idx) != hi - lo:
            self.rows[lo:hi] = [self.rows[j] for j in idx]
            self.ts[lo:hi] = [self.ts[j] for j in idx]


def _start(b: DerivBar) -> int:
    return b.start_ms


def _end(b: DerivBar) -> int:
    return b.end_ms


_FAMILIES: Final = ("open_interest", "funding", "basis", "liquidation_notional")


class DerivativesEngine:
    """Per-symbol state: the bar grid (at most `max_bars`), the rows it reads, the series."""

    def __init__(
        self, instrument: InstrumentMeta, *, max_bars: int = MAX_BARS, prune: bool = True
    ) -> None:
        """`prune=False` keeps every row (no compaction): TEST-ONLY, the oracle that a pruning
        bug shared by the full and incremental paths cannot hide from."""
        if max_bars < 1:
            raise DerivativesInputError("max_bars must be at least 1")
        self._interval_ms = resolve_funding_interval_minutes(instrument) * _MS_PER_MIN
        self._interval_min = self._interval_ms // _MS_PER_MIN
        self._max_bars = max_bars
        self._prune = prune
        self._bars: list[DerivBar] = []
        self._oi: _Sorted[OiSample] = _Sorted()
        self._tickers: _Sorted[TickerSnapshot] = _Sorted()
        self._funding: _Sorted[FundingRow] = _Sorted()
        self._liqs: _Sorted[LiquidationPrint] = _Sorted()
        self._series: list[BarMetrics] = []
        self._none: list[str | None] = []  # per bar: why its OI delta / quadrant is None
        self._counted_ms: int | None = None  # the latest closed bar the None counter has seen
        self._next_funding: tuple[int, int] | None = None  # (ts_ms, next_funding_time_ms)

    @property
    def series(self) -> tuple[BarMetrics, ...]:
        return tuple(self._series)

    def retained(self) -> Mapping[str, int]:
        """How many bars and rows the engine holds (the C-2.18 bound, observable)."""
        return {
            "bars": len(self._bars), "oi": len(self._oi.rows), "tickers": len(self._tickers.rows),
            "funding": len(self._funding.rows), "liquidations": len(self._liqs.rows),
        }  # fmt: skip

    def load(
        self,
        bars: Sequence[DerivBar],
        *,
        oi: Iterable[OiSample] = (),
        tickers: Iterable[TickerSnapshot] = (),
        funding: Iterable[FundingRow] = (),
        liquidations: Iterable[LiquidationPrint] = (),
    ) -> tuple[BarMetrics, ...]:
        """Replace every input (the last `max_bars` bars) and recompute the window; each closed
        bar's None case counts once, however often it is loaded."""
        for prev, nxt in pairwise(bars):
            if nxt.start_ms < prev.end_ms:
                raise DerivativesInputError("bar grid must be ordered and non-overlapping")
        self._bars = list(bars[-self._max_bars :])
        self._oi, self._tickers = _Sorted(oi), _Sorted(tickers)
        self._funding, self._liqs = _Sorted(funding), _Sorted(dict.fromkeys(liquidations))
        self._next_funding = None
        for snap in self._tickers.rows:
            self._note_next_funding(snap)
        self._tidy_all()
        try:
            self._check_pending()
        except DerivativesInputError:
            self.load(())  # refuse the whole load, leave an empty engine
            raise
        self.recompute()
        self._count_closed()
        return self.series

    def recompute(self) -> tuple[BarMetrics, ...]:
        """The full recompute over the window."""
        self._series, self._none = self._compute(self._bars)
        return self.series

    def upsert_bar(self, bar: DerivBar) -> BarMetrics:
        """Replace the current bar (same `[start, end)`, revised prices) or append the next."""
        if self._bars and bar.start_ms == self._bars[-1].start_ms:
            if bar.end_ms != self._bars[-1].end_ms:
                raise DerivativesInputError("the current bar is replaced on the same grid slot")
            self._bars[-1] = bar
            (self._series[-1],), (self._none[-1],) = self._compute(self._bars[-1:])
            return self._series[-1]
        if self._bars and bar.start_ms < self._bars[-1].end_ms:
            raise DerivativesInputError("only the current bar is replaced; bars are appended")
        self._bars.append(bar)
        self._count_closed()  # the previous bar just closed
        prev_end = self._bars[-2].end_ms if len(self._bars) > 1 else _LOW
        self._tidy("head" if len(self._bars) == 1 else "gap", prev_end, bar.start_ms)
        self._tidy("bar", bar.start_ms, bar.end_ms)
        (metrics,), (reason,) = self._compute([bar])
        self._series.append(metrics)
        self._none.append(reason)
        if len(self._bars) > self._max_bars:
            del self._bars[0], self._series[0], self._none[0]
            self._tidy("head", _LOW, self._bars[0].start_ms)
        return metrics

    def on_oi(self, sample: OiSample) -> Update:
        """Recomputes the sample's bar and the bars starting within `OI_STALENESS_MS` of it."""
        t = sample.ts_ms
        self._add(self._oi, sample)
        first = bisect_left(self._bars, t, key=_start)
        last = bisect_right(self._bars, t + OI_STALENESS_MS, key=_start)
        own = bisect_right(self._bars, t, key=_start) - 1
        lo = own if own >= 0 and t < self._bars[own].end_ms else first
        return self._refresh(range(lo, last))

    def on_ticker(self, snapshot: TickerSnapshot) -> Update:
        self._add(self._tickers, snapshot)
        self._note_next_funding(snapshot)
        return self._refresh(self._own(snapshot.ts_ms))

    def on_liquidation(self, liq: LiquidationPrint) -> Update:
        """An identical print already held is ignored (counted once)."""
        lo, hi = self._liqs.span(liq.ts_ms, liq.ts_ms + 1)
        if liq in self._liqs.rows[lo:hi]:
            return ()
        self._add(self._liqs, liq)
        return self._refresh(self._own(liq.ts_ms))

    def on_funding(self, row: FundingRow) -> Update:
        """A settlement at `T` covers the bars whose last ms lies in `[T - interval, T)`."""
        self._add(self._funding, row)
        t = row.ts_ms
        lo = bisect_left(self._bars, t - self._interval_ms + 1, key=_end)
        return self._refresh(range(lo, bisect_right(self._bars, t, key=_end)))

    def time_to_funding_ms(self, now_ms: int, clock_offset_ms: int) -> int | None:
        """Live countdown: the latest `next_funding_time_ms` minus the exchange-synced now
        (`now_ms + clock_offset_ms`, the offset being exchange minus local), floored at 0."""
        if self._next_funding is None:
            return None
        return max(0, self._next_funding[1] - (now_ms + clock_offset_ms))

    # --- state ------------------------------------------------------------------------------

    def _note_next_funding(self, snap: TickerSnapshot) -> None:
        nft, cur = snap.next_funding_time_ms, self._next_funding
        if nft is not None and (cur is None or snap.ts_ms >= cur[0]):
            self._next_funding = (snap.ts_ms, nft)

    def _segment(self, ts: int) -> tuple[_Seg, int, int]:
        """The grid segment holding `ts`, as (kind, start, end)."""
        bars = self._bars
        i = bisect_right(bars, ts, key=_start) - 1
        if not bars or (i == len(bars) - 1 and ts >= bars[i].end_ms):
            return "tail", (bars[-1].end_ms if bars else _LOW), _HIGH
        if i < 0:
            return "head", _LOW, bars[0].start_ms
        if ts < bars[i].end_ms:
            return "bar", bars[i].start_ms, bars[i].end_ms
        return "gap", bars[i].end_ms, bars[i + 1].start_ms

    def _add[R: _Row](self, store: _Sorted[R], row: R) -> None:
        seg, start, end = self._segment(row.ts_ms)
        if seg == "tail" and len(store.rows) - store.span(start, end)[0] >= MAX_PENDING_ROWS:
            raise DerivativesBackpressure("too many rows past the bar grid; append the next bar")
        store.add(row)
        if seg != "tail":
            self._tidy(seg, start, end)

    def _check_pending(self) -> None:
        start = self._bars[-1].end_ms if self._bars else _LOW
        for store in self._all():
            if len(store) - store.span(start, _HIGH)[0] > MAX_PENDING_ROWS:
                raise DerivativesBackpressure("too many rows past the bar grid")

    def _keep_idx(self, seg: _Seg, start: int, end: int) -> list[tuple[int, int, list[int]]]:
        """Per store (oi, tickers, funding, liquidations): the span `[lo, hi)` of one segment
        and the indices a bar in the window still reads."""
        out: list[tuple[int, int, list[int]]] = []
        lo, hi = self._oi.span(start, end)
        keep: list[int] = []
        if hi > lo:
            if seg == "bar":
                j = bisect_right(self._oi.ts, start, lo, hi) - 1  # the last sample at the start
                keep = [j, hi - 1] if lo <= j < hi - 1 else [hi - 1]
            elif seg == "gap" or self._oi.ts[hi - 1] >= self._bars[0].start_ms - OI_STALENESS_MS:
                keep = [hi - 1]
        out.append((lo, hi, keep))
        lo, hi = self._tickers.span(start, end)
        out.append((lo, hi, [hi - 1] if seg == "bar" and hi > lo else []))
        lo, hi = self._funding.span(start, end)
        out.append((lo, hi, [] if seg == "head" else list(range(lo, hi))))
        lo, hi = self._liqs.span(start, end)
        out.append((lo, hi, list(range(lo, hi)) if seg == "bar" else []))
        return out

    def _all(self) -> tuple[_Store, ...]:
        return self._oi, self._tickers, self._funding, self._liqs

    def _tidy(self, seg: _Seg, start: int, end: int) -> None:
        if seg == "tail" or not self._bars or not self._prune:
            return
        for store, (lo, hi, idx) in zip(self._all(), self._keep_idx(seg, start, end), strict=True):
            store.keep(lo, hi, idx)

    def _tidy_all(self) -> None:
        """Compact every store in one pass over the grid (`load`)."""
        if not self._bars or not self._prune:
            return
        segs: list[tuple[_Seg, int, int]] = [("head", _LOW, self._bars[0].start_ms)]
        for b, nxt in pairwise(self._bars):
            segs += [("bar", b.start_ms, b.end_ms), ("gap", b.end_ms, nxt.start_ms)]
        last = self._bars[-1]
        segs.append(("bar", last.start_ms, last.end_ms))
        keeps: list[list[int]] = [[], [], [], []]
        for seg, start, end in segs:
            for k, (_, _, idx) in zip(keeps, self._keep_idx(seg, start, end), strict=True):
                k += idx
        for store, k in zip(self._all(), keeps, strict=True):
            k += range(store.span(last.end_ms, _HIGH)[0], len(store))  # pending: all of them
            store.keep(0, len(store), k)

    def _own(self, ts: int) -> range:
        i = bisect_right(self._bars, ts, key=_start) - 1
        return range(i, i + 1) if i >= 0 and ts < self._bars[i].end_ms else range(0)

    def _count_closed(self) -> None:
        """Count the None case of every closed bar (all but the last) not counted yet."""
        lo = (
            0
            if self._counted_ms is None
            else bisect_right(self._bars, self._counted_ms, key=_start)
        )
        for i in range(lo, len(self._bars) - 1):
            if (reason := self._none[i]) is not None:
                deriv_engine_none_bars_total.labels(reason=reason).inc()
            self._counted_ms = self._bars[i].start_ms

    def _refresh(self, idx: range) -> Update:
        """Recompute the bars at `idx`; return those whose metrics changed, oldest first."""
        if not idx:
            return ()
        rows, reasons = self._compute(self._bars[idx.start : idx.stop])
        changed: list[BarMetrics] = []
        for i, row, reason in zip(idx, rows, reasons, strict=True):
            if row != self._series[i]:
                changed.append(row)
            self._series[i], self._none[i] = row, reason
        return tuple(changed)

    # --- formulas ---------------------------------------------------------------------------

    def _compute(self, bars: Sequence[DerivBar]) -> tuple[list[BarMetrics], list[str | None]]:
        """One pass per metric family (each timed as a batch), then one row per bar."""
        with localcontext(_CTX):
            t0 = time.perf_counter()
            ois = [self._oi_part(b) for b in bars]
            t1 = time.perf_counter()
            snaps = [self._snapshot(b) for b in bars]
            annual: dict[DecimalTuple, Decimal] = {}
            funding = [self._funding_part(b, s, annual) for b, s in zip(bars, snaps, strict=True)]
            t2 = time.perf_counter()
            bases = [_basis_part(s) for s in snaps]
            t3 = time.perf_counter()
            liqs = [self._liquidation_part(b) for b in bars]
            t4 = time.perf_counter()
        for family, dt in zip(_FAMILIES, (t1 - t0, t2 - t1, t3 - t2, t4 - t3), strict=True):
            deriv_engine_compute_seconds.labels(metric=family).observe(dt)
        rows = [
            BarMetrics(b.start_ms, *o[:5], *f, *bs, *lq)
            for b, o, f, bs, lq in zip(bars, ois, funding, bases, liqs, strict=True)
        ]
        return rows, [o[5] for o in ois]

    def _oi_part(self, bar: DerivBar) -> _OiPart:
        start, oi = bar.start_ms, self._oi
        lo, hi = oi.span(start, bar.end_ms)
        close = oi.rows[hi - 1] if hi > lo else None
        j = bisect_right(oi.ts, start) - 1
        open_ = oi.rows[j] if j >= 0 and start - oi.ts[j] <= OI_STALENESS_MS else None
        latest = close if close is not None else open_  # in the bar, else carried within the bound
        delta = None
        if close is not None and open_ is not None:
            delta = close.open_interest - open_.open_interest
        quadrant = classify_quadrant(bar.close - bar.open, delta)
        reason = (
            "no_oi_sample" if close is None
            else "stale_oi_open" if open_ is None
            else "flat" if quadrant is None
            else None
        )  # fmt: skip
        if latest is None:
            return None, None, None, delta, quadrant, reason
        return (
            latest.open_interest, latest.open_interest_value, latest.source, delta, quadrant, reason
        )  # fmt: skip

    def _snapshot(self, bar: DerivBar) -> TickerSnapshot | None:
        lo, hi = self._tickers.span(bar.start_ms, bar.end_ms)
        return self._tickers.rows[hi - 1] if hi > lo else None

    def _funding_part(
        self, bar: DerivBar, snap: TickerSnapshot | None, annual: dict[DecimalTuple, Decimal]
    ) -> tuple[Decimal | None, Decimal | None, int | None]:
        rate = snap.funding_rate if snap is not None else None
        if rate is None:
            rate = self._settled_rate(bar.end_ms - 1)
        to_funding = None
        if snap is not None and snap.next_funding_time_ms is not None:
            to_funding = max(0, snap.next_funding_time_ms - snap.ts_ms)
        if rate is None:
            return None, None, to_funding
        key = rate.as_tuple()  # the exact representation, so the result never depends on order
        if key not in annual:
            annual[key] = annualised_pct(rate, self._interval_min)
        return rate * _HUNDRED, annual[key], to_funding

    def _liquidation_part(self, bar: DerivBar) -> tuple[Decimal, Decimal]:
        lo, hi = self._liqs.span(bar.start_ms, bar.end_ms)
        long_, short = _ZERO, _ZERO
        for p in self._liqs.rows[lo:hi]:
            if p.liquidated_side == "long":
                long_ += p.notional
            else:
                short += p.notional
        return long_, short

    def _settled_rate(self, at_ms: int) -> Decimal | None:
        """The settled rate whose period `[T - interval, T)` contains `at_ms`, if any."""
        i = bisect_right(self._funding.ts, at_ms)
        if i < len(self._funding.ts) and self._funding.ts[i] - self._interval_ms <= at_ms:
            return self._funding.rows[i].funding_rate
        return None


_OiPart = tuple[
    Decimal | None, Decimal | None, str | None, Decimal | None, Quadrant | None, str | None
]


_Dn = Decimal | None


def _basis_part(snap: TickerSnapshot | None) -> tuple[_Dn, _Dn, _Dn, _Dn]:
    if snap is None:
        return None, None, None, None
    index = snap.index_price
    last, mark = _basis(snap.last_price, index), _basis(snap.mark_price, index)
    return last, mark, _premium(last, index), _premium(mark, index)


def _basis(price: Decimal | None, index: Decimal | None) -> Decimal | None:
    return None if price is None or index is None else price - index


def _premium(basis: Decimal | None, index: Decimal | None) -> Decimal | None:
    return None if basis is None or index is None or index == 0 else basis / index * _HUNDRED

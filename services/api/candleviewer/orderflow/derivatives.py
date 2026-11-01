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
  `oi_price_quadrant` are None, never 0 or a quadrant (US-DERIV-002 scenario 3).
- The quadrant is the sign of the bar's price move (`close - open`) against the sign of the OI
  delta; a flat price or flat OI classifies nothing (None).
- Ticker values (funding, basis, premium) come from the last snapshot inside the bar. A bar with
  no snapshot falls back, for the funding rate only, to the settled row whose period covers it.
- `funding_rate` and `funding_annualized` are percent (the descriptors' unit); the
  annualisation is `domain.funding.annualised_pct`, the one formula.
- Liquidations bucket per bar by `liquidated_side`; half-open bars count every print once.

Incremental path: an input at or after the current (last) bar's start recomputes that bar only;
an earlier one, or a replaced earlier bar, recomputes the window. Both give the same series.
"""

from __future__ import annotations

import time
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from typing import Final, Literal

from candleviewer.domain.funding import annualised_pct, resolve_funding_interval_minutes
from candleviewer.orderflow.derivatives_metrics import (
    deriv_engine_compute_seconds,
    deriv_engine_none_bars_total,
)
from candleviewer.orderflow.errors import OrderflowError

#: OI resampling staleness bound: twice the coarsest OI sampling the engine is fed (the 5-min
#: history interval). Past it the open sample is absent; never carried forward (BQ-5).
OI_STALENESS_MS: Final = 600_000
_MS_PER_MIN: Final = 60_000
_HUNDRED: Final = Decimal(100)
_ZERO: Final = Decimal(0)

LiquidatedSide = Literal["long", "short"]
Quadrant = Literal["long_buildup", "short_covering", "short_buildup", "long_unwind"]
Value = Decimal | int | str | None


class DerivativesInputError(OrderflowError, ValueError):
    """An input row is malformed: a NaN/infinite number, an unordered grid or a bad param."""


def _finite(v: Decimal | None, what: str) -> None:
    if v is not None and not v.is_finite():
        raise DerivativesInputError(f"{what} is not a finite number")


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
        _finite(self.open_interest, "open_interest")
        _finite(self.open_interest_value, "open_interest_value")


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
    ts_ms: int
    liquidated_side: LiquidatedSide
    notional: Decimal

    def __post_init__(self) -> None:
        _finite(self.notional, "notional")
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
            else m.liquidation_long + m.liquidation_short
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

    def span(self, start: int, end: int) -> tuple[int, int]:
        """Indices `[lo, hi)` of the rows with `start <= ts_ms < end`."""
        return bisect_left(self.ts, start), bisect_left(self.ts, end)


_FAMILIES: Final = ("open_interest", "funding", "basis", "liquidation_notional")


class DerivativesEngine:
    """Per-symbol state: the bar grid, the input rows, and the computed series."""

    def __init__(self, instrument: InstrumentMeta) -> None:
        self._interval_ms = resolve_funding_interval_minutes(instrument) * _MS_PER_MIN
        self._interval_min = self._interval_ms // _MS_PER_MIN
        self._bars: list[DerivBar] = []
        self._oi: _Sorted[OiSample] = _Sorted()
        self._tickers: _Sorted[TickerSnapshot] = _Sorted()
        self._funding: _Sorted[FundingRow] = _Sorted()
        self._liqs: _Sorted[LiquidationPrint] = _Sorted()
        self._series: list[BarMetrics] = []
        self._none: list[str | None] = []  # per bar: why its OI delta / quadrant is None

    @property
    def series(self) -> tuple[BarMetrics, ...]:
        return tuple(self._series)

    def load(
        self,
        bars: Sequence[DerivBar],
        *,
        oi: Iterable[OiSample] = (),
        tickers: Iterable[TickerSnapshot] = (),
        funding: Iterable[FundingRow] = (),
        liquidations: Iterable[LiquidationPrint] = (),
    ) -> tuple[BarMetrics, ...]:
        """Replace every input and recompute the window; the closed bars' None cases count."""
        for prev, nxt in pairwise(bars):
            if nxt.start_ms < prev.end_ms:
                raise DerivativesInputError("bar grid must be ordered and non-overlapping")
        self._bars = list(bars)
        self._oi, self._tickers = _Sorted(oi), _Sorted(tickers)
        self._funding, self._liqs = _Sorted(funding), _Sorted(liquidations)
        self.recompute()
        for reason in self._none[:-1]:
            if reason is not None:
                deriv_engine_none_bars_total.labels(reason=reason).inc()
        return self.series

    def recompute(self) -> tuple[BarMetrics, ...]:
        """The full recompute over the window."""
        self._series, self._none = self._compute(self._bars)
        return self.series

    def upsert_bar(self, bar: DerivBar) -> BarMetrics:
        """Replace the current bar (same start) or append the next one."""
        if self._bars and bar.start_ms == self._bars[-1].start_ms:
            if len(self._bars) > 1 and bar.start_ms < self._bars[-2].end_ms:
                raise DerivativesInputError("bar overlaps the previous bar")
            self._bars[-1] = bar
            return self._recompute_current()
        if self._bars and bar.start_ms < self._bars[-1].end_ms:
            raise DerivativesInputError("only the current bar is replaced; bars are appended")
        if self._none and self._none[-1] is not None:
            deriv_engine_none_bars_total.labels(reason=self._none[-1]).inc()  # it just closed
        self._bars.append(bar)
        (metrics,), (reason,) = self._compute([bar])
        self._series.append(metrics)
        self._none.append(reason)
        return metrics

    def on_oi(self, sample: OiSample) -> BarMetrics | None:
        self._oi.add(sample)
        return self._after(sample.ts_ms)

    def on_ticker(self, snapshot: TickerSnapshot) -> BarMetrics | None:
        self._tickers.add(snapshot)
        return self._after(snapshot.ts_ms)

    def on_liquidation(self, liq: LiquidationPrint) -> BarMetrics | None:
        self._liqs.add(liq)
        return self._after(liq.ts_ms)

    def on_funding(self, row: FundingRow) -> BarMetrics | None:
        """A settlement covers a whole funding period, so it may touch closed bars: full."""
        self._funding.add(row)
        self.recompute()
        return self._series[-1] if self._series else None

    def time_to_funding_ms(self, now_ms: int, clock_offset_ms: int) -> int | None:
        """Live countdown: the latest `next_funding_time_ms` minus the exchange-synced now
        (`now_ms + clock_offset_ms`, the offset being exchange minus local), floored at 0."""
        for snap in reversed(self._tickers.rows):
            if snap.next_funding_time_ms is not None:
                return max(0, snap.next_funding_time_ms - (now_ms + clock_offset_ms))
        return None

    def _after(self, ts_ms: int) -> BarMetrics | None:
        if not self._bars:
            return None
        if ts_ms >= self._bars[-1].start_ms:
            return self._recompute_current()
        self.recompute()  # a late row may change a closed bar
        return self._series[-1]

    def _recompute_current(self) -> BarMetrics:
        (self._series[-1],), (self._none[-1],) = self._compute(self._bars[-1:])
        return self._series[-1]

    def _compute(self, bars: Sequence[DerivBar]) -> tuple[list[BarMetrics], list[str | None]]:
        """One pass per metric family (each timed as a batch), then one row per bar."""
        t0 = time.perf_counter()
        ois = [self._oi_part(b) for b in bars]
        t1 = time.perf_counter()
        snaps = [self._snapshot(b) for b in bars]
        annual: dict[Decimal, Decimal] = {}
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
        self, bar: DerivBar, snap: TickerSnapshot | None, annual: dict[Decimal, Decimal]
    ) -> tuple[Decimal | None, Decimal | None, int | None]:
        rate = snap.funding_rate if snap is not None else None
        if rate is None:
            rate = self._settled_rate(bar.end_ms - 1)
        to_funding = None
        if snap is not None and snap.next_funding_time_ms is not None:
            to_funding = max(0, snap.next_funding_time_ms - snap.ts_ms)
        if rate is None:
            return None, None, to_funding
        if rate not in annual:
            annual[rate] = annualised_pct(rate, self._interval_min)
        return rate * _HUNDRED, annual[rate], to_funding

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

"""Range and delta bar builders (`24-internal-schemas.md` §3.3, ticket E12-S03).

Hot path (C-2.20): plain synchronous code, no statechart. Both reuse the `_Draft` accumulator and
the `_ActivityBuilder` envelope (snapshot/restore/index/`partial`) of `activity_builders`.

Deliberately NOT a shared threshold abstraction: the three threshold kinds differ exactly at the
threshold and a generic helper is how that is lost.
- volume bars SPLIT the overshooting trade (S02);
- delta bars never split: the whole trade lands in one bar and the overshoot stays in its `delta`;
- range bars never split either: the closing trade belongs to the bar it closes, and the next bar
  opens at that bar's close price.

Range bars. Width `range_ticks * tick_size` (exact `Decimal`). After each trade the bar closes
when `high - low >= width` (inclusive); the closing trade is part of the closed bar and its price
(in event order) is `close`. The next bar's `open` is that close price (no gap), but the bar is
only created by the next real trade: a bar always holds >= 1 trade, so a gap never produces a
synthetic bar (BR-06, "no phantom bars"). Consequence: the open of a bar need not be a price
traded in it. A *jump* is a closing trade that leaves `high - low >= 2 * width`, i.e. at least
one whole range of prices was skipped (a naive builder would emit an intermediate bar there);
the next bar carries `gap_before=True`, `bar_range_jump_gaps_total` is incremented, and the
closed bar's span may exceed the width. `open_source_ts` (21 §4.8) is the `ts_event` of the
trade that opened the bar in arrival order, carried on `RangeBarUpdate` until the `bars_range`
row gains the column.

Delta bars. After each trade the bar closes when `abs(delta) >= delta_threshold`; closure is final
(delta moving back below the threshold cannot reopen it). A closing trade may overshoot; nothing is
split and no `split_from_trade_id` exists. `gap_before` is False unless `mark_gap()` was called
(an unrecovered tape gap, #529).

Late / out-of-order trades follow the S02 rule still pending ratification (#2013): a closed bar is
final and a late trade joins the open bar. `on_clock` is a no-op.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any, Final

import orjson
import structlog

from candleviewer.bars.activity_builders import ActivityBarUpdate, _ActivityBuilder
from candleviewer.bars.errors import BarsError, BarSpecError
from candleviewer.bars.models import BarSpec, BarUpdate, BuilderState
from candleviewer.bars.time_builder import _Draft
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.observability.metrics import Counter

#: Smallest `range_ticks` / `delta_threshold` a builder accepts.
MIN_RANGE_TICKS: Final = 1
#: Subscribable-series bounds, E12 threat model SR-E12-03 / BR-29 (reject, never clamp); enforced by
#: E12-T05/T06: `range` 2..100 000 ticks, `delta` >= 10 `qty_step`s and <= 10^12.
MIN_SUBSCRIBABLE_RANGE_TICKS: Final = 2
MAX_SUBSCRIBABLE_RANGE_TICKS: Final = 100_000
MIN_SUBSCRIBABLE_DELTA_QTY_STEPS: Final = 10
MAX_SUBSCRIBABLE_DELTA: Final = Decimal(10) ** 12
_RATE_WARN_MIN_TRADES: Final = 1_000

bar_range_jump_gaps_total = Counter(
    "bar_range_jump_gaps_total",
    "Range bars closed by a trade that skipped at least one whole range.",
    labelnames=("symbol",),
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class RangeBarUpdate(ActivityBarUpdate):
    """`BarUpdate` plus `open_source_ts` (21 §4.8): `ts_event` of the trade that opened the bar."""

    open_source_ts: int


def _check_rate(b: _ThresholdBuilder, n_trades: int) -> None:
    # Same-module helper; reads the builder's counters directly (cosmetic, kept deliberately).
    if not b._warned and n_trades >= _RATE_WARN_MIN_TRADES and b._n_bars * 10 >= n_trades * 9:
        b._warned = True
        _log().warning(
            "bars_emit_rate_high",
            symbol=b.symbol,
            spec_hash=b._hash,
            hint="the threshold is probably tiny for this symbol: about one bar per trade",
        )


class _ThresholdBuilder(_ActivityBuilder):
    def __init__(self, spec: BarSpec, symbol: str) -> None:
        super().__init__(spec, symbol)
        self._n_trades = self._n_bars = 0
        self._warned = False


class DeltaBarBuilder(_ThresholdBuilder):
    """`BarBuilder` for `kind="delta"`. See the module docstring."""

    _kind = "delta"

    def __init__(self, spec: BarSpec, symbol: str) -> None:
        super().__init__(spec, symbol)
        self._thr = Decimal(spec.param_value)

    def on_trade(self, t: TradeEvent) -> Sequence[BarUpdate]:
        self._guard(t)
        d = self._draft(t)
        d.apply(t)
        self._n_trades += 1
        closed = abs(d.delta) >= self._thr
        if closed:
            self._n_bars += 1
            _check_rate(self, self._n_trades)
        return (self._emit(d, closed=closed),)


class RangeBarBuilder(_ThresholdBuilder):
    """`BarBuilder` for `kind="range"`; `tick_size_of` returns None for an unknown symbol."""

    _kind = "range"

    def __init__(
        self, spec: BarSpec, symbol: str, tick_size_of: Callable[[str], Decimal | None]
    ) -> None:
        super().__init__(spec, symbol)
        tick = tick_size_of(symbol)
        if tick is None or tick <= 0:
            raise BarSpecError(f"No tick size is known for the symbol {symbol}.")
        self._width = Decimal(spec.param_value) * tick
        self._two_widths = self._width * 2
        self._jumps = bar_range_jump_gaps_total.labels(symbol=symbol)
        self._open_px: Decimal | None = None  # pinned open of the current bar (None: first bar)
        self._open_src = 0
        self._carry: Decimal | None = None  # close of the last closed bar, next bar's open
        self._gap = False

    def on_trade(self, t: TradeEvent) -> Sequence[BarUpdate]:
        self._guard(t)
        if t.ts_event > self._max_ts:
            self._max_ts = t.ts_event
        d = self._cur
        if d is None:
            d = self._draft(t)
            self._open_px, self._carry = self._carry, None
            if self._open_px is not None:
                d.open = d.high = d.low = self._open_px
            d.gap_before, self._gap = d.gap_before or self._gap, False
            self._open_src = t.ts_event
        elif self._gap_pending and t.ts_event > self._gap_floor:  # `_draft` stamps a new bar
            d.gap_before, self._gap_pending = True, False
        d.apply(t)
        if self._open_px is not None:
            d.open = self._open_px
        self._n_trades += 1
        span = d.high - d.low
        if span < self._width:
            return (self._emit(d, closed=False),)
        self._carry = d.close
        if span >= self._two_widths:
            self._gap = True
            self._jumps.inc()
        self._n_bars += 1
        _check_rate(self, self._n_trades)
        return (self._emit(d, closed=True),)

    def _emit(self, d: _Draft, closed: bool, split: str | None = None) -> RangeBarUpdate:
        u = super()._emit(d, closed, split)
        return RangeBarUpdate.model_construct(kind=u.kind, bar=u.bar, open_source_ts=self._open_src)

    def snapshot(self) -> BuilderState:
        s = super().snapshot()
        doc = orjson.loads(s.blob)
        doc.update(
            open_px=None if self._open_px is None else str(self._open_px),
            src=self._open_src,
            carry=None if self._carry is None else str(self._carry),
            gap=self._gap,
        )
        return s.model_copy(update={"blob": orjson.dumps(doc)})

    def restore(self, state: BuilderState) -> None:
        super().restore(state)
        doc = orjson.loads(state.blob)
        try:
            op, ca = doc["open_px"], doc["carry"]
            self._open_src, self._gap = doc["src"], doc["gap"]
        except KeyError as e:
            raise BarsError("The range builder state is incomplete.") from e
        self._open_px = None if op is None else Decimal(op)
        self._carry = None if ca is None else Decimal(ca)

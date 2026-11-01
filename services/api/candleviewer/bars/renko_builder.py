"""Renko brick builder (`24-internal-schemas.md` §3.3 Renko (a)-(c), ticket E12-S04).

Hot path (C-2.20): plain synchronous code, no statechart; `Decimal` brick grid, never float.

Grid. Brick width `B = range_ticks * tick_size`, frozen in price units at construction
(ADR-0033 epoch rule: `restore()` refuses a state captured under another tick size, so the
service starts a new epoch). The first trade's price is the initial anchor; `price_source` must
be `last` (no mark-price stream reaches builders yet; `mark` is refused, see the PR).

Formation, from the anchor `c` (the last brick's close) and the prevailing direction `s`:
- continuation: price `p` with `(p - c) * s >= k * B` emits `k` bricks from `c`;
- reversal: a move of `n >= reversal_bricks` whole bricks against `s` emits `n - (R - 1)` bricks
  opening at `c - s * (R - 1) * B` (R = 2: the first one opens at the previous brick's open);
- no direction yet: the first whole-brick move either way starts the series.

Volume (edge case a). One trade that completes N bricks emits N `close` bricks with identical
`open_time`/`close_time`/`open_source_ts` and incrementing `index`. Everything the forming draft
accumulated (volume, delta, trades, turnover) goes to the LAST brick, `volume_allocated=True`;
the others are flat zero-volume bricks with `volume_allocated=False`. The forming brick is
emitted as `open`/`update` (closed=False, provisional open = anchor) so BI-1 holds on
`final_bars` at any point.

Wicks (b). `renko_wick=False`: high/low are the brick's open/close bounds. True: the extreme
trade prices observed while the run formed extend the trailing side of the first brick and the
leading side of the last brick. Time (c): bricks have no time width; see `series.layout`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Final

import orjson

from candleviewer.bars.errors import BarsError, BarSpecError
from candleviewer.bars.limits import MAX_BRICKS_PER_TRADE
from candleviewer.bars.metrics import (
    bar_build_latency_seconds,
    bar_renko_multi_brick_total,
    bar_renko_reversals_total,
    bars_print_rejected_total,
)
from candleviewer.bars.models import Bar, BarSpec, BarUpdate, BuilderState, check_renko_bounds
from candleviewer.bars.time_builder import _NONE, _Draft, bars_built_total
from candleviewer.domain.primitives import TsUs
from candleviewer.exchange.base.models import TradeEvent

STATE_VERSION: Final = 1
_ZERO: Final = Decimal(0)


class RenkoBarUpdate(BarUpdate):
    """`BarUpdate` plus the renko fields (21 §4.8, 24 §3.3a).

    Stop-gap like `RangeBarUpdate`: `volume_allocated` becomes a `Bar` field with the
    contract-first change of the bar model / wire payload (see PR deviations).
    """

    # TODO(#2130): move `volume_allocated` onto `Bar` + the `bars_renko` column + wire payload.

    volume_allocated: bool
    open_source_ts: int


def check_renko_spec(spec: BarSpec) -> None:
    """Builder-side bounds (defence in depth; `BarSpec` and `from_wire` reject first)."""
    if spec.kind != "renko":
        raise BarSpecError("A renko builder needs a bar spec of kind 'renko'.")
    check_renko_bounds(spec.param_value, spec.reversal_bricks)
    if spec.price_source != "last":
        raise BarSpecError("Renko bricks from the mark price are not available yet; use 'last'.")


class RenkoBarBuilder:
    """`BarBuilder` for `kind="renko"`; `tick_size_of` returns None for an unknown symbol."""

    def __init__(
        self, spec: BarSpec, symbol: str, tick_size_of: Callable[[str], Decimal | None]
    ) -> None:
        check_renko_spec(spec)
        tick = tick_size_of(symbol)
        if tick is None or tick <= 0:
            raise BarSpecError(f"No tick size is known for the symbol {symbol}.")
        self.spec, self.symbol, self._hash = spec, symbol, spec.spec_hash
        self._w = Decimal(spec.param_value) * tick  # frozen for this epoch (ADR-0033)
        self._rev = spec.reversal_bricks
        self._wick = spec.renko_wick
        self._anchor: Decimal | None = None  # close of the last brick (first trade: seed)
        self._dir = 0  # prevailing direction: 1 up, -1 down, 0 none yet
        self._cur: _Draft | None = None
        self._next = 0
        self._last_seq: int | None = None
        self._gap_pending = False  # #529: in memory only, never snapshotted
        self._gap_floor = -(2**63)  # `mark_gap`'s hole lower bound: only later prints take it
        self._built = bars_built_total.labels(symbol=symbol, kind="renko")
        self._multi = bar_renko_multi_brick_total.labels(symbol=symbol)
        self._revs = bar_renko_reversals_total.labels(symbol=symbol)
        self._lat = bar_build_latency_seconds.labels(kind="renko")

    def on_trade(self, t: TradeEvent) -> Sequence[BarUpdate]:
        t0 = time.perf_counter()
        if t.symbol != self.symbol:
            raise BarsError(f"Trade for {t.symbol} sent to the {self.symbol} renko builder.")
        self._last_seq = t.seq
        if self._anchor is None:
            self._anchor = t.price
        d = self._cur
        if d is None:
            d = self._cur = _Draft(self._next, 0, 0, t.price)
            d.partial = self._next == 0
        if (
            self._gap_pending and t.ts_event > self._gap_floor
        ):  # the run taking the first post-hole print
            d.gap_before, self._gap_pending = True, False
        d.apply(t)
        out = self._bricks(d, self._anchor, t.price - self._anchor)
        self._lat.observe(time.perf_counter() - t0)
        return out

    def mark_gap(self, floor_us: int) -> None:
        """An unrecovered tape gap precedes the next trade: its first brick carries `gap_before`."""
        self._gap_floor, self._gap_pending = floor_us, True

    def _bricks(self, d: _Draft, c: Decimal, diff: Decimal) -> Sequence[BarUpdate]:
        w, s = self._w, self._dir
        n = int(abs(diff) // w)
        sign = 1 if diff > 0 else -1
        if n == 0 or (s == -sign and n < self._rev):
            return (self._forming(d, c),)
        first = c
        if s == -sign:  # reversal: the first R-1 bricks of the move are its cost
            first = c + sign * (self._rev - 1) * w
            n -= self._rev - 1
            self._revs.inc()
        if n > MAX_BRICKS_PER_TRADE:  # bad print / outlier: refuse, the set quarantines us
            bars_print_rejected_total.labels(reason="renko").inc()  # BR-11 (#2294)
            raise BarsError(
                f"One trade would complete {n} renko bricks (cap {MAX_BRICKS_PER_TRADE})."
            )
        if n > 1:
            self._multi.inc()
        out: list[BarUpdate] = []
        for i in range(n):
            o = first + sign * i * w
            out.append(self._brick(d, o, o + sign * w, last=i == n - 1))
        self._anchor, self._dir, self._cur = first + sign * n * w, sign, None
        self._built.inc(n)
        return out

    def _forming(self, d: _Draft, c: Decimal) -> BarUpdate:
        """The brick in formation: provisional open at the anchor, carries the run's volume."""
        hi, lo = (d.high, d.low) if self._wick else (d.close, d.close)
        bar = self._bar(d, d.index, c, max(c, hi), min(c, lo), d.close, owner=True, closed=False)
        kind = "open" if d.count == 1 else "update"
        return RenkoBarUpdate.model_construct(
            kind=kind, bar=bar, volume_allocated=True, open_source_ts=d.first_ts
        )

    def _brick(self, d: _Draft, o: Decimal, c: Decimal, *, last: bool) -> BarUpdate:
        hi, lo = max(o, c), min(o, c)
        idx = self._next
        self._next += 1
        if self._wick:
            up = c > o
            if idx == d.index:  # first brick of the run: trailing wick
                lo, hi = (min(lo, d.low), hi) if up else (lo, max(hi, d.high))
            if last:  # leading wick
                lo, hi = (lo, max(hi, d.high)) if up else (min(lo, d.low), hi)
        bar = self._bar(d, idx, o, hi, lo, c, owner=last, closed=True)
        return RenkoBarUpdate.model_construct(
            kind="close", bar=bar, volume_allocated=last, open_source_ts=d.first_ts
        )

    def _bar(
        self,
        d: _Draft,
        idx: int,
        o: Decimal,
        hi: Decimal,
        lo: Decimal,
        c: Decimal,
        *,
        owner: bool,
        closed: bool,
    ) -> Bar:
        if owner:
            src = d.to_bar(self._hash, self.symbol, closed)
            vol = src.volume
            return src.model_copy(
                update={
                    "index": idx,
                    "open_time": d.first_ts,
                    "close_time": d.last_ts,
                    "open": o,
                    "high": hi,
                    "low": lo,
                    "close": c,
                    "partial": idx == 0,
                    "gap_before": d.gap_before and idx == d.index,
                    "vwap": src.vwap if vol else o,
                }
            )
        return Bar.model_construct(
            spec_hash=self._hash,
            symbol=self.symbol,
            index=idx,
            open_time=d.first_ts,
            close_time=d.last_ts,
            open=o,
            high=hi,
            low=lo,
            close=c,
            volume=_ZERO,
            buy_volume=_ZERO,
            sell_volume=_ZERO,
            delta=_ZERO,
            min_delta=_ZERO,
            max_delta=_ZERO,
            trade_count=0,
            turnover=_ZERO,
            vwap=o,
            closed=True,
            partial=idx == 0,
            gap_before=d.gap_before and idx == d.index,
            synthetic=False,
        )

    def on_clock(self, now_us: TsUs) -> Sequence[BarUpdate]:
        return _NONE  # bricks never close on the clock

    def snapshot(self) -> BuilderState:
        """Versioned orjson state; carries the prevailing direction and the frozen width (BI-5)."""
        doc = {
            "cur": None if self._cur is None else self._cur.dump(),
            "next": self._next,
            "anchor": None if self._anchor is None else str(self._anchor),
            "dir": self._dir,
            "width": str(self._w),
        }
        return BuilderState(
            spec_hash=self._hash,
            symbol=self.symbol,
            state_version=STATE_VERSION,
            last_trade_seq=self._last_seq,
            blob=orjson.dumps(doc),
        )

    def restore(self, state: BuilderState) -> None:
        if (state.spec_hash, state.symbol) != (self._hash, self.symbol):
            raise BarsError("The builder state belongs to a different symbol or bar spec.")
        if state.state_version != STATE_VERSION:
            raise BarsError(f"Builder state version {state.state_version} is not supported.")
        try:
            doc = orjson.loads(state.blob)
            cur, nxt, anchor, direction, width = (
                doc["cur"], doc["next"], doc["anchor"], doc["dir"], doc["width"]
            )  # fmt: skip
            w = Decimal(width)
            a = None if anchor is None else Decimal(anchor)
            d = None if cur is None else _Draft.load(cur)
        except (KeyError, TypeError, ValueError, ArithmeticError) as e:  # JSON/Decimal errors
            raise BarsError("The renko builder state is incomplete or corrupt.") from e
        if w != self._w:  # ADR-0033: a tick-size change starts a new epoch
            raise BarsError("The renko state was built with another brick size; start a new epoch.")
        if direction not in (-1, 0, 1):
            raise BarsError("The renko builder state has an invalid direction.")
        self._cur, self._next, self._dir, self._anchor = d, nxt, direction, a
        self._last_seq = state.last_trade_seq

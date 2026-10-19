"""Tick and volume bar builders (`24-internal-schemas.md` §3.3, ticket E12-S02).

Hot path (C-2.20): plain synchronous code, no statechart. Both builders reuse the
`time_builder._Draft` accumulator and materialise a frozen `Bar` only on emit.

Shared rules (tick and volume bars are activity bars, not time-aligned):
- `open_time`/`close_time` are the `ts_event` of the first/last trade in the bar (event order
  `(ts_event, seq)`), matching `/market/bars`.
- Trades are folded in arrival order. A closed bar is final: a late or out-of-order trade
  goes into the open bar, never back into a closed one (re-splitting closed volume bars
  would renumber the series). Duplicate suppression is upstream (`TradeStream`).
- `gap_before` is always `False`: these builders see no data-gap signal; the recorder
  marks gaps (E16).
- The first bar of a fresh builder has `partial=True`; its `open_time` is the timestamp
  where the available tape begins. Only trades are consumed, never REST klines.
- `on_clock` is a no-op: activity bars never close on the clock.
- A bar closed by the same trade that opened it emits only `close` (no `open`).

Tick bars close on exactly `tick_count` trade events, however they were batched. Block
trades count as one tick each (`exclude_block_trades` is not in `BarSpec` yet; see PR).

Volume bars close at exactly `volume_threshold` (Decimal). A trade that overshoots is split:
the bar takes the remaining quota and closes, and the remainder opens the next bar at the
same price, timestamp and side, so BI-1 holds. A print spanning N thresholds closes N
identical flat bars. Both emissions of a split carry `split_from_trade_id`. A split trade
counts once in `trade_count` of every bar that holds a part of it.

SR-E12-15: one print closes at most `MAX_BRICKS_PER_TRADE` bars (the remainder that opens the next
bar is not a close). The check comes before any state changes, and a print over it raises
`BarsError`, as the renko builder does: the builder is left as if the print never arrived, and on
the live path `BarBuilderSet` quarantines, counts and logs the series. Tick, delta and range bars
never split a trade, so each emits one update per print and needs no such check.

The bound is exact for thresholds of at most 25 significant digits (the wire takes whole numbers up
to 10^12); a 26 to 28 digit threshold built directly can close one bar more or fewer, and can
refuse a print that closes exactly 1 000.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Final

import orjson
import structlog

from candleviewer.bars.errors import BarsError, BarSpecError
from candleviewer.bars.limits import MAX_BRICKS_PER_TRADE
from candleviewer.bars.models import BarSpec, BarUpdate, BuilderState
from candleviewer.bars.time_builder import _NONE, _Draft, bars_built_total
from candleviewer.domain.primitives import TsUs
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.observability.metrics import Counter

STATE_VERSION: Final = 1
#: Smallest `tick_count` a builder accepts.
MIN_TICK_COUNT: Final = 1
#: Smallest `tick_count` for a subscribable series, per the E12 threat model SR-E12-03 / BR-29
#: (`tick` 100..1 000 000; reject, never clamp). E12-T05/T06 enforce it: `tick:1` over 30 days
#: is one bar per trade, a CPU and storage exhaustion vector.
MIN_SUBSCRIBABLE_TICK_COUNT: Final = 100
_SPLIT_WARN_MIN_TRADES: Final = 1_000
_ZERO: Final = Decimal(0)

bar_volume_splits_total = Counter(
    "bar_volume_splits_total", "Trades split across volume bars.", labelnames=("symbol",)
)
bars_partial_series_total = Counter(
    "bars_partial_series_total",
    "Series whose first bar is partial (tape starts mid-bar).",
    labelnames=("kind",),
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class ActivityBarUpdate(BarUpdate):
    """`BarUpdate` plus `split_from_trade_id`: the id of the trade split by this emission
    (set on the `close` that took the head and on the emission that took the remainder).

    Stop-gap (#2012): the persisted row and wire payload need a
    contract change first (21 §4.8, `/market/bars`).
    """

    split_from_trade_id: str | None = None


def _check(spec: BarSpec, kind: str) -> None:
    if spec.kind != kind:
        raise BarSpecError(f"A {kind}-bar builder needs a bar spec of kind '{kind}'.")
    if kind == "tick" and int(spec.param_value) < MIN_TICK_COUNT:  # pragma: no cover - spec gt=0
        raise BarSpecError(f"tick_count must be at least {MIN_TICK_COUNT}.")


class _ActivityBuilder:
    """Shared state, emit and snapshot for tick and volume bars."""

    _kind: str

    def __init__(self, spec: BarSpec, symbol: str) -> None:
        _check(spec, self._kind)
        self.spec = spec
        self.symbol = symbol
        self._hash = spec.spec_hash
        self._cur: _Draft | None = None
        self._next_index = 0
        self._last_seq: int | None = None
        self._built = bars_built_total.labels(symbol=symbol, kind=self._kind)

    def _check_symbol(self, t: TradeEvent) -> None:
        # `VolumeBarBuilder.on_trade` calls this directly (the cap check must come before the
        # last-seq write); keep it in step with `_guard`.
        if t.symbol != self.symbol:
            raise BarsError(f"Trade for {t.symbol} sent to the {self.symbol} {self._kind} builder.")

    def _guard(self, t: TradeEvent) -> None:
        # Not called by `VolumeBarBuilder.on_trade` (see `_check_symbol`): keep the two in step.
        self._check_symbol(t)
        self._last_seq = t.seq

    def _draft(self, t: TradeEvent) -> _Draft:
        cur = self._cur
        if cur is None:
            cur = self._cur = _Draft(self._next_index, 0, 0, t.price)
            cur.partial = self._next_index == 0
            if cur.partial:
                bars_partial_series_total.labels(kind=self._kind).inc()
            self._next_index += 1
        return cur

    def _emit(self, d: _Draft, closed: bool, split: str | None = None) -> ActivityBarUpdate:
        d.open_time, d.close_time = d.first_ts, d.last_ts
        kind = "close" if closed else ("open" if d.count == 1 else "update")
        bar = d.to_bar(self._hash, self.symbol, closed)
        if closed:
            self._cur = None
            self._built.inc()
        return ActivityBarUpdate.model_construct(kind=kind, bar=bar, split_from_trade_id=split)

    def on_clock(self, now_us: TsUs) -> Sequence[BarUpdate]:
        return _NONE

    def snapshot(self) -> BuilderState:
        """Versioned orjson draft, same envelope as `TimeBarBuilder.snapshot` (#1987)."""
        doc = {"cur": None if self._cur is None else self._cur.dump(), "next": self._next_index}
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
        doc = orjson.loads(state.blob)
        self._cur = None if doc["cur"] is None else _Draft.load(doc["cur"])
        self._next_index = doc["next"]
        self._last_seq = state.last_trade_seq


class TickBarBuilder(_ActivityBuilder):
    """`BarBuilder` for `kind="tick"`. See the module docstring."""

    _kind = "tick"

    def __init__(self, spec: BarSpec, symbol: str) -> None:
        super().__init__(spec, symbol)
        self._n = int(spec.param_value)

    def on_trade(self, t: TradeEvent) -> Sequence[BarUpdate]:
        self._guard(t)
        d = self._draft(t)
        d.apply(t)
        return (self._emit(d, closed=d.count >= self._n),)


class VolumeBarBuilder(_ActivityBuilder):
    """`BarBuilder` for `kind="volume"`. See the module docstring."""

    _kind = "volume"

    def __init__(self, spec: BarSpec, symbol: str) -> None:
        super().__init__(spec, symbol)
        self._quota = Decimal(spec.param_value)
        self._cap_qty = MAX_BRICKS_PER_TRADE * self._quota  # SR-E12-15: the overshoot it refuses
        self._splits = bar_volume_splits_total.labels(symbol=symbol)
        self._n_trades = self._n_splits = 0
        self._warned = False

    def on_trade(self, t: TradeEvent) -> Sequence[BarUpdate]:
        self._check_symbol(t)
        px, ts, seq, buy, rem = t.price, t.ts_event, t.seq, t.side == "buy", t.qty
        cur = self._cur
        room = self._quota if cur is None else self._quota - cur.buy - cur.sell
        # SR-E12-15: a print that reaches the room closes 1 + (rem - room) // quota bars, more than
        # the cap iff rem - room >= `_cap_qty`. Refused before any state changes, so the builder is
        # left as if it never arrived. `rem >= room` first: the common path skips the subtraction.
        if rem >= room and rem - room >= self._cap_qty:
            raise self._refusal(rem - room)
        self._last_seq = seq
        self._n_trades += 1
        d = self._draft(t)
        if rem < room:  # common path: no close, no split
            d.fold(px, rem, ts, seq, buy)
            return (self._emit(d, closed=False),)
        split = t.trade_id if rem > room else None
        out: list[BarUpdate] = []
        while True:  # bounded: one iteration per close (at most the cap), plus one for a remainder
            take = room if rem > room else rem
            d.fold(px, take, ts, seq, buy)
            rem -= take
            if take == room:
                out.append(self._emit(d, closed=True, split=split))
            if rem == _ZERO:
                break
            d = self._draft(t)
            room = self._quota
        if self._cur is not None:
            out.append(self._emit(self._cur, closed=False, split=split))
        if split is not None:
            self._split_seen()
        return out

    def _refusal(self, over: Decimal) -> BarsError:
        """The refusal of a print that overshoots the open bar's room by `over`. The count is for
        the message only: a quotient past the Decimal context reads "over 1000", never raises."""
        try:
            count = f"{1 + int(over // self._quota)}"
        except ArithmeticError:
            count = f"over {MAX_BRICKS_PER_TRADE}"
        return BarsError(f"One trade would close {count} volume bars (cap {MAX_BRICKS_PER_TRADE}).")

    def _split_seen(self) -> None:
        self._splits.inc()
        self._n_splits += 1
        n = self._n_trades
        if not self._warned and n >= _SPLIT_WARN_MIN_TRADES and self._n_splits * 100 >= n * 99:
            self._warned = True
            _log().warning(
                "bars_volume_split_rate_high",
                symbol=self.symbol,
                spec_hash=self._hash,
                hint="volume_threshold is probably smaller than typical trade size",
            )

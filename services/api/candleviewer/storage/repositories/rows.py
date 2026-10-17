"""Market-data row types for the hot read/write path (M10).

`slots=True` dataclasses, not pydantic models: the ticket's "Performance
notes" is explicit that market-data rows on the read path must avoid pydantic
validation/ORM hydration cost so the `<100 ms for 100k bars` budget
(`docs/plan/20-architecture.md` Sec.13.2) is reachable. `msgspec.Struct` is
the eventual target once that dependency is added to `services/api/
pyproject.toml` by an engine-facing ticket (E07-T02/T03); slotted dataclasses
give the same "no `__dict__`, no validation" shape today with zero new
dependencies, and are a drop-in rename later.

All timestamps are integer microseconds UTC (matching `TimeRange`), never
`datetime`, for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class TradeRow:
    """One executed trade print."""

    ts_us: int
    symbol: str
    price: str  # Decimal-precision string; callers parse with `Decimal()`
    qty: str
    side: str  # "buy" | "sell" (taker side)
    trade_id: str


@dataclass(slots=True, frozen=True)
class TradeTotals:
    """How many prints one symbol has in a `TimeRange`, and their summed qty (#2093)."""

    prints: int
    qty: Decimal  # the store's sum of the prints' qty; 0 when there are none


@dataclass(slots=True, frozen=True)
class BookDeltaRow:
    """One order-book delta (post-snapshot, sequence-checked upstream)."""

    ts_us: int
    symbol: str
    seq: int
    side: str  # "bid" | "ask"
    price: str
    qty: str  # "0" means the level was removed


@dataclass(slots=True, frozen=True)
class BookSnapshotRow:
    """A full order-book snapshot at a point in time, up to `depth` levels."""

    ts_us: int
    symbol: str
    seq: int
    bids: tuple[tuple[str, str], ...]  # ((price, qty), ...) best-first
    asks: tuple[tuple[str, str], ...]


@dataclass(slots=True, frozen=True)
class TickerRow:
    """One ticker update (mark/index/last price, funding, open interest)."""

    ts_us: int
    symbol: str
    last_price: str
    mark_price: str
    index_price: str
    funding_rate: str
    open_interest: str
    bid1_price: str | None = None
    bid1_size: str | None = None
    ask1_price: str | None = None
    ask1_size: str | None = None


@dataclass(slots=True, frozen=True)
class BarRow:
    """One OHLCV bar for a given `(family, param)` spec.

    `family`/`param` mirror `docs/plan/24-internal-schemas.md`
    `EngineConfig.default_bar_specs` (e.g. `family="time"`,
    `param="60000"` for a 1-minute time bar) — the read Protocol's
    `read_bars(sym, family, param, rng, tier)` signature.
    """

    ts_us: int
    symbol: str
    family: str
    param: str
    open: str
    high: str
    low: str
    close: str
    volume: str


@dataclass(slots=True, frozen=True)
class KlineRow:
    """One exchange kline / cross-check bar (E08-S06, `docs/plan/
    21-database-schema.md` §4.5). `confirmed=False` rows are the
    in-progress bar and MUST NOT be treated as a closed candle by any
    reader — mirrors `KlineEvent`'s own docstring."""

    ts_us: int
    symbol: str
    interval: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str
    confirmed: bool
    source: str = "rest"


@dataclass(slots=True, frozen=True)
class OrderflowMetricRow:
    """One aggregated order-flow metric sample (CVD, imbalance, ...)."""

    ts_us: int
    symbol: str
    metric: str
    value: str


@dataclass(slots=True, frozen=True)
class FootprintCellRow:
    """One footprint cell: a `(bar, price level)` bid/ask volume pair."""

    bar_ts_us: int
    symbol: str
    price_level: str
    bid_qty: str
    ask_qty: str

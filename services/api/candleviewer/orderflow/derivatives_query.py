"""The `/market/metrics` read side of the derivatives engine (E24-T04 PR B, #723).

One request is one engine: the stored bars, OI points, settled funding and liquidation prints of
the window, plus the latest ticker snapshot, are loaded into a fresh `DerivativesEngine`, and
every value is read through `metric_value`, the read path a pane and a rule condition share.

Module boundary (C-3.1): orderflow may not import `storage`, `bars`, `ingestion` or the exchange
adapter, so every source is a local structural Protocol the composition root injects.

Bounds (C-2.18, STRIDE D12; 22 `/market/metrics`), all checked before any store read: at most
`MAX_WINDOW_BARS` bars and `MAX_WINDOW_DAYS` days, and at most `MAX_OI_ROWS` OI points estimated
from the window and the OI series read. A read that returns more than its cap (liquidations,
funding) refuses the request rather than summing a truncated window. Every read shares one
`QUERY_TIMEOUT_S` deadline.

The OI series is the coarsest one that still gives two samples per bar (`oi_interval_for`): a
bar whose only sample is its own open would read a flat delta, never the move.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from candleviewer.domain.funding import HasFundingInterval, resolve_funding_interval_minutes
from candleviewer.domain.liquidations import LiqPrint
from candleviewer.domain.open_interest import INTERVAL_US, REST_INTERVALS, source_of
from candleviewer.orderflow.deriv_limits import US_PER_DAY, DerivInvalidRequest, DerivSymbolUnlisted
from candleviewer.orderflow.derivatives import (
    DESCRIPTORS,
    MAX_BARS,
    OI_STALENESS_MS,
    BarMetrics,
    DerivativesEngine,
    DerivBar,
    FundingRow,
    InstrumentMeta,
    LiquidatedSide,
    LiquidationPrint,
    OiSample,
    TickerSnapshot,
)
from candleviewer.orderflow.funding import FundingStore
from candleviewer.orderflow.liquidations import LiquidationStore
from candleviewer.orderflow.open_interest import OiStore

MAX_WINDOW_BARS: Final = MAX_BARS
DEFAULT_WINDOW_BARS: Final = 500
MAX_WINDOW_DAYS: Final = 400
MAX_OI_ROWS: Final = 250_000
MAX_LIQ_PRINTS: Final = 100_000
MAX_FUNDING_ROWS: Final = 10_000
QUERY_TIMEOUT_S: Final = 10.0

#: Every 22 `MetricCode` this engine serves -> its 24 §7.2 descriptor (two codes are aliases).
DERIVATIVE_CODES: Final[Mapping[str, str]] = {
    **{name: name for name in DESCRIPTORS},
    "funding_basis": "basis",
    "liquidation_intensity": "liquidation_notional",
}


class BarSource(Protocol):
    """Stored time bars of `interval_ms` opening in `[start_us, end_us)`, at most `limit`."""

    async def __call__(
        self, symbol: str, interval_ms: int, start_us: int, end_us: int, limit: int
    ) -> Sequence[DerivBar]: ...


class TickerLike(Protocol):
    @property
    def ts_event(self) -> int: ...
    @property
    def last_price(self) -> Decimal | None: ...
    @property
    def mark_price(self) -> Decimal | None: ...
    @property
    def index_price(self) -> Decimal | None: ...
    @property
    def funding_rate(self) -> Decimal | None: ...
    @property
    def next_funding_time(self) -> int | None: ...


class TickerLatest(Protocol):
    def latest(self, symbol: str) -> TickerLike | None: ...


@dataclass(frozen=True, slots=True)
class Window:
    start_us: int
    end_us: int


def oi_interval_for(interval_ms: int) -> str:
    """The coarsest OI history interval with at least two samples per bar, else the 1 s series."""
    fits = [i for i in REST_INTERVALS if 2 * INTERVAL_US[i] <= interval_ms * 1000]
    return fits[-1] if fits else "1s"


def plan_window(
    start_us: int | None, end_us: int | None, *, interval_ms: int, now_us: int
) -> Window:
    """Resolve and bound `[from, to)`, or raise `DerivInvalidRequest` (no store is read)."""
    step = interval_ms * 1000
    span_cap = MAX_WINDOW_DAYS * US_PER_DAY
    end = end_us if end_us is not None else now_us
    start = start_us if start_us is not None else end - min(DEFAULT_WINDOW_BARS * step, span_cap)
    span = end - start
    if span <= 0 or span > span_cap or -(-span // step) > MAX_WINDOW_BARS:
        raise DerivInvalidRequest(
            "invalid_time_range",
            f"from/to must be ordered and span <= {MAX_WINDOW_DAYS} days "
            f"and <= {MAX_WINDOW_BARS} bars",
        )
    oi_rows = (span + OI_STALENESS_MS * 1000) // INTERVAL_US[oi_interval_for(interval_ms)]
    if oi_rows > MAX_OI_ROWS:
        raise DerivInvalidRequest(
            "invalid_time_range", "the window holds too many open-interest points; narrow it"
        )
    return Window(start, end)


def _capped[R](rows: Sequence[R], cap: int, what: str) -> Sequence[R]:
    if len(rows) > cap:
        raise DerivInvalidRequest(
            "invalid_time_range", f"the window holds more than {cap} {what}; narrow it"
        )
    return rows


def _liquidation(p: LiqPrint) -> LiquidationPrint:
    """A long is closed by a sell, a short by a buy (`domain.liquidations.closing_side`)."""
    side: LiquidatedSide = "long" if p.side == "sell" else "short"
    return LiquidationPrint(p.ts_us // 1000, side, p.notional, p.batch_index)


def _snapshot(t: TickerLike) -> TickerSnapshot:
    nft = t.next_funding_time
    return TickerSnapshot(
        ts_ms=t.ts_event // 1000,
        last_price=t.last_price,
        mark_price=t.mark_price,
        index_price=t.index_price,
        funding_rate=t.funding_rate,
        next_funding_time_ms=None if nft is None else nft // 1000,
    )


class DerivativesQuery:
    def __init__(
        self,
        *,
        bars: BarSource,
        oi: OiStore,
        funding: FundingStore,
        liquidations: LiquidationStore,
        instrument: Callable[[str], HasFundingInterval | None],
        listed: Callable[[str], bool | None],
        tickers: Callable[[], TickerLatest | None],
        timeout_s: float = QUERY_TIMEOUT_S,
    ) -> None:
        self._bars, self._oi, self._funding, self._liqs = bars, oi, funding, liquidations
        self._instrument, self._listed, self._tickers = instrument, listed, tickers
        self._timeout_s = timeout_s

    def check_symbol(self, symbol: str) -> InstrumentMeta:
        """`DerivSymbolUnlisted` for an unlisted symbol; `FundingIntervalUnknown` while the
        catalogue cannot give its funding interval. Reads no store."""
        if self._listed(symbol) is False:
            raise DerivSymbolUnlisted(symbol)
        return InstrumentMeta(resolve_funding_interval_minutes(self._instrument(symbol)))

    async def compute(
        self, symbol: str, meta: InstrumentMeta, *, interval_ms: int, window: Window
    ) -> tuple[BarMetrics, ...]:
        """Load the window into a fresh engine; one deadline over every read (`TimeoutError`)."""
        start, end = window.start_us, window.end_us
        stale_us = OI_STALENESS_MS * 1000
        oi_interval = oi_interval_for(interval_ms)
        settle_us = meta.funding_interval_min * 60_000_000  # the settlement after the last bar
        async with asyncio.timeout(self._timeout_s):
            bars = await self._bars(symbol, interval_ms, start, end, MAX_WINDOW_BARS)
            oi = await self._oi.read_points(
                symbol, oi_interval, source_of(oi_interval),
                Window(start - stale_us, end), MAX_OI_ROWS + 1,
            )  # fmt: skip
            funding = await self._funding.read_settled(
                symbol, Window(start, end + settle_us), MAX_FUNDING_ROWS + 1
            )
            liqs = await self._liqs.read_prints(symbol, window, None, MAX_LIQ_PRINTS + 1)
        grid = sorted(bars, key=lambda b: b.start_ms)[-MAX_WINDOW_BARS:]
        if not grid:
            return ()
        # Rows past the last stored bar are read by no bar: never handed to the engine, so a
        # grid that stops early cannot fill its pending queue (`DerivativesBackpressure`).
        last_us = grid[-1].end_ms * 1000
        source = self._tickers()
        latest = source.latest(symbol) if source is not None else None
        engine = DerivativesEngine(meta, count_none=False)
        return engine.load(
            grid,
            oi=[
                OiSample(p.ts_us // 1000, p.open_interest, p.open_interest_value, p.source)
                for p in _capped(oi, MAX_OI_ROWS, "open-interest points")
                if p.ts_us < last_us
            ],
            funding=[
                FundingRow(r.ts_us // 1000, r.funding_rate)
                for r in _capped(funding, MAX_FUNDING_ROWS, "funding settlements")
            ],
            liquidations=[
                _liquidation(p)
                for p in _capped(liqs, MAX_LIQ_PRINTS, "liquidation prints")
                if p.ts_us < last_us
            ],
            tickers=() if latest is None else (_snapshot(latest),),
        )


__all__ = [
    "DEFAULT_WINDOW_BARS",
    "DERIVATIVE_CODES",
    "MAX_FUNDING_ROWS",
    "MAX_LIQ_PRINTS",
    "MAX_OI_ROWS",
    "MAX_WINDOW_BARS",
    "MAX_WINDOW_DAYS",
    "QUERY_TIMEOUT_S",
    "BarSource",
    "DerivativesQuery",
    "TickerLatest",
    "Window",
    "oi_interval_for",
    "plan_window",
]

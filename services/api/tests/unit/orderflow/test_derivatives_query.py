"""E24-T04 PR B (#723): the derivatives engine fed from the stores for `/market/metrics`.

In-memory stores and a fake bar source; no network, no clock (C-13.5, C-13.7).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import pytest

from candleviewer.domain.funding import FundingIntervalUnknown, settle
from candleviewer.domain.liquidations import LiqPrint
from candleviewer.domain.open_interest import OiPoint
from candleviewer.orderflow.deriv_limits import DerivInvalidRequest, DerivSymbolUnlisted
from candleviewer.orderflow.derivatives import (
    DerivativesEngine,
    DerivBar,
    FundingRow,
    InstrumentMeta,
    LiquidationPrint,
    OiSample,
    TickerSnapshot,
    metric_value,
)
from candleviewer.orderflow.derivatives_query import (
    DEFAULT_WINDOW_BARS,
    DERIVATIVE_CODES,
    MAX_LIQ_PRINTS,
    MAX_WINDOW_BARS,
    DerivativesQuery,
    Window,
    oi_interval_for,
    plan_window,
)
from candleviewer.storage.questdb.funding_store import InMemoryFundingStore
from candleviewer.storage.questdb.liquidation_store import InMemoryLiquidationStore
from candleviewer.storage.questdb.oi_store import InMemoryOiStore

S = 1_000_000
MIN_US = 60 * S
T0 = 1_757_844_900 * S  # 2025-09-14T10:15:00Z, on the 15-minute grid
BAR_MS = 15 * 60_000
SYM = "BTCUSDT"


@dataclass(frozen=True)
class _Inst:
    funding_interval_min: int = 480


@dataclass(frozen=True)
class _Ticker:
    ts_event: int
    last_price: Decimal | None
    mark_price: Decimal | None
    index_price: Decimal | None
    funding_rate: Decimal | None
    next_funding_time: int | None


class _Tickers:
    def __init__(self, ticker: _Ticker | None) -> None:
        self.ticker = ticker

    def latest(self, symbol: str) -> _Ticker | None:
        return self.ticker


_PRICES = ((Decimal(100), Decimal(101)), (Decimal(101), Decimal(100)), (Decimal(100), Decimal(100)))
TICKER = _Ticker(T0 + 40 * MIN_US, Decimal("100.5"), Decimal("100.4"), Decimal("100.0"),
                 Decimal("0.0002"), T0 + 60 * MIN_US)  # fmt: skip


class _Bars:
    def __init__(self, bars: Sequence[DerivBar]) -> None:
        self.bars, self.calls = list(bars), 0

    async def __call__(
        self, symbol: str, interval_ms: int, start_us: int, end_us: int, limit: int
    ) -> Sequence[DerivBar]:
        self.calls += 1
        return [b for b in self.bars if start_us <= b.start_ms * 1000 < end_us][:limit]


def _grid() -> list[DerivBar]:
    return [
        DerivBar(T0 // 1000 + i * BAR_MS, T0 // 1000 + (i + 1) * BAR_MS, o, c)
        for i, (o, c) in enumerate(_PRICES)
    ]


# OI 5-minute history (`rest`, no value) up to 10:40: bars 0 and 1 rise, bar 2 has no sample.
_OI = [OiPoint(T0 + k * 5 * MIN_US, SYM, Decimal(1000 + 10 * k), None, "5min", "rest")
       for k in range(-1, 6)]  # fmt: skip
_LIQS = [
    LiqPrint(T0 + 1 * MIN_US, SYM, "sell", Decimal(1), Decimal(1), Decimal(10), 0),  # long
    LiqPrint(T0 + 16 * MIN_US, SYM, "buy", Decimal(1), Decimal(1), Decimal(5), 0),  # short
    LiqPrint(T0 + 16 * MIN_US, SYM, "buy", Decimal(1), Decimal(1), Decimal(5), 1),  # its twin
]


async def _query(
    *, listed: bool | None = True, inst: _Inst | None = None, ticker: _Ticker | None = TICKER,
    bars: _Bars | None = None, timeout_s: float = 10.0, extra_liqs: Sequence[LiqPrint] = (),
) -> tuple[DerivativesQuery, _Bars]:  # fmt: skip
    oi, funding, liqs = InMemoryOiStore(), InMemoryFundingStore(), InMemoryLiquidationStore()
    await oi.write_points(_OI)
    await funding.write_settled([settle(SYM, T0 + 60 * MIN_US, Decimal("0.0001"), 480)])
    await liqs.write_prints([*_LIQS, *extra_liqs])
    source = bars or _Bars(_grid())
    query = DerivativesQuery(
        # The in-memory funding store takes the concrete `TimeRange`; `Window` is one.
        bars=source, oi=oi, funding=funding, liquidations=liqs,  # type: ignore[arg-type]
        instrument=lambda s: inst if inst is not None else _Inst(), listed=lambda s: listed,
        tickers=lambda: _Tickers(ticker), timeout_s=timeout_s,
    )  # fmt: skip
    return query, source


WINDOW = Window(T0, T0 + 3 * BAR_MS * 1000)


def test_oi_interval_gives_two_samples_per_bar() -> None:
    assert [oi_interval_for(m * 60_000) for m in (1, 5, 10, 15, 60, 240, 1440)] == [
        "1s", "1s", "5min", "5min", "30min", "1h", "4h"
    ]  # fmt: skip


def test_plan_window_defaults_to_500_bars_before_now() -> None:
    w = plan_window(None, None, interval_ms=60_000, now_us=T0)
    assert (w.start_us, w.end_us) == (T0 - DEFAULT_WINDOW_BARS * MIN_US, T0)


def test_plan_window_default_is_clamped_to_400_days_on_daily_bars() -> None:
    w = plan_window(None, None, interval_ms=86_400_000, now_us=T0)
    assert w.end_us - w.start_us == 400 * 86_400 * S


@pytest.mark.parametrize(
    ("start", "end", "interval_ms"),
    [
        (T0, T0, 60_000),  # empty
        (T0 + MIN_US, T0, 60_000),  # unordered
        (T0, T0 + (MAX_WINDOW_BARS + 1) * MIN_US, 60_000),  # 1 501 bars
        (T0, T0 + 401 * 86_400 * S, 86_400_000),  # over 400 days
        (T0, T0 + 1000 * 5 * MIN_US, 300_000),  # 1 000 five-minute bars: 300 000 OI points
    ],
)
def test_plan_window_refuses_an_oversized_or_unordered_window(
    start: int, end: int, interval_ms: int
) -> None:
    with pytest.raises(DerivInvalidRequest) as exc:
        plan_window(start, end, interval_ms=interval_ms, now_us=T0)
    assert exc.value.code == "invalid_time_range"


def test_plan_window_accepts_the_full_1500_one_minute_bars() -> None:
    w = plan_window(T0, T0 + MAX_WINDOW_BARS * MIN_US, interval_ms=60_000, now_us=T0)
    assert w.end_us - w.start_us == MAX_WINDOW_BARS * MIN_US


def test_derivative_codes_alias_the_two_declared_codes() -> None:
    assert DERIVATIVE_CODES["funding_basis"] == "basis"
    assert DERIVATIVE_CODES["liquidation_intensity"] == "liquidation_notional"
    assert len(DERIVATIVE_CODES) == 12


async def test_compute_feeds_every_store_into_one_engine() -> None:
    query, _ = await _query()
    rows = await query.compute(SYM, query.check_symbol(SYM), interval_ms=BAR_MS, window=WINDOW)
    assert [metric_value(m, "oi_price_quadrant") for m in rows] == [
        "long_buildup", "short_buildup", None
    ]  # fmt: skip
    assert [metric_value(m, "open_interest_delta") for m in rows] == [Decimal(20), Decimal(20),
                                                                       None]  # fmt: skip
    assert [metric_value(m, "open_interest_value") for m in rows] == [None, None, None]
    liq = [
        tuple(metric_value(m, "liquidation_notional", {"side": s}) for s in ("long", "short"))
        for m in rows
    ]
    assert liq == [(Decimal(10), 0), (0, Decimal(10)), (0, 0)]
    assert metric_value(rows[0], "funding_rate") == Decimal("0.0100")  # the settled fallback
    assert metric_value(rows[2], "funding_rate") == Decimal("0.0200")  # the latest snapshot
    assert metric_value(rows[2], "basis") == Decimal("0.5")
    assert metric_value(rows[2], "basis", {"source": "mark"}) == Decimal("0.4")
    assert metric_value(rows[2], "premium_pct") == Decimal("0.500")
    assert metric_value(rows[1], "basis") is None  # no stored ticker snapshot for a past bar


async def test_compute_equals_an_engine_loaded_with_the_same_rows() -> None:
    """One number: the store-fed read equals the engine a pane or a rule loads directly."""
    query, _ = await _query()
    rows = await query.compute(SYM, query.check_symbol(SYM), interval_ms=BAR_MS, window=WINDOW)
    direct = DerivativesEngine(InstrumentMeta(480)).load(
        _grid(),
        oi=[OiSample(p.ts_us // 1000, p.open_interest, None, "rest") for p in _OI],
        funding=[FundingRow((T0 + 60 * MIN_US) // 1000, Decimal("0.0001"))],
        liquidations=[
            LiquidationPrint(T0 // 1000 + 60_000, "long", Decimal(10), 0),
            LiquidationPrint(T0 // 1000 + 16 * 60_000, "short", Decimal(5), 0),
            LiquidationPrint(T0 // 1000 + 16 * 60_000, "short", Decimal(5), 1),
        ],
        tickers=[TickerSnapshot(TICKER.ts_event // 1000, TICKER.last_price, TICKER.mark_price,
                                TICKER.index_price, TICKER.funding_rate,
                                (T0 + 60 * MIN_US) // 1000)],
    )  # fmt: skip
    assert rows == direct


async def test_compute_of_an_empty_grid_reads_nothing_more_and_returns_no_bar() -> None:
    query, bars = await _query(bars=_Bars([]))
    assert await query.compute(SYM, InstrumentMeta(480), interval_ms=BAR_MS, window=WINDOW) == ()
    assert bars.calls == 1


async def test_compute_drops_rows_past_the_last_stored_bar() -> None:
    """A grid that stops early never fills the engine's pending queue (backpressure)."""
    query, _ = await _query(bars=_Bars(_grid()[:1]))
    rows = await query.compute(SYM, InstrumentMeta(480), interval_ms=BAR_MS, window=WINDOW)
    assert len(rows) == 1 and metric_value(rows[0], "liquidation_notional") == Decimal(10)


async def test_compute_without_a_ticker_has_no_basis() -> None:
    query, _ = await _query(ticker=None)
    rows = await query.compute(SYM, InstrumentMeta(480), interval_ms=BAR_MS, window=WINDOW)
    assert [metric_value(m, "basis") for m in rows] == [None, None, None]


async def test_compute_refuses_a_window_over_the_liquidation_read_cap() -> None:
    many = [LiqPrint(T0 + i, SYM, "buy", Decimal(1), Decimal(1), Decimal(1), 0)
            for i in range(MAX_LIQ_PRINTS)]  # fmt: skip
    query, _ = await _query(extra_liqs=many)  # with the three seeded prints: over the cap
    with pytest.raises(DerivInvalidRequest) as exc:
        await query.compute(SYM, InstrumentMeta(480), interval_ms=BAR_MS, window=WINDOW)
    assert exc.value.code == "invalid_time_range"


async def test_compute_has_one_deadline_over_every_read() -> None:
    class _Slow(_Bars):
        async def __call__(self, *a: object, **kw: object) -> Sequence[DerivBar]:
            await asyncio.Event().wait()  # never set: only the deadline ends it
            return []

    query, _ = await _query(bars=_Slow([]), timeout_s=0.01)
    with pytest.raises(TimeoutError):
        await query.compute(SYM, InstrumentMeta(480), interval_ms=BAR_MS, window=WINDOW)


async def test_check_symbol_refuses_an_unlisted_symbol_before_any_read() -> None:
    query, bars = await _query(listed=False)
    with pytest.raises(DerivSymbolUnlisted):
        query.check_symbol(SYM)
    assert bars.calls == 0


async def test_check_symbol_needs_the_funding_interval() -> None:
    query, _ = await _query(inst=_Inst(funding_interval_min=0))
    with pytest.raises(FundingIntervalUnknown):
        query.check_symbol(SYM)

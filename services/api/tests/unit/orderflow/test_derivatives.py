"""E24-T04 DerivativesEngine: the 24 §7.2 Derivatives formulas, the None case, bucketing and the
incremental path. Synthetic in-memory rows only (no network, no fixtures needed: inputs are plain
rows and the engine is pure)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.domain.funding import FundingIntervalUnknown
from candleviewer.orderflow.derivatives import (
    OI_STALENESS_MS,
    BarMetrics,
    DerivativesEngine,
    DerivativesInputError,
    DerivBar,
    FundingRow,
    InstrumentMeta,
    LiquidationPrint,
    OiSample,
    TickerSnapshot,
    classify_quadrant,
    metric_value,
)

D = Decimal
H = 3_600_000
DAY = 24 * H
T0 = 20_000 * DAY  # a UTC midnight


def bar(i: int, o: str = "100", c: str = "101", width: int = H) -> DerivBar:
    return DerivBar(T0 + i * width, T0 + (i + 1) * width, D(o), D(c))


def oi(ts: int, v: str) -> OiSample:
    return OiSample(ts, D(v), D(v) * 100, "ws_ticker")


def engine(interval_min: int = 60) -> DerivativesEngine:
    return DerivativesEngine(InstrumentMeta(funding_interval_min=interval_min))


@pytest.mark.parametrize(
    ("price", "oi_delta", "expected"),
    [
        ("1", "5", "long_buildup"),
        ("1", "-5", "short_covering"),
        ("-1", "5", "short_buildup"),
        ("-1", "-5", "long_unwind"),
        ("1", None, None),
        ("0", "5", None),
        ("1", "0", None),
    ],
)
def test_classify_quadrant_truth_table_and_none(
    price: str, oi_delta: str | None, expected: str | None
) -> None:
    assert classify_quadrant(D(price), None if oi_delta is None else D(oi_delta)) == expected


def test_engine_quadrant_per_bar_follows_price_and_oi_direction() -> None:
    bars = [bar(0, "100", "101"), bar(1, "101", "99")]
    out = engine().load(bars, oi=[oi(T0, "10"), oi(T0 + H - 1_000, "12"), oi(T0 + H + 5, "11")])
    assert (out[0].open_interest_delta, out[0].oi_price_quadrant) == (D(2), "long_buildup")
    assert (out[1].open_interest_delta, out[1].oi_price_quadrant) == (D(-1), "long_unwind")


def test_bar_without_an_oi_sample_is_none_not_zero_or_a_quadrant() -> None:
    out = engine().load([bar(0), bar(1), bar(2)], oi=[oi(T0 + 1, "10"), oi(T0 + 2 * H + 1, "12")])
    middle = out[1]
    assert middle.open_interest_delta is None and middle.oi_price_quadrant is None
    assert metric_value(middle, "open_interest_delta") is None
    assert metric_value(middle, "oi_price_quadrant") is None


def test_open_sample_past_the_staleness_bound_routes_to_none() -> None:
    b = bar(0)
    old = oi(b.start_ms - OI_STALENESS_MS - 1, "10")
    out = engine().load([b], oi=[old, oi(b.start_ms + 10, "11")])
    assert out[0].open_interest_delta is None and out[0].oi_price_quadrant is None
    fresh = oi(b.start_ms - OI_STALENESS_MS, "10")
    assert engine().load([b], oi=[fresh, oi(b.start_ms + 10, "11")])[0].open_interest_delta == 1


def test_open_interest_keeps_its_source() -> None:
    m = engine().load([bar(0)], oi=[OiSample(T0 + 1, D("5"), D("500"), "rest_history")])[0]
    assert (m.open_interest, m.open_interest_value, m.oi_source) == (D(5), D(500), "rest_history")


@pytest.mark.parametrize("interval_min", [60, 120, 240, 480])
def test_funding_annualized_follows_the_instrument_interval(interval_min: int) -> None:
    snap = TickerSnapshot(T0 + 1, funding_rate=D("0.0001"))
    m = engine(interval_min).load([bar(0)], tickers=[snap])[0]
    assert m.funding_rate == D("0.01")  # percent, the descriptor unit
    assert m.funding_annualized == D("0.0001") * (D(525600) / D(interval_min)) * 100
    assert metric_value(m, "funding_annualized") == m.funding_annualized


def test_unknown_funding_interval_is_refused_not_defaulted() -> None:
    with pytest.raises(FundingIntervalUnknown):
        engine(0)


def test_bar_without_a_ticker_takes_the_settled_rate_of_its_period() -> None:
    rows = [FundingRow(T0 + H, D("0.0002")), FundingRow(T0 + 2 * H, D("0.0003"))]
    out = engine(60).load([bar(0), bar(1), bar(2)], funding=rows)
    assert [m.funding_rate for m in out] == [D("0.02"), D("0.03"), None]


@pytest.mark.parametrize(
    ("source", "basis", "premium"), [("last", "0.1", "0.1"), ("mark", "-0.2", "-0.2")]
)
def test_basis_and_premium_for_both_sources(source: str, basis: str, premium: str) -> None:
    snap = TickerSnapshot(T0 + 1, last_price=D("100.1"), mark_price=D("99.8"), index_price=D(100))
    m = engine().load([bar(0)], tickers=[snap])[0]
    assert metric_value(m, "basis", {"source": source}) == D(basis)  # exact: no 0.0999999
    assert metric_value(m, "premium_pct", {"source": source}) == D(premium)
    assert metric_value(m, "basis") == m.basis_last


def test_basis_is_none_without_an_index_and_premium_none_on_a_zero_index() -> None:
    no_index = engine().load([bar(0)], tickers=[TickerSnapshot(T0 + 1, last_price=D(1))])[0]
    assert no_index.basis_last is None and no_index.premium_pct_last is None
    zero = TickerSnapshot(T0 + 1, last_price=D(1), index_price=D(0))
    m = engine().load([bar(0)], tickers=[zero])[0]
    assert m.basis_last == 1 and m.premium_pct_last is None


def test_liquidations_bucket_on_the_grid_across_the_utc_day_boundary() -> None:
    grid = [DerivBar(T0 + DAY - 2 * H + i * H, T0 + DAY - H + i * H, D(1), D(1)) for i in range(4)]
    prints = [
        LiquidationPrint(T0 + DAY - 1, "long", D("10")),  # 23:59:59.999 -> the 23:00 bar
        LiquidationPrint(T0 + DAY, "short", D("7")),  # 00:00:00.000 -> the 00:00 bar
        LiquidationPrint(T0 + DAY, "long", D("3")),
        LiquidationPrint(T0 + DAY - 2 * H, "short", D("1")),  # the first bar's start
        LiquidationPrint(T0 + DAY + 2 * H, "long", D("100")),  # past the grid: not counted
    ]
    out = engine().load(grid, liquidations=prints)
    assert [metric_value(m, "liquidation_notional", {"side": "long"}) for m in out] == [
        0, 10, 3, 0,
    ]  # fmt: skip
    assert [metric_value(m, "liquidation_notional", {"side": "short"}) for m in out] == [
        1, 0, 7, 0,
    ]  # fmt: skip
    total = sum((m.liquidation_long + m.liquidation_short for m in out), D(0))
    assert [metric_value(m, "liquidation_notional") for m in out] == [1, 10, 10, 0]
    assert total == D(21)  # every in-grid print once, none twice


def test_time_to_funding_per_bar_and_live_against_a_skewed_clock() -> None:
    snap = TickerSnapshot(T0 + 1_000, next_funding_time_ms=T0 + 61_000)
    e = engine()
    assert e.time_to_funding_ms(T0, 0) is None
    m = e.load([bar(0)], tickers=[snap])[0]
    assert m.time_to_funding_ms == 60_000
    assert e.time_to_funding_ms(now_ms=T0 + 10_000, clock_offset_ms=-2_500) == 53_500
    assert e.time_to_funding_ms(now_ms=T0 + 10_000, clock_offset_ms=2_500) == 48_500
    assert e.time_to_funding_ms(now_ms=T0 + 90_000, clock_offset_ms=0) == 0


@pytest.mark.parametrize(
    "make",
    [
        lambda: DerivBar(0, 1, D("NaN"), D(1)),
        lambda: OiSample(0, D("Infinity"), D(1), "x"),
        lambda: TickerSnapshot(0, index_price=D("-Infinity")),
        lambda: FundingRow(0, D("sNaN")),
        lambda: LiquidationPrint(0, "long", D("NaN")),
        lambda: LiquidationPrint(0, "both", D(1)),  # type: ignore[arg-type]  # the refused value
        lambda: DerivBar(5, 5, D(1), D(1)),
    ],
)
def test_non_finite_or_malformed_inputs_are_rejected(make: object) -> None:
    with pytest.raises(DerivativesInputError):
        make()  # type: ignore[operator]  # each case is a zero-argument constructor


@pytest.mark.parametrize(
    ("name", "params"),
    [("nope", None), ("basis", {"source": "index"}), ("open_interest", {"x": "1"})],
)
def test_metric_value_refuses_unknown_metrics_and_params(
    name: str, params: dict[str, str] | None
) -> None:
    m = engine().load([bar(0)])[0]
    with pytest.raises(DerivativesInputError):
        metric_value(m, name, params)


def test_bar_grid_must_be_ordered_and_only_the_current_bar_replaced() -> None:
    e = engine()
    with pytest.raises(DerivativesInputError):
        e.load([bar(1), bar(0)])
    e.load([bar(0), bar(1)])
    with pytest.raises(DerivativesInputError):
        e.upsert_bar(bar(0))
    assert e.upsert_bar(bar(1, "101", "99")).start_ms == bar(1).start_ms
    assert e.upsert_bar(bar(2)).start_ms == bar(2).start_ms and len(e.series) == 3


def test_incremental_ticker_recomputes_the_current_bar_only() -> None:
    e = engine()
    e.load([bar(0), bar(1)], tickers=[TickerSnapshot(T0 + 1, last_price=D(1), index_price=D(1))])
    before = e.series[0]
    cur = e.on_ticker(TickerSnapshot(T0 + H + 1, last_price=D(3), index_price=D(2)))
    assert cur is not None and cur.basis_last == 1 and e.series[0] is before


def test_a_late_row_recomputes_the_window() -> None:
    e = engine()
    e.load([bar(0), bar(1)])
    e.on_liquidation(LiquidationPrint(T0 + 5, "short", D(4)))
    assert e.series[0].liquidation_short == 4


def test_inputs_before_any_bar_return_none() -> None:
    e = engine()
    assert e.on_oi(oi(T0, "1")) is None
    assert e.on_funding(FundingRow(T0, D("0.0001"))) is None


# --- property: incremental == full recompute -------------------------------------------------

_ts = st.integers(min_value=T0 - H, max_value=T0 + 4 * H)
_px = st.decimals(min_value=1, max_value=1000, places=2)
_rows = st.one_of(
    st.builds(OiSample, _ts, _px, _px, st.just("ws_ticker")),
    st.builds(TickerSnapshot, _ts, _px, _px, _px, st.just(D("0.0001")), _ts),
    st.builds(LiquidationPrint, _ts, st.sampled_from(["long", "short"]), _px),
)


def _feed(e: DerivativesEngine, row: object) -> BarMetrics | None:
    if isinstance(row, OiSample):
        return e.on_oi(row)
    if isinstance(row, TickerSnapshot):
        return e.on_ticker(row)
    assert isinstance(row, LiquidationPrint)
    return e.on_liquidation(row)


@settings(max_examples=150, deadline=None)
@given(prices=st.lists(st.tuples(_px, _px), min_size=1, max_size=4), data=st.data())
def test_incremental_updates_equal_a_full_recompute(
    prices: list[tuple[Decimal, Decimal]], data: st.DataObject
) -> None:
    """Bars appended one by one, rows (current-bar and late ones) fed after each, the current
    bar re-closed: the series equals one full recompute over the same inputs."""
    bars = [DerivBar(T0 + i * H, T0 + (i + 1) * H, o, c) for i, (o, c) in enumerate(prices)]
    inc, fed = engine(), []
    inc.load(bars[:1])
    for i, b in enumerate(bars):
        if i:
            inc.upsert_bar(b)
        for row in data.draw(st.lists(_rows, max_size=10)):
            _feed(inc, row)
            fed.append(row)
    inc.upsert_bar(bars[-1])  # the current bar re-closed with the same prices
    full = engine()
    full.load(
        bars,
        oi=[r for r in fed if isinstance(r, OiSample)],
        tickers=[r for r in fed if isinstance(r, TickerSnapshot)],
        liquidations=[r for r in fed if isinstance(r, LiquidationPrint)],
    )
    assert inc.series == full.series

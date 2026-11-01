"""E24-T04 DerivativesEngine: the 24 §7.2 Derivatives formulas, the None case, bucketing and the
incremental path. Synthetic in-memory rows only (no network, no fixtures needed: inputs are plain
rows and the engine is pure)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from prometheus_client import REGISTRY

from candleviewer.domain.funding import FundingIntervalUnknown
from candleviewer.orderflow.derivatives import (
    MAX_PENDING_ROWS,
    OI_STALENESS_MS,
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
        lambda: OiSample(0, D(-1), D(1), "x"),
        lambda: OiSample(0, D(1), D("-0.5"), "x"),
        lambda: LiquidationPrint(0, "short", D(-3)),
        lambda: TickerSnapshot(0, last_price=D("1e999999")),  # huge: refused, not an Overflow
        lambda: TickerSnapshot(0, index_price=D("1e-40")),  # a tiny divisor likewise
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
    with pytest.raises(DerivativesInputError):  # same start, another slot
        e.upsert_bar(DerivBar(T0 + H, T0 + 3 * H, D(1), D(1)))
    assert e.upsert_bar(bar(2)).start_ms == bar(2).start_ms and len(e.series) == 3


def test_incremental_ticker_recomputes_the_current_bar_only() -> None:
    e = engine()
    e.load([bar(0), bar(1)], tickers=[TickerSnapshot(T0 + 1, last_price=D(1), index_price=D(1))])
    before = e.series[0]
    (cur,) = e.on_ticker(TickerSnapshot(T0 + H + 1, last_price=D(3), index_price=D(2)))
    assert cur.start_ms == T0 + H and cur.basis_last == 1 and e.series[0] is before


def test_a_late_liquidation_revises_only_its_closed_bar_and_names_it() -> None:
    e = engine()
    e.load([bar(0), bar(1), bar(2)])
    changed = e.on_liquidation(LiquidationPrint(T0 + 5, "short", D(4)))
    assert [m.start_ms for m in changed] == [T0] and e.series[0].liquidation_short == 4


def test_a_late_oi_sample_revises_its_bar_and_the_bars_it_opens() -> None:
    e = engine()
    e.load([bar(i, width=OI_STALENESS_MS // 2) for i in range(5)], oi=[oi(T0 + 1, "1")])
    w = OI_STALENESS_MS // 2
    e.on_oi(oi(T0 + 3 * w + 1, "2"))
    changed = e.on_oi(oi(T0 + w + 1, "5"))  # bar 1's close, bars 2-3's open within the bound
    assert [m.start_ms for m in changed] == [T0 + w, T0 + 2 * w, T0 + 3 * w]


def test_a_settlement_revises_the_bars_of_its_period_only() -> None:
    e = engine(60)
    e.load([bar(i, width=H // 2) for i in range(6)])
    changed = e.on_funding(FundingRow(T0 + 2 * H, D("0.0001")))  # covers [T0 + H, T0 + 2H)
    assert [m.start_ms for m in changed] == [T0 + H, T0 + H + H // 2]
    assert [m.funding_rate for m in e.series] == [None, None, D("0.01"), D("0.01"), None, None]


def test_inputs_before_any_bar_change_nothing() -> None:
    e = engine()
    assert e.on_oi(oi(T0, "1")) == ()
    assert e.on_funding(FundingRow(T0, D("0.0001"))) == ()


def test_a_duplicate_liquidation_print_counts_once() -> None:
    e = engine()
    p = LiquidationPrint(T0 + 5, "long", D(2))
    e.load([bar(0), bar(1)], liquidations=[p, p])
    assert e.series[0].liquidation_long == 2
    assert e.on_liquidation(p) == () and e.series[0].liquidation_long == 2
    e.on_liquidation(LiquidationPrint(T0 + 5, "long", D(2), batch_index=1))  # a distinct print
    assert e.series[0].liquidation_long == 4


def test_state_stays_bounded_after_many_appends() -> None:
    e = DerivativesEngine(InstrumentMeta(funding_interval_min=60), max_bars=50)
    w = 60_000
    e.load([DerivBar(T0, T0 + w, D(1), D(1))])
    for i in range(1, 2_000):
        s = T0 + i * w
        e.upsert_bar(DerivBar(s, s + w, D(1), D(2)))
        for k in range(10):  # ten 100 ms-ish snapshots and samples per bar
            e.on_ticker(TickerSnapshot(s + k, last_price=D(1), index_price=D(1)))
            e.on_oi(oi(s + k, str(k)))
        e.on_liquidation(LiquidationPrint(s + 1, "long", D(1)))
        e.on_funding(FundingRow(s + 1, D("0.0001")))
    got = e.retained()
    assert got["bars"] == len(e.series) == 50
    assert got["tickers"] <= 50 and got["oi"] <= 2 * 50 + 1 and got["liquidations"] <= 50
    assert got["funding"] <= 50


def test_a_stalled_grid_refuses_rows_past_the_pending_bound() -> None:
    e = engine()
    e.load([bar(0)], tickers=[TickerSnapshot(T0 + H + i) for i in range(MAX_PENDING_ROWS)])
    with pytest.raises(DerivativesInputError):
        e.on_ticker(TickerSnapshot(T0 + 2 * H))
    with pytest.raises(DerivativesInputError):
        engine().load([bar(0)], oi=[oi(T0 + H + i, "1") for i in range(MAX_PENDING_ROWS + 1)])


def _none_count(reason: str) -> float:
    return REGISTRY.get_sample_value("deriv_engine_none_bars_total", {"reason": reason}) or 0.0


def test_none_bars_count_once_across_reloads() -> None:
    e = engine()
    before = _none_count("no_oi_sample")
    e.load([bar(0), bar(1), bar(2)])
    e.load([bar(0), bar(1), bar(2)])
    assert _none_count("no_oi_sample") - before == 2  # bars 0 and 1 closed; bar 2 is current
    e.upsert_bar(bar(3))
    assert _none_count("no_oi_sample") - before == 3


def test_a_lone_sample_at_the_bar_start_is_flat() -> None:
    m = engine().load([bar(0)], oi=[oi(T0, "10")])[0]
    assert (m.open_interest, m.open_interest_delta, m.oi_price_quadrant) == (D(10), D(0), None)


def test_annualisation_is_independent_of_the_rate_representation() -> None:
    snaps = [TickerSnapshot(T0 + 1, funding_rate=D("0.00010")), TickerSnapshot(T0 + H + 1,
             funding_rate=D("0.0001"))]  # fmt: skip
    a = engine().load([bar(0), bar(1)], tickers=snaps)
    b = engine().load([bar(1)], tickers=snaps[1:])
    assert str(a[1].funding_annualized) == str(b[0].funding_annualized)


# --- property: targeted incremental == full recompute -------------------------------------

_EDGES = sorted(
    {T0 + i * H + d for i in range(-1, 6) for d in (0, -1, OI_STALENESS_MS, -OI_STALENESS_MS)}
)
_ts = st.one_of(st.integers(min_value=T0 - H, max_value=T0 + 5 * H), st.sampled_from(_EDGES))
_px = st.decimals(min_value=1, max_value=1000, places=2)
_rate = st.sampled_from([D("0.0001"), D("-0.0002"), D("0.00010")])
_rows = st.one_of(
    st.builds(OiSample, _ts, _px, _px, st.just("ws_ticker")),
    st.builds(TickerSnapshot, _ts, _px, _px, _px, st.one_of(st.none(), _rate), _ts),
    st.builds(LiquidationPrint, _ts, st.sampled_from(["long", "short"]), _px),
    st.builds(FundingRow, _ts, _rate),
)
_Row = OiSample | TickerSnapshot | LiquidationPrint | FundingRow


def _feed(e: DerivativesEngine, row: _Row) -> tuple[object, ...]:
    if isinstance(row, OiSample):
        return e.on_oi(row)
    if isinstance(row, TickerSnapshot):
        return e.on_ticker(row)
    if isinstance(row, FundingRow):
        return e.on_funding(row)
    return e.on_liquidation(row)


@settings(max_examples=200, deadline=None)
@given(
    prices=st.lists(st.tuples(_px, _px), min_size=1, max_size=5),
    max_bars=st.integers(min_value=2, max_value=6),
    data=st.data(),
)
def test_incremental_updates_equal_a_full_recompute(
    prices: list[tuple[Decimal, Decimal]], max_bars: int, data: st.DataObject
) -> None:
    """Bars appended one by one (the oldest dropping past `max_bars`), rows on and off the grid
    and at its edges fed after each, the current bar re-priced: after every row the targeted
    update equals a full recompute and returns exactly the bars that changed; at the end the
    series equals one fresh load of every input."""
    bars = [DerivBar(T0 + i * H, T0 + (i + 1) * H, o, c) for i, (o, c) in enumerate(prices)]
    inc = DerivativesEngine(InstrumentMeta(funding_interval_min=60), max_bars=max_bars)
    fed: list[_Row] = []
    inc.load(bars[:1])
    for i, b in enumerate(bars):
        if i:
            inc.upsert_bar(b)
        for row in data.draw(st.lists(_rows, max_size=8)):
            before = inc.series
            changed = _feed(inc, row)
            fed.append(row)
            after = inc.series
            assert changed == tuple(a for a, p in zip(after, before, strict=True) if a != p)
            assert inc.recompute() == after
        o, c = data.draw(st.tuples(_px, _px))
        bars[i] = DerivBar(b.start_ms, b.end_ms, o, c)
        inc.upsert_bar(bars[i])  # the current bar re-priced
    full = DerivativesEngine(InstrumentMeta(funding_interval_min=60), max_bars=max_bars)
    oracle = DerivativesEngine(InstrumentMeta(funding_interval_min=60), max_bars=max_bars)
    # The oracle keeps every row (no compaction), so a pruning bug shared by both engine paths
    # still shows up as a difference.
    oracle._tidy_all = lambda: None  # type: ignore[method-assign]  # disable pruning only
    for e in (full, oracle):
        e.load(
            bars,
            oi=[r for r in fed if isinstance(r, OiSample)],
            tickers=[r for r in fed if isinstance(r, TickerSnapshot)],
            funding=[r for r in fed if isinstance(r, FundingRow)],
            liquidations=[r for r in fed if isinstance(r, LiquidationPrint)],
        )
    assert inc.series == full.series == oracle.series
    assert inc.time_to_funding_ms(T0, 0) == full.time_to_funding_ms(T0, 0)

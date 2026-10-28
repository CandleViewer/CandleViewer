"""`scanner_eval` (E08-T09 PR 2b, #4708): matching, the derived values and their quantum, the
row shape, the ranking and the cap (22 `runScanner`, `ScannerRow`), with Hypothesis properties of
the ranking. Gherkin 2 (a recorded-history criterion over a mixed universe) is automatable only
here: through the API such a criterion is still refused `criterion_unavailable` until its source
lands (22 `ScannerCriterion.available`)."""

from __future__ import annotations

import json
import random
from dataclasses import replace
from decimal import Decimal
from typing import Any

from _scan_env import TS_US, ticker, universe
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api.scanner_criteria import CRITERIA, CRITERIA_BY_ID
from candleviewer.api.scanner_eval import (
    ScanQuery,
    build_body,
    evaluate,
    range_pct_24h,
    row_body,
    scan_query,
    spread_bps,
    tickers_input,
)

D = Decimal


def q(flt: dict[str, Any] | None = None, sort: str = "volume_24h", limit: int = 100) -> ScanQuery:
    return scan_query(flt or {}, sort, limit, CRITERIA_BY_ID)


def run(
    tickers: list[Any], query: ScanQuery, recorded: frozenset[str] = frozenset(), **kw: Any
) -> list[str]:
    result = evaluate(universe(tickers), recorded, {}, query, criteria=CRITERIA, **kw)
    return [r.symbol for r in result.rows]


def test_a_range_matches_inclusively_at_both_bounds() -> None:
    rows = [ticker(f"S{i}USDT", funding_rate=D(f"0.000{i}")) for i in range(1, 6)]
    hit = run(rows, q({"funding_rate": {"min": "0.0002", "max": "0.0004"}}, sort="funding_rate"))
    assert hit == ["S4USDT", "S3USDT", "S2USDT"]


def test_a_one_sided_range_bounds_one_side_only() -> None:
    rows = [ticker(f"S{i}USDT", turnover_24h=D(i * 1000)) for i in range(1, 6)]
    assert run(rows, q({"turnover_24h": {"min": "3000"}})) == ["S3USDT", "S4USDT", "S5USDT"]
    assert run(rows, q({"turnover_24h": {"max": "2000"}})) == ["S1USDT", "S2USDT"]


def test_a_live_criterion_with_no_value_does_not_match() -> None:
    rows = [ticker("AAAUSDT", funding_rate=None), ticker("BBBUSDT")]
    assert run(rows, q({"funding_rate": {"min": "-1"}})) == ["BBBUSDT"]


def test_every_active_criterion_must_match() -> None:
    rows = [
        ticker("AAAUSDT", turnover_24h=D(1)),
        ticker("BBBUSDT", price_24h_pcnt=D("-0.5")),
        ticker("CCCUSDT"),
    ]
    flt = {"turnover_24h": {"min": "100"}, "price_change_pct_24h": {"min": "0"}}
    assert run(rows, q(flt)) == ["CCCUSDT"]


def test_an_empty_filter_keeps_every_valid_symbol_and_drops_non_usdt_ones() -> None:
    rows = [ticker("AAAUSDT"), ticker("BTCPERP"), ticker("ETHUSDC")]
    assert run(rows, q()) == ["AAAUSDT"]


def test_spread_bps_is_the_mid_spread_to_4_places_half_even() -> None:
    t = ticker("AAAUSDT", bid1_price=D("99.99"), ask1_price=D("100.01"))
    assert spread_bps(t) == D("2.0000")  # 0.02 / 100 * 10000
    odd = ticker("AAAUSDT", bid1_price=D("3"), ask1_price=D("3.0001"))
    # 0.0001 / 3.00005 * 10000 = 0.33332777... -> 0.3333
    assert spread_bps(odd) == D("0.3333")
    assert str(spread_bps(odd)) == "0.3333"


def test_spread_bps_is_none_without_both_sides() -> None:
    assert spread_bps(ticker("AAAUSDT", bid1_price=None)) is None
    assert spread_bps(ticker("AAAUSDT", ask1_price=None)) is None


def test_range_pct_24h_is_a_fraction_to_8_places_and_none_without_its_inputs() -> None:
    assert range_pct_24h(ticker("AAAUSDT", high_24h=D("110"), low_24h=D("100"))) == D("0.1")
    third = range_pct_24h(ticker("AAAUSDT", high_24h=D("4"), low_24h=D("3")))
    assert str(third) == "0.33333333"
    assert range_pct_24h(ticker("AAAUSDT", high_24h=None)) is None
    assert range_pct_24h(ticker("AAAUSDT", low_24h=None)) is None


def test_a_row_is_compared_on_the_value_it_shows() -> None:
    # 1/3 shows as 0.33333333; a bound of exactly that value includes it, one ulp above does not
    t = ticker("AAAUSDT", high_24h=D("4"), low_24h=D("3"))
    shown = row_body(evaluate(universe([t]), frozenset(), {}, q(), criteria=CRITERIA).rows[0])
    assert shown["range_pct_24h"] == "0.33333333"
    assert run([t], q({"range_pct_24h": {"min": "0.33333333"}})) == ["AAAUSDT"]
    assert run([t], q({"range_pct_24h": {"min": "0.33333334"}})) == []


def test_the_row_omits_absent_decimals_nulls_the_nullable_ones_and_has_no_price_path() -> None:
    t = ticker("AAAUSDT", last_price=None, turnover_24h=None, open_interest=None)
    body = row_body(evaluate(universe([t]), frozenset(), {}, q(), criteria=CRITERIA).rows[0])
    assert "last_price" not in body and "open_interest" not in body
    for absent in ("cvd", "tape_speed", "liquidation_intensity", "price_path_24h"):
        assert absent not in body
    assert body["turnover_24h"] is None
    for nullable in ("oi_change_pct_24h", "tape_speed_zscore", "regime"):
        assert body[nullable] is None
    assert (body["coverage"], body["recording"], body["skipped_criteria"]) == (
        "live_only",
        False,
        [],
    )
    assert body["volume_24h"] == "50000" and body["spread_bps"] == "2.0000"


def test_coverage_is_recorded_for_a_recorded_symbol() -> None:
    result = evaluate(universe([ticker("AAAUSDT")]), {"AAAUSDT"}, {}, q(), criteria=CRITERIA)
    body = row_body(result.rows[0])
    assert (body["coverage"], body["recording"]) == ("recorded", True)


def test_the_catalogue_narrows_the_universe_and_counts_what_it_drops() -> None:
    rows = [ticker("AAAUSDT"), ticker("BBBUSDT"), ticker("CCCUSDT")]
    result = evaluate(
        universe(rows), frozenset(), {}, q(), criteria=CRITERIA, listed={"AAAUSDT", "CCCUSDT"}
    )
    assert ([r.symbol for r in result.rows], result.dropped) == (["AAAUSDT", "CCCUSDT"], 1)
    assert evaluate(universe(rows), frozenset(), {}, q(), criteria=CRITERIA).dropped == 0


def test_canonical_query_compares_bounds_as_numbers_and_classes_as_sets() -> None:
    assert q({"funding_rate": {"min": "0.10"}}) == q({"funding_rate": {"min": "0.1"}})
    assert hash(q({"funding_rate": {"min": "0.10"}})) == hash(q({"funding_rate": {"min": "0.1"}}))
    two = {"regime": {"classes": ["calm", "range"]}}
    assert q(two) == q({"regime": {"classes": ["range", "calm"]}})
    assert q({"funding_rate": {"min": "0.1"}}) != q({"funding_rate": {"max": "0.1"}})
    assert q(sort="funding_rate") != q() and q(limit=5) != q()


# --- Gherkin 2: a recorded-history criterion over recorded and live-only rows ------------------

_ZSCORE = replace(CRITERIA_BY_ID["tape_speed_zscore"], available=True)
_WITH_ZSCORE = tuple(_ZSCORE if c.id == _ZSCORE.id else c for c in CRITERIA)


def test_gherkin_2_a_live_only_row_skips_the_criterion_and_ranks_after_every_value() -> None:
    rows = [ticker("AAAUSDT"), ticker("BBBUSDT"), ticker("CCCUSDT")]
    recorded = frozenset({"AAAUSDT", "BBBUSDT"})
    values = {"AAAUSDT": {"tape_speed_zscore": D("2.5")}, "BBBUSDT": {"tape_speed_zscore": D("3")}}
    query = q({"tape_speed_zscore": {"min": "2"}}, sort="tape_speed_zscore")
    result = evaluate(universe(rows), recorded, values, query, criteria=_WITH_ZSCORE)
    bodies = [row_body(r) for r in result.rows]
    assert [b["symbol"] for b in bodies] == ["BBBUSDT", "AAAUSDT", "CCCUSDT"]
    live = bodies[-1]
    assert (live["coverage"], live["skipped_criteria"], live["tape_speed_zscore"]) == (
        "live_only",
        ["tape_speed_zscore"],
        None,
    )
    assert bodies[0]["skipped_criteria"] == [] and bodies[0]["tape_speed_zscore"] == "3"


def test_a_recorded_row_without_the_recorded_value_does_not_match() -> None:
    query = q({"tape_speed_zscore": {"min": "2"}})
    result = evaluate(universe([ticker("AAAUSDT")]), {"AAAUSDT"}, {}, query, criteria=_WITH_ZSCORE)
    assert result.rows == ()


def test_a_class_set_matches_on_membership_for_recorded_rows() -> None:
    regime = replace(CRITERIA_BY_ID["regime"], available=True)
    crit = tuple(regime if c.id == "regime" else c for c in CRITERIA)
    values = {"AAAUSDT": {"regime": "calm"}, "BBBUSDT": {"regime": "volatile"}}
    query = q({"regime": {"classes": ["calm", "range"]}})
    rows = universe([ticker("AAAUSDT"), ticker("BBBUSDT")])
    result = evaluate(rows, {"AAAUSDT", "BBBUSDT"}, values, query, criteria=crit)
    assert [(r.symbol, row_body(r)["regime"]) for r in result.rows] == [("AAAUSDT", "calm")]


def test_the_cap_returns_the_first_limit_rows_and_flags_capped() -> None:
    rows = [ticker(f"S{i:03d}USDT", volume_24h=D(i)) for i in range(10)]
    result = evaluate(universe(rows), frozenset(), {}, q(limit=3), criteria=CRITERIA)
    assert [r.symbol for r in result.rows] == ["S009USDT", "S008USDT", "S007USDT"]
    assert (result.matched, result.capped) == (10, True)
    exact = evaluate(universe(rows), frozenset(), {}, q(limit=10), criteria=CRITERIA)
    assert exact.capped is False


def test_the_body_carries_the_meta_and_the_ticker_input() -> None:
    rows = [ticker(f"S{i}USDT") for i in range(3)]
    result = evaluate(universe(rows), frozenset(), {}, q(limit=2), criteria=CRITERIA)
    stale = tickers_input(TS_US, TS_US, TS_US + 5_000_001)
    fresh = tickers_input(TS_US, TS_US, TS_US + 5_000_000)
    assert (stale["stale"], fresh["stale"]) == (True, False)
    body = json.loads(build_body(result, generated_at_us=TS_US, inputs=[fresh]))
    assert body["meta"] == {
        "next_cursor": None,
        "has_more": True,
        "count": 2,
        "capped": True,
        "generated_at": "2026-10-26T07:33:20.000000Z",
        "sources": ["memory", "postgres"],
        "inputs": [{"input": "tickers", "as_of": "2026-10-26T07:33:20.000000Z", "stale": False}],
    }
    assert "total" not in body["meta"]


# --- Hypothesis properties of the ranking -------------------------------------------------------

_VALUES = st.one_of(st.none(), st.integers(-50, 50).map(lambda i: D(i) / 10))
_UNIVERSE = st.dictionaries(
    st.from_regex(r"[A-Z]{3,5}", fullmatch=True).map(lambda s: s + "USDT"),
    _VALUES,
    min_size=0,
    max_size=40,
)


def _rows(values: dict[str, Decimal | None]) -> dict[str, Any]:
    return universe(ticker(s, funding_rate=v) for s, v in values.items())


def _key(row: dict[str, Any]) -> tuple[int, Decimal, str]:
    v = row["funding_rate"]
    return (1, D(0), row["symbol"]) if v is None else (0, -D(v), row["symbol"])


@settings(max_examples=60, deadline=None)
@given(values=_UNIVERSE, limit=st.integers(1, 50), rng=st.randoms(use_true_random=False))
def test_ranking_is_sorted_null_last_capped_a_prefix_and_order_independent(
    values: dict[str, Decimal | None], limit: int, rng: random.Random
) -> None:
    tickers = _rows(values)
    query = q(sort="funding_rate", limit=limit)
    result = evaluate(tickers, frozenset(), {}, query, criteria=CRITERIA)
    rows = [row_body(r) for r in result.rows]
    assert rows == sorted(rows, key=_key)
    nulls = [r["funding_rate"] is None for r in rows]
    assert nulls == sorted(nulls)  # no null before a value
    assert len(rows) == min(limit, len(values)) and result.capped == (len(values) > limit)
    full = evaluate(tickers, frozenset(), {}, q(sort="funding_rate", limit=200), criteria=CRITERIA)
    assert [r.symbol for r in result.rows] == [r.symbol for r in full.rows][: len(rows)]
    shuffled = list(tickers.items())
    rng.shuffle(shuffled)
    again = evaluate(dict(shuffled), frozenset(), {}, query, criteria=CRITERIA)
    assert again.rows == result.rows


@settings(max_examples=60, deadline=None)
@given(values=_UNIVERSE, lo=st.integers(-50, 50), width=st.integers(0, 50))
def test_a_range_keeps_exactly_the_values_inside_it(
    values: dict[str, Decimal | None], lo: int, width: int
) -> None:
    low, high = D(lo) / 10, D(lo + width) / 10
    flt = {"funding_rate": {"min": str(low), "max": str(high)}}
    query = scan_query(flt, "volume_24h", 200, CRITERIA_BY_ID)
    result = evaluate(_rows(values), frozenset(), {}, query, criteria=CRITERIA)
    expected = {s for s, v in values.items() if v is not None and low <= v <= high}
    assert {r.symbol for r in result.rows} == expected

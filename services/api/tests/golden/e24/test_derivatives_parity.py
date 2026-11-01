"""E24-T06 per-PR slice: the derivatives engine against the DuckDB reference on the recorded
corpus (AC1, AC3, AC4). Default lane: the 150-bar / 30-bar slices; the full window is
`test_derivatives_parity_full.py` (`harness`). Fixtures: `packages/fixtures/golden/derivatives/`
(README: provenance and the symbol-day deviation). No network, no clock, `tmp_path` only."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from candleviewer.orderflow.derivatives import DESCRIPTORS, OI_STALENESS_MS, metric_value
from tests.golden.e24 import _loader as L
from tests.golden.e24 import _parity as P
from tests.golden.e24 import _reference as R
from tests.golden.e24.conftest import RefOf

PR_CASES = [c.id for c in L.cases("pr")]
REGEN = os.environ.get("CV_REGEN_GOLDEN") == "1"
SUMMARY = L.GOLDEN_DIR / "summary.json"
SETTLEMENT_MS = 1_700_006_400_000  # 2023-11-15T00:00Z, a UTC day boundary and an 8 h settlement


def golden_path(case_id: str) -> Path:
    return L.GOLDEN_DIR / f"expected_{case_id}.json.gz"


def _regenerate(case_id: str, got: str) -> None:
    """`CV_REGEN_GOLDEN=1`: rewrite one case's golden and its summary entry (review the diff)."""
    golden_path(case_id).write_bytes(gzip.compress(got.encode(), mtime=0))
    summary: dict[str, Any] = (
        json.loads(SUMMARY.read_text()) if SUMMARY.exists() else {"version": 1, "cases": {}}
    )
    summary["cases"][case_id] = {
        "bars": len(json.loads(got)),
        "sha256": hashlib.sha256(got.encode()).hexdigest(),
    }
    SUMMARY.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _series(case_id: str) -> str:
    return P.canonical_json(P.run_full(L.build_rows(L.case_by_id(case_id))))


@pytest.mark.parametrize("case_id", PR_CASES)
def test_parity_engine_matches_reference_on_every_series(case_id: str, ref_of: RefOf) -> None:
    rows, ref = ref_of(case_id)
    for series in (P.run_full(rows), P.run_incremental(rows)):
        P.assert_parity(P.compare(series, ref))


@pytest.mark.parametrize("case_id", PR_CASES)
def test_parity_series_are_not_vacuous(case_id: str, ref_of: RefOf) -> None:
    rows, ref = ref_of(case_id)
    report = P.compare(P.run_full(rows), ref)
    assert report.non_none["open_interest"] > 0
    assert report.non_none["funding_rate"] > 0
    assert report.non_none["funding_annualized"] > 0


@pytest.mark.parametrize("case_id", PR_CASES)
def test_incremental_replay_equals_full_recompute(case_id: str) -> None:
    rows = L.build_rows(L.case_by_id(case_id))
    assert P.run_incremental(rows) == P.run_full(rows)


@pytest.mark.parametrize("case_id", PR_CASES)
def test_full_recompute_is_byte_identical_across_runs(case_id: str) -> None:
    assert _series(case_id) == _series(case_id)


@pytest.mark.parametrize("case_id", PR_CASES)
def test_golden_matches_engine_output(case_id: str) -> None:
    got = _series(case_id)
    if REGEN:
        _regenerate(case_id, got)
    want = gzip.decompress(golden_path(case_id).read_bytes()).decode()
    assert got == want, f"{case_id}: engine output drifted from the committed golden"
    summary = json.loads(SUMMARY.read_text())
    assert summary["cases"][case_id]["sha256"] == hashlib.sha256(got.encode()).hexdigest()


def test_golden_summary_names_exactly_the_default_lane_cases() -> None:
    summary = json.loads(SUMMARY.read_text())
    assert sorted(summary["cases"]) == sorted(PR_CASES)


def test_day_boundary_and_settlement_fall_inside_the_slice(ref_of: RefOf) -> None:
    rows, ref = ref_of("btc_8h_slice")
    starts = [b[0] for b in rows.bars]
    assert starts[0] < SETTLEMENT_MS < starts[-1]
    before = ref[SETTLEMENT_MS - 60_000]["funding_rate"]
    after = ref[SETTLEMENT_MS]["funding_rate"]
    assert before == Decimal("0.0100")  # the settled 0.0001 (fraction) at T, x100
    assert after is None  # the next settlement is not in the corpus: no row covers the bar


def test_annualisation_factor_follows_the_instrument_interval() -> None:
    """24 §2.7: rate * 100 * 525600 / interval; 480 min -> 1095, 240 min -> 2190."""
    for case_id, factor in (("btc_8h_slice", 1095), ("btc_4h_paired", 2190)):
        series = P.run_full(L.build_rows(L.case_by_id(case_id)))
        got = next(m for m in series if m.funding_rate is not None)
        assert got.funding_rate is not None
        assert got.funding_annualized == got.funding_rate * factor


def test_no_oi_bars_have_no_delta_and_an_expired_open_is_not_carried() -> None:
    series = {m.start_ms: m for m in P.run_full(L.build_rows(L.case_by_id("btc_8h_no_oi")))}
    held = series[1_700_004_000_000 + 4 * 60_000]  # 23:24: the 23:15 open is within the bound
    assert held.open_interest == series[1_700_003_700_000].open_interest
    assert held.open_interest_delta is None
    expired = series[1_700_004_600_000]  # 23:30: the 23:15 sample is 15 min old, past the bound
    assert expired.open_interest is None
    assert expired.open_interest_delta is None
    assert expired.oi_price_quadrant is None
    on_sample = series[1_700_005_800_000]  # 23:50: a sample on the bar start is open and close
    assert on_sample.open_interest_delta == 0  # flat, and a flat OI delta classifies nothing
    assert on_sample.oi_price_quadrant is None


def test_stale_open_under_a_wide_bar_is_none_never_zero(ref_of: RefOf) -> None:
    rows, ref = ref_of("btc_8h_15m_stale_open")
    bar = ref[1_700_005_380_000]  # 23:43: samples at 23:50, 23:55; last open sample 23:30
    assert bar["open_interest"] is not None
    assert bar["open_interest_delta"] is None
    assert bar["oi_price_quadrant"] is None
    series = {m.start_ms: m for m in P.run_full(rows)}
    assert series[1_700_005_380_000].open_interest_delta is None
    assert series[1_700_004_480_000].open_interest_delta is not None  # 23:28: open 23:25, fresh


def test_recorder_gap_leaves_no_ticker_value_and_falls_back_to_settled_funding(
    ref_of: RefOf,
) -> None:
    rows, ref = ref_of("btc_8h_recorder_gap")
    assert not [t for t in rows.tickers if 1_699_999_800_000 <= t[0] < 1_700_000_700_000]
    head = ref[rows.bars[0][0]]
    assert head["funding_rate"] == Decimal("0.0100")
    assert head["time_to_funding_ms"] is None
    assert head["basis:last"] is None
    assert head["premium_pct:last"] is None


def test_fifteen_minute_bars_classify_the_quadrant(ref_of: RefOf) -> None:
    rows, ref = ref_of("btc_8h_15m")
    quadrants = {r["oi_price_quadrant"] for r in ref.values()} - {None}
    assert quadrants, "the 15 m grid must classify at least one bar"
    assert all(r["open_interest_delta"] != 0 for r in ref.values() if r["oi_price_quadrant"])
    assert len(rows.bars) == 30


def test_paired_four_hour_case_uses_the_eth_settled_rows() -> None:
    rows = L.build_rows(L.case_by_id("btc_4h_paired"))
    assert rows.interval_min == 240
    assert [ts for ts, _ in rows.funding] == [
        1_699_963_200_000, 1_699_977_600_000, 1_699_992_000_000, 1_700_006_400_000
    ]  # fmt: skip
    assert L.case_by_id("btc_4h_paired").paired


def test_tolerance_table_names_only_the_two_divisions() -> None:
    assert set(P.TOLERANCE) == {"funding_annualized", "premium_pct[last]", "premium_pct[mark]"}
    assert all(t == Decimal("1e-12") for t in P.TOLERANCE.values())


def test_series_cover_every_descriptor_but_the_follow_up_one() -> None:
    covered = {name for _, name, _, _ in P.SERIES}
    assert covered | P.FOLLOW_UP_DESCRIPTORS == set(DESCRIPTORS)
    for _, name, params, _ in P.SERIES:
        for key, allowed in DESCRIPTORS[name].items():
            assert params.get(key, allowed[0]) in allowed
    labels = [s[0] for s in P.SERIES]
    assert len(labels) == len(set(labels))


def test_manifest_lists_the_follow_up_liquidation_cases_and_the_case_ids_are_unique() -> None:
    man = L.load_manifest()
    follow = {c["id"] for c in man["follow_up_cases"]}
    assert follow == {"btc_8h_cascade", "btc_8h_liquidation_dedup"}
    assert all("#5273" in c["status"] for c in man["follow_up_cases"])
    ids = [c.id for c in L.cases()]
    assert len(ids) == len(set(ids))
    assert {c.lane for c in L.cases()} == {"pr", "harness"}


def test_loader_refuses_a_file_the_corpus_manifest_does_not_list() -> None:
    with pytest.raises(ValueError, match="not in the fixture manifest"):
        L._fixture(L.load_manifest(), "rest/not-recorded.json")


def test_reference_staleness_bound_is_restated_not_imported() -> None:
    assert R.STALENESS_MS == OI_STALENESS_MS == 600_000


def test_metric_value_read_path_is_what_the_series_use() -> None:
    m = P.run_full(L.build_rows(L.case_by_id("btc_8h_slice")))[0]
    assert metric_value(m, "basis", {"source": "mark"}) == m.basis_mark

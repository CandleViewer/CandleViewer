"""E16-Q04 (#481): the recorder budgets are pure pass/fail on fake samples (no I/O, no clock)."""

from __future__ import annotations

import pytest

from bench.recorder.budgets import (
    FLUSH_P95_MS,
    RunResult,
    check_backlog,
    check_flush,
    check_gb_per_day,
    check_memory,
    check_rate,
    check_reconciliation,
    ingest_verdict,
    soak_verdict,
)


def _clean(**kw: object) -> RunResult:
    r = RunResult("full", 100.0, 10.0, ("BTCUSDT", "ETHUSDT"))
    r.produced_msgs, r.produced_rows, r.written_rows = 1_000, {"all": 3_000}, {"all": 3_000}
    r.dropped_rows = {"all": 0}
    r.flush_ms, r.rss_bytes = [1.0] * 20, [200 * 2**20] * 5
    r.backlog_rows, r.spill_bytes = [0] * 5, [0] * 5
    r.hot_bytes = int(14.04e9 * 2 * 10 / 86_400)  # 14.04 GB/day/symbol over 10 s
    for key, value in kw.items():
        setattr(r, key, value)
    return r


def test_soak_budget_passes_a_clean_run() -> None:
    v = soak_verdict(_clean(), 14.04, at_scale=True)
    assert v.passed, [(c.name, c.measured) for c in v.checks if not c.passed]


def test_soak_budget_fails_on_dropped_message() -> None:
    v = soak_verdict(
        _clean(written_rows={"all": 2_999}, dropped_rows={"all": 1}), 14.04, at_scale=True
    )
    failed = {c.name for c in v.checks if not c.passed}
    assert not v.passed and failed == {"dropped_rows"}  # accounted for by a gap, still a loss


def test_soak_budget_fails_on_spill_bytes() -> None:
    v = soak_verdict(_clean(spill_bytes=[0, 0, 4096, 0, 0]), 14.04, at_scale=True)
    assert not v.passed and {c.name for c in v.checks if not c.passed} == {"spill_bytes"}


def test_soak_budget_fails_on_backlog_p95_above_zero() -> None:
    assert not check_backlog([0] * 18 + [5, 5]).passed
    assert check_backlog([0] * 19 + [5]).passed  # p95 of 20 samples is the 19th


def test_soak_reconciliation_produced_equals_rows_plus_gap() -> None:
    assert check_reconciliation({"all": 10}, {"all": 7}, {"all": 3}).passed
    lost = check_reconciliation({"all": 10}, {"all": 7}, {"all": 2})
    duplicated = check_reconciliation({"all": 10}, {"all": 11}, {})
    assert not lost.passed and lost.measured == 1 and "all=+1" in lost.note
    assert not duplicated.passed and "all=-1" in duplicated.note


@pytest.mark.parametrize(
    ("measured", "passed"), [(14.04, True), (16.8, True), (17.0, False), (11.0, False)]
)
def test_soak_gb_per_day_fails_beyond_20_percent(measured: float, passed: bool) -> None:
    assert check_gb_per_day(measured, 14.04).passed is passed


def test_soak_gb_per_day_is_reported_not_gated_on_a_scaled_run() -> None:
    v = soak_verdict(_clean(hot_bytes=1), 14.04, at_scale=False)
    (gb,) = [c for c in v.checks if c.name == "gb_per_day_per_symbol"]
    assert not gb.passed and not gb.hard and v.passed


def test_gb_per_day_with_no_baseline_never_passes() -> None:
    assert not check_gb_per_day(1.0, 0.0).passed


def test_ingest_budget_fails_when_p95_flush_reaches_50ms() -> None:
    assert check_flush([1.0] * 19 + [49.9]).passed
    assert not check_flush([FLUSH_P95_MS] * 20).passed
    assert not ingest_verdict(_clean(flush_ms=[60.0] * 20)).passed


def test_flush_budget_fails_a_run_that_wrote_nothing() -> None:
    c = check_flush([])
    assert not c.passed and "wrote nothing" in c.note


def test_memory_ceiling_is_512_mib() -> None:
    assert check_memory([512 * 2**20]).passed
    assert not check_memory([512 * 2**20 + 1]).passed


def test_soak_rss_peak_is_reported_not_judged_on_a_scaled_run() -> None:
    """A smoke soak shares its process (CI's pytest session measured 866.8 MiB): its RSS peak is
    reported, never judged; the full profile keeps the absolute 512 MiB ceiling."""
    heavy = _clean(rss_bytes=[900 * 2**20])
    smoke = soak_verdict(heavy, 14.04, at_scale=False)
    (rss,) = [c for c in smoke.checks if c.name == "rss_peak"]
    assert not rss.passed and not rss.hard and "reported, not judged" in rss.note
    assert smoke.passed
    full = soak_verdict(heavy, 14.04, at_scale=True)
    assert not full.passed and {c.name for c in full.checks if not c.passed} == {"rss_peak"}
    (full_rss,) = [c for c in full.checks if c.name == "rss_peak"]
    assert full_rss.hard and full_rss.limit == 512.0


def test_rate_below_95_percent_of_target_fails() -> None:
    assert check_rate(95.0, 100.0).passed and not check_rate(94.9, 100.0).passed
    assert not ingest_verdict(_clean(produced_msgs=900)).passed  # 90 msg/s of 100


def test_run_result_rates_are_zero_for_an_empty_run() -> None:
    r = RunResult("smoke", 1.0, 0.0, ())
    assert r.achieved_msgs_per_s == 0.0 and r.gb_per_day_per_symbol() == 0.0

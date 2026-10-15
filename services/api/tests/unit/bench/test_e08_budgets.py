"""E08-Q04 assertion logic on fake samples: each budget passes and fails where it should.
Pure (no I/O, no clock)."""

from __future__ import annotations

import pytest

from bench.ingestion import budgets as b
from bench.ingestion.budgets import Sample

MiB = 2**20


def _samples(rss: list[int], cpu_step: float = 0.1, storage_step: int = 0) -> list[Sample]:
    return [Sample(i * 60.0, r, i * cpu_step, 1.0, 0, i * storage_step) for i, r in enumerate(rss)]


def test_loss_balanced_with_detected_gaps_passes() -> None:
    c = b.check_loss({"BTC": 100, "ETH": 50}, {"BTC": 95, "ETH": 50}, {"BTC": 5})
    assert c.passed and c.measured == 0


def test_loss_undetected_drop_fails_as_p0() -> None:
    c = b.check_loss({"BTC": 100}, {"BTC": 97}, {})
    assert not c.passed and c.measured == 3 and "P0" in c.note and "BTC=+3" in c.note


def test_loss_duplication_is_also_a_discrepancy() -> None:
    assert not b.check_loss({"BTC": 10}, {"BTC": 11}, {}).passed


def test_flatness_uses_baseline_sample_and_max_deviation() -> None:
    s = _samples([90 * MiB, 100 * MiB, 103 * MiB, 101 * MiB])
    dev, at = b.flatness(s, baseline_at_s=60.0)
    assert at == 60.0 and dev == pytest.approx(0.03)


def test_soak_checks_pass_within_budgets() -> None:
    checks = {c.name: c for c in b.check_soak(_samples([300 * MiB] * 5), 3, 60.0, 0.05)}
    assert all(c.passed for c in checks.values())
    assert checks["rss_per_symbol_p95"].measured == pytest.approx(100.0)


def test_soak_rss_over_budget_and_growth_fail() -> None:
    rss = [1000 * MiB, 1000 * MiB, 1060 * MiB, 1100 * MiB]
    checks = {c.name: c for c in b.check_soak(_samples(rss), 3, 60.0, 0.05)}
    assert not checks["rss_per_symbol_p95"].passed  # 1100/3 > 300 MB
    assert not checks["memory_flatness"].passed  # +10 %


def test_soak_cpu_and_storage_are_soft() -> None:
    s = _samples([10 * MiB] * 4, cpu_step=600.0, storage_step=10**9)
    checks = {c.name: c for c in b.check_soak(s, 1, 0.0, 0.05)}
    assert not checks["vcpu_per_symbol_p95"].passed and not checks["vcpu_per_symbol_p95"].hard
    assert not checks["storage_gb_day_symbol"].passed and not checks["storage_gb_day_symbol"].hard
    v = b.Verdict("x", list(checks.values()))
    assert v.passed  # soft budgets never fail the verdict


def test_isolation_detects_cross_symbol_impact() -> None:
    steady = {"A": [1.0] * 20, "B": [1.0] * 20, "HOT": [1.0] * 20}
    calm = {"A": [1.2] * 20, "B": [1.0] * 20, "HOT": [900.0] * 20}
    assert b.check_isolation(steady, calm, ["HOT"], 0.5, 0.5).passed
    hit = {**calm, "B": [5.0] * 20}
    c = b.check_isolation(steady, hit, ["HOT"], 0.5, 0.5)
    assert not c.passed and "worst=B" in c.note


def test_lag_band_never_tighter_than_floor() -> None:
    assert b.lag_band([0.01] * 10, 2.0, 0.5) == 2.0
    assert b.lag_band([10.0] * 10, 2.0, 0.5) == 15.0


@pytest.mark.parametrize(
    ("backlog", "recovery", "bp", "failed"),
    [
        (100, 5.0, 3.0, set()),
        (5000, 5.0, 3.0, {"queue_growth_bounded"}),
        (100, None, 3.0, {"recovery_s"}),
        (100, 45.0, 3.0, {"recovery_s"}),
        (100, 5.0, 0.0, {"backpressure_applied"}),
    ],
)
def test_burst_checks(backlog: int, recovery: float | None, bp: float, failed: set[str]) -> None:
    checks = b.check_burst(backlog, 2000, recovery, 30.0, bp)
    assert {c.name for c in checks if not c.passed} == failed


def test_latency_budget() -> None:
    assert b.check_latency([1.0] * 95 + [50.0] * 5).passed  # p95 = 1 ms
    assert not b.check_latency([1.0] * 90 + [25.0] * 10).passed


def test_rest_budget_and_cache_speedup() -> None:
    ok = b.check_rest({"a": 20.0, "klines_cold": 100.0}, 100.0, 10.0, 2.0)
    assert all(c.passed for c in ok)
    bad = {c.name: c for c in b.check_rest({"klines_cold": 200.0}, 200.0, 150.0, 2.0)}
    assert not bad["rest_p95[klines_cold]"].passed and not bad["klines_cache_speedup"].passed


def test_headroom_zero_or_ip_limit_fails() -> None:
    assert all(c.passed for c in b.check_headroom(3.0, 0, 0))
    assert not b.check_headroom(0.0, 0, 0)[0].passed
    assert not b.check_headroom(3.0, 0, 1)[1].passed
    assert not b.check_headroom(3.0, 1, 0)[1].passed


def test_summary_shape_matches_baseline_schema() -> None:
    assert b.summary([3.0, 1.0, 2.0]) == {"p50": 2.0, "p95": 3.0, "max": 3.0, "count": 3.0}
    assert b.summary([])["p95"] == 0.0

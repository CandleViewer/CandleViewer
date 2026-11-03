"""E12-Q05 slice 1 (#528): reporting math, the 5 % compare, the loopback guard and the scrubber.
Built on the BQ defaults; rulings pending."""

from __future__ import annotations

import math

import pytest

from bench.bars.compare import compare, compare_one, failures
from bench.bars.guard import assert_loopback_target
from bench.bars.scrub import scrub
from bench.bars.stats import RUNS_PER_CONFIG, distribution, median_run, relative_spread


def test_distribution_nearest_rank_percentiles() -> None:
    d = distribution([float(i) for i in range(1, 101)])
    assert (d.n, d.p50, d.p95, d.p99, d.max) == (100, 50.0, 95.0, 99.0, 100.0)


def test_distribution_discards_warmup_samples() -> None:
    d = distribution([1000.0, 1000.0, 1.0, 2.0, 3.0], warmup=2)
    assert (d.n, d.max) == (3, 3.0)


@pytest.mark.parametrize("samples,warmup", [([], 0), ([1.0, 2.0], 2), ([1.0, math.nan], 0)])
def test_distribution_rejects_empty_or_nan(samples: list[float], warmup: int) -> None:
    with pytest.raises(ValueError):
        distribution(samples, warmup=warmup)


def test_distribution_rejects_negative_warmup() -> None:
    with pytest.raises(ValueError):
        distribution([1.0], warmup=-1)


def test_median_run_picks_middle_regardless_of_order() -> None:
    assert median_run([9.0, 1.0, 5.0]) == 5.0


@pytest.mark.parametrize("n", [0, 1, 2, 4])
def test_median_run_requires_three_runs(n: int) -> None:
    assert RUNS_PER_CONFIG == 3
    with pytest.raises(ValueError):
        median_run([1.0] * n)


def test_relative_spread_flags_noisy_runs() -> None:
    assert relative_spread([9.0, 10.0, 11.0]) == pytest.approx(0.2)
    assert relative_spread([0.0, 0.0, 0.0]) == 0.0
    assert relative_spread([0.0, 0.0, 1.0]) == math.inf


def test_compare_boundary_exactly_at_threshold_passes() -> None:
    assert not compare_one("p95", 100.0, 105.0).regressed
    assert compare_one("p95", 100.0, 105.5).regressed


def test_compare_noise_floor_absorbs_tiny_absolute_deltas() -> None:
    d = compare_one("p95", 1.0, 1.15)  # +15 % but 0.15 ms < 0.2 ms floor
    assert not d.regressed and d.fraction == pytest.approx(0.15)


def test_compare_higher_is_better_flags_drops_only() -> None:
    assert compare_one("prints_s", 1000.0, 900.0, higher_is_better=True, min_delta=0).regressed
    assert not compare_one("prints_s", 1000.0, 1500.0, higher_is_better=True).regressed


def test_compare_names_series_and_delta_for_seeded_regression() -> None:
    ds = compare({"candle@100k": 10.0, "ohlc@100k": 10.0}, {"candle@100k": 15.0, "ohlc@100k": 10.1})
    msgs = failures(ds)
    assert len(msgs) == 1
    assert "candle@100k" in msgs[0] and "+50.0 %" in msgs[0]


def test_compare_missing_series_is_an_error() -> None:
    with pytest.raises(KeyError, match="ohlc"):
        compare({"candle": 1.0, "ohlc": 1.0}, {"candle": 1.0})


def test_compare_rejects_non_positive_baseline() -> None:
    with pytest.raises(ValueError):
        compare_one("x", 0.0, 1.0)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8000/x", "http://localhost:9/", "ws://[::1]:80", "127.0.0.5:1"]
)
def test_guard_accepts_loopback(url: str) -> None:
    assert assert_loopback_target(url) in ("127.0.0.1", "localhost", "::1", "127.0.0.5")


@pytest.mark.parametrize(
    "url",
    [
        "http://api.bybit.com/v5",
        "https://stream.bytick.com",
        "http://10.0.0.5:8000",
        "http://100.64.1.2",
        "http://staging.tailnet.ts.net",
        "http://0.0.0.0:1",
        "",
    ],
)
def test_guard_refuses_everything_else(url: str) -> None:
    with pytest.raises(RuntimeError):
        assert_loopback_target(url)


def test_scrub_removes_cookies_tokens_and_bearer() -> None:
    raw = (
        "Cookie: cv_session=abc123\nAuthorization: Bearer abc.def\n"
        "csrf_token=zzz9 url?access_token=qq&x=1 "
        'eyJhbGciOi.eyJzdWIiOi.sig123 password: "hunter2"\n'
    )
    out = scrub(raw)
    for leaked in ("abc123", "abc.def", "zzz9", "qq", "eyJhbGciOi", "hunter2"):
        assert leaked not in out
    assert "x=1" in out


def test_scrub_keeps_plain_numbers_and_names() -> None:
    line = "| builder | p95 | 12.3 |\nprints/s 1.2e6 at sha a7d659a"
    assert scrub(line) == line

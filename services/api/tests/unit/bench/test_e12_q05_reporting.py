"""E12-Q05 slice 1 (#528): reporting math, the per-class compare, the allow-list, the scrubber.
BQ ruling of record: #528, 15:33Z."""

from __future__ import annotations

import math
import time

import pytest

from bench.bars.compare import (
    THROUGHPUT,
    class_of,
    compare,
    compare_one,
    exit_code,
    failures,
    new_series,
)
from bench.bars.guard import assert_allowed_target, assert_may_record, gate_mode
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


def test_frame_class_is_five_percent_at_the_boundary() -> None:
    assert compare_one("frame_p95_ms", 100.0, 105.0).status == "ok"
    assert compare_one("frame_p95_ms", 100.0, 105.5).status == "fail"
    assert compare_one("draw_calls", 100.0, 105.5).regressed  # draw calls and memory: same class
    assert compare_one("rss_mib", 100.0, 105.5).regressed


def test_ms_floor_absorbs_tiny_absolute_deltas() -> None:
    d = compare_one("p95_ms", 1.0, 1.15)  # +15 % but 0.15 ms is under the 0.2 ms floor
    assert d.status == "ok" and d.fraction == pytest.approx(0.15)
    assert compare_one("draw_calls", 1.0, 1.15).regressed  # no floor off the _ms series


def test_throughput_class_is_t04_warn_10_fail_25_and_higher_is_better() -> None:
    assert class_of("renko_prints_per_s") is THROUGHPUT
    assert compare_one("x_prints_per_s", 1000.0, 920.0).status == "ok"
    assert compare_one("x_prints_per_s", 1000.0, 890.0).status == "warn"
    assert compare_one("x_prints_per_s", 1000.0, 749.0).status == "fail"
    assert compare_one("x_prints_per_s", 1000.0, 1500.0).status == "ok"  # faster is never worse


def test_seeded_regression_fails_the_job_and_names_series_and_delta() -> None:
    """AC3: a decimation-off style regression makes the compare fail the job (exit 1)."""
    base = {"candle@100k_ms": 10.0, "ohlc@100k_ms": 10.0}
    ds = compare(base, {"candle@100k_ms": 15.0, "ohlc@100k_ms": 10.1})
    msgs = failures(ds)
    assert exit_code(ds) == 1 and len(msgs) == 1
    assert "candle@100k_ms" in msgs[0] and "+50.0 %" in msgs[0] and "FAIL" in msgs[0]
    assert exit_code(compare(base, base)) == 0


def test_compare_new_series_are_listed_not_gated() -> None:
    assert new_series({"a": 1.0}, {"a": 1.0, "z": 2.0, "b": 3.0}) == ["b", "z"]
    assert len(compare({"a": 1.0}, {"a": 1.0, "z": 9.0})) == 1


def test_compare_missing_series_is_an_error() -> None:
    with pytest.raises(KeyError, match="ohlc"):
        compare({"candle": 1.0, "ohlc": 1.0}, {"candle": 1.0})


def test_compare_rejects_non_positive_baseline() -> None:
    with pytest.raises(ValueError):
        compare_one("x", 0.0, 1.0)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/",
        "http://localhost:9",
        "http://[::1]:80",
        "http://api:8000",
        "HTTP://API",
    ],
)
def test_guard_accepts_loopback_and_compose_api_only(url: str) -> None:
    assert assert_allowed_target(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://api.bybit.com/v5",
        "http://api.bybit.com./v5",
        "https://stream.bytick.com",
        "http://localhost.:9",  # a trailing dot is another name: no DNS-style normalising
        "http://127.0.0.5:1",
        "http://10.0.0.5:8000",
        "http://100.64.1.2",
        "http://staging.tailnet.ts.net",
        "http://api.example.com",
        "http://0.0.0.0:1",
        "http://127.0.0.1:8000@evil.example",
        "https://127.0.0.1",
        "",
    ],
)
def test_guard_refuses_everything_else(url: str) -> None:
    with pytest.raises(RuntimeError):
        assert_allowed_target(url)


def test_refuse_to_start_rules_follow_ws_load() -> None:
    assert_may_record({})
    with pytest.raises(RuntimeError):
        assert_may_record({"CI": "true"})
    assert gate_mode("ci-runner", "ci-runner") == "gate"
    assert gate_mode(None, "ci-runner") == gate_mode("laptop", "ci-runner") == "record-only"


def _pem(kind: str, body: str, *, end: bool) -> str:
    """Built at run time so no key-shaped literal sits in the source (gitleaks private-key rule)."""
    label = kind + "PRIVATE" + " KEY"
    tail = f"\n-----END {label}-----" if end else ""
    return f"-----BEGIN {label}-----\n{body}{tail}"


@pytest.mark.parametrize(
    "raw,secret",
    [
        ("Cookie: cv_session=abc123", "abc123"),
        ("Authorization: Bearer abc.def", "abc.def"),
        ('{"apiKey": "k-123"}', "k-123"),
        ('{"api_secret":"s3cr3t"}', "s3cr3t"),
        ('{"password" : "hunter2 x"}', "hunter2"),
        ("cv_session=zz9", "zz9"),
        ("passwd=pw1", "pw1"),
        ("apikey=ak1", "ak1"),
        ("dek=ZGVr", "ZGVr"),
        ("kek=a2Vr", "a2Vr"),
        ("totp=123456", "123456"),
        ("otp: 654321", "654321"),
        ("refresh_token=rt1", "rt1"),
        ("x?access_token=qq&y=1", "qq"),
        ("csrf_token=zzz9", "zzz9"),
        ("eyJhbGciOi.eyJzdWIiOi.sig123", "eyJhbGciOi"),
        (_pem("", "MIIEv\nabc", end=True), "MIIEv"),
        (_pem("RSA ", "MIIEp\ntruncated", end=False), "MIIEp"),
    ],
)
def test_scrub_removes_every_secret_shape(raw: str, secret: str) -> None:
    out = scrub(raw)
    assert secret not in out and "[REDACTED]" in out


@pytest.mark.parametrize("blank", ["\n" * 50_000, " \n" * 50_000, "\t\r\n" * 30_000])
def test_scrub_is_linear_on_blank_lines(blank: str) -> None:
    t0 = time.perf_counter()
    assert scrub(blank + "Cookie: a=b").endswith("Cookie: [REDACTED]")
    assert time.perf_counter() - t0 < 1.0


def test_scrub_keeps_quotes_so_json_stays_valid() -> None:
    import json

    out = scrub('{"apiKey": "k-1", "n": 3, "token": "a\\"b c"}')
    assert json.loads(out) == {"apiKey": "[REDACTED]", "n": 3, "token": "[REDACTED]"}


@pytest.mark.parametrize(
    "raw,secret",
    [
        ("password: 'p w'", " w"),
        ("token='a\\'b c' tail", "b c"),
        ("{'apiKey': 'k 1'}", "k 1"),
    ],
)
def test_scrub_handles_single_quoted_values(raw: str, secret: str) -> None:
    out = scrub(raw)
    assert secret not in out and "'[REDACTED]'" in out


def test_scrub_redacts_an_unterminated_single_quoted_value() -> None:
    assert "oops" not in scrub("secret: 'oops here")


def test_scrub_redacts_an_unterminated_quoted_value() -> None:
    assert "oops" not in scrub('{"secret": "oops')


def test_scrub_leaves_neighbouring_fields() -> None:
    assert "y=1" in scrub("x?access_token=qq&y=1")
    assert "inside=5" in scrub("inside=5 outside=6")


def test_scrub_keeps_plain_numbers_and_names() -> None:
    line = "| builder | p95 | 12.3 |\nprints/s 1.2e6 at sha a7d659a"
    assert scrub(line) == line

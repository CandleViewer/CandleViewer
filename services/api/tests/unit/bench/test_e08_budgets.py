"""E08-Q04 assertion logic on fake samples: each budget passes and fails where it should.
Pure (no I/O, no clock), apart from the k6 driver's tests, which fake k6, the fixture app and its
server, and write to `tmp_path`."""

from __future__ import annotations

import copy
import functools
import json
import math
import statistics
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bench.ingestion import budgets as b
from bench.ingestion import rest_load
from bench.ingestion.budgets import Sample
from bench.ingestion.config import Scenario
from bench.ingestion.fixture_app import requests_plan

MiB = 2**20
HOUR = 3600.0


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


def test_rss_per_symbol_is_what_the_lanes_added_and_the_footprint_is_reported_apart() -> None:
    s = _samples([300 * MiB, 330 * MiB, 360 * MiB])
    # a 270 MiB process before the lanes were built: 30, 60, 90 MiB added over 3 symbols
    assert b.rss_per_symbol_mb(s, 3, 270 * MiB) == pytest.approx([10.0, 20.0, 30.0])
    assert b.rss_process_mb(s) == pytest.approx([300.0, 330.0, 360.0])
    assert b.rss_per_symbol_mb(_samples([250 * MiB]), 3, 270 * MiB) == [0.0]  # RSS fell: not < 0


def test_budget_8_ignores_the_import_footprint_but_still_fails_real_lane_growth() -> None:
    imports = _samples([2000 * MiB, 2010 * MiB, 2030 * MiB])  # a big process, small lane growth
    ok = b.check_soak(imports, 3, 60.0, 0.05, 2000 * MiB)[0]
    assert ok.name == "rss_per_symbol_p95" and ok.passed and ok.measured == pytest.approx(10.0)
    assert "2000.0 MiB" in ok.note
    lanes = _samples([2000 * MiB, 2500 * MiB, 3000 * MiB])  # 3 x 333 MB added: a real breach
    bad = b.check_soak(lanes, 3, 60.0, 0.05, 2000 * MiB)[0]
    assert not bad.passed and bad.hard and bad.limit == b.B8_RSS_MB_PER_SYMBOL == 300.0


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
    assert bad["rest_p95[klines_cold]"].hard and bad["klines_cache_speedup"].hard


def test_rest_budget_reported_soft_keeps_the_cache_speedup_hard() -> None:
    soft = {
        c.name: c
        for c in b.check_rest({"klines_cold": 200.0}, 200.0, 150.0, 2.0, budget_hard=False)
    }
    cold = soft["rest_p95[klines_cold]"]
    assert not cold.passed and not cold.hard and soft["klines_cache_speedup"].hard


def _rest(profile: str) -> Scenario:
    return Scenario(
        name="rest_k6",
        title="",
        kind="rest",
        profile=profile,
        scaling="",
        params={"min_cache_speedup": 2.0},
        tolerances={},
    )


@pytest.mark.parametrize(
    ("profile", "passed"), [("smoke", True), ("full", False)], ids=["smoke", "full"]
)
def test_rest_verdict_gates_budget_13_only_in_the_full_profile(profile: str, passed: bool) -> None:
    """#399: the smoke profile reports Budget #13's 150 ms (`06` measures it with k6 on the bench
    runner, the full profile) and fails only on its hard checks; the cache speed-up holds here."""
    lat = {r: [20.0] * 20 for r in requests_plan()}
    lat |= {"klines_cold": [400.0] * 20, "klines_warm": [10.0] * 20}
    v = rest_load.verdict(_rest(profile), lat)
    assert v.passed is passed
    assert {c.hard for c in v.checks if c.name.startswith("rest_p95[")} == {not passed}


@pytest.mark.parametrize(
    "absent", [("klines_warm", "trades"), ("klines_cold",)], ids=["warm", "cold"]
)
@pytest.mark.parametrize("profile", ["smoke", "full"])
def test_a_route_with_no_reading_fails_the_verdict_in_every_profile(
    profile: str, absent: tuple[str, ...]
) -> None:
    """#399: a route the driver did not measure (k6 wrote no p95 for it) fails, named; an
    unmeasured cold or warm read fails the speed-up, never a 0.0 or an `inf` that passes."""
    lat = {r: [20.0] * 20 for r in requests_plan() if r not in absent}
    v = rest_load.verdict(_rest(profile), lat)
    named = {c.name: c for c in v.checks if c.name.startswith("rest_measured[")}
    assert not v.passed and set(named) == {f"rest_measured[{r}]" for r in absent}
    assert all(c.hard and not c.passed for c in named.values())
    speed = next(c for c in v.checks if c.name == "klines_cache_speedup")
    assert speed.hard and not speed.passed
    assert not {f"rest_p95[{r}]" for r in absent} & {c.name for c in v.checks}  # never a 0.0 row


def test_a_warm_read_of_zero_fails_the_cache_speed_up() -> None:
    """#2825: a 0 ms warm p95 is no reading, never an `inf` speed-up that passes."""
    speed = b.check_rest({}, 100.0, 0.0, 2.0)[-1]
    assert speed.name == "klines_cache_speedup" and speed.hard and not speed.passed


#: A canned `--summary-export` (#2825), with the stats the script asks k6 for (`summaryTrendStats`)
#: and no failed check: a route sampled, one sampled under a millisecond, one with no samples, one
#: from an export with no `count` and a 0.0 p95, one with no `count` and a real p95, and one whose
#: `count` of 0 contradicts its p95; the rest absent.
_K6: dict[str, Any] = {
    "metrics": {
        "checks": {"passes": 2400, "fails": 0, "value": 1.0},
        "route_instruments_ms": {"p(50)": 3.0, "p(95)": 8.5, "max": 20.0, "count": 300},
        "route_data_coverage_ms": {"p(50)": 0.2, "p(95)": 0.4, "max": 0.9, "count": 900},
        "route_klines_cold_ms": {"p(50)": 0.0, "p(95)": 0.0, "max": 0.0, "count": 0},
        "route_klines_warm_ms": {"p(95)": 0.0},
        "route_trades_ms": {"p(95)": 12.0},
        "route_orderbook_ms": {"p(95)": 5.0, "count": 0},
    }
}
_K6_READ = {"instruments": [8.5], "data_coverage": [0.4], "trades": [12.0]}


def _k6(checks: dict[str, float] | None = None, **p95: float) -> str:
    """`_K6` as k6 writes it: `checks` replaces its checks counts (an empty mapping drops them), and
    each keyword sets that route's p95."""
    doc = copy.deepcopy(_K6)
    metrics = doc["metrics"]
    if checks is not None:
        metrics["checks"] = checks
    for route, value in p95.items():
        metrics[f"route_{route}_ms"]["p(95)"] = value
    return json.dumps(doc)


def test_k6_reading_keeps_only_the_routes_k6_sampled() -> None:
    """#2825: a route k6 took no samples for (`count` 0, or a 0.0 p95) has no reading, like a
    route it wrote nothing for; a summary with neither checks nor routes reads nothing."""
    assert rest_load.k6_reading(0, _k6()) == _K6_READ
    assert rest_load.k6_reading(0, json.dumps({"metrics": {}})) == {}


def test_k6_reading_keeps_a_99_that_a_route_over_150_ms_explains() -> None:
    """#2825: a route's p95 over Budget #13 crosses its threshold (99), and `verdict` fails it."""
    assert rest_load.k6_reading(99, _k6(trades=160.0)) == _K6_READ | {"trades": [160.0]}


@pytest.mark.parametrize("code", [1, 98, 107, 255])
def test_k6_reading_refuses_a_run_k6_ended_with_an_error(code: int) -> None:
    """#2825: only 0 and 99 leave a reading; a script, configuration or run error refuses it."""
    with pytest.raises(RuntimeError, match=f"k6 exited {code}"):
        rest_load.k6_reading(code, _k6())


@pytest.mark.parametrize(
    ("code", "text", "match"),
    [
        (0, _k6({"passes": 2397, "fails": 3, "value": 0.99875}), "counted 3 failed checks"),
        (99, _k6(), "no route's p95 over 150 ms"),
        (99, _k6({}), "no route's p95 over 150 ms"),
        (0, "", "wrote no summary"),
        (0, '{"metrics": {', "unreadable summary"),
    ],
    ids=["failed-checks", "unexplained-99", "unexplained-99-no-count", "no-summary", "cut-short"],
)
def test_k6_reading_refuses_a_summary_of_no_valid_run(code: int, text: str, match: str) -> None:
    """#2825: a response that was not a 200 fails a check, and a failed check refuses the run, as
    the in-process driver refuses a non-200: counted, or as a 99 no route's p95 explains; so do a
    missing or an unreadable summary."""
    with pytest.raises(RuntimeError, match=match):
        rest_load.k6_reading(code, text)


def test_a_k6_run_whose_routes_took_no_samples_fails_the_full_verdict() -> None:
    """#2825: the canned summary through `verdict`: each route without samples fails, named."""
    v = rest_load.verdict(_rest("full"), rest_load.k6_reading(0, _k6()))
    failed = {c.name for c in v.checks if c.name.startswith("rest_measured[") and not c.passed}
    assert not v.passed and failed == {
        f"rest_measured[{r}]" for r in set(requests_plan()) - set(_K6_READ)
    }


@pytest.fixture
def faked_k6(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """`drive_k6` with k6, the fixture app and its server faked: no network, no sleep, its files
    under `tmp_path`. Set `.code`, `.text` (None: k6 writes no summary) and `.starts` first."""
    import uvicorn

    state = SimpleNamespace(code=0, text=_k6(), starts=True, servers=[])

    class Server:
        def __init__(self, config: object) -> None:
            self.started, self.should_exit = state.starts, False
            state.servers.append(self)

        def run(self) -> None:
            return None

    def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        if state.text is not None:
            Path(argv[argv.index("--summary-export") + 1]).write_text(state.text, "utf-8")
        return subprocess.CompletedProcess(argv, state.code)

    async def build_app(_: Path) -> object:
        return object()

    temp = functools.partial(tempfile.TemporaryDirectory, dir=tmp_path)
    monkeypatch.setattr("bench.ingestion.rest_load.shutil.which", lambda _: "/fake/k6")
    monkeypatch.setattr(rest_load, "write_cold_lake", lambda _: None)
    monkeypatch.setattr(rest_load, "build_app", build_app)
    monkeypatch.setattr(rest_load, "_free_port", lambda: 8123)
    monkeypatch.setattr("bench.ingestion.rest_load.subprocess.run", run)
    monkeypatch.setattr("bench.ingestion.rest_load.time.sleep", lambda _: None)
    monkeypatch.setattr("bench.ingestion.rest_load.tempfile.TemporaryDirectory", temp)
    monkeypatch.setattr(uvicorn, "Server", Server)
    monkeypatch.setattr(uvicorn, "Config", lambda *_, **__: None)
    return state


def test_drive_k6_reads_k6s_summary_and_stops_the_app(faked_k6: SimpleNamespace) -> None:
    """#2825: the driver hands k6's exit code and summary to `k6_reading`, then stops the app."""
    assert rest_load.drive_k6("1s", 1) == _K6_READ
    assert [s.should_exit for s in faked_k6.servers] == [True]


@pytest.mark.parametrize(
    ("code", "text", "starts", "match"),
    [
        (107, None, True, "k6 exited 107"),
        (0, None, True, "wrote no summary"),
        (0, _k6(), False, "fixture app did not start"),
    ],
    ids=["k6-error", "no-summary", "app-not-started"],
)
def test_drive_k6_refuses_an_invalid_run_and_still_stops_the_app(
    faked_k6: SimpleNamespace, code: int, text: str | None, starts: bool, match: str
) -> None:
    """#2825: a k6 error, a missing summary or an app that never started is no reading."""
    faked_k6.code, faked_k6.text, faked_k6.starts = code, text, starts
    with pytest.raises(RuntimeError, match=match):
        rest_load.drive_k6("1s", 1)
    assert [s.should_exit for s in faked_k6.servers] == [True]


def test_headroom_zero_or_ip_limit_fails() -> None:
    assert all(c.passed for c in b.check_headroom(3.0, 0, 0))
    assert not b.check_headroom(0.0, 0, 0)[0].passed
    assert not b.check_headroom(3.0, 0, 1)[1].passed
    assert not b.check_headroom(3.0, 1, 0)[1].passed


def test_summary_shape_matches_baseline_schema() -> None:
    assert b.summary([3.0, 1.0, 2.0]) == {"p50": 2.0, "p95": 3.0, "max": 3.0, "count": 3.0}
    assert b.summary([])["p95"] == 0.0


# --- R4, the plateau of the bars soak (#399 D2-G4) ----------------------------------------------


def _lane_curve(
    per_symbol_mb: Callable[[float], float],
    *,
    pre: int = 58 * MiB,
    symbols: int = 3,
    end_s: float = 86_400.0,
    step_s: float = 60.0,
) -> list[Sample]:
    """A sample every `step_s` to `end_s`: `pre` bytes and what `per_symbol_mb(t)` adds a symbol."""
    n = int(end_s / step_s) + 1
    return [
        Sample(t, pre + round(per_symbol_mb(t) * symbols * MiB), t * 0.01, 1.0, 0, 0)
        for t in (i * step_s for i in range(n))
    ]


def _wobble(t: float) -> float:
    """A zero-mean wobble of at most 0.5 MB, deterministic in `t` (no random numbers)."""
    return ((int(t / 60) * 41) % 101 - 50) / 100.0


def test_the_plateau_limit_is_the_headroom_under_budget_8_over_30_days() -> None:
    # R4 as pre-registered on #399: (300 - 170) MB over 720 h, 0.18 MB/h, at least 100 samples
    assert b.SLOPE_LIMIT_MB_PER_H == round((b.B8_RSS_MB_PER_SYMBOL - 170.0) / 720.0, 2) == 0.18
    assert b.PLATEAU_MIN_SAMPLES == 100


def test_theil_sen_is_the_median_of_the_pairwise_slopes_in_mb_per_hour() -> None:
    line = [(t, 5.0 + 2.0 * t / HOUR) for t in (0.0, 600.0, 1800.0, 3600.0, 7200.0)]
    assert b.theil_sen_mb_per_h(line) == pytest.approx(2.0)
    assert b.theil_sen_mb_per_h(line[::-1]) == pytest.approx(2.0)  # the order of the points is moot
    wild = [*line[:2], (1800.0, 500.0), *line[3:]]  # one wild sample moves no median of 10 slopes
    assert b.theil_sen_mb_per_h(wild) == pytest.approx(2.0)
    assert b.theil_sen_mb_per_h([(0.0, 1.0), (0.0, 9.0), (3600.0, 3.0)]) == pytest.approx(-2.0)


def test_theil_sen_has_no_slope_without_two_points_at_different_times() -> None:
    for points in ([], [(0.0, 1.0)], [(5.0, 1.0), (5.0, 2.0)]):
        with pytest.raises(statistics.StatisticsError):
            b.theil_sen_mb_per_h(points)


@pytest.mark.parametrize(
    ("mb_per_h", "passed"),
    [(0.0, True), (0.05, True), (0.15, True), (0.25, False), (0.42, False)],
)
def test_plateau_holds_the_slope_a_symbol_to_the_pre_registered_limit(
    mb_per_h: float, passed: bool
) -> None:
    s = _lane_curve(lambda t: 170.0 + mb_per_h * t / HOUR + _wobble(t))
    c = b.check_plateau(s, 3, 12 * HOUR)
    assert (c.name, c.budget, c.limit) == ("rss_plateau_slope", "#8", 0.18)
    assert (c.unit, c.hard) == ("MB/h", True)
    assert c.measured == pytest.approx(mb_per_h, abs=0.01) and c.passed is passed
    assert "721 samples" in c.note  # hours 12 to 24, both ends in


def test_a_creep_inside_the_flatness_band_passes_it_and_fails_the_plateau() -> None:
    """0.25 MB/h a symbol is 16.5 MiB over the 22 h after hour 2: 2.9 % of the process RSS, inside
    R2's 5 % band, and far under 300 MB. Only the slope sees it use the headroom in 22 days."""
    pre = 58 * MiB
    s = _lane_curve(lambda t: 170.0 + 0.25 * t / HOUR, pre=pre)
    checks = {c.name: c for c in b.check_soak(s, 3, 0.0833 * 86_400, 0.05, pre)}
    assert checks["memory_flatness"].passed and checks["rss_per_symbol_p95"].passed
    assert checks["memory_flatness"].measured == pytest.approx(0.029, abs=0.002)
    r4 = b.check_plateau(s, 3, 12 * HOUR, pre)
    assert not r4.passed and r4.measured == pytest.approx(0.25, abs=0.001)
    assert not b.Verdict("x", [*checks.values(), r4]).passed  # a hard check: it fails the verdict


def test_plateau_reads_the_last_window_and_neither_more_nor_less() -> None:
    def climb_before_the_window(t: float) -> float:  # +20 MB a symbol over hours 0-12, flat after
        return 170.0 + 20.0 * min(t, 12 * HOUR) / (12 * HOUR)

    def climb_inside_the_window(t: float) -> float:  # +10 MB a symbol over hours 12-18, flat after
        return 170.0 + 10.0 * max(0.0, min(t, 18 * HOUR) - 12 * HOUR) / (6 * HOUR)

    before = b.check_plateau(_lane_curve(climb_before_the_window), 3, 12 * HOUR)
    assert before.passed  # the window is flat: the climb before it is not read
    inside = b.check_plateau(_lane_curve(climb_inside_the_window), 3, 12 * HOUR)
    assert not inside.passed and inside.measured == pytest.approx(10.0 / 12.0, abs=0.01)


def test_plateau_reads_a_step_only_near_the_middle_and_under_reads_late_growth() -> None:
    """A step moves the median only if it separates more than half of the pairs: +10 MB a symbol
    (+30 MiB over three symbols) fails at hour 18, the window's middle, and reads 0 at hours 16 and
    20 (measured: it reads non-zero only within about 13 minutes of the middle). Growth of 4 MB/h a
    symbol from hour 22 (+8 MB, inside R2's band) reads 0 too: R4 reads sustained growth, and R2's
    band (5 % of the process RSS) stays the guard for a large step."""

    def step(hour: float, mb: float) -> b.Check:
        s = _lane_curve(lambda t: 170.0 + (mb if t >= hour * HOUR else 0.0))
        return b.check_plateau(s, 3, 12 * HOUR)

    middle, small = step(18, 10.0), step(18, 1.0)  # the small one is +3 MiB
    assert not middle.passed and middle.measured > 0.5
    assert small.passed and 0.05 < small.measured < b.SLOPE_LIMIT_MB_PER_H
    assert step(16, 10.0).measured == 0.0 and step(20, 10.0).measured == 0.0
    late = _lane_curve(lambda t: 170.0 + 4.0 * max(0.0, t - 22 * HOUR) / HOUR)
    assert b.check_plateau(late, 3, 12 * HOUR).measured == 0.0


def test_plateau_passes_noise_around_a_flat_level_and_a_decline() -> None:
    noisy = b.check_plateau(_lane_curve(lambda t: 170.0 + 2 * _wobble(t)), 3, 12 * HOUR)
    assert noisy.passed and abs(noisy.measured) < 0.01
    falling = b.check_plateau(_lane_curve(lambda t: 200.0 - 0.5 * t / HOUR), 3, 12 * HOUR)
    assert falling.passed and falling.measured == pytest.approx(-0.5, abs=0.001)  # not growth


def test_plateau_reads_budget_8s_figure_the_rss_the_lanes_added() -> None:
    """The figure is the RSS since before the lanes, never below 0: the first half of the window
    here sits under it and reads 0, so the climb that follows is 10 MB over 6 h, not 20 over 12."""
    pre = 600 * MiB
    s = _lane_curve(lambda t: -10.0 + 20.0 * (t - 12 * HOUR) / (12 * HOUR), pre=pre)
    c = b.check_plateau(s, 3, 12 * HOUR, pre)
    assert c.measured == pytest.approx(10.0 / 12.0, abs=0.01) and not c.passed
    # a whole-process RSS (nothing taken out) would read the climb as 20 MB over 12 h
    assert b.check_plateau(s, 3, 12 * HOUR).measured == pytest.approx(20.0 / 12.0, abs=0.01)


def test_plateau_is_in_the_unit_of_budget_8_a_mebibyte_not_a_million_bytes() -> None:
    """The harness's "MB" is 2**20 bytes: R1's 300 is compared in it, and so is R4's 0.18."""
    # one symbol, 2**20 bytes more each hour, a sample an hour for 100 hours
    s = _lane_curve(lambda t: t / HOUR, pre=0, symbols=1, end_s=100 * HOUR, step_s=HOUR)
    r1_figure = b.rss_per_symbol_mb(s, 1)
    assert r1_figure[1] - r1_figure[0] == 1.0  # R1's figure rises by 1 MB each hour
    assert b.check_plateau(s, 1, 99 * HOUR).measured == 1.0  # and R4 reads 1 MB/h, not 1.048576


def test_plateau_is_per_symbol() -> None:
    s = _lane_curve(lambda t: 170.0 + 0.15 * t / HOUR)  # three symbols, 0.45 MB/h in all
    assert b.check_plateau(s, 3, 12 * HOUR).passed
    one = b.check_plateau(s, 1, 12 * HOUR)  # the same bytes on one symbol
    assert not one.passed and one.measured == pytest.approx(0.45, abs=0.001)


def test_plateau_passes_a_slope_exactly_at_the_limit_and_fails_just_over_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(b, "SLOPE_LIMIT_MB_PER_H", 0.5)  # 0.5 MB an hour is exact in binary
    at = _lane_curve(lambda t: 0.5 * t / HOUR, pre=0, symbols=1, end_s=100 * HOUR, step_s=HOUR)
    exact = b.check_plateau(at, 1, 99 * HOUR)  # 100 samples, one an hour: 0.5 MiB between two
    assert exact.measured == 0.5 and exact.limit == 0.5 and exact.passed  # "<=", not "<"
    over = _lane_curve(lambda t: 0.5001 * t / HOUR, pre=0, symbols=1, end_s=100 * HOUR, step_s=HOUR)
    assert not b.check_plateau(over, 1, 99 * HOUR).passed


def test_plateau_wants_100_samples_in_the_window_and_fails_with_a_note_on_fewer() -> None:
    s = _lane_curve(lambda t: 170.0, end_s=300.0, step_s=1.0)  # 301 samples, one a second
    enough = b.check_plateau(s, 3, 99.0)  # t >= 201: 100 samples, both ends in
    assert enough.passed and enough.measured == 0.0 and "100 samples" in enough.note
    few = b.check_plateau(s, 3, 98.0)  # 99 samples
    assert not few.passed and few.hard and few.measured == math.inf
    assert "99 samples" in few.note and "no reading" in few.note
    assert not b.check_plateau([], 3, 12 * HOUR).passed  # no sample at all

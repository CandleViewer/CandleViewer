"""E08-Q04 assertion logic on fake samples: each budget passes and fails where it should.
Pure (no I/O, no clock), apart from the drivers' tests, which fake k6, the two fixture apps and
their servers, and write to `tmp_path` (the weekly run's tests start the runner, whose reports go
there too), and the k6 script's tests, which read the script or run it under node over stubbed
k6 modules."""

from __future__ import annotations

import asyncio
import copy
import functools
import json
import math
import re
import shutil
import statistics
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode

import pytest

from bench.ingestion import budgets as b
from bench.ingestion import rest_load, runner
from bench.ingestion.budgets import Sample
from bench.ingestion.config import Scenario
from bench.ingestion.fixture_app import FIRST_READ, assert_loopback_target, requests_plan

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


def _rest_checks(p95: dict[str, float], **kw: Any) -> dict[str, b.Check]:
    """`check_rest` as `verdict` calls it: the first read over the warm read, at least 2.0x."""
    checks = b.check_rest(p95, 2.0, first="klines_cold_first", repeat="klines_warm", **kw)
    return {c.name: c for c in checks}


def test_rest_budget_and_cache_speedup() -> None:
    ok = _rest_checks({"a": 20.0, "klines_cold_first": 100.0, "klines_warm": 10.0})
    assert all(c.passed for c in ok.values())
    bad = _rest_checks({"klines_cold": 200.0, "klines_cold_first": 200.0, "klines_warm": 150.0})
    assert not bad["rest_p95[klines_cold]"].passed and not bad["klines_cache_speedup"].passed
    assert bad["rest_p95[klines_cold]"].hard and bad["klines_cache_speedup"].hard


def test_rest_budget_reported_soft_keeps_the_cache_speedup_hard() -> None:
    soft = _rest_checks(
        {"klines_cold": 200.0, "klines_cold_first": 200.0, "klines_warm": 150.0}, budget_hard=False
    )
    cold = soft["rest_p95[klines_cold]"]
    assert not cold.passed and not cold.hard and soft["klines_cache_speedup"].hard


def test_the_cache_speed_up_is_the_first_read_over_the_warm_read() -> None:
    """#2523: a read no cache has served (`klines_cold_first`) over a repeat read (`klines_warm`),
    both named in the note. `klines_cold` is not in it: with a page cache it is a repeat read."""
    rows = _rest_checks({"klines_cold": 5.0, "klines_cold_first": 100.0, "klines_warm": 10.0})
    speed = rows["klines_cache_speedup"]
    assert speed.passed and speed.measured == 10.0
    assert speed.note == "klines_cold_first p95 100.00ms vs klines_warm p95 10.00ms"
    slow_cold = {"klines_cold": 400.0, "klines_cold_first": 15.0, "klines_warm": 10.0}
    assert not _rest_checks(slow_cold)["klines_cache_speedup"].passed  # 1.5x, whatever cold reads


@pytest.mark.parametrize("budget_hard", [True, False])
def test_the_first_reads_row_is_reported_and_never_gated(budget_hard: bool) -> None:
    """#2523: the first read's 150 ms row is soft whatever the profile, under its own note; the
    other routes' rows are as before."""
    rows = _rest_checks(
        {"klines_cold": 400.0, "klines_cold_first": 400.0, "klines_warm": 10.0},
        budget_hard=budget_hard,
    )
    first, cold = rows["rest_p95[klines_cold_first]"], rows["rest_p95[klines_cold]"]
    assert (first.measured, first.limit, first.passed, first.hard) == (400.0, 150.0, False, False)
    assert first.note == b.B13_FIRST_READ == "a first read: reported, no budget (#2523)"
    assert (cold.passed, cold.hard) == (False, budget_hard)
    assert cold.note == ("" if budget_hard else "reported, not gated, in the smoke profile (#399)")


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
    runner, the full profile) and fails only on its hard checks; the cache speed-up holds here.
    The first read's row is reported in both (#2523)."""
    lat = {r: [20.0] * 20 for r in requests_plan()}
    lat |= {r: [400.0] * 20 for r in ("klines_cold", "klines_cold_first")}
    lat |= {"klines_warm": [10.0] * 20}
    v = rest_load.verdict(_rest(profile), lat)
    assert v.passed is passed
    rows = {c.name: c.hard for c in v.checks if c.name.startswith("rest_p95[")}
    assert rows.pop("rest_p95[klines_cold_first]") is False
    assert set(rows.values()) == {not passed}


_SMOKE_SOFT = "reported, not gated, in the smoke profile (#399)"


@pytest.mark.parametrize(
    ("profile", "weekly", "note"),
    [
        ("smoke", False, _SMOKE_SOFT),
        ("full", False, ""),
        ("full", True, rest_load.B13_SOFT_WEEKLY),
    ],
    ids=["smoke", "full", "weekly"],
)
def test_a_slow_first_read_fails_no_hard_check_in_any_profile(
    profile: str, weekly: bool, note: str
) -> None:
    """#2523: a first read at 400 ms is reported against 150 ms, under its own note, and gates
    nothing in the smoke, the full profile or the weekly run; every other route's row is as
    before (all at 20 ms here, the warm one at 10)."""
    lat = {r: [20.0] * 20 for r in requests_plan()}
    lat |= {"klines_cold_first": [400.0] * 20, "klines_warm": [10.0] * 20}
    v = rest_load.verdict(_rest(profile), lat, b13_report_only=weekly)
    assert v.passed and [c.name for c in v.checks if c.hard and not c.passed] == []
    rows = {c.name: c for c in v.checks if c.name.startswith("rest_p95[")}
    first = rows.pop("rest_p95[klines_cold_first]")
    assert (first.passed, first.hard, first.note) == (False, False, b.B13_FIRST_READ)
    others = {(c.limit, c.passed, c.hard, c.note) for c in rows.values()}
    assert others == {(150.0, True, profile == "full" and not weekly, note)}
    assert len(rows) == len(requests_plan()) - 1


@pytest.mark.parametrize(
    "absent",
    [("klines_warm", "trades"), ("klines_cold_first",), ("klines_cold",)],
    ids=["warm", "first", "cold"],
)
@pytest.mark.parametrize("profile", ["smoke", "full"])
def test_a_route_with_no_reading_fails_the_verdict_in_every_profile(
    profile: str, absent: tuple[str, ...]
) -> None:
    """#399: a route the driver did not measure (k6 wrote no p95 for it) fails, named; an
    unmeasured first or warm read fails the speed-up, never a 0.0 or an `inf` that passes. The
    first read is such a route too (#2523), and `klines_cold` is not in the speed-up."""
    lat = {r: [20.0] * 20 for r in requests_plan() if r not in absent}
    lat |= {r: [400.0] * 20 for r in ("klines_cold_first",) if r not in absent}  # a 20x speed-up
    v = rest_load.verdict(_rest(profile), lat)
    named = {c.name: c for c in v.checks if c.name.startswith("rest_measured[")}
    assert not v.passed and set(named) == {f"rest_measured[{r}]" for r in absent}
    assert all(c.hard and not c.passed for c in named.values())
    speed = next(c for c in v.checks if c.name == "klines_cache_speedup")
    unmeasured = bool({"klines_cold_first", "klines_warm"} & set(absent))
    assert speed.hard and speed.passed is not unmeasured
    assert math.isnan(speed.measured) is unmeasured
    assert not {f"rest_p95[{r}]" for r in absent} & {c.name for c in v.checks}  # never a 0.0 row


def test_a_warm_read_of_zero_fails_the_cache_speed_up() -> None:
    """#2825: a 0 ms warm p95 is no reading, never an `inf` speed-up that passes."""
    speed = _rest_checks({"klines_cold_first": 100.0, "klines_warm": 0.0})["klines_cache_speedup"]
    assert speed.hard and not speed.passed and math.isnan(speed.measured)


def test_the_plan_marks_klines_colds_request_alone_for_the_first_read_server() -> None:
    """#2523: `klines_cold_first` is `klines_cold`'s request, marked `FIRST_READ` for the drivers
    to send to the first-read server, and the only route marked; the marker is no parameter."""
    plan = requests_plan()
    assert [r for r, spec in plan.items() if spec.get(FIRST_READ)] == ["klines_cold_first"]
    assert plan["klines_cold_first"] == {**plan["klines_cold"], FIRST_READ: True}
    assert FIRST_READ == "first_read" and FIRST_READ not in plan["klines_cold_first"]["params"]


@pytest.mark.parametrize("marked", [[], ["klines_cold", "klines_cold_first"]], ids=["none", "two"])
def test_verdict_refuses_a_plan_that_marks_no_single_first_read(
    monkeypatch: pytest.MonkeyPatch, marked: list[str]
) -> None:
    """#2523: `verdict` takes the first read from the plan's `FIRST_READ` marker, as the drivers
    do, never by its name: a plan that marks no route, or two, is refused, never guessed."""
    plan = {r: {**spec, FIRST_READ: r in marked} for r, spec in requests_plan().items()}
    monkeypatch.setattr(rest_load, "requests_plan", lambda: plan)
    with pytest.raises(RuntimeError, match=re.escape(f"the plan marks {marked} as the first read")):
        rest_load.verdict(_rest("full"), {r: [20.0] * 20 for r in plan})


_Seen = list[tuple[str, str, tuple[tuple[str, str], ...]]]


def _asgi(name: str, seen: _Seen) -> Any:
    """An ASGI app that answers 200 to anything and notes who answered which path and query."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        query = tuple(sorted(parse_qsl(scope["query_string"].decode())))
        seen.append((name, scope["path"], query))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    return app


async def test_drive_inprocess_sends_the_first_read_to_its_own_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#2523: the marked route goes to the first-read app (`build_first_read_app`) through a client
    of its own, and every other route to the app: each warmed once untimed, then timed `iterations`
    times under its own name. Its query is `klines_cold`'s params, and nothing else."""
    seen: _Seen = []

    async def app(_: Path) -> Any:
        return _asgi("app", seen)

    async def first_read_app(_: Path) -> Any:
        return _asgi("first-read app", seen)

    temp = functools.partial(tempfile.TemporaryDirectory, dir=tmp_path)
    monkeypatch.setattr("bench.ingestion.rest_load.tempfile.TemporaryDirectory", temp)
    monkeypatch.setattr(rest_load, "write_cold_lake", lambda _: 0)
    monkeypatch.setattr(rest_load, "build_app", app)
    monkeypatch.setattr(rest_load, "build_first_read_app", first_read_app)

    lat = await rest_load.drive_inprocess(iterations=3, concurrency=2)

    plan = requests_plan()
    assert {r: len(x) for r, x in lat.items()} == dict.fromkeys(plan, 3)
    want: Counter[tuple[str, str, tuple[tuple[str, str], ...]]] = Counter()
    for spec in plan.values():
        server = "first-read app" if spec.get(FIRST_READ) else "app"
        query = tuple(sorted((k, str(v)) for k, v in spec["params"].items()))
        want[(server, spec["path"], query)] += 1 + 3  # one untimed warm-up, three timed calls
    assert Counter(seen) == want


@pytest.mark.parametrize("concurrency", [1, 2])
async def test_drive_inprocess_runs_the_first_read_in_a_pool_of_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, concurrency: int
) -> None:
    """#2523: the 7 routes run `iterations` rounds on the driver's `concurrency` slots, the mix
    recorded before the first-read leg, and the first read as many rounds beside them, in a pool
    of its own (`FIRST_READ_POOL`, one at a time). The first-read app holds each timed first read
    until the mix's last request is answered: a first read on one of the mix's slots, or a mix
    request waiting on the first read's pool, would leave the mix waiting on it, and time out."""
    mix_left, mix_done = 7 * (1 + 3), asyncio.Event()  # each route warmed once, then timed 3 times
    busy, peak = {"app": 0, "first": 0}, {"app": 0, "first": 0}
    firsts: list[bool] = []  # at each first read, whether the mix was done

    def fake(name: str) -> Callable[[Path], Any]:
        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            nonlocal mix_left
            busy[name] += 1
            peak[name] = max(peak[name], busy[name])
            if name == "first":
                firsts.append(mix_done.is_set())
                if len(firsts) > 1:  # its warm-up is answered at once
                    await mix_done.wait()
            await asyncio.sleep(0)  # a read yields to the loop, as a real one does
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})
            busy[name] -= 1
            if name == "app":
                mix_left -= 1
                if mix_left == 0:
                    mix_done.set()

        async def build(_: Path) -> Any:
            return app

        return build

    temp = functools.partial(tempfile.TemporaryDirectory, dir=tmp_path)
    monkeypatch.setattr("bench.ingestion.rest_load.tempfile.TemporaryDirectory", temp)
    monkeypatch.setattr(rest_load, "write_cold_lake", lambda _: 0)
    monkeypatch.setattr(rest_load, "build_app", fake("app"))
    monkeypatch.setattr(rest_load, "build_first_read_app", fake("first"))

    async with asyncio.timeout(10):  # a bound on a failure, never the pass condition
        lat = await rest_load.drive_inprocess(iterations=3, concurrency=concurrency)

    assert {r: len(x) for r, x in lat.items()} == dict.fromkeys(requests_plan(), 3)
    assert rest_load.FIRST_READ_POOL == 1 and peak == {"app": concurrency, "first": 1}
    assert firsts == [False, False, True, True]  # warmed, then timed beside the mix, one at a time


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
    """`_K6` as k6 writes it, a zero `fails` among its checks counts: `checks` replaces those (an
    empty mapping leaves no `fails`), and each keyword sets that route's p95."""
    doc = copy.deepcopy(_K6)
    metrics = doc["metrics"]
    if checks is not None:
        metrics["checks"] = checks
    for route, value in p95.items():
        metrics[f"route_{route}_ms"]["p(95)"] = value
    return json.dumps(doc)


def _no_checks(text: str) -> str:
    """`text`, a k6 summary, as an export that wrote no `checks` metric at all."""
    doc = json.loads(text)
    del doc["metrics"]["checks"]
    return json.dumps(doc)


_NO_COUNT = "k6 wrote no checks count: the run is unknown"


def test_k6_reading_keeps_only_the_routes_k6_sampled() -> None:
    """#2825: a route k6 took no samples for (`count` 0, or a 0.0 p95) has no reading, like a
    route it wrote nothing for; a summary with a clean checks count and no routes reads nothing."""
    assert rest_load.k6_reading(0, _k6()) == _K6_READ
    assert rest_load.k6_reading(0, json.dumps({"metrics": {"checks": {"fails": 0}}})) == {}


def test_k6_reading_keeps_a_99_that_a_route_at_or_over_150_ms_explains() -> None:
    """#2825: a route's p95 at or over Budget #13 crosses its threshold (99), so the run is kept
    for `verdict` to judge; at exactly 150.0, which a `<=` would refuse."""
    assert rest_load.k6_reading(99, _k6(trades=150.0)) == _K6_READ | {"trades": [150.0]}


def test_k6_reading_a_first_read_over_150_ms_explains_no_99() -> None:
    """#2523: the script arms no threshold on the first-read route, so its p95 over 150 ms is read
    on a 0, and a 99 that it alone would explain is a failed check."""
    slow = _every_route(klines_cold_first=527.5)
    assert rest_load.k6_reading(0, slow)["klines_cold_first"] == [527.5]
    with pytest.raises(RuntimeError, match="no route's p95 at or over 150 ms"):
        rest_load.k6_reading(99, slow)


@pytest.mark.parametrize("code", [1, 98, 107, 255])
def test_k6_reading_refuses_a_run_k6_ended_with_an_error(code: int) -> None:
    """#2825: only 0 and 99 leave a reading; a script, configuration or run error refuses it."""
    with pytest.raises(RuntimeError, match=f"k6 exited {code}"):
        rest_load.k6_reading(code, _k6())


@pytest.mark.parametrize(
    ("code", "text", "match"),
    [
        (0, _k6({"passes": 2397, "fails": 3, "value": 0.99875}), "counted 3 failed checks"),
        (99, _k6(), "no route's p95 at or over 150 ms"),
        (99, _k6(trades=149.9), "no route's p95 at or over 150 ms"),
        (0, _no_checks(_k6()), _NO_COUNT),
        (0, _k6({"passes": 2400, "value": 1.0}), _NO_COUNT),
        (99, _k6({}), _NO_COUNT),
        (99, _no_checks(_k6(trades=527.5)), _NO_COUNT),
        (0, "", "wrote no summary"),
        (0, '{"metrics": {', "unreadable summary"),
    ],
    ids=[
        "failed-checks",
        "unexplained-99",
        "unexplained-99-just-under",
        "no-checks",
        "no-fails",
        "empty-checks-99",
        "slow-route-no-checks",
        "no-summary",
        "cut-short",
    ],
)
def test_k6_reading_refuses_a_summary_of_no_valid_run(code: int, text: str, match: str) -> None:
    """#2825: a response that was not a 200 fails a check, and a failed check refuses the run, as
    the in-process driver refuses a non-200: counted, or as a 99 no route's p95 explains. A summary
    with no `checks` count is an unknown run (the script always calls `check()`, so the export
    changed), refused on every exit, a 99 that a slow route explains too. So are a missing and an
    unreadable summary."""
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
    """`drive_k6` with k6, the two fixture apps and their servers faked: no network, no sleep, its
    files under `tmp_path`. Set `.code`, `.text` (None: k6 writes no summary) and `.starts` first;
    `.argv` is then k6's command line, and each of `.servers` has the `.config` it was made with."""
    import uvicorn

    state = SimpleNamespace(code=0, text=_k6(), starts=True, servers=[], argv=[])

    class Server:
        def __init__(self, config: dict[str, object]) -> None:
            self.config, self.started, self.should_exit = config, state.starts, False
            state.servers.append(self)

        def run(self) -> None:
            return None

    def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        state.argv = argv
        if state.text is not None:
            Path(argv[argv.index("--summary-export") + 1]).write_text(state.text, "utf-8")
        return subprocess.CompletedProcess(argv, state.code)

    async def build_app(_: Path) -> str:
        return "app"

    async def build_first_read_app(_: Path) -> str:
        return "first-read app"

    temp = functools.partial(tempfile.TemporaryDirectory, dir=tmp_path)
    monkeypatch.delenv(rest_load.K6_EXPORT_ENV, raising=False)  # a developer's own never leaks in
    monkeypatch.setattr("bench.ingestion.rest_load.shutil.which", lambda _: "/fake/k6")
    monkeypatch.setattr(rest_load, "write_cold_lake", lambda _: None)
    monkeypatch.setattr(rest_load, "build_app", build_app)
    monkeypatch.setattr(rest_load, "build_first_read_app", build_first_read_app)
    monkeypatch.setattr(rest_load, "_free_ports", lambda n: [8123, 8124][:n])
    monkeypatch.setattr("bench.ingestion.rest_load.subprocess.run", run)
    monkeypatch.setattr("bench.ingestion.rest_load.time.sleep", lambda _: None)
    monkeypatch.setattr("bench.ingestion.rest_load.tempfile.TemporaryDirectory", temp)
    monkeypatch.setattr(uvicorn, "Server", Server)
    monkeypatch.setattr(uvicorn, "Config", lambda app, **kw: {"app": app, **kw})
    return state


def test_drive_k6_reads_k6s_summary_and_stops_the_app(faked_k6: SimpleNamespace) -> None:
    """#2825: the driver hands k6's exit code and summary to `k6_reading`, then stops the apps."""
    assert rest_load.drive_k6("1s", 1) == _K6_READ
    assert [s.should_exit for s in faked_k6.servers] == [True, True]


def test_drive_k6_serves_the_first_read_from_its_own_loopback_server(
    faked_k6: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2523: a second server, over the first-read app, on a loopback port of its own; both URLs
    pass the loopback check before any server is made, k6 gets the second as BASE_URL_FIRST
    beside BASE_URL, and both servers stop once k6 is done."""
    checked: list[str] = []

    def check(url: str) -> None:
        assert not faked_k6.servers, "a server was made before its URL was checked"
        assert_loopback_target(url)
        checked.append(url)

    monkeypatch.setattr(rest_load, "assert_loopback_target", check)
    assert rest_load.drive_k6("1s", 1) == _K6_READ
    assert checked == ["http://127.0.0.1:8123", "http://127.0.0.1:8124"]
    served = [(s.config["app"], s.config["host"], s.config["port"]) for s in faked_k6.servers]
    assert served == [("app", "127.0.0.1", 8123), ("first-read app", "127.0.0.1", 8124)]
    env = [faked_k6.argv[i + 1] for i, arg in enumerate(faked_k6.argv) if arg == "-e"]
    assert env[:2] == ["BASE_URL=http://127.0.0.1:8123", "BASE_URL_FIRST=http://127.0.0.1:8124"]
    assert [s.should_exit for s in faked_k6.servers] == [True, True]


def test_drive_k6_sets_the_load_with_e_never_with_k6s_own_load_flags(
    faked_k6: SimpleNamespace,
) -> None:
    """#2523: the duration and the VUs reach the script as `-e` DURATION and VUS, and none of
    k6's own load flags, long or short: --vus and --duration would replace both scenarios with
    one that runs the default export, which the script lacks (the node run below)."""
    assert rest_load.drive_k6("7s", 3) == _K6_READ
    env = [faked_k6.argv[i + 1] for i, arg in enumerate(faked_k6.argv) if arg == "-e"]
    assert {"DURATION=7s", "VUS=3"} <= set(env)
    k6_load = {"--vus", "-u", "--duration", "-d", "--iterations", "-i", "--stage", "-s"}
    assert k6_load.isdisjoint(arg.partition("=")[0] for arg in faked_k6.argv)


def test_free_ports_binds_every_socket_before_it_closes_any(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2523: a port is free again once its socket closes, so `_free_ports` holds every socket
    until all are bound: each bind precedes any close, and the `n` ports differ. The fake OS binds
    the lowest port no open socket holds, so a socket closed early would hand its port on."""
    held: set[int] = set()
    calls: list[str] = []

    class Socket:
        def __init__(self) -> None:
            self.port, self.closed = 0, False

        def __enter__(self) -> Socket:
            return self

        def __exit__(self, *_: object) -> None:
            self.close()

        def bind(self, address: tuple[str, int]) -> None:
            assert address == ("127.0.0.1", 0)
            self.port = min(set(range(40_000, 40_010)) - held)
            held.add(self.port)
            calls.append("bind")

        def getsockname(self) -> tuple[str, int]:
            if self.closed:
                raise OSError(9, "Bad file descriptor")  # as a closed socket's does
            return ("127.0.0.1", self.port)

        def close(self) -> None:
            self.closed = True
            held.discard(self.port)
            calls.append("close")

    monkeypatch.setattr(rest_load, "socket", SimpleNamespace(socket=Socket))
    assert rest_load._free_ports(3) == [40_000, 40_001, 40_002]
    assert calls == ["bind"] * 3 + ["close"] * 3 and not held


def test_drive_k6_refuses_one_port_for_both_servers(
    faked_k6: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2523: two uvicorn servers bound to one port can both report started, so the driver refuses
    a pair of equal ports before it makes a server, and k6 never runs."""
    monkeypatch.setattr(rest_load, "_free_ports", lambda n: [8123] * n)
    with pytest.raises(RuntimeError, match="both fixture apps were given port 8123: no reading"):
        rest_load.drive_k6("1s", 1)
    assert faked_k6.servers == [] and faked_k6.argv == []


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
    assert [s.should_exit for s in faked_k6.servers] == [True, True]


def test_drive_k6_app_up_on_the_third_sleep_reads_the_run(
    faked_k6: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2825: the driver waits for the servers to listen, a short sleep at a time; one that looked
    once would refuse every run whose app came up a moment late. It waits for both (#2523): the
    app listens after the first sleep, the first-read app only after the third."""
    faked_k6.starts = False
    naps: list[float] = []

    def sleep(seconds: float) -> None:
        naps.append(seconds)
        if len(naps) == 1:
            faked_k6.servers[0].started = True  # the app
        elif len(naps) == 3:
            faked_k6.servers[1].started = True  # the first-read app, two sleeps later

    monkeypatch.setattr("bench.ingestion.rest_load.time.sleep", sleep)
    assert rest_load.drive_k6("1s", 1) == _K6_READ and len(naps) == 3


def test_drive_k6_refuses_a_run_whose_first_read_server_never_listens(
    faked_k6: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2523: the driver waits for both servers; the app up and the first-read app never is no
    reading, and both are stopped."""
    faked_k6.starts = False

    def sleep(_: float) -> None:
        faked_k6.servers[0].started = True

    monkeypatch.setattr("bench.ingestion.rest_load.time.sleep", sleep)
    with pytest.raises(RuntimeError, match="fixture app did not start"):
        rest_load.drive_k6("1s", 1)
    assert [s.should_exit for s in faked_k6.servers] == [True, True]


@pytest.mark.parametrize(
    "text", [_k6().replace(", ", ",\r\n"), None], ids=["crlf-summary", "no-summary"]
)
def test_drive_k6_refused_run_keeps_k6s_export_byte_for_byte(
    faked_k6: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str | None
) -> None:
    """#2825: k6's own bytes (CRLFs, which a text copy would not keep) where the workflow names,
    written before `k6_reading` refuses the run: a refused run's export is its evidence. Where k6
    wrote no summary, nothing is kept and the run is still refused, never an `OSError`."""
    keep = tmp_path / "reports" / "rest_k6-k6-summary.json"
    monkeypatch.setenv(rest_load.K6_EXPORT_ENV, str(keep))
    faked_k6.code, faked_k6.text = 107, text
    with pytest.raises(RuntimeError, match="k6 exited 107"):
        rest_load.drive_k6("1s", 1)
    kept = keep.read_bytes() if keep.exists() else None
    assert kept == (text.encode("utf-8") if text else None)


def test_drive_k6_no_export_variable_writes_nothing(
    faked_k6: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#2825: unset (a local run), the driver keeps nothing: once its temporary directory is gone,
    the directory it ran in is as empty as before."""
    monkeypatch.delenv(rest_load.K6_EXPORT_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    assert rest_load.drive_k6("1s", 1) == _K6_READ and not any(tmp_path.iterdir())


def _every_route(**p95: float) -> str:
    """k6's summary of a run that sampled every route, at 20 ms but for `p95`; no check failed."""
    routes = {f"route_{r}_ms": {"p(95)": p95.get(r, 20.0), "count": 300} for r in requests_plan()}
    return json.dumps({"metrics": {"checks": {"passes": 2100, "fails": 0}, **routes}})


@pytest.fixture
def weekly(faked_k6: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The full pack's rest_k6 as the weekly cron starts it (#2825), over the faked k6: cold
    klines at 527.5 ms cross their threshold (99), the first read is as slow (it has none,
    #2523), and every other check passes."""
    monkeypatch.setenv("CV_BENCH_MACHINE_PROFILE", "unit-test")  # gated against no baseline
    monkeypatch.setenv(rest_load.B13_REPORT_ONLY_ENV, "1")
    faked_k6.code, faked_k6.text = 99, _every_route(klines_cold=527.5, klines_cold_first=527.5)
    return faked_k6


def _pack(tmp_path: Path) -> int:
    """The runner's exit code, started as the pack step starts it."""
    return runner.main(["rest_k6", "--profile", "full", "--out-dir", str(tmp_path / "reports")])


def test_runner_weekly_run_only_budget_13_over_warns_and_exits_0(
    weekly: SimpleNamespace, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#2825: until slice 2 decides Budget #13, the weekly run names the routes over it, green,
    so it files no issue. The first read is not one of them: it has no budget (#2523)."""
    assert _pack(tmp_path) == 0
    warned = [x for x in capsys.readouterr().out.splitlines() if x.startswith("::warning::")]
    over = "over Budget #13's 150 ms: rest_p95[klines_cold] 527.5 ms"
    assert warned == [f"::warning::rest_k6: {over}; {rest_load.B13_SOFT_WEEKLY}"]


def test_runner_dispatch_budget_13_over_exits_1(
    weekly: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#2825: a dispatch sets the variable empty, so Budget #13 still gates it."""
    monkeypatch.setenv(rest_load.B13_REPORT_ONLY_ENV, "")
    assert _pack(tmp_path) == 1


def test_runner_dispatch_only_the_first_read_over_150_ms_exits_0(
    weekly: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#2523: a dispatch gates Budget #13, and the first read has no budget: alone over 150 ms
    (k6 exits 0, as no threshold is armed on it), it fails nothing and is in no annotation."""
    monkeypatch.setenv(rest_load.B13_REPORT_ONLY_ENV, "")
    weekly.code, weekly.text = 0, _every_route(klines_cold_first=527.5)
    assert _pack(tmp_path) == 0
    assert not [x for x in capsys.readouterr().out.splitlines() if x.startswith("::")]


@pytest.mark.parametrize(
    ("code", "text", "starts", "match"),
    [
        (107, None, True, "k6 exited 107"),
        (0, None, True, "wrote no summary"),
        (0, _k6({"passes": 2397, "fails": 3, "value": 0.99875}), True, "counted 3 failed"),
        (99, _no_checks(_every_route(klines_cold=527.5)), True, _NO_COUNT),
        (99, _every_route(klines_cold=527.5), False, "fixture app did not start"),
    ],
    ids=["k6-error", "no-summary", "failed-checks", "no-checks-count", "app-not-started"],
)
def test_runner_weekly_run_invalid_k6_run_still_fails(
    weekly: SimpleNamespace,
    tmp_path: Path,
    code: int,
    text: str | None,
    starts: bool,
    match: str,
) -> None:
    """#2825: report-only never masks a broken run: no reading, no report, and the step fails."""
    weekly.code, weekly.text, weekly.starts = code, text, starts
    with pytest.raises(RuntimeError, match=match):
        _pack(tmp_path)
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize(
    "p95",
    [{"klines_warm": 0.0}, {"klines_warm": 400.0}, {"trades": 0.0}],
    ids=["warm-no-reading", "no-speed-up", "trades-no-reading"],
)
def test_runner_weekly_run_another_failed_check_exits_1(
    weekly: SimpleNamespace, tmp_path: Path, p95: dict[str, float]
) -> None:
    """#2825: only the 150 ms rows are reported; every other hard check still fails the weekly run:
    warm klines with no samples (no reading, so no speed-up either), warm klines at 400 ms (a 1.3x
    speed-up from the first read's 527.5 ms, under the minimum, #2523) and a route with no
    samples, each of the last two failing that one check alone."""
    weekly.text = _every_route(klines_cold=527.5, klines_cold_first=527.5, **p95)
    assert _pack(tmp_path) == 1


def test_k6_script_arms_only_checks_and_each_gated_routes_budget_13_p95() -> None:
    """#2825: `k6_reading` blames a 99 that no route's p95 at or over Budget #13 explains on a
    failed check, which holds while the script arms those two kinds of threshold and no other, at
    the budget's own number: a drift fails here, not as "a check failed" on the bench runner. The
    route the plan marks `FIRST_READ` arms none (#2523): it is reported, never gated."""
    src = rest_load.K6_SCRIPT.read_text(encoding="utf-8")
    assert src.count("thresholds") == 3  # declared, filled in per gated route, handed to `options`
    assert re.search(r'^const thresholds = \{ checks: \["rate>0\.99"\] \};$', src, re.M)
    gated = rf"^const GATED = ROUTES\.filter\(\(r\) => !PLAN\[r\]\.{FIRST_READ}\);"
    route = r'^for \(const r of GATED\) thresholds\[`route_\$\{r\}_ms`\] = \["p\(95\)<(\d+)"\];'
    (limit,) = re.findall(route, src, re.M)
    assert re.search(gated, src, re.M) and re.search(r"^  thresholds,$", src, re.M)
    assert float(limit) == b.B13_READ_P95_MS


def test_k6_script_sends_the_first_read_to_its_own_loopback_server() -> None:
    """#2523: BASE_URL_FIRST, where the first read goes (its own scenario, run under node below),
    must be set and pass BASE_URL's own loopback check, or the script fails; only `params` reach
    the query."""
    src = rest_load.K6_SCRIPT.read_text(encoding="utf-8")
    assert re.search(r'^const BASE_FIRST = __ENV\.BASE_URL_FIRST \|\| "";$', src, re.M)
    for base in ("BASE", "BASE_FIRST"):
        assert re.search(rf"^if \(!LOOPBACK\.test\({base}\)\) \{{\n  fail\(`refusing ", src, re.M)
    assert "http.get(`${base}${spec.path}?${qs(spec.params)}`" in src


#: `k6`, `k6/http` and `k6/metrics` for node, so that the k6 script runs outside k6 (#2523): each
#: request, the trend it adds to and its check are noted in `globalThis.did`, in order, and every
#: response is a 200.
_K6_STUB = (
    "export default { get(url, params) { globalThis.did.push(['get', params.tags.route, url]); "
    "return { status: 200, timings: { duration: 1 } }; } }; "
    "export class Trend { constructor(name) { this.name = name; } "
    "add() { globalThis.did.push(['add', this.name]); } } "
    "export function check(res, sets) { for (const [name, ok] of Object.entries(sets)) "
    "globalThis.did.push(['check', name, ok(res)]); } "
    "export function fail(why) { throw new Error(why); }"
)
_BASE, _BASE_FIRST = "http://127.0.0.1:8123", "http://127.0.0.1:8124"
#: What `encodeURIComponent` leaves as it is beyond `quote`'s own: `quote` then encodes as it does.
_URI_SAFE = "!*'()"


def _k6_iteration(tmp_path: Path, **k6_env: str) -> dict[str, Any]:
    """The k6 script, run by node over `_K6_STUB` with `drive_k6`'s two base URLs and `k6_env` in
    its `__ENV` (#2523): the names it exports, its `options`, and what one iteration of each
    scenario's `exec` did."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH: the k6 script runs under it here")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(requests_plan()), encoding="utf-8")
    env = {"BASE_URL": _BASE, "BASE_URL_FIRST": _BASE_FIRST, "PLAN": str(plan), **k6_env}
    hook = (
        "export async function resolve(s, c, next) { return s === 'k6' || s.startsWith('k6/') ? "
        f"{{ url: 'data:text/javascript,' + encodeURIComponent({json.dumps(_K6_STUB)}), "
        "shortCircuit: true } : next(s, c); }"
    )
    script = f"""
    import {{ register }} from 'node:module';
    import {{ readFileSync }} from 'node:fs';
    register('data:text/javascript,' + encodeURIComponent({json.dumps(hook)}));
    Object.assign(globalThis, {{ __ENV: {json.dumps(env)}, open: (p) => readFileSync(p, 'utf8') }});
    const k6 = await import({json.dumps(rest_load.K6_SCRIPT.as_uri())});
    const did = {{}};
    for (const [name, scenario] of Object.entries(k6.options.scenarios)) {{
      globalThis.did = did[name] = [];
      k6[scenario.exec ?? 'default']();
    }}
    console.log(JSON.stringify({{ exports: Object.keys(k6), options: k6.options, did }}));
    """
    done = subprocess.run(  # noqa: S603 - node, over a script of this test's own
        [node, "--no-warnings", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    got: dict[str, Any] = json.loads(done.stdout)
    return got


@pytest.mark.parametrize(
    ("k6_env", "vus", "duration"),
    [({}, 5, "60s"), ({"VUS": "3", "DURATION": "7s"}, 3, "7s")],
    ids=["default-env", "vus-3-duration-7s"],
)
def test_k6_script_runs_the_first_read_in_a_scenario_of_its_own(
    tmp_path: Path, k6_env: dict[str, str], vus: int, duration: str
) -> None:
    """#2523: `reads`, VUS users (5 by default), sends the 7 budget routes to BASE_URL, the mix
    recorded before the first-read leg; `first_read` sends the marked route alone to
    BASE_URL_FIRST, at a fixed arrival rate of its own, so its latency sets neither its own load
    nor the 7 routes' pace. Both run for DURATION, so the first read spans the pack's 10 minutes.
    Each request adds to its route's trend and is checked; only the 7 routes arm Budget #13. No
    default export: the one scenario k6's own --vus and --duration would make runs it, so such a
    run fails rather than send a mix of its own."""
    got, plan = _k6_iteration(tmp_path, **k6_env), requests_plan()
    assert got["exports"] == ["firstRead", "options", "reads"]  # a namespace lists them sorted
    mix = [r for r, spec in plan.items() if not spec.get(FIRST_READ)]
    assert got["options"]["scenarios"] == {
        "reads": {"executor": "constant-vus", "exec": "reads", "vus": vus, "duration": duration},
        "first_read": {
            "executor": "constant-arrival-rate",
            "exec": "firstRead",
            "rate": 1,
            "timeUnit": "1s",
            "duration": duration,
            "preAllocatedVUs": 2,
        },
    }
    budget = {f"route_{r}_ms": [f"p(95)<{b.B13_READ_P95_MS:g}"] for r in mix}
    assert got["options"]["thresholds"] == {"checks": ["rate>0.99"], **budget}

    def iteration(base: str, routes: list[str]) -> list[list[Any]]:
        out: list[list[Any]] = []
        for r in routes:
            query = urlencode(plan[r]["params"], safe=_URI_SAFE, quote_via=quote)
            out += [["get", r, f"{base}{plan[r]['path']}?{query}"], ["add", f"route_{r}_ms"]]
            out.append(["check", f"{r} 200", True])
        return out

    assert got["did"] == {
        "reads": iteration(_BASE, mix),
        "first_read": iteration(_BASE_FIRST, ["klines_cold_first"]),
    }


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

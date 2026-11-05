"""E42-Q03 (#1216) part 4 self-tests: the WAL check and the load judge [BQ-8].

No network, no stack, run in the ordinary PR lane, as part 1's. Pins the WAL check (its cap is the
writer's, its depth the bytes no compaction frees, a blind reading never a pass) and the load judge
(the probe's nearest-rank p90 against 300 ms and against its idle figure, the reads' A/B, the
bounds held in every run, a failed call never a duration, and every flood miss named as waiting on
#2836), and SCR-143's added-load judge (the A/A noise gates the delta, the median of the three
B-minus-A deltas, the CPU per read set).
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bench.admin import datasets, load_harness
from candleviewer.audit.wal import AuditWal

wal_check = load_harness("wal_check")
load_results = load_harness("load_results")
T0 = datetime(2026, 11, 4, 10, tzinfo=UTC)


# -- the WAL check ---------------------------------------------------------------------------
def _wal(directory: Path, name: str, size: int, committed: int) -> None:
    (directory / name).write_bytes(b"x" * size)
    (directory / f"{name}.committed").write_text(str(committed))


def test_wal_check_reads_each_wal_with_a_cursor_and_its_uncompactable_depth(tmp_path: Path) -> None:
    _wal(tmp_path, "audit.wal", 1000, 400)
    _wal(tmp_path, "oms_lane.main", 10, 10)
    (tmp_path / "audit.wal.lock").write_text("")
    (tmp_path / "notes.txt").write_text("not a wal")
    reading = wal_check.sample(tmp_path)
    assert reading == {
        "audit.wal": {"size": 1000, "committed": 400, "depth": 600},
        "oms_lane.main": {"size": 10, "committed": 10, "depth": 0},
    }


def test_wal_cap_is_the_writers_and_the_limit_is_80_percent() -> None:
    assert inspect.signature(AuditWal).parameters["max_bytes"].default == wal_check.CAP_BYTES
    assert wal_check.LIMIT == 0.8 == load_results.WAL_LIMIT
    assert load_results.WAL_CAP_BYTES == wal_check.CAP_BYTES


def test_wal_judge_fails_past_the_limit_and_a_blind_reading_never_passes() -> None:
    limit = int(wal_check.LIMIT * wal_check.CAP_BYTES)
    at = [{"audit.wal": {"size": limit, "committed": 0, "depth": limit}}]
    over = [{"audit.wal": {"size": limit + 1, "committed": 0, "depth": limit + 1}}]
    cap = wal_check.CAP_BYTES
    full_but_committed = [{"audit.wal": {"size": cap, "committed": cap, "depth": 0}}]
    assert wal_check.judge(at)["verdict"] == "PASS"
    assert wal_check.judge(over)["verdict"] == "FAIL"
    assert wal_check.judge(full_but_committed)["verdict"] == "PASS"  # a full file compacts
    assert wal_check.judge([])["verdict"] == "BLIND" == wal_check.judge([{}])["verdict"]


def test_wal_watch_reads_before_during_and_after(tmp_path: Path) -> None:
    _wal(tmp_path, "audit.wal", 5, 0)
    calls = iter([False, False, True])
    ticks = iter(range(10))
    readings = wal_check.watch(tmp_path, lambda _i: next(calls), clock=lambda: float(next(ticks)))
    assert [r["at"] for r in readings] == [0.0, 1.0, 2.0, 3.0]
    assert wal_check.main(["check", str(tmp_path)]) == 0


def test_wal_watch_records_a_failed_reading_blind_and_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wal(tmp_path, "audit.wal", 5, 0)
    moving = iter([None, OSError("cursor kept moving"), None, None])

    def flaky(path: Path) -> dict[str, int]:
        if isinstance(err := next(moving), OSError):
            raise err
        return {"size": 5, "committed": 0, "depth": 5}

    monkeypatch.setattr(wal_check, "read_one", flaky)
    calls = iter([False, False, True])
    readings = wal_check.watch(tmp_path, lambda _i: next(calls), clock=lambda: 0.0)
    assert [bool(r["wal"]) for r in readings] == [True, False, True, True]
    assert wal_check.judge([r["wal"] for r in readings])["verdict"] == "BLIND"


# -- the load judge --------------------------------------------------------------------------
def _at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "123Z"


def _point(metric: str, at_s: float, value: float, **tags: str) -> str:
    data = {"time": _at(at_s), "value": value, "tags": tags}
    return json.dumps({"type": "Point", "metric": metric, "data": data})


def _run(
    path: Path,
    probe_idle: list[float],
    probe_load: list[float],
    reads: tuple[float, float] = (50.0, 50.0),
    depth: int = 1000,
    bounds: dict[str, bool] | None = None,
    extra: list[str] | None = None,
) -> Path:
    """A run: the window is 30 s to 60 s; idle samples before it, loaded ones inside it."""
    edge0 = (T0 + timedelta(seconds=30)).timestamp() * 1000
    lines = [_point("cv_admin_edge_at", 30, edge0, edge="start"),
             _point("cv_admin_edge_at", 60, edge0 + 30_000, edge="end")]  # fmt: skip
    for i, v in enumerate(probe_idle):
        lines.append(_point("cv_admin_probe_ms", i, v, ok="0" if v < 0 else "1", code="x"))
    for i, v in enumerate(probe_load):
        lines.append(_point("cv_admin_probe_ms", 31 + i, v, ok="0" if v < 0 else "1", code="x"))
    for i in range(20):
        lines.append(_point("cv_admin_read_ms", 5 + i, reads[0], combo="actor", ok="1"))
        lines.append(_point("cv_admin_read_ms", 31 + i, reads[1], combo="actor", ok="1"))
    for name, held in (bounds or {}).items():
        lines.append(_point("cv_admin_bound", 70, 1, bound=name, ok="1" if held else "0"))
    lines += extra or []
    lines.append(json.dumps({"type": "Point", "metric": "http_reqs", "data": {"value": 1}}))
    path.mkdir(parents=True, exist_ok=True)
    (path / load_results.POINTS_JSON).write_text("\n".join(lines) + "\n")
    wal = [{"at": 0, "wal": {"audit.wal": {"size": depth, "committed": 0, "depth": depth}}}]
    (path / load_results.WAL_JSON).write_text(json.dumps(wal))
    return path


def _judged(tmp_path: Path, profile: str, runs: list[Path], *more: str) -> dict[str, Any]:
    out = tmp_path / "out"
    code = load_results.main(["judge", profile, *map(str, runs), "--out", str(out), *more])
    doc = json.loads((out / load_results.LOAD_RESULTS_JSON).read_text())
    return {"code": code, "rows": {r["row"]: r for r in doc["results"]}, "doc": doc, "out": out}


FLOOD_SENT = [_point("cv_admin_flood", 40, 12_000, status="403", code="forbidden")]


def test_percentile_is_nearest_rank_at_a_fractional_rank() -> None:
    assert load_results.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 95) == 5.0  # rank 4.75 is the 5th
    assert load_results.percentile([float(v) for v in range(1, 21)], 90) == 18.0


def test_four_loaded_reads_are_incomplete_never_judged(tmp_path: Path) -> None:
    run = _run(tmp_path / "r", [10.0] * 20, [10.0] * 20, extra=FLOOD_SENT)

    def late_read(line: str) -> bool:  # a loaded read after 34 s: four are left (31 s to 34 s)
        point = json.loads(line)
        return point["metric"] == "cv_admin_read_ms" and int(point["data"]["time"][17:19]) > 34

    lines = (run / load_results.POINTS_JSON).read_text().splitlines()
    (run / load_results.POINTS_JSON).write_text(
        "\n".join(x for x in lines if not late_read(x)) + "\n"
    )
    assert load_results.MIN_LOADED_READS == 5
    rows = _judged(tmp_path, "flood", [run])["rows"]
    assert rows["reads_loaded_p95"]["verdict"] == "INCOMPLETE"
    assert rows["reads_loaded_p95"]["measured"] is None


def test_probe_is_judged_on_its_nearest_rank_p90_not_its_median(tmp_path: Path) -> None:
    # 17 fast and 3 slow: p50 100 ms, p90 (the 18th) 400 ms, a FAIL against 300 ms.
    slow = [100.0] * 17 + [400.0] * 3
    runs = [_run(tmp_path / f"r{i}", [100.0] * 20, slow, extra=FLOOD_SENT) for i in range(3)]
    j = _judged(tmp_path, "flood", runs)
    p90 = j["rows"]["probe_p90"]
    assert p90["measured"] == 400.0 and p90["verdict"] == "FAIL"
    assert j["rows"]["probe_ratio"]["measured"] == 4.0 and j["code"] == 1


def test_probe_passes_at_its_budget_and_within_20_percent_of_idle(tmp_path: Path) -> None:
    at = [250.0] * 17 + [300.0] * 3
    runs = [_run(tmp_path / f"r{i}", [250.0] * 20, at, extra=FLOOD_SENT) for i in range(3)]
    rows = _judged(tmp_path, "flood", runs)["rows"]
    assert rows["probe_p90"]["verdict"] == "PASS" and rows["probe_ratio"]["verdict"] == "PASS"
    assert rows["probe_ratio"]["measured"] == pytest.approx(1.2)
    over = [_run(tmp_path / f"o{i}", [250.0] * 20, [250.0] * 17 + [301.0] * 3) for i in range(1)]
    rows = _judged(tmp_path, "flood", over)["rows"]
    assert rows["probe_p90"]["verdict"] == "FAIL" and rows["probe_ratio"]["verdict"] == "FAIL"


def test_every_flood_miss_names_2836_and_a_pass_names_nothing(tmp_path: Path) -> None:
    deep = int(load_results.WAL_LIMIT * load_results.WAL_CAP_BYTES) + 1
    unavailable = [_point("cv_admin_audit_unavailable", 50, 1)]
    runs = [_run(tmp_path / "r", [10.0] * 20, [10.0] * 20, depth=deep,
                 extra=FLOOD_SENT + unavailable)]  # fmt: skip
    rows = _judged(tmp_path, "flood", runs)["rows"]
    assert rows["wal_depth"]["verdict"] == "FAIL" and rows["wal_depth"]["waits_on"] == "#2836"
    assert rows["audit_unavailable"]["verdict"] == "FAIL"
    assert rows["audit_unavailable"]["waits_on"] == "#2836"
    assert rows["probe_p90"]["verdict"] == "PASS" and rows["probe_p90"]["waits_on"] == ""
    assert rows["flood_sent"]["verdict"] == "PASS" == rows["flood_refused"]["verdict"]
    short = [_run(tmp_path / "s", [10.0] * 20, [10.0] * 20)]  # no flood points: it never ran
    rows = _judged(tmp_path, "flood", short)["rows"]
    assert rows["flood_sent"]["verdict"] == "INCOMPLETE" and rows["flood_sent"]["waits_on"] == ""
    assert rows["flood_refused"]["verdict"] == "INCOMPLETE"  # C-03: the harness's, not #2836's


def test_a_flood_answered_404_never_passes(tmp_path: Path) -> None:
    lost = [_point("cv_admin_flood", 40, 12_000, status="404", code="not_found")]
    j = _judged(tmp_path, "flood", [_run(tmp_path / "r", [10.0] * 20, [10.0] * 20, extra=lost)])
    refused = j["rows"]["flood_refused"]
    assert refused["measured"] == 0.0 and refused["verdict"] == "FAIL" and j["code"] == 1
    assert refused["waits_on"] == "" and j["rows"]["flood_sent"]["verdict"] == "PASS"
    mixed = [*FLOOD_SENT, _point("cv_admin_flood", 41, 1_000, status="404", code="not_found")]
    rows = _judged(tmp_path, "flood", [_run(tmp_path / "m", [10.0] * 20, [10.0] * 20,
                                            extra=mixed)])["rows"]  # fmt: skip
    assert rows["flood_refused"]["measured"] == pytest.approx(12 / 13)
    assert rows["flood_refused"]["verdict"] == "FAIL"  # 92 %: under 95 %


def test_a_short_load_window_is_held_open_for_the_probes(tmp_path: Path) -> None:
    run = _run(tmp_path / "r", [10.0] * 20, [10.0] * 20, extra=FLOOD_SENT)
    lines = (run / load_results.POINTS_JSON).read_text().splitlines()
    edge1 = (T0 + timedelta(seconds=31)).timestamp() * 1000  # a 1 s verify: the window ends at 31 s
    lines[1] = _point("cv_admin_edge_at", 31, edge1, edge="end")
    (run / load_results.POINTS_JSON).write_text("\n".join(lines) + "\n")
    rows = _judged(tmp_path, "flood", [run])["rows"]
    assert rows["probe_p90"]["measured"] == 10.0 and rows["probe_p90"]["verdict"] == "PASS"


def test_probes_are_taken_in_time_order_not_file_order(tmp_path: Path) -> None:
    early = [_point("cv_admin_probe_ms", -5 + i, 999.0, ok="1", code="x") for i in range(5)]
    run = _run(tmp_path / "r", [10.0] * 20, [10.0] * 20, extra=FLOOD_SENT + early)
    rows = _judged(tmp_path, "flood", [run])["rows"]  # the idle 20 are the last 20 by time
    assert rows["probe_ratio"]["measured"] == 1.0


def test_export_judges_the_reads_ab_and_its_bounds_and_names_no_issue(tmp_path: Path) -> None:
    held = dict.fromkeys(load_results.BOUNDS["export"], True)
    runs = [_run(tmp_path / f"r{i}", [10.0] * 20, [10.0] * 20, reads=(100.0, 106.0),
                 bounds=held | {"export_hourly": i != 1}) for i in range(3)]  # fmt: skip
    rows = _judged(tmp_path, "export", runs)["rows"]
    assert rows["reads_ab"]["measured"] == pytest.approx(1.06)
    assert rows["reads_ab"]["verdict"] == "FAIL" and rows["reads_ab"]["waits_on"] == ""
    assert rows["reads_loaded_p95"]["verdict"] == "PASS"
    assert rows["export_hourly"]["verdict"] == "FAIL"  # one run's miss is a miss
    assert rows["export_rows"]["verdict"] == "PASS"
    assert "reads_ab" not in _judged(tmp_path, "verify", runs)["rows"]


def test_a_missing_bound_or_window_is_never_a_pass(tmp_path: Path) -> None:
    runs = [_run(tmp_path / "r", [10.0] * 20, [10.0] * 20)]
    rows = _judged(tmp_path, "verify", runs)["rows"]
    assert rows["verify_verified"]["verdict"] == "FAIL"  # never emitted: it did not hold
    lines = (runs[0] / load_results.POINTS_JSON).read_text().splitlines()
    (runs[0] / load_results.POINTS_JSON).write_text(
        "\n".join(x for x in lines if "edge_at" not in x)
    )
    rows = _judged(tmp_path, "verify", runs)["rows"]
    assert rows["probe_p90"]["verdict"] == "INCOMPLETE" and rows["probe_p90"]["measured"] is None
    assert (
        "| probe_p90 | p90 <= 300 ms | n/a |"
        in (tmp_path / "out" / load_results.LOAD_RESULTS_MD).read_text()
    )


def test_a_failed_probe_is_errors_never_a_duration(tmp_path: Path) -> None:
    runs = [_run(tmp_path / "r", [10.0] * 20, [10.0] * 19 + [-1.0], extra=FLOOD_SENT)]
    rows = _judged(tmp_path, "flood", runs)["rows"]
    assert rows["probe_p90"]["verdict"] == "ERRORS" and rows["probe_ratio"]["verdict"] == "ERRORS"
    assert rows["probe_p90"]["waits_on"] == ""  # C-03: an ERRORS row never blames #2836


def test_results_name_the_dataset_and_only_the_full_chained_set_is_the_verdict(
    tmp_path: Path,
) -> None:
    runs = [_run(tmp_path / "r", [10.0] * 20, [10.0] * 20, extra=FLOOD_SENT)]
    base = ["--database", "admin_perf1m_test", "--mode", "chained", "--rows"]
    j = _judged(tmp_path, "flood", runs, *base, "1000000")
    assert j["doc"]["kind"] == "verdict" and j["doc"]["profile"] == "flood" and j["code"] == 0
    assert _judged(tmp_path, "flood", runs, *base, "100000")["doc"]["kind"] != "verdict"
    assert load_results.FULL_ROWS == datasets.DEFAULT_ROWS["chained"]


def test_point_times_are_read_to_the_millisecond() -> None:
    assert load_results.epoch_ms("2026-11-04T10:00:00.123456789Z") == pytest.approx(
        T0.timestamp() * 1000 + 123.456, abs=0.01
    )
    assert load_results.epoch_ms("2026-11-04T11:00:00+01:00") == T0.timestamp() * 1000
    with pytest.raises(ValueError):
        load_results.epoch_ms("yesterday")


# -- SCR-143's added load (one run, no WAL) ----------------------------------------------------
W = 600


def _added(path: Path, rates: dict[str, float], sets: int = 300, failed: int = 0) -> Path:
    """One run: each window's CPU counter grows at its rate (CPU seconds a second)."""
    lines, cpu = [], 100.0
    for i, name in enumerate(load_results.ADDED_WINDOWS):
        for k in range(0, W + 1, 60):
            lines.append(_point("cv_admin_cpu_s", i * (W + 1) + k, cpu + rates[name] * k,
                                window=name))  # fmt: skip
        cpu += rates[name] * W
        if name.startswith("b_"):
            lines.append(_point("cv_admin_mounts", i * W + 5, sets, window=name))
    if failed:
        lines.append(_point("cv_admin_read_failed", 5, failed, read="/admin/health"))
    path.mkdir(parents=True, exist_ok=True)
    (path / load_results.POINTS_JSON).write_text("\n".join(lines) + "\n")
    return path


def _judge(tmp_path: Path, run: Path) -> tuple[int, dict[str, Any]]:
    out = tmp_path / "out"
    code = load_results.main(["judge", "added", str(run), "--out", str(out)])
    doc = json.loads((out / load_results.LOAD_RESULTS_JSON).read_text())
    return code, {r["row"]: r for r in doc["results"]}


QUIET = {"aa_1": 0.5, "aa_2": 0.5005, "a_1": 0.5, "a_2": 0.5, "a_3": 0.5}


def test_added_load_is_the_median_delta_judged_on_a_quiet_floor(tmp_path: Path) -> None:
    rates = QUIET | {"b_1": 0.502, "b_2": 0.5045, "b_3": 0.51}  # 0.4 %, 0.9 %, 2 %: median 0.9 %
    code, rows = _judge(tmp_path, _added(tmp_path / "r", rates))
    assert rows["noise_floor"]["verdict"] == "PASS"
    assert rows["added_load"]["measured"] == pytest.approx(0.009)
    assert rows["added_load"]["verdict"] == "PASS" and code == 0
    assert rows["cpu_ms_per_read_set"]["measured"] == pytest.approx(0.0045 * W * 1000 / 300)
    over = QUIET | {"b_1": 0.506, "b_2": 0.506, "b_3": 0.501}
    code, rows = _judge(tmp_path, _added(tmp_path / "o", over))
    assert rows["added_load"]["verdict"] == "FAIL" and code == 1


def test_a_noisy_floor_never_judges_the_delta_and_a_failed_read_fails(tmp_path: Path) -> None:
    noisy = QUIET | {"aa_2": 0.502, "b_1": 0.5, "b_2": 0.5, "b_3": 0.5}  # 0.4 % A/A
    code, rows = _judge(tmp_path, _added(tmp_path / "n", noisy, failed=1))
    assert rows["noise_floor"]["verdict"] == "NOISY"
    assert rows["added_load"]["verdict"] == "NOT JUDGED (noise)" and code == 1
    assert rows["cpu_ms_per_read_set"]["verdict"] == "RECORDED"
    assert rows["read_failures"]["verdict"] == "FAIL"

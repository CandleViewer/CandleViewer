"""Tests for tools/statechart/nightly_gate.py (E50-T04)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.statechart.nightly_gate import (
    BENCH6_ROW,
    KNOWN_DELTAS,
    bench6,
    delta_drift,
    documented_deltas,
    main,
    measured,
    regressions,
)


def _res(*checks: tuple[str, str, str]) -> dict:
    return {
        "library_version": "0.9.1",
        "library_commit": "abc",
        "build": "b",
        "exit_code": 1,
        "checks": [{"kind": k, "id": i, "status": s} for k, i, s in checks],
    }


BASE = _res(("verify", "LC-01", "FAIL"), ("verify", "LC-02", "PASS"), ("repro", "R1", "FAIL"))


def _run(tmp_path: Path, mode: str, result: dict, bench: dict | None = None) -> tuple[int, str]:
    r, b, out = tmp_path / "r.json", tmp_path / "b.json", tmp_path / "a" / "d.md"
    r.write_text(json.dumps(result))
    b.write_text(json.dumps(BASE))
    argv = [
        "--mode",
        mode,
        "--result",
        str(r),
        "--baseline",
        str(b),
        "--date",
        "2026-10-04",
        "--out",
        str(out),
    ]
    if bench is not None:
        bp = tmp_path / "bench.json"
        bp.write_text(json.dumps(bench))
        argv += ["--bench", str(bp)]
    return main(argv), out.read_text(encoding="utf-8")


def test_regressions_known_baseline_failure_is_not_a_regression() -> None:
    assert regressions(BASE, BASE) == []


def test_regressions_new_blocking_failure_is_reported_repro_is_not() -> None:
    cur = _res(("verify", "LC-01", "FAIL"), ("verify", "LC-02", "FAIL"), ("repro", "R2", "FAIL"))
    assert regressions(cur, BASE) == ["verify:LC-02"]


def test_regressions_error_always_counts() -> None:
    assert regressions(_res(("probe", "P1", "ERROR")), BASE) == ["probe:P1"]


def test_pinned_regression_is_red_and_notifies_liaison(tmp_path: Path) -> None:
    rc, report = _run(tmp_path, "pinned", _res(("verify", "LC-02", "FAIL")))
    assert rc == 1
    assert "RED" in report and "E50-C17" in report


def test_pinned_baseline_state_is_green(tmp_path: Path) -> None:
    rc, report = _run(tmp_path, "pinned", BASE)
    assert rc == 0 and "GREEN" in report


def test_upstream_failure_never_gates_and_is_informational(tmp_path: Path) -> None:
    rc, report = _run(tmp_path, "upstream", _res(("verify", "LC-02", "FAIL")))
    assert rc == 0
    assert "informational" in report and "E50-C17" not in report


def test_bench6_budget_and_missing_evidence() -> None:
    ok = {"summary_by_busy_level": {"500": {"p99": 55.8}}}
    over = {"summary_by_busy_level": {"500": {"p99": 100.1}}}
    assert bench6(ok, 100.0) == (True, 55.8)
    assert bench6(over, 100.0)[0] is False
    assert bench6({"summary_by_busy_level": {}}, 100.0) == (False, None)
    assert bench6(None, 100.0) == (None, None)


def test_pinned_bench_breach_fails(tmp_path: Path) -> None:
    bench = {"summary_by_busy_level": {"500": {"p99": 250.0}}}
    rc, report = _run(tmp_path, "pinned", BASE, bench)
    assert rc == 1 and "BREACH" in report


def test_unreadable_input_exits_2(tmp_path: Path) -> None:
    rc = main(
        [
            "--mode",
            "pinned",
            "--result",
            str(tmp_path / "x"),
            "--baseline",
            str(tmp_path / "y"),
            "--date",
            "d",
            "--out",
            str(tmp_path / "o.md"),
        ]
    )
    assert rc == 2


# --- #579: documented deltas and the superseded run_gate BENCH-6 row -------------

GOOD_BENCH = {"summary_by_busy_level": {"500": {"p99": 28.7}}}


def _with(*extra: tuple[str, str, str]) -> dict[str, Any]:
    """The baseline's own rows plus ``extra`` (so only ``extra`` can regress)."""
    cur = _res(*extra)
    cur["checks"] = BASE["checks"] + cur["checks"]
    return cur


def _bench2(detail: str | None, *extra: tuple[str, str, str]) -> dict[str, Any]:
    """A BENCH-2 FAIL whose detail is ``detail`` (none when None), plus any ``extra`` rows."""
    cur = _with(("bench", "BENCH-2", "FAIL"), *extra)
    if detail is not None:
        next(c for c in cur["checks"] if c["id"] == "BENCH-2")["detail"] = detail
    return cur


def _need(value: str) -> str:
    """The detail run_gate.py writes for a BENCH-2 reading of ``value`` ev/s."""
    return f"{value} ev/s (need >= 2,000.00; 0.7.0 baseline 288.00)"


def test_every_known_delta_excuses_a_fail_and_carries_a_justification() -> None:
    assert KNOWN_DELTAS
    for key, delta in KNOWN_DELTAS.items():
        assert delta.status == "FAIL", key  # an ERROR row is never excusable
        assert delta.why.startswith(("(c) ", "(d) ")) and len(delta.why) > 80, key
    assert KNOWN_DELTAS["bench:BENCH-2"].floor == 380.9  # the study figure the decision rests on


def test_regressions_excused_keys_are_not_reported() -> None:
    cur = _with(("bench", "BENCH-2", "FAIL"), ("verify", "LC-02", "FAIL"))
    assert regressions(cur, BASE, frozenset({"bench:BENCH-2"})) == ["verify:LC-02"]


def test_pinned_documented_deltas_are_excused_and_listed(tmp_path: Path) -> None:
    cur = _bench2(_need("569.00"), ("verifyM4", "174", "FAIL"), ("verifyM5", "174", "FAIL"))
    assert documented_deltas(cur) == ["bench:BENCH-2", "verifyM4:174", "verifyM5:174"]
    assert delta_drift(cur) == []
    rc, report = _run(tmp_path, "pinned", cur)
    assert rc == 0 and "**GREEN**" in report
    assert "- bench:BENCH-2 FAIL: (c) " in report and "- verifyM5:174 FAIL: (d) " in report


def test_documented_delta_excuses_only_its_own_status(tmp_path: Path) -> None:
    cur = _with(("bench", "BENCH-2", "ERROR"), ("verifyM4", "174", "ERROR"))
    cur["checks"][-2]["detail"] = _need("569.00")  # readable, so only its status keeps it out
    rc, report = _run(tmp_path, "pinned", cur)
    assert rc == 1 and "**RED**" in report
    assert "- bench:BENCH-2\n" in report and "- verifyM4:174\n" in report
    assert regressions(cur, BASE) == ["bench:BENCH-2", "verifyM4:174"]


def test_measured_reads_the_leading_number_of_a_bench_detail() -> None:
    assert measured(_need("569.00")) == 569.0 and measured(_need("1,195.00")) == 1195.0
    assert not any(measured(d) is not None for d in ("", "exit 1: boom", "ev/s 569.00", None))


@pytest.mark.parametrize("value", ["380.90", "380.91", "569.00", "1,195.00", "12,345.00"])
def test_bench2_is_excused_at_its_floor_and_above(tmp_path: Path, value: str) -> None:
    cur = _bench2(_need(value))
    assert documented_deltas(cur) == ["bench:BENCH-2"]
    rc, report = _run(tmp_path, "pinned", cur)
    assert rc == 0 and "**GREEN**" in report and "NOT EXCUSED" not in report


@pytest.mark.parametrize("value", ["380.89", "379.00", "40.00", "0.00"])
def test_bench2_below_its_floor_is_a_regression(tmp_path: Path, value: str) -> None:
    cur = _bench2(_need(value))
    assert documented_deltas(cur) == []
    assert regressions(cur, BASE, frozenset(documented_deltas(cur))) == ["bench:BENCH-2"]
    rc, report = _run(tmp_path, "pinned", cur)
    assert rc == 1 and "**RED**" in report and "- bench:BENCH-2\n" in report
    assert f"- NOT EXCUSED (blocking): bench:BENCH-2 FAIL: measured {value}, floor 380.9" in report


@pytest.mark.parametrize("detail", [None, "", "exit 1: boom", "n/a (need >= 2,000.00)"])
def test_bench2_without_a_readable_value_is_not_excused(tmp_path: Path, detail: str | None) -> None:
    cur = _bench2(detail)
    assert documented_deltas(cur) == []
    rc, report = _run(tmp_path, "pinned", cur)
    assert rc == 1 and "measured unreadable, floor 380.9" in report


def test_documented_delta_drift_is_reported_but_never_gates(tmp_path: Path) -> None:
    cur = _with(("verifyM4", "174", "PASS"))
    assert "verifyM4:174 is PASS, documented as FAIL" in delta_drift(cur)
    assert "bench:BENCH-2 is missing, documented as FAIL" in delta_drift(cur)
    rc, report = _run(tmp_path, "pinned", cur)
    assert rc == 0 and "DRIFT (re-triage the entry, non-blocking): verifyM4:174" in report


def test_upstream_mode_does_not_excuse_documented_deltas(tmp_path: Path) -> None:
    rc, report = _run(tmp_path, "upstream", _bench2(_need("569.00"), ("verifyM4", "174", "FAIL")))
    assert rc == 0 and "- bench:BENCH-2" in report and "- verifyM4:174" in report
    assert "Documented deltas" not in report


def test_bench6_row_is_superseded_only_when_bench_is_supplied(tmp_path: Path) -> None:
    cur = _with(("bench", "BENCH-6", "ERROR"))
    rc, report = _run(tmp_path, "pinned", cur, GOOD_BENCH)
    assert rc == 0 and f"run_gate row {BENCH6_ROW} (ERROR)" in report
    rc, report = _run(tmp_path, "pinned", cur)
    assert rc == 1 and f"- {BENCH6_ROW}" in report


def test_superseded_bench6_row_never_hides_a_breach(tmp_path: Path) -> None:
    over = {"summary_by_busy_level": {"500": {"p99": 140.0}}}
    rc, report = _run(tmp_path, "pinned", _with(("bench", "BENCH-6", "FAIL")), over)
    assert rc == 1 and "BREACH" in report

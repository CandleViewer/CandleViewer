"""E08-Q04 regression gate + report: an injected 40 % backend-internal p95 regression fails a
same-profile gated baseline (AC 5), only WARNs on a foreign/warn-only baseline, the baseline is
never rewritten by CI, and the report is redacted (security notes)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from bench.ingestion import gate, report
from bench.ingestion.budgets import Check, Verdict
from bench.ingestion.config import SCENARIOS, load

M = "receipt_to_publish_ms"
T = datetime(2026, 10, 11, tzinfo=UTC)


def _verdict(p95: float) -> Verdict:
    v = Verdict("latency_internal", [Check("x", "#6", p95, 20.0, "ms", True)])
    v.metrics = {M: {"p50": p95 / 2, "p95": p95, "max": p95, "count": 100.0}}
    return v


def _baseline(profile: str = "ci-ubuntu", mode: str = "gated") -> dict[str, Any]:
    return {
        "machine_profile": profile,
        "gate": mode,
        "run_profile": "smoke",
        "metrics": {M: {"p50": 5.0, "p95": 10.0, "max": 12.0, "count": 100.0}},
    }


def test_gate_fails_on_40pct_regression_and_names_metric() -> None:
    g = gate.compare(_verdict(14.0), _baseline(), "ci-ubuntu")
    assert g.status == "FAIL"
    assert M in g.failures[0] and "+40.0%" in g.failures[0]
    assert "| receipt_to_publish_ms | 10 | 14 | +40.0% |" in gate.render_diff(g)


def test_gate_warns_between_bands_and_passes_within() -> None:
    assert gate.compare(_verdict(11.5), _baseline(), "ci-ubuntu").status == "WARN"
    assert gate.compare(_verdict(10.2), _baseline(), "ci-ubuntu").status == "PASS"


def test_gate_per_metric_tolerance_tightens_the_band() -> None:
    assert gate.compare(_verdict(11.5), _baseline(), "ci-ubuntu", {M: 0.05}).status == "FAIL"


def test_gate_foreign_profile_or_warn_only_never_fails() -> None:
    for base in (_baseline("laptop-i7-8550U"), _baseline("ci-ubuntu", "warn-only")):
        g = gate.compare(_verdict(14.0), base, "ci-ubuntu")
        assert g.status == "WARN" and not g.gated and g.reason


def test_gate_smoke_baseline_not_compared_to_full_run() -> None:
    g = gate.compare(_verdict(99.0), _baseline(), "ci-ubuntu", run_profile="full")
    assert g.status == "PASS" and not g.gated


def test_gate_missing_baseline_is_not_gated() -> None:
    assert not gate.compare(_verdict(99.0), None, "x").gated


def test_record_refused_under_ci(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    with pytest.raises(RuntimeError, match="never rewritten"):
        gate.record(_verdict(1.0), "p", "s", "smoke", tmp_path)


def test_record_writes_the_74_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    path = gate.record(_verdict(3.0), "lap", "s", "smoke", tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["machine_profile"] == "lap" and data["gate"] == "warn-only"
    assert data["harness_version"] and {"p50", "p95", "max"} <= set(data["metrics"][M])


def test_committed_baselines_are_laptop_warn_only_and_cover_every_scenario() -> None:
    for name in SCENARIOS:
        base = gate.load_baseline(name)
        assert base is not None, name
        assert base["machine_profile"] == "laptop-i7-8550U" and base["gate"] == "warn-only"
        assert all({"p50", "p95", "max"} <= set(m) for m in base["metrics"].values())


def test_every_scenario_config_has_both_profiles_with_scaling_notes() -> None:
    for name in SCENARIOS:
        full, smoke = load(name, "full"), load(name, "smoke")
        assert full.kind == smoke.kind and "scaling" not in smoke.params
        assert smoke.scaling and full.scaling.startswith("none")
    with pytest.raises(ValueError, match="unknown scenario"):
        load("nope")


def test_report_has_measured_beside_budget_and_redacts_secrets() -> None:
    sc = load("soak_steady")
    leak = "token=abc123 X-VENUE-SIGN: deadbeef"
    v = Verdict(
        "soak_steady", [Check("rss_per_symbol_p95", "#8", 42.0, 300.0, "MB", True, note=leak)]
    )
    v.metrics = {"_curve": {"0": 100.0, "60": 101.0}, M: {"p50": 1, "p95": 2, "max": 3, "count": 4}}
    md = report.render([(sc, v, gate.compare(v, None, "p"))], "laptop", T, T)
    assert "| #8 | 42 | 300 | MB | pass |" in md
    assert "abc123" not in md and "deadbeef" not in md and "[REDACTED]" in md
    assert "<svg" in md and sc.scaling in md and "PASS" in md.splitlines()[0]


def test_report_flags_failure_in_title() -> None:
    sc = load("burst_5x")
    v = Verdict("burst_5x", [Check("recovery_s", "#5", 99.0, 30.0, "s", False)])
    md = report.render([(sc, v, gate.compare(v, None, "p"))], "p", T, T)
    assert md.startswith("# E08-Q04 ingestion performance report — FAIL") and "| FAIL |" in md


def test_svg_curve_needs_two_points() -> None:
    assert report.svg_curve({"0": 1.0}) == ""


def _headroom(uid: float, ip: float) -> Verdict:
    v = Verdict("ratelimit_headroom")
    v.metrics = {
        "uid_tokens": {"p50": uid, "p95": uid, "max": uid, "count": 1.0},
        "ip_window_headroom_min": {"p50": ip, "p95": ip, "max": ip, "count": 1.0},
    }
    return v


@pytest.mark.parametrize("declared", [True, False])
def test_gate_headroom_drop_fails_and_rise_passes(declared: bool) -> None:
    """M1: headroom is higher-is-better, even for a baseline that predates the key."""
    base: dict[str, Any] = {
        "machine_profile": "ci", "gate": "gated", "run_profile": "smoke",
        "metrics": _headroom(10.0, 584.0).metrics,
    }  # fmt: skip
    if declared:
        base["higher_is_better"] = ["uid_tokens", "ip_window_headroom_min"]
    drop = gate.compare(_headroom(2.0, 20.0), base, "ci")
    assert drop.status == "FAIL" and any("uid_tokens" in f for f in drop.failures)
    assert any("ip_window_headroom_min" in f for f in drop.failures)
    assert gate.compare(_headroom(14.0, 590.0), base, "ci").status == "PASS"


def test_record_emits_direction_and_committed_headroom_baseline_declares_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    data = json.loads(gate.record(_headroom(10.0, 584.0), "p", "s", "smoke", tmp_path).read_text())
    assert data["higher_is_better"] == ["ip_window_headroom_min", "uid_tokens"]
    committed = gate.load_baseline("ratelimit_headroom")
    assert committed is not None
    assert set(committed["higher_is_better"]) == {"uid_tokens", "ip_window_headroom_min"}


def test_only_headroom_metrics_are_higher_is_better() -> None:
    """Direction audit: every other committed metric is latency/size/cost (lower is better)."""
    for name in SCENARIOS:
        base = gate.load_baseline(name)
        assert base is not None
        for metric in base["metrics"]:
            assert (metric in gate.HIGHER_IS_BETTER) == (name == "ratelimit_headroom"), metric

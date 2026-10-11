"""Regression gate vs `bench/baselines/e08/<scenario>.json` (06-performance §7.4).

Shape copied from `bench/bar_determinism/run.py`: per-metric WARN / FAIL bands. Metrics are
"lower is better" (latency, RSS, CPU, backlog, recovery) unless listed in `higher_is_better`.
A baseline recorded on another `machine_profile`, or flagged `gate: "warn-only"`, never FAILs —
it only WARNs until a same-profile (CI-runner) baseline is recorded. The gate never rewrites a
baseline; `--record-baseline` is a deliberate, reviewed local action and is refused under CI.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bench.ingestion import HARNESS_VERSION
from bench.ingestion.budgets import Verdict
from bench.ingestion.config import BASELINES_DIR

#: Default bands (fraction of baseline). Scenario configs may tighten/loosen per metric under
#: `tolerances` ("<metric>": fail band) — loss/lag tight, absolute CPU loose (ticket perf notes).
WARN_BAND, FAIL_BAND = 0.10, 0.25
#: Absolute noise floor: a delta below this (same unit as the metric) is never a regression.
ABS_FLOOR = {"ms": 0.5, "count": 1.0}


@dataclass(slots=True)
class GateResult:
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    diff: list[dict[str, Any]] = field(default_factory=list)
    gated: bool = True
    reason: str = ""

    @property
    def status(self) -> str:
        return "FAIL" if self.failures else "WARN" if self.warnings else "PASS"


def baseline_path(scenario: str, root: Path = BASELINES_DIR) -> Path:
    return root / f"{scenario}.json"


def load_baseline(scenario: str, root: Path = BASELINES_DIR) -> dict[str, Any] | None:
    p = baseline_path(scenario, root)
    if not p.exists():
        return None
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return data


def _floor(metric: str) -> float:
    return ABS_FLOOR["ms"] if metric.endswith("_ms") else 0.0


def compare(
    verdict: Verdict,
    baseline: dict[str, Any] | None,
    profile: str,
    tolerances: dict[str, float] | None = None,
    run_profile: str = "smoke",
) -> GateResult:
    """p95 of each baseline metric vs the run's p95. Missing baseline -> PASS, not gated."""
    g = GateResult()
    if baseline is None:
        g.gated, g.reason = False, "no baseline recorded"
        return g
    if baseline.get("run_profile", "smoke") != run_profile:
        g.gated = False
        g.reason = f"baseline is a {baseline.get('run_profile')!r} run, this is {run_profile!r}"
        return g
    if baseline.get("machine_profile") != profile:
        g.gated = False
        g.reason = (
            f"baseline profile {baseline.get('machine_profile')!r} != run profile {profile!r}: "
            "reported, not gated; record a baseline on this runner"
        )
    elif baseline.get("gate") == "warn-only":
        g.gated, g.reason = False, "baseline marked warn-only until a CI-runner baseline exists"
    tol = tolerances or {}
    higher = set(baseline.get("higher_is_better", ()))
    for metric, base in sorted(baseline.get("metrics", {}).items()):
        now = verdict.metrics.get(metric)
        if now is None or "p95" not in base:
            continue
        b, n = float(base["p95"]), float(now["p95"])
        delta = (b - n) if metric in higher else (n - b)
        rel = delta / b if b > 0 else 0.0
        row = {"metric": metric, "baseline_p95": b, "run_p95": n, "change": rel}
        g.diff.append(row)
        if delta <= _floor(metric):
            continue
        fail_band = tol.get(metric, FAIL_BAND)
        warn_band = min(WARN_BAND, fail_band)
        msg = f"{metric}: p95 {n:.4g} vs baseline {b:.4g} ({rel:+.1%}, fail band {fail_band:.0%})"
        if rel > fail_band:
            (g.failures if g.gated else g.warnings).append(msg)
        elif rel > warn_band:
            g.warnings.append(msg)
    return g


def render_diff(g: GateResult) -> str:
    """Plain-text before/after table (attached to the defect issue on FAIL)."""
    lines = ["| metric | baseline p95 | run p95 | change |", "|---|---:|---:|---:|"]
    lines += [
        f"| {r['metric']} | {r['baseline_p95']:.4g} | {r['run_p95']:.4g} | {r['change']:+.1%} |"
        for r in g.diff
    ]
    return "\n".join(lines)


def record(
    verdict: Verdict, profile: str, scaling: str, run_profile: str, root: Path = BASELINES_DIR
) -> Path:
    """Write a baseline from this run. Refused under CI (never auto-updated by a run)."""
    if os.environ.get("CI"):
        raise RuntimeError("refused: baselines are never rewritten by CI (06-perf §7.4)")
    root.mkdir(parents=True, exist_ok=True)
    out = {
        "scenario": verdict.scenario,
        "harness_version": HARNESS_VERSION,
        "machine_profile": profile,
        "gate": "warn-only",
        "run_profile": run_profile,
        "profile_scaling": scaling,
        "metrics": {k: v for k, v in verdict.metrics.items() if not k.startswith("_")},
    }
    p = baseline_path(verdict.scenario, root)
    p.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p

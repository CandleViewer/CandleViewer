"""Scenario configs: one checked-in JSON per scenario with a `full` and a `smoke` profile.

`full` is the 06-performance §9 definition (nightly / on-demand lane). `smoke` is the scaled
PR-lane variant that runs the *same* assertion set; its `scaling` note says exactly what was
scaled, and the report prints it beside every verdict.
"""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCENARIOS_DIR = HERE / "scenarios"
BASELINES_DIR = HERE.parent / "baselines" / "e08"
REPORTS_DIR = HERE.parent / "reports"
SCENARIOS: tuple[str, ...] = (
    "soak_steady",
    "aggregate_10sym",
    "burst_5x",
    "rest_k6",
    "latency_internal",
    "ratelimit_headroom",
)


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    title: str
    kind: str
    profile: str
    scaling: str
    params: dict[str, Any]
    tolerances: dict[str, float]

    def p(self, key: str) -> Any:
        return self.params[key]


def load(name: str, profile: str = "smoke") -> Scenario:
    """`params` = `common` overlaid with the profile block (profile wins)."""
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}")
    if profile not in ("smoke", "full"):
        raise ValueError(f"unknown profile {profile!r}")
    raw = json.loads((SCENARIOS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    block = raw[profile]
    params = {**raw.get("common", {}), **{k: v for k, v in block.items() if k != "scaling"}}
    return Scenario(
        name=name,
        title=str(raw["title"]),
        kind=str(raw["kind"]),
        profile=profile,
        scaling=str(block.get("scaling", "none (full definition)")),
        params=params,
        tolerances={k: float(v) for k, v in raw.get("tolerances", {}).items()},
    )


def machine_profile() -> str:
    """Baselines are per profile (§7.4): a laptop run is never gated against a CI baseline."""
    explicit = os.environ.get("CV_BENCH_MACHINE_PROFILE")
    if explicit:
        return explicit
    return f"{platform.system().lower()}-{platform.machine().lower()}-{os.cpu_count() or 0}c"

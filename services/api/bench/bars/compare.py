"""Regression compare against a baseline (06-performance §7.4: 5 % on hard budgets).

BQ-02 (rulings pending, ORCH default): 5 %, plus an absolute noise floor like engine-bench's
`--min-delta-ms`. Latency-style metrics are lower-is-better; throughput is higher-is-better.
The verdict names the series and the measured delta (AC3). A baseline is never rewritten here.

The noise floor applies to latency series only (names ending `_ms`); throughput and other
series have none. Differences from `ci-compare.mjs` (packages/chart-engine/bench): the floor is
strict (`worse > min_delta`), a baseline series missing from the run is an error (not skipped),
and a run series with no baseline is not compared; `new_series` lists them so a caller can
report them as new.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

REGRESSION_THRESHOLD = 0.05
MIN_DELTA_MS = 0.2


@dataclass(frozen=True, slots=True)
class Delta:
    series: str
    baseline: float
    measured: float
    fraction: float  # signed, positive = worse
    regressed: bool

    def describe(self) -> str:
        verdict = "REGRESSION" if self.regressed else "ok"
        return (
            f"{self.series}: {self.baseline:.4g} -> {self.measured:.4g} "
            f"({self.fraction * 100:+.1f} % worse) {verdict}"
        )


def compare_one(
    series: str,
    baseline: float,
    measured: float,
    *,
    higher_is_better: bool = False,
    threshold: float = REGRESSION_THRESHOLD,
    min_delta: float = 0.0,
) -> Delta:
    if baseline <= 0:
        raise ValueError(f"{series}: baseline must be > 0")
    worse = (baseline - measured) if higher_is_better else (measured - baseline)
    fraction = worse / baseline
    regressed = fraction > threshold and worse > min_delta
    return Delta(series, baseline, measured, fraction, regressed)


def compare(
    baselines: Mapping[str, float],
    measured: Mapping[str, float],
    *,
    higher_is_better: frozenset[str] = frozenset(),
    threshold: float = REGRESSION_THRESHOLD,
    min_delta_ms: float = MIN_DELTA_MS,
) -> list[Delta]:
    """One `Delta` per baseline series; a series missing from the run is an error, not a pass.
    `min_delta_ms` is the floor of the `_ms` series only."""
    missing = sorted(set(baselines) - set(measured))
    if missing:
        raise KeyError(f"series missing from the run: {', '.join(missing)}")
    return [
        compare_one(
            name,
            base,
            measured[name],
            higher_is_better=name in higher_is_better,
            threshold=threshold,
            min_delta=min_delta_ms if name.endswith("_ms") else 0.0,
        )
        for name, base in sorted(baselines.items())
    ]


def new_series(baselines: Mapping[str, float], measured: Mapping[str, float]) -> list[str]:
    """Series in the run that have no baseline yet (reported, never gated)."""
    return sorted(set(measured) - set(baselines))


def failures(deltas: list[Delta]) -> list[str]:
    return [d.describe() for d in deltas if d.regressed]

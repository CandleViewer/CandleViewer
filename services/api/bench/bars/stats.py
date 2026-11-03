"""Distribution summary, median-of-3 run pick and variance (ticket Technical notes).

The gate reports a distribution with a stated sample size, never a mean. Three runs per
configuration; the median run is the figure, the spread is recorded so a flaky gate shows.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from bench.ingestion.budgets import percentile

RUNS_PER_CONFIG = 3


@dataclass(frozen=True, slots=True)
class Distribution:
    n: int
    p50: float
    p95: float
    p99: float
    max: float


def distribution(samples: Sequence[float], *, warmup: int = 0) -> Distribution:
    """Summary of `samples` after discarding the first `warmup` (the explicit warm-up window)."""
    if warmup < 0:
        raise ValueError("warmup must be >= 0")
    kept = [float(x) for x in samples[warmup:]]
    if not kept:
        raise ValueError("no samples left after warm-up")
    if any(math.isnan(x) for x in kept):
        raise ValueError("NaN sample")
    return Distribution(
        n=len(kept),
        p50=percentile(kept, 0.50),
        p95=percentile(kept, 0.95),
        p99=percentile(kept, 0.99),
        max=max(kept),
    )


def median_run(values: Sequence[float]) -> float:
    """The median of the per-run figures; exactly `RUNS_PER_CONFIG` runs are required."""
    if len(values) != RUNS_PER_CONFIG:
        raise ValueError(f"expected {RUNS_PER_CONFIG} runs, got {len(values)}")
    return sorted(values)[RUNS_PER_CONFIG // 2]


def relative_spread(values: Sequence[float]) -> float:
    """(max - min) / median across runs; 0 for a zero median with no spread, inf otherwise."""
    med = median_run(values)
    spread = max(values) - min(values)
    if med == 0:
        return 0.0 if spread == 0 else math.inf
    return spread / abs(med)

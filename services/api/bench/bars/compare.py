"""Regression compare against a baseline, one threshold per metric class (BQ-02, ruled 15:33Z).

- **frame** (frame time, draw calls, memory; lower is better): 5 % fail, C-9.1 #16 and
  06-performance §7.4, with an absolute floor for `_ms` series like engine-bench's
  `--min-delta-ms`. The 5 % outranks the 10 % in 26 :820 and 30 :320 (A-rows in 06).
- **throughput** (prints/s; higher is better): T04's warn 10 % / fail 25 %
  (`bar_determinism/run.py` `WARN_DROP`/`FAIL_DROP`), a different metric class. A-row in 06.

The verdict names the series and the measured delta (AC3); `exit_code` is 1 on any fail, so a
seeded regression fails the job. Unlike `ci-compare.mjs` the floor is strict (`worse > floor`),
a baseline series missing from the run is an error, and a run series with no baseline is only
listed (`new_series`). A baseline is never rewritten here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

MIN_DELTA_MS = 0.2


@dataclass(frozen=True, slots=True)
class MetricClass:
    name: str
    warn: float  # fraction worse than baseline that warns
    fail: float  # fraction worse than baseline that fails
    higher_is_better: bool = False
    floor_ms: float = 0.0  # absolute floor, applied to `_ms` series only


FRAME = MetricClass("frame", warn=0.05, fail=0.05, floor_ms=MIN_DELTA_MS)
THROUGHPUT = MetricClass("throughput", warn=0.10, fail=0.25, higher_is_better=True)


def class_of(series: str) -> MetricClass:
    """Throughput series are named `*prints_per_s`; everything else is frame-class."""
    return THROUGHPUT if series.endswith("prints_per_s") else FRAME


@dataclass(frozen=True, slots=True)
class Delta:
    series: str
    baseline: float
    measured: float
    fraction: float  # signed, positive = worse
    status: str  # "ok" | "warn" | "fail"

    @property
    def regressed(self) -> bool:
        return self.status == "fail"

    def describe(self) -> str:
        return (
            f"{self.series}: {self.baseline:.4g} -> {self.measured:.4g} "
            f"({self.fraction * 100:+.1f} % worse) {self.status.upper()}"
        )


def compare_one(
    series: str, baseline: float, measured: float, cls: MetricClass | None = None
) -> Delta:
    cls = cls or class_of(series)
    if baseline <= 0:
        raise ValueError(f"{series}: baseline must be > 0")
    worse = (baseline - measured) if cls.higher_is_better else (measured - baseline)
    fraction = worse / baseline
    floor = cls.floor_ms if series.endswith("_ms") else 0.0
    if fraction > cls.fail and worse > floor:
        status = "fail"
    elif fraction > cls.warn and worse > floor:
        status = "warn"
    else:
        status = "ok"
    return Delta(series, baseline, measured, fraction, status)


def compare(
    baselines: Mapping[str, float],
    measured: Mapping[str, float],
) -> list[Delta]:
    """One `Delta` per baseline series; a series missing from the run is an error, not a pass."""
    missing = sorted(set(baselines) - set(measured))
    if missing:
        raise KeyError(f"series missing from the run: {', '.join(missing)}")
    return [compare_one(name, base, measured[name]) for name, base in sorted(baselines.items())]


def new_series(baselines: Mapping[str, float], measured: Mapping[str, float]) -> list[str]:
    """Series in the run that have no baseline yet (reported, never gated)."""
    return sorted(set(measured) - set(baselines))


def failures(deltas: list[Delta]) -> list[str]:
    return [d.describe() for d in deltas if d.status == "fail"]


def exit_code(deltas: list[Delta]) -> int:
    """What the CI job returns: 1 when any series fails (AC3), else 0; warnings never fail."""
    return 1 if any(d.status == "fail" for d in deltas) else 0

"""Pure pass/fail logic for the E08-Q04 scenarios (no I/O, no clock — unit-tested on fake samples).

Budgets are 06-performance-and-load-standard §2 rows; each `Check` carries the measured number
beside the budget so the report can print both (AC 1). Hard vs soft follows the §2 table.

Budget #8 is per symbol (06 §2: book state, bar builders, rolling aggregation buffers):
`rss_per_symbol_mb` is the RSS the lanes add, i.e. the sample minus the RSS taken before they were
built, per symbol. The soak lanes run the trade stream and the book state; with `bars_specs` they
also run the bars path, bar builders and the WS series store (`soak_bars` at the 32-spec cap, #399
D2-G4; `check_bars` says when the figure is a reading at that cap). Aggregation enters this figure
when it enters the lanes. `rss_process_mb` is the whole-process RSS at each sample, imports
included, reported beside it so that growth in what is imported is not read as per-symbol growth.
The full `soak_bars` profile also judges the figure's slope over its last 12 h (`check_plateau`).
"""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

#: §2 budget numbers (06-performance-and-load-standard).
B8_RSS_MB_PER_SYMBOL = 300.0
B11_VCPU_PER_SYMBOL = 0.5
B12_GB_PER_DAY_PER_SYMBOL = 0.75
B13_READ_P95_MS = 150.0
B6_BACKEND_SLICE_P95_MS = 20.0
MEMORY_FLATNESS = 0.05


@dataclass(frozen=True, slots=True)
class Sample:
    """One sampling point (every 60 s full / 5 s smoke). `t_s` is scenario (virtual) time."""

    t_s: float
    rss_bytes: int
    cpu_s: float  # cumulative process CPU seconds (user+system)
    loop_lag_ms: float
    queue_depth: int
    storage_bytes: int  # cumulative modelled on-disk delta since start


@dataclass(slots=True)
class Check:
    name: str
    budget: str
    measured: float
    limit: float
    unit: str
    passed: bool
    hard: bool = True
    note: str = ""


@dataclass(slots=True)
class Verdict:
    scenario: str
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.hard)

    def add(self, check: Check) -> None:
        self.checks.append(check)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "passed": self.passed,
            "checks": [asdict(c) for c in self.checks],
            "metrics": self.metrics,
        }


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile (same rule as `bench/ingestion_soak.percentile`); 0 when empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(pct * len(ordered)) - 1))
    return float(ordered[idx])


def summary(values: Sequence[float]) -> dict[str, float]:
    """p50/p95/max/count — the §7.4 baseline shape."""
    return {
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "max": max(values) if values else 0.0,
        "count": float(len(values)),
    }


# --- budget #5: zero undetected loss ------------------------------------------------------------


def check_loss(
    injected: Mapping[str, int], ingested: Mapping[str, int], detected_gap: Mapping[str, int]
) -> Check:
    """AC 2: injected == ingested + detected-and-reported gaps, per symbol. Any undetected
    discrepancy (either sign: loss or duplication) fails as P0."""
    bad = {
        s: n - ingested.get(s, 0) - detected_gap.get(s, 0)
        for s, n in injected.items()
        if n != ingested.get(s, 0) + detected_gap.get(s, 0)
    }
    undetected = float(sum(abs(v) for v in bad.values()))
    note = (
        ""
        if not bad
        else "P0 undetected discrepancy: "
        + ", ".join(f"{s}={v:+d}" for s, v in sorted(bad.items()))
    )
    return Check("undetected_loss", "#5", undetected, 0.0, "events", undetected == 0.0, note=note)


# --- budget #8 / #11 / #12 and memory flatness --------------------------------------------------


def rss_per_symbol_mb(
    samples: Sequence[Sample], n_symbols: int, pre_lanes_bytes: int = 0
) -> list[float]:
    """Budget #8's figure at each sample: the RSS the lanes added per symbol, never below 0.
    `pre_lanes_bytes` is the RSS taken before the market and lanes existed (0: whole process)."""
    return [max(0, s.rss_bytes - pre_lanes_bytes) / 2**20 / max(1, n_symbols) for s in samples]


def rss_process_mb(samples: Sequence[Sample]) -> list[float]:
    """Whole-process RSS (MiB) at each sample: the footprint, imports included (not budget #8)."""
    return [s.rss_bytes / 2**20 for s in samples]


def vcpu_per_symbol(samples: Sequence[Sample], n_symbols: int) -> list[float]:
    """CPU seconds consumed per scenario second per symbol, between consecutive samples. On a
    virtual-time run this is the cost of simulating 1 s of 1x cadence, i.e. vCPU at 1x."""
    out: list[float] = []
    for a, b in itertools.pairwise(samples):
        dt = b.t_s - a.t_s
        if dt > 0:
            out.append(max(0.0, b.cpu_s - a.cpu_s) / dt / max(1, n_symbols))
    return out


def storage_gb_per_day_per_symbol(samples: Sequence[Sample], n_symbols: int) -> float:
    if len(samples) < 2 or samples[-1].t_s <= samples[0].t_s:
        return 0.0
    delta = samples[-1].storage_bytes - samples[0].storage_bytes
    span = samples[-1].t_s - samples[0].t_s
    return delta / span * 86_400 / 1e9 / max(1, n_symbols)


def flatness(samples: Sequence[Sample], baseline_at_s: float) -> tuple[float, float]:
    """AC 1: max |rss - base| / base over samples at/after `baseline_at_s`, where `base` is the
    first sample at/after `baseline_at_s` (hour 2 on the 24 h run; same fraction when scaled).
    Returns (max_deviation, baseline_t_s)."""
    steady = [s for s in samples if s.t_s >= baseline_at_s]
    if len(steady) < 2:
        return 0.0, baseline_at_s
    base = steady[0].rss_bytes
    if base <= 0:
        return 0.0, steady[0].t_s
    return max(abs(s.rss_bytes - base) / base for s in steady), steady[0].t_s


def check_soak(
    samples: Sequence[Sample],
    n_symbols: int,
    baseline_at_s: float,
    tolerance: float,
    pre_lanes_bytes: int = 0,
) -> list[Check]:
    rss = percentile(rss_per_symbol_mb(samples, n_symbols, pre_lanes_bytes), 0.95)
    cpu = percentile(vcpu_per_symbol(samples, n_symbols), 0.95)
    gb = storage_gb_per_day_per_symbol(samples, n_symbols)
    dev, at = flatness(samples, baseline_at_s)
    return [
        Check(
            "rss_per_symbol_p95",
            "#8",
            rss,
            B8_RSS_MB_PER_SYMBOL,
            "MB",
            rss <= B8_RSS_MB_PER_SYMBOL,
            note=(
                f"RSS added since the {pre_lanes_bytes / 2**20:.1f} MiB before the lanes"
                if pre_lanes_bytes
                else ""
            ),
        ),
        Check(
            "vcpu_per_symbol_p95",
            "#11",
            cpu,
            B11_VCPU_PER_SYMBOL,
            "vCPU",
            cpu <= B11_VCPU_PER_SYMBOL,
            hard=False,
        ),
        Check(
            "storage_gb_day_symbol",
            "#12",
            gb,
            B12_GB_PER_DAY_PER_SYMBOL,
            "GB/day",
            gb <= B12_GB_PER_DAY_PER_SYMBOL,
            hard=False,
            note="modelled bytes/row (E16-K01)",
        ),
        Check(
            "memory_flatness",
            "±5%",
            dev,
            tolerance,
            "ratio",
            dev <= tolerance,
            note=f"max deviation from the t={at:.0f}s baseline sample",
        ),
    ]


def check_bars(
    fewest: Sequence[int], per_series: int, folded: Sequence[int], unhealthy: Sequence[str]
) -> list[Check]:
    """#399 D2-G4: budget #8's figure is a reading at the bars cap only while every series stays
    full and its builders are live.

    `fewest`: at each sample, the fewest closed bars any series held. A series only grows from the
    `per_series` it was hydrated with, so one below that was reset or never hydrated; a sum over
    the series would hide it unless `per_series` is the store's own cap (`MAX_HISTORY`), where no
    series can outgrow another. `folded`: each lane's live closes past its stored tail (one live
    builder passes it). `unhealthy`: the sticky degraded reasons each lane's bar set reported at
    its stop (`BarsHealthReason`: a quarantined builder, a dead lane or ticker task, a cold-started
    state blob, a restore gap, an emit-sink timeout), which the other two cannot see."""
    low = float(min(fewest, default=0))
    fold = float(min(folded, default=0))
    return [
        Check(
            "bars_store_at_cap",
            "#8",
            low,
            float(per_series),
            "bars",
            low >= per_series,
            note="closed bars the fewest-held series had, lowest sample",
        ),
        Check(
            "bars_closes_folded",
            "#8",
            fold,
            1.0,
            "closes",
            fold >= 1.0,
            note="live closes folded past the stored tail, lowest lane",
        ),
        Check(
            "bars_builders_healthy",
            "#8",
            float(len(unhealthy)),
            0.0,
            "reasons",
            not unhealthy,
            note=", ".join(unhealthy) or "no degraded reason from any lane's bar set",
        ),
    ]


# --- budget #8's plateau: R4 of the bars soak (#399 D2-G4) --------------------------------------

#: R4 was pre-registered on #399 before its 24 h reading (issuecomment-6297719530): over the last
#: 12 h of scenario time, the Theil-Sen slope of the RSS the lanes add per symbol is at most
#: `SLOPE_LIMIT_MB_PER_H`, over at least `PLATEAU_MIN_SAMPLES` samples. The limit is the growth that
#: would use up budget #8's headroom over the horizon, (B8 - the 170 MB the 1.5 h leg measured,
#: #3861) / 720 h = 0.18 MB/h; R2's 5 % band alone admits about 0.42 MB/h a symbol. "MB" is the
#: harness's own, a MiB (`rss_per_symbol_mb` divides bytes by 2**20): the unit of R1's 300 and of
#: the 170, so 0.18 here is 0.189 in decimal MB. The scenario sets the window (`plateau_window_s`);
#: no scenario sets the limit.
PLATEAU_LEVEL_MB = 170.0
PLATEAU_HORIZON_H = 720.0  # 30 days: the horizon 06 §6.3 and §10.2 already use for retention, disk
SLOPE_LIMIT_MB_PER_H = round((B8_RSS_MB_PER_SYMBOL - PLATEAU_LEVEL_MB) / PLATEAU_HORIZON_H, 2)
PLATEAU_MIN_SAMPLES = 100


def theil_sen_mb_per_h(points: Sequence[tuple[float, float]]) -> float:
    """The Theil-Sen slope of `points`, (seconds, MB), in MB per hour: the median of the slopes
    between every two points that differ in time. Noise and a few wild samples leave it where it
    was. It reads growth that is sustained across the points: one step moves it only when the
    step separates more than half of the pairs, which for equally spaced points is within about
    1.7 % of the span of the middle (13 minutes of a 12 h window), and growth confined to the last
    29 % of the points (3.5 h of 12) reads 0 at any rate. Quadratic in the points (259 560 pairs
    for the 721 samples of a 12 h window at 60 s). Raises `statistics.StatisticsError` when no two
    points differ in time."""
    return statistics.median(
        (y2 - y1) * 3600.0 / (t2 - t1)
        for (t1, y1), (t2, y2) in itertools.combinations(points, 2)
        if t1 != t2
    )


def check_plateau(
    samples: Sequence[Sample], n_symbols: int, window_s: float, pre_lanes_bytes: int = 0
) -> Check:
    """R4: the Theil-Sen slope of budget #8's figure (`rss_per_symbol_mb`) over the samples of the
    last `window_s` of scenario time (from the last sample's `t_s` less `window_s` on, both ends
    in) is at most `SLOPE_LIMIT_MB_PER_H`, in the figure's unit: MB is a MiB, as for R1. It reads
    sustained growth across the window, such as a creep inside R2's band that would use the
    headroom up in days. A single step registers only within about 13 minutes of a 12 h window's
    middle, and growth that starts in the last 3.5 h reads 0 (`theil_sen_mb_per_h`): R2's band
    stays the guard for a large step, and a late leak is not seen. Fewer than
    `PLATEAU_MIN_SAMPLES` samples in the window is no reading, and a hard FAIL."""
    end = max((s.t_s for s in samples), default=0.0)
    kept = [s for s in samples if s.t_s >= end - window_s]
    if len(kept) < PLATEAU_MIN_SAMPLES:
        note = (
            f"no reading: {len(kept)} samples in the last {window_s:.0f} s, "
            f"need {PLATEAU_MIN_SAMPLES}"
        )
        return Check(
            "rss_plateau_slope", "#8", math.inf, SLOPE_LIMIT_MB_PER_H, "MB/h", False, note=note
        )
    per_symbol = rss_per_symbol_mb(kept, n_symbols, pre_lanes_bytes)
    slope = theil_sen_mb_per_h([(s.t_s, mb) for s, mb in zip(kept, per_symbol, strict=True)])
    return Check(
        "rss_plateau_slope",
        "#8",
        slope,
        SLOPE_LIMIT_MB_PER_H,
        "MB/h",
        slope <= SLOPE_LIMIT_MB_PER_H,
        note=f"Theil-Sen slope of the RSS the lanes add per symbol, last {window_s:.0f} s, "
        f"{len(kept)} samples",
    )


# --- scenario 2/3: per-symbol isolation ---------------------------------------------------------


def lag_band(steady_lag_ms: Sequence[float], abs_floor_ms: float, rel: float) -> float:
    """The documented steady-state band for one symbol: p95 of its own steady lag times
    (1 + rel), never tighter than `abs_floor_ms` (sub-ms timer noise must not fail a run)."""
    return max(abs_floor_ms, percentile(steady_lag_ms, 0.95) * (1.0 + rel))


def check_isolation(
    steady: Mapping[str, Sequence[float]],
    loaded: Mapping[str, Sequence[float]],
    skip: Sequence[str],
    abs_floor_ms: float,
    rel: float,
) -> Check:
    """AC 3: every symbol not in `skip` keeps its loaded-phase p95 lag inside its own band."""
    worst, worst_sym, ratio = 0.0, "", 0.0
    for sym, base in steady.items():
        if sym in skip:
            continue
        band = lag_band(base, abs_floor_ms, rel)
        p95 = percentile(loaded.get(sym, ()), 0.95)
        if p95 / band > ratio:
            worst, worst_sym, ratio = p95, sym, p95 / band
    passed = ratio <= 1.0
    note = f"worst={worst_sym} p95={worst:.3f}ms ({ratio:.2f}x band)" if worst_sym else ""
    return Check("cross_symbol_lag_band", "#5/#6", ratio, 1.0, "x band", passed, note=note)


def check_burst(
    max_backlog: int,
    backlog_bound: int,
    recovery_s: float | None,
    recovery_window_s: float,
    backpressure_events: float,
) -> list[Check]:
    rec = math.inf if recovery_s is None else recovery_s
    return [
        Check(
            "queue_growth_bounded",
            "#5",
            float(max_backlog),
            float(backlog_bound),
            "events",
            max_backlog <= backlog_bound,
        ),
        Check(
            "recovery_s",
            "#5",
            rec,
            recovery_window_s,
            "s",
            rec <= recovery_window_s,
            note="burst end -> backlog empty",
        ),
        Check(
            "backpressure_applied",
            "#5",
            backpressure_events,
            1.0,
            "events",
            backpressure_events >= 1.0,
            note="the burst must actually exercise backpressure",
        ),
    ]


# --- scenario 4/5/6 -----------------------------------------------------------------------------


def check_latency(stage_ms: Sequence[float], budget_ms: float = B6_BACKEND_SLICE_P95_MS) -> Check:
    p95 = percentile(stage_ms, 0.95)
    return Check(
        "receipt_to_publish_p95",
        "#6",
        p95,
        budget_ms,
        "ms",
        p95 <= budget_ms,
        note="E08 slice (parse+derive); fan-out slice is E17",
    )


def check_rest(
    p95_by_route: Mapping[str, float], cold_p95: float, warm_p95: float, min_speedup: float
) -> list[Check]:
    out = [
        Check(f"rest_p95[{r}]", "#13", p, B13_READ_P95_MS, "ms", p <= B13_READ_P95_MS)
        for r, p in sorted(p95_by_route.items())
    ]
    speedup = cold_p95 / warm_p95 if warm_p95 > 0 else math.inf
    out.append(
        Check(
            "klines_cache_speedup",
            "#13",
            speedup,
            min_speedup,
            "x",
            speedup >= min_speedup,
            note=f"cold p95 {cold_p95:.2f}ms vs warm p95 {warm_p95:.2f}ms",
        )
    )
    return out


def check_headroom(min_tokens: float, ip_holds: int, ip_limit_errors: int) -> list[Check]:
    return [
        Check(
            "min_bucket_headroom",
            "C-12.7",
            min_tokens,
            0.0,
            "tokens",
            min_tokens > 0.0,
            note="headroom must never reach zero",
        ),
        Check(
            "provoked_ip_limit",
            "C-12.7",
            float(ip_limit_errors),
            0.0,
            "responses",
            ip_limit_errors == 0 and ip_holds == 0,
        ),
    ]

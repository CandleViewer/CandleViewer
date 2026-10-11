"""Pure pass/fail logic for the E08-Q04 scenarios (no I/O, no clock — unit-tested on fake samples).

Budgets are 06-performance-and-load-standard §2 rows; each `Check` carries the measured number
beside the budget so the report can print both (AC 1). Hard vs soft follows the §2 table.
"""

from __future__ import annotations

import math
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
    note = "" if not bad else "P0 undetected discrepancy: " + ", ".join(
        f"{s}={v:+d}" for s, v in sorted(bad.items())
    )
    return Check("undetected_loss", "#5", undetected, 0.0, "events", undetected == 0.0, note=note)


# --- budget #8 / #11 / #12 and memory flatness --------------------------------------------------


def rss_per_symbol_mb(samples: Sequence[Sample], n_symbols: int) -> list[float]:
    return [s.rss_bytes / 2**20 / max(1, n_symbols) for s in samples]


def vcpu_per_symbol(samples: Sequence[Sample], n_symbols: int) -> list[float]:
    """CPU seconds consumed per scenario second per symbol, between consecutive samples. On a
    virtual-time run this is the cost of simulating 1 s of 1x cadence, i.e. vCPU at 1x."""
    out: list[float] = []
    for a, b in zip(samples, samples[1:], strict=False):
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
    samples: Sequence[Sample], n_symbols: int, baseline_at_s: float, tolerance: float
) -> list[Check]:
    rss = percentile(rss_per_symbol_mb(samples, n_symbols), 0.95)
    cpu = percentile(vcpu_per_symbol(samples, n_symbols), 0.95)
    gb = storage_gb_per_day_per_symbol(samples, n_symbols)
    dev, at = flatness(samples, baseline_at_s)
    return [
        Check("rss_per_symbol_p95", "#8", rss, B8_RSS_MB_PER_SYMBOL, "MB", rss <= B8_RSS_MB_PER_SYMBOL),
        Check(
            "vcpu_per_symbol_p95", "#11", cpu, B11_VCPU_PER_SYMBOL, "vCPU",
            cpu <= B11_VCPU_PER_SYMBOL, hard=False,
        ),  # fmt: skip
        Check(
            "storage_gb_day_symbol", "#12", gb, B12_GB_PER_DAY_PER_SYMBOL, "GB/day",
            gb <= B12_GB_PER_DAY_PER_SYMBOL, hard=False, note="modelled bytes/row (E16-K01)",
        ),  # fmt: skip
        Check(
            "memory_flatness", "±5%", dev, tolerance, "ratio", dev <= tolerance,
            note=f"max deviation from the t={at:.0f}s baseline sample",
        ),  # fmt: skip
    ]


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
            "queue_growth_bounded", "#5", float(max_backlog), float(backlog_bound), "events",
            max_backlog <= backlog_bound,
        ),  # fmt: skip
        Check(
            "recovery_s", "#5", rec, recovery_window_s, "s", rec <= recovery_window_s,
            note="burst end -> backlog empty",
        ),  # fmt: skip
        Check(
            "backpressure_applied", "#5", backpressure_events, 1.0, "events",
            backpressure_events >= 1.0, note="the burst must actually exercise backpressure",
        ),  # fmt: skip
    ]


# --- scenario 4/5/6 -----------------------------------------------------------------------------


def check_latency(stage_ms: Sequence[float], budget_ms: float = B6_BACKEND_SLICE_P95_MS) -> Check:
    p95 = percentile(stage_ms, 0.95)
    return Check(
        "receipt_to_publish_p95", "#6", p95, budget_ms, "ms", p95 <= budget_ms,
        note="E08 slice (parse+derive); fan-out slice is E17",
    )  # fmt: skip


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
            "klines_cache_speedup", "#13", speedup, min_speedup, "x", speedup >= min_speedup,
            note=f"cold p95 {cold_p95:.2f}ms vs warm p95 {warm_p95:.2f}ms",
        )  # fmt: skip
    )
    return out


def check_headroom(min_tokens: float, ip_holds: int, rate_limited_10018: int) -> list[Check]:
    return [
        Check("min_bucket_headroom", "C-12.7", min_tokens, 0.0, "tokens", min_tokens > 0.0,
              note="headroom must never reach zero"),  # fmt: skip
        Check("provoked_10018", "C-12.7", float(rate_limited_10018), 0.0, "responses",
              rate_limited_10018 == 0 and ip_holds == 0),  # fmt: skip
    ]

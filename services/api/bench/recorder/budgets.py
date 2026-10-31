"""Pure pass/fail logic for the E16-Q04 recorder scripts (no I/O, no clock: unit-tested on fakes).

Budgets (ticket perf notes, 06-performance-and-load-standard budget #12 and the API/WS rows):
p95 flush < 50 ms, process RSS <= 512 MiB, API p95 < 150 ms, a `recorder` frame < 8 KiB for 20
symbols, GB/day within 20 % of the E16-K01 figure, and no silent loss: zero dropped rows, a backlog
p95 of 0 at flush boundaries, zero spill bytes, and produced rows == written rows + rows a gap
accounts for, per stream, exactly (either sign is a failure: loss or duplication).
The API and frame budgets are judged by k6's thresholds (`tests/load/k6/recorder_api.js`); their
numbers live here so the script and the docs quote one place.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from bench.ingestion.budgets import Check, Verdict, percentile, summary

FLUSH_P95_MS = 50.0
RSS_CEILING_MIB = 512.0
API_P95_MS = 150.0
FRAME_MAX_BYTES = 8192
FRAME_SYMBOLS = 20
GB_PER_DAY_TOLERANCE = 0.20
#: A run that produced under this share of its target rate measured a lighter load than it names.
RATE_FLOOR = 0.95


@dataclass(slots=True)
class RunResult:
    """What one harness run measured. Samples are taken at flush boundaries (see `harness`)."""

    profile: str
    target_msgs_per_s: float
    duration_s: float
    symbols: tuple[str, ...]
    produced_msgs: int = 0
    produced_rows: dict[str, int] = field(default_factory=dict)
    written_rows: dict[str, int] = field(default_factory=dict)
    dropped_rows: dict[str, int] = field(default_factory=dict)
    flush_ms: list[float] = field(default_factory=list)
    rss_bytes: list[int] = field(default_factory=list)
    backlog_rows: list[int] = field(default_factory=list)
    spill_bytes: list[int] = field(default_factory=list)
    hot_bytes: int = 0
    critical_events: int = 0

    @property
    def achieved_msgs_per_s(self) -> float:
        return self.produced_msgs / self.duration_s if self.duration_s > 0 else 0.0

    def gb_per_day_per_symbol(self) -> float:
        """Modelled hot-tier bytes of the written rows, extrapolated to a day, per symbol."""
        if self.duration_s <= 0 or not self.symbols:
            return 0.0
        return self.hot_bytes / self.duration_s * 86_400 / 1e9 / len(self.symbols)


def check_flush(flush_ms: Sequence[float], limit_ms: float = FLUSH_P95_MS) -> Check:
    p95 = percentile(flush_ms, 0.95)
    ok = bool(flush_ms) and p95 < limit_ms
    note = "" if flush_ms else "no flush observed: the run wrote nothing"
    return Check("flush_p95", "E16-Q04 flush", p95, limit_ms, "ms", ok, note=note)


def check_memory(rss_bytes: Sequence[int], ceiling_mib: float = RSS_CEILING_MIB) -> Check:
    peak = max(rss_bytes, default=0) / 2**20
    return Check("rss_peak", "E16-Q04 memory", peak, ceiling_mib, "MiB", peak <= ceiling_mib)


def check_drops(dropped_rows: Mapping[str, int]) -> Check:
    n = float(sum(dropped_rows.values()))
    return Check("dropped_rows", "E16-Q04 no loss", n, 0.0, "rows", n == 0.0)


def check_backlog(backlog_rows: Sequence[int]) -> Check:
    p95 = percentile([float(b) for b in backlog_rows], 0.95)
    return Check("backlog_p95", "E16-Q04 no loss", p95, 0.0, "rows", p95 == 0.0)


def check_spill(spill_bytes: Sequence[int]) -> Check:
    peak = float(max(spill_bytes, default=0))
    return Check("spill_bytes", "E16-Q04 no loss", peak, 0.0, "bytes", peak == 0.0)


def check_reconciliation(
    produced: Mapping[str, int], written: Mapping[str, int], gap_accounted: Mapping[str, int]
) -> Check:
    """Produced == written + gap-accounted, per stream; any difference is undetected loss (or a
    duplicate) and fails."""
    streams = sorted(set(produced) | set(written) | set(gap_accounted))
    bad = {
        s: produced.get(s, 0) - written.get(s, 0) - gap_accounted.get(s, 0)
        for s in streams
        if produced.get(s, 0) != written.get(s, 0) + gap_accounted.get(s, 0)
    }
    off = float(sum(abs(v) for v in bad.values()))
    note = ", ".join(f"{s}={v:+d}" for s, v in sorted(bad.items()))
    return Check(
        "reconciliation", "E16-Q04 oracle", off, 0.0, "rows", off == 0.0,
        note=f"undetected: {note}" if bad else "",
    )  # fmt: skip


def check_gb_per_day(
    measured: float, baseline: float, *, tolerance: float = GB_PER_DAY_TOLERANCE, hard: bool = True
) -> Check:
    """Within `tolerance` of the E16-K01 figure. `hard=False` reports it (a scaled smoke run)."""
    rel = abs(measured - baseline) / baseline if baseline > 0 else float("inf")
    return Check(
        "gb_per_day_per_symbol", "#12 / E16-K01", measured, baseline, "GB/day",
        rel <= tolerance, hard=hard, note=f"{rel:+.1%} vs baseline (band {tolerance:.0%})",
    )  # fmt: skip


def check_rate(achieved: float, target: float, floor: float = RATE_FLOOR) -> Check:
    """The run produced the load it names: a slow generator never passes as a light load."""
    limit = target * floor
    return Check("achieved_rate", "E16-Q04 load", achieved, limit, "msg/s", achieved >= limit)


def ingest_verdict(r: RunResult) -> Verdict:
    """The 50k msg/s ingest load: flush p95, the memory ceiling, the rate it reached, no loss."""
    v = Verdict("recorder_ingest")
    for c in (
        check_rate(r.achieved_msgs_per_s, r.target_msgs_per_s),
        check_flush(r.flush_ms),
        check_memory(r.rss_bytes),
        check_drops(r.dropped_rows),
        check_reconciliation(r.produced_rows, r.written_rows, r.dropped_rows),
    ):
        v.add(c)
    v.metrics = _metrics(r)
    return v


def soak_verdict(r: RunResult, baseline_gb: float, *, gate_gb: bool) -> Verdict:
    """The soak: no silent loss and the storage rate. `gate_gb` is False on a scaled run, whose
    feed rate is not the reference one, so its GB/day is reported only."""
    v = Verdict("recorder_soak")
    for c in (
        check_drops(r.dropped_rows),
        check_backlog(r.backlog_rows),
        check_spill(r.spill_bytes),
        check_reconciliation(r.produced_rows, r.written_rows, r.dropped_rows),
        check_flush(r.flush_ms),
        check_memory(r.rss_bytes),
        check_gb_per_day(r.gb_per_day_per_symbol(), baseline_gb, hard=gate_gb),
    ):
        v.add(c)
    v.metrics = _metrics(r)
    return v


def _metrics(r: RunResult) -> dict[str, dict[str, float]]:
    return {
        "flush_ms": summary(r.flush_ms),
        "rss_mib": summary([b / 2**20 for b in r.rss_bytes]),
        "backlog_rows": summary([float(b) for b in r.backlog_rows]),
    }

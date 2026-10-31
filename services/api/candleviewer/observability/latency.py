"""Per-stage latency arithmetic for the tick → paint budget (E04-T06, US-OBS-002).

An exchange event carries five stage timestamps (`StageStamps`); each stage's
cost is a subtraction, not a guess. The exchange-origin stage
(`t_exchange → t_received`) is on the exchange's clock, so it is only
reported when a clock-offset measurement exists (`exchange_clock_drift_ms`,
E08/US-MKT-009); without one it is `None` ("unavailable") — never a raw,
skew-dominated or negative number.

Percentiles do not sum: per-stage histograms are for *attribution*; the
end-to-end p95 comes from `e2e_tick_to_paint_seconds`, a genuine paired
measurement on a 1-in-N sampled event (`EndToEndSampler`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol

Stage = Literal["exchange", "parse", "derive", "fanout"]

#: Closed stage label set for `ingest_stage_seconds{stage}`.
STAGES: Final[tuple[Stage, ...]] = ("exchange", "parse", "derive", "fanout")

#: Buckets straddling the 06-performance §5.1 allocations
#: (parse ≤3 ms, derive ≤5+5 ms, fan-out ≤7 ms, backend envelope ≤20 ms).
STAGE_BUCKETS: Final = (
    0.0005,
    0.001,
    0.002,
    0.003,
    0.005,
    0.007,
    0.01,
    0.015,
    0.02,
    0.05,
    0.1,
    0.25,
)
#: End-to-end tick → paint: p95 < 100 ms, p99 < 250 ms (budget #3).
E2E_BUCKETS: Final = (0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.25, 0.5, 1.0, 2.5)


@dataclass(frozen=True, slots=True)
class StageStamps:
    """Stage timestamps in epoch milliseconds. `t_exchange` is exchange-clock."""

    t_exchange: int
    t_received: int
    t_parsed: int
    t_derived: int
    t_emitted: int


def _nonneg_seconds(later_ms: float, earlier_ms: float) -> float | None:
    """Duration in seconds, or `None` when negative (clock step / bad stamp)."""
    delta = later_ms - earlier_ms
    if delta < 0:
        return None
    return delta / 1000.0


def stage_durations(stamps: StageStamps, clock_offset_ms: int | None) -> dict[Stage, float | None]:
    """Seconds per stage; `None` means unavailable.

    `clock_offset_ms` is the signed offset ``exchange - local`` (as
    `exchange_clock_drift_ms`). The exchange stamp is shifted onto the
    local clock before subtracting; with no measurement the stage is
    unavailable rather than a plausible-looking wrong number.
    """
    exchange: float | None = None
    if clock_offset_ms is not None:
        exchange = _nonneg_seconds(stamps.t_received, stamps.t_exchange - clock_offset_ms)
    return {
        "exchange": exchange,
        "parse": _nonneg_seconds(stamps.t_parsed, stamps.t_received),
        "derive": _nonneg_seconds(stamps.t_derived, stamps.t_parsed),
        "fanout": _nonneg_seconds(stamps.t_emitted, stamps.t_derived),
    }


class _Observer(Protocol):
    def observe(self, amount: float) -> None: ...


class _Labelled(Protocol):
    def labels(self, *values: str) -> _Observer: ...


def record_stages(
    histogram: _Labelled, stamps: StageStamps, clock_offset_ms: int | None
) -> dict[Stage, float | None]:
    """Observe every available stage into `ingest_stage_seconds{stage}`."""
    out = stage_durations(stamps, clock_offset_ms)
    for stage, value in out.items():
        if value is not None:
            histogram.labels(stage).observe(value)
    return out


class EndToEndSampler:
    """Deterministic 1-in-N selection (`CV_TELEMETRY_SAMPLE_N`, default 100).

    Sampling keeps the measurement overhead inside the ≤1 % CPU NFR: only
    sampled events are stage-recorded and carry `t_received` to the client
    for end-to-end pairing; unsampled events pay one counter increment.
    """

    __slots__ = ("_counter", "_n")

    def __init__(self, n: int) -> None:
        if n < 1:
            raise ValueError("sample N must be >= 1")
        self._n = n
        self._counter = 0

    def should_sample(self) -> bool:
        self._counter += 1
        if self._counter >= self._n:
            self._counter = 0
            return True
        return False


def e2e_seconds(t_received_ms: int, t_paint_local_ms: int) -> float | None:
    """Paired tick → paint on the local clock (paint stamp already corrected
    to backend time by the client's session clock offset)."""
    return _nonneg_seconds(t_paint_local_ms, t_received_ms)


def dominant_stage(mean_seconds: dict[Stage, float | None]) -> Stage | None:
    """The stage consuming the largest share of the budget.

    Mirrors `cv:latency_stage_share:ratio_5m` + `topk(1, …)` in
    `infra/prometheus/alerts/latency_budget.yml` (the breach annotation), so
    the attribution rule is unit-tested without Prometheus.
    """
    known = {k: v for k, v in mean_seconds.items() if v is not None}
    total = sum(known.values())
    if not known or total <= 0:
        return None
    return max(known, key=lambda k: known[k] / total)


class StageRecorder:
    """Hot-path entry point: sample 1-in-N, then record stages.

    Pre-binds the four `stage` children once so a sampled event costs four
    subtractions and four observes; an unsampled one costs a counter bump.
    """

    __slots__ = ("_children", "_sampler")

    def __init__(self, histogram: _Labelled, sample_n: int) -> None:
        self._sampler = EndToEndSampler(sample_n)
        self._children = {stage: histogram.labels(stage) for stage in STAGES}

    def sample(self) -> bool:
        """1-in-N gate for callers that build `StageStamps` only when sampled
        (keeps the unsampled hot path allocation-free, C-2.20)."""
        return self._sampler.should_sample()

    def record(self, stamps: StageStamps, clock_offset_ms: int | None) -> None:
        """Observe an already-sampled event (pair with `sample()`)."""
        for stage, value in stage_durations(stamps, clock_offset_ms).items():
            if value is not None:
                self._children[stage].observe(value)

    def on_event(self, stamps: StageStamps, clock_offset_ms: int | None) -> bool:
        """Returns True when the event was sampled (caller then forwards
        `t_received` to the client for e2e pairing)."""
        if not self._sampler.should_sample():
            return False
        for stage, value in stage_durations(stamps, clock_offset_ms).items():
            if value is not None:
                self._children[stage].observe(value)
        return True

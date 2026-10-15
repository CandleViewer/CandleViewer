"""Feature-flag metrics (E42-T03 Observability), on the facade like E42-T01's admin series.

`key` is always a registry key (unknown keys are refused before any series is touched) and
`result` one of the fixed write outcomes, so both label sets are bounded.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Histogram,
    ReexportCollector,
)

flag_evaluations_total = Counter(
    "cv_feature_flag_evaluations_total",
    "Server-side feature-flag resolutions, per flag.",
    ["key"],
)
flag_changes_total = Counter(
    "cv_feature_flag_changes_total",
    "Feature-flag write attempts past validation: ok, conflict or gate_evidence_required.",
    ["key", "result"],
)

flag_push_latency_seconds = Histogram(
    "cv_flag_push_latency_seconds",
    "Time from a committed flag write to the last session frame queued (budget 2 s).",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
)

EXPORTED_NAMES: Final = frozenset(
    {
        "cv_feature_flag_evaluations_total",
        "cv_feature_flag_changes_total",
        "cv_flag_push_latency_seconds",
    }
)


def export_flag_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the flag series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

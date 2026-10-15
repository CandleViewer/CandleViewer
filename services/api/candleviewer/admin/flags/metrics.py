"""Feature-flag metrics (E42-T03 Observability), on the facade like E42-T01's admin series.

`key` is always a registry key (unknown keys are refused before any series is touched) and
`result` one of the fixed write outcomes, so both label sets are bounded.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import CollectorRegistry, Counter, ReexportCollector

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

EXPORTED_NAMES: Final = frozenset(
    {"cv_feature_flag_evaluations_total", "cv_feature_flag_changes_total"}
)


def export_flag_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the flag series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

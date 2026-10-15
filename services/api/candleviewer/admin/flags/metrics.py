"""Feature-flag metrics (E42-T03 Observability), on the facade like E42-T01's admin series.

The `flag` label (not `key`, which SR-125's `DISALLOWED_LABEL_NAMES` refuses) only ever holds a
registry key, a closed set of about 16 reviewed values (unknown keys are refused before any
series is touched); `result` is one of the fixed write outcomes. Both are bounded and carry no
personal data; the series are declared in `observability/metrics_catalogue.py`.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import CollectorRegistry, Counter, ReexportCollector

flag_evaluations_total = Counter(
    "cv_feature_flag_evaluations_total",
    "Server-side feature-flag resolutions, per flag.",
    ["flag"],
)
flag_changes_total = Counter(
    "cv_feature_flag_changes_total",
    "Feature-flag write attempts past validation: ok, conflict or gate_evidence_required.",
    ["flag", "result"],
)

EXPORTED_NAMES: Final = frozenset(
    {"cv_feature_flag_evaluations_total", "cv_feature_flag_changes_total"}
)


def export_flag_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the flag series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

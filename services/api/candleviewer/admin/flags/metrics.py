"""Feature-flag metrics (E42-T03 Observability), on the facade like E42-T01's admin series.

The `flag` label (not `key`, which SR-125's `DISALLOWED_LABEL_NAMES` refuses) only ever holds a
registry key, a closed set of about 16 reviewed values (unknown keys are refused before any
series is touched); `result` is one of the fixed write outcomes. Both are bounded and carry no
personal data; the series are declared in `observability/metrics_catalogue.py`.
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
    ["flag"],
)
unreadable_overrides_total = Counter(
    "cv_feature_flag_unreadable_overrides_total",
    "Override rows ignored at resolution because their value does not fit the flag's kind.",
    ["flag"],
)
flag_changes_total = Counter(
    "cv_feature_flag_changes_total",
    "Feature-flag writes past RBAC, by result: ok, conflict, store_unavailable or a 422 rule.",
    ["flag", "result"],
)

flag_push_latency_seconds = Histogram(
    "cv_flag_push_latency_seconds",
    "Time from a committed flag write to the last session frame queued (budget 2 s).",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
)

EXPORTED_NAMES: Final = frozenset(
    {
        "cv_feature_flag_evaluations_total",
        "cv_feature_flag_unreadable_overrides_total",
        "cv_feature_flag_changes_total",
        "cv_flag_push_latency_seconds",
    }
)


def export_flag_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the flag series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

"""Metrics for the admin read-model fan-out (E42-T01 Observability), via the facade (E04-T03).

Module-level series on the library registry, like the recorder's; the composition root serves
them on the scraped registry with the mandatory `env` label through `export_overview_metrics`.
`source` is always one of the fixed slice names in code, so the label set is bounded.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Histogram,
    ReexportCollector,
)

#: Edges around the 300 ms per-source budget (the ticket's p95 targets are 300 / 500 ms).
SOURCE_BUCKETS: Final = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0)

source_duration_seconds = Histogram(
    "cv_admin_overview_source_duration_seconds",
    "Time one admin read-model source took, success or not (cache hits are not timed).",
    ["source"],
    buckets=SOURCE_BUCKETS,
)
source_errors_total = Counter(
    "cv_admin_overview_source_errors_total",
    "Admin read-model sources that timed out or failed (their slice became status=error).",
    ["source"],
)

EXPORTED_NAMES: Final = frozenset(
    {"cv_admin_overview_source_duration_seconds", "cv_admin_overview_source_errors_total"}
)


def export_overview_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the fan-out series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

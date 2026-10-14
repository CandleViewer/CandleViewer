"""Audit read-path series (E42-T02), defined in `observability` so that both `storage` (the
repository, which knows why a read ran out of time) and `api` (the router, which times a
page) may import them. `export_audit_query_metrics` serves them on the scraped registry
with `env`.

Labels are closed sets and never carry a filter value: `filter_class` is one of
`FILTER_CLASSES`, `cause` one of `budget | pool | statement_timeout`.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Histogram,
    ReexportCollector,
)
from candleviewer.observability.metrics_catalogue import AUDIT_QUERY_BUCKETS

FILTER_CLASSES: Final = (
    "q",
    "ip",
    "actor_action",
    "actor",
    "action",
    "object",
    "severity",
    "outcome",
    "range",
    "none",
)

cv_audit_query_duration_seconds = Histogram(
    "cv_audit_query_duration_seconds",
    "GET /admin/audit page time (SQL and chain check), by filter class.",
    labelnames=("filter_class",),
    buckets=AUDIT_QUERY_BUCKETS,
)
cv_audit_query_timeouts_total = Counter(
    "cv_audit_query_timeouts_total",
    "Audit page reads over their time budget (cause: budget | pool | statement_timeout).",
    labelnames=("cause",),
)

EXPORTED_NAMES: Final = frozenset(
    {"cv_audit_query_duration_seconds", "cv_audit_query_timeouts_total"}
)


def export_audit_query_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the audit read-path series on the scraped registry with the `env` label."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

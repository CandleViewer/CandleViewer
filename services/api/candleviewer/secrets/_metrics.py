"""M2 metrics (e27-kek.md §6, E27-T02 Observability). Labels never carry key material."""

from __future__ import annotations

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)

kek_load_seconds = Histogram(
    "cv_kek_load_seconds", "KEK acquisition time.", buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 10.0)
)
kek_load_failures_total = Counter(
    "cv_kek_load_failures_total", "KEK load failures.", labelnames=("reason",)
)
kek_version = Gauge("cv_kek_version_state", "Active KEK version (0 = none).")
credential_borrow_seconds = Histogram(
    "cv_credential_borrow_seconds",
    "Unwrap + decrypt time of one borrow.",
    buckets=(0.0005, 0.001, 0.002, 0.005, 0.01),
)
credential_borrow_total = Counter(
    "cv_credential_borrow_total", "Credential borrows.", labelnames=("stage", "result")
)
credential_rewrap_rows_total = Counter("cv_credential_rewrap_rows_total", "DEKs re-wrapped.")
dek_cache_hits_total = Counter("cv_dek_cache_hits_total", "Unwrapped-DEK cache hits.")

EXPORTED_NAMES = frozenset(
    {
        "cv_kek_load_seconds",
        "cv_kek_load_failures_total",
        "cv_kek_version_state",
        "cv_credential_borrow_seconds",
        "cv_credential_borrow_total",
        "cv_credential_rewrap_rows_total",
        "cv_dek_cache_hits_total",
    }
)


def export_secrets_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve every M2 series on the scraped registry with the `env` label."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

"""M2 metrics (e27-kek.md §6, E27-T02 Observability). Labels never carry key material."""

from __future__ import annotations

from candleviewer.observability.metrics import Counter, Gauge, Histogram

kek_load_seconds = Histogram(
    "cv_kek_load_seconds", "KEK acquisition time.", buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 10.0)
)
kek_load_failures_total = Counter(
    "cv_kek_load_failures_total", "KEK load failures.", labelnames=("reason",)
)
kek_version = Gauge("cv_kek_version", "Active KEK version (0 = none).")
credential_borrow_seconds = Histogram(
    "cv_credential_borrow_seconds",
    "Unwrap + decrypt time of one borrow.",
    buckets=(0.0005, 0.001, 0.002, 0.005, 0.01),
)
credential_borrow_total = Counter(
    "cv_credential_borrow_total", "Credential borrows.", labelnames=("module", "result")
)
credential_rewrap_rows_total = Counter("cv_credential_rewrap_rows_total", "DEKs re-wrapped.")
dek_cache_hits_total = Counter("cv_dek_cache_hits_total", "Unwrapped-DEK cache hits.")

"""M2 metrics (e27-kek.md §6, E27-T02 Observability). Labels never carry key material.

Module-level series; the composition root serves them on `/metrics` (wired in the service PR).
"""

from __future__ import annotations

from candleviewer.observability.metrics import Counter, Gauge, Histogram

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
credential_candidate_sign_total = Counter(
    "cv_credential_candidate_sign_total", "Candidate-key signings.", labelnames=("stage", "result")
)
credential_rewrap_rows_total = Counter("cv_credential_rewrap_rows_total", "DEKs re-wrapped.")
dek_cache_hits_total = Counter("cv_dek_cache_hits_total", "Unwrapped-DEK cache hits.")
credential_touch_failures_total = Counter(
    "cv_credential_touch_failures_total", "Best-effort last_used_at writes that failed."
)
kek_degraded_state = Gauge(
    "cv_kek_degraded_state",
    "1 while M2 is latched degraded (KEK unavailable or API key rows stranded), else 0.",
)
process_hardening_failures_total = Counter(
    "cv_process_hardening_failures_total", "SR-009 hardening that did not take effect."
)
credential_outcome_audit_failures_total = Counter(
    "cv_credential_outcome_audit_failures_total", "Failure-outcome audit records that failed."
)

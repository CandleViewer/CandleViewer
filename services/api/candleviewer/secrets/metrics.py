"""Public: serve the M2 series on the scraped registry (composition root via `admin.wiring`)."""

from __future__ import annotations

from candleviewer.observability.metrics import CollectorRegistry, ReexportCollector

EXPORTED_NAMES = frozenset(
    {
        "cv_kek_load_seconds",
        "cv_kek_load_failures_total",
        "cv_kek_version_state",
        "cv_credential_borrow_seconds",
        "cv_credential_borrow_total",
        "cv_credential_rewrap_rows_total",
        "cv_dek_cache_hits_total",
        "cv_credential_touch_failures_total",
        "cv_kek_degraded_state",
        "cv_process_hardening_failures_total",
        "cv_credential_outcome_audit_failures_total",
    }
)


def export_secrets_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve every M2 series on the scraped registry with the `env` label."""
    from candleviewer.secrets import _metrics  # noqa: F401 -- registers the module-level series

    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

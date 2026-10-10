"""CVWB encode metrics (E17-T02 follow-up, docs/plan/20-architecture.md section 12.1).

Module-level series (the encoder is a pure function with no facade); `export_cvwb_metrics()`
serves them on the scraped registry. ``kind`` is the six-name body-kind enum of section 3.4, so
children are pre-bound once and the encoder does two dict-free increments per frame.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)
from candleviewer.ws._generated.cvwb_layout import KINDS

cvwb_frames_encoded_total = Counter(
    "cvwb_frames_encoded_total", "CVWB frames encoded.", labelnames=("kind",)
)
cvwb_bytes_encoded_total = Counter(
    "cvwb_bytes_encoded_total", "CVWB bytes encoded (header + body).", labelnames=("kind",)
)

# -- E17-S01 connection lifecycle (gateway.py); bounded labels only (reason/code enums) --------
cv_ws_clients = Gauge("cv_ws_clients", "Open client WS connections (any lifecycle state).")
cv_ws_handshake_seconds = Histogram(
    "cv_ws_handshake_seconds",
    "Socket accept to first auth_ok.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
cv_ws_auth_failures_total = Counter(
    "cv_ws_auth_failures_total", "Failed WS auth frames, by reason.", labelnames=("reason",)
)
cv_ws_closes_total = Counter(
    "cv_ws_closes_total",
    "Server-initiated WS closes, by close code and bye reason.",
    labelnames=("code", "reason"),
)
cv_ws_clock_skew_ms = Histogram(
    "cv_ws_clock_skew_ms",
    "Absolute client clock skew reported in welcome (milliseconds).",
    buckets=(10, 50, 100, 250, 500, 1000, 2000, 5000, 30000),
)

#: Bounded `cv_ws_auth_failures_total{reason}` values.
AUTH_FAILURE_REASONS: Final = frozenset({"missing_token", "rejected", "user_mismatch"})

#: Every `cv_ws_*` series the ws package owns (module-level, re-exported on the app registry).
CV_WS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "cv_ws_clients",
        "cv_ws_handshake_seconds",
        "cv_ws_auth_failures_total",
        "cv_ws_closes_total",
        "cv_ws_clock_skew_ms",
        "cv_ws_subscribe_total",
        "cv_ws_topics_per_client",
        "cv_ws_revoked_total",
        "cv_ws_upstream_refcount",
        "cv_ws_resync_total",
        "cv_ws_snapshot_bytes",
        "cv_ws_snapshot_build_seconds",
        "cv_ws_sequence_gaps_detected_total",
        "cv_ws_stale_topics",
    }
)

EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {"cvwb_frames_encoded_total", "cvwb_bytes_encoded_total"}
)

#: body_kind -> (frames child, bytes child); fixed at import, never grows.
ENCODED: Final = {
    k: (
        cvwb_frames_encoded_total.labels(kind=v.name),
        cvwb_bytes_encoded_total.labels(kind=v.name),
    )
    for k, v in KINDS.items()
}


def export_ws_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve every `cv_ws_*` series on `registry` (the scraped one) with `env`."""
    # The owning modules declare their series at import; import them so all 14 families exist.
    from candleviewer.ws import permissions, revocation, sequencing, upstream  # noqa: F401

    return ReexportCollector(registry, names=CV_WS_NAMES, const_labels={"env": env})


def export_cvwb_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the CVWB encode series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

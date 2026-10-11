"""Recorder policy metrics (E16-T02), via the observability facade."""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)

recorder_cap_refused_total = Counter(
    "recorder_cap_refused_total",
    "Recording starts refused by CV_RECORDER_MAX_SYMBOLS (queued, retried each tick).",
    ["reason"],
)
recorder_cap_preempted_total = Counter(
    "recorder_cap_preempted_total",
    "Chart-only recordings stopped to make room for an open position.",
)
recorder_b11_error_total = Counter(
    "recorder_b11_error_total",
    "B11 recording machines that entered `error` (retried with backoff).",
    ["env"],
)

# --- Sessions / gaps (E16-T04) ---------------------------------------------------------------
recorder_gaps_total = Counter(
    "recorder_gaps_total", "recording_gaps rows written by cause (E16-T04).", ["cause"]
)
recorder_gap_seconds_total = Counter(
    "recorder_gap_seconds_total", "Seconds of recorded data lost to gaps.", ["symbol"]
)
recorder_sessions_open = Gauge("recorder_sessions_open", "Open recording sessions.")
recorder_integrity_anomalies_total = Counter(
    "recorder_integrity_anomalies_total",
    "Daily integrity-job anomalies (gap = explained, event = unexplainable).",
    ["kind"],
)

# --- StreamWriter (E16-T03) — exported via `export_recorder_metrics` ------------------------
recorder_rows_total = Counter(
    "recorder_rows_total", "Rows written to QuestDB by the recorder.", ["stream"]
)
recorder_bytes_written_total = Counter(
    "recorder_bytes_written_total",
    "ILP bytes written by the recorder.",
    ["symbol", "stream"],
)
recorder_spill_bytes = Gauge("recorder_spill_bytes", "Recorder WAL spill size on disk.")
recorder_write_backlog_rows = Gauge(
    "recorder_write_backlog_rows", "Rows queued in memory, not yet flushed to QuestDB."
)
recorder_flush_duration_seconds = Histogram(
    "recorder_flush_duration_seconds",
    "Time to write + flush one recorder batch.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1.0, 5.0),
)

#: Names served by `export_recorder_metrics`.
EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "recorder_rows_total",
        "recorder_bytes_written_total",
        "recorder_spill_bytes",
        "recorder_write_backlog_rows",
        "recorder_flush_duration_seconds",
    }
)


def export_recorder_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the StreamWriter series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

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

# --- DiskBudget (E16-T07) — names fixed by the ticket's Observability section ---------------
disk_used_ratio = Gauge(
    "disk_used_ratio",
    "Recorded bytes / CV_DISK_CAP_GB (SR-125 disk high-watermark, SR-096 ladder).",
)
disk_free_bytes = Gauge("disk_free_bytes", "Free bytes on the recording volume (statvfs).")
recorder_disk_pressure_level = Gauge(
    "recorder_disk_pressure_level",
    "Disk-pressure ladder level: 0 normal, 1 warn, 2 autostop, 3 halt.",
)
recorder_bytes_per_day = Gauge(
    "recorder_bytes_per_day", "Measured recorded bytes per day per symbol (write rate).", ["symbol"]
)
recorder_projected_full_timestamp = Gauge(
    "recorder_projected_full_timestamp", "Unix time the disk budget is projected full; 0 = none."
)
recorder_disk_budget_last_sample_timestamp_seconds = Gauge(
    "recorder_disk_budget_last_sample_timestamp_seconds",
    "Unix time of the last completed DiskBudget pass (a stale value = a stuck ladder).",
)

#: Names served by `export_recorder_metrics`.
EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "recorder_rows_total",
        "recorder_bytes_written_total",
        "recorder_spill_bytes",
        "recorder_write_backlog_rows",
        "recorder_flush_duration_seconds",
        "disk_used_ratio",
        "disk_free_bytes",
        "recorder_disk_pressure_level",
        "recorder_bytes_per_day",
        "recorder_projected_full_timestamp",
        "recorder_disk_budget_last_sample_timestamp_seconds",
    }
)


def export_recorder_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the StreamWriter series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})


def current_write_backlog_rows() -> int:
    """Live recorder write backlog as last published by the StreamWriter (`_publish_gauges`).

    The archive importer (E16-T10) polls this so live capture always wins; reads the gauge's
    public `collect()` sample, so it needs no reference to the writer instance.
    """
    for metric in recorder_write_backlog_rows.collect():
        for sample in metric.samples:
            return int(sample.value)
    return 0

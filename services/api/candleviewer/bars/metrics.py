"""Bars-module metrics (E12-T03) and their export onto the scraped `/metrics` registry.

Every name is declared `live` in `observability/metrics_catalogue.py` with `exported=True`:
the series are module-level (builders create children on the hot path, so they cannot use
the facade) and `export_bars_metrics()` re-exports them, with the `env` label, from the
library registry onto the app registry. `register_r0()` skips exported names, so nothing is
registered twice.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.kline_boundary_metrics import (  # noqa: F401 - registers it
    kline_hot_boundary_fallback_total,
)
from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)

bar_builder_specs_in_use = Gauge(
    "bar_builder_specs_in_use", "Active bar specs per symbol.", labelnames=("symbol",)
)
bar_builder_fanout_latency_seconds = Histogram(
    "bar_builder_fanout_latency_seconds",
    "Time to fan one trade to every builder of its symbol.",
    buckets=(0.00001, 0.00005, 0.0001, 0.0005, 0.001, 0.005, 0.02),
)
bar_state_snapshots_written_total = Counter(
    "bar_state_snapshots_written_total", "Builder state blobs written."
)
bar_state_write_failed_total = Counter(
    "bar_state_write_failed_total",
    "Builder state blob writes that failed.",
    labelnames=("stage",),
)
bars_blob_discarded_total = Counter(
    "bars_blob_discarded_total",
    "State blobs discarded on restore.",
    labelnames=("reason",),
)
bar_builder_cold_starts_total = Counter(
    "bar_builder_cold_starts_total", "Specs started without a usable state blob."
)
bar_builder_cold_start_seconds = Histogram(
    "bar_builder_cold_start_seconds",
    "Restore + tape replay time before a spec goes live.",
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0),
)
bars_spec_cap_rejected_total = Counter(
    "bars_spec_cap_rejected_total",
    "Spec registrations refused by a cap.",
    labelnames=("reason",),
)
bar_builder_quarantined_total = Counter(
    "bar_builder_quarantined_total",
    "Series removed after their builder raised, or bars tasks that died.",
    labelnames=("reason",),
)
bars_restore_gap_total = Counter(
    "bars_restore_gap_total",
    "Restores whose tape lag exceeded the lane's recent-trade ring (trades missed).",
)
bars_kline_refused_total = Counter(
    "bars_kline_refused_total",
    "Kline rows refused before queueing (reason: precedence_unknown = tape lookup failed).",
    labelnames=("reason",),
)
#: E12-S04 renko builder series (S03's `bar_build_latency_seconds{kind}`, first emitted here).
bar_renko_multi_brick_total = Counter(
    "bar_renko_multi_brick_total",
    "Trades that completed more than one renko brick.",
    labelnames=("symbol",),
)
bar_renko_reversals_total = Counter(
    "bar_renko_reversals_total", "Renko direction reversals.", labelnames=("symbol",)
)
bar_build_latency_seconds = Histogram(
    "bar_build_latency_seconds",
    "Trade-to-bar-update latency inside one builder.",
    labelnames=("kind",),
    buckets=(0.000001, 0.000005, 0.00001, 0.00005, 0.0001, 0.0005, 0.001, 0.01),
)
bar_emit_sink_errors_total = Counter(
    "bar_emit_sink_errors_total",
    "Bar emissions a sink (questdb, series_store, ws) failed to accept, by sink or <sink>_timeout;"
    " ws also counts generation swaps (ws_generation_swap) and binary groups sent structured"
    " (ws_no_scales, ws_binary_refused).",
    labelnames=("reason",),
)
#: The WS series store (E12-T06 D3): failed reads, by the tape tier's degrade reasons
#: (`reader.degrade_reason`); live closes past a gap; series resets, by cause; reads that waited
#: for one of the process-wide read slots (D2-G1, `limits.MAX_CONCURRENT_TAIL_READS`).
bars_series_hydrate_failed_total = Counter(
    "bars_series_hydrate_failed_total",
    "WS series store tail reads that failed (reason: timeout, connection, query_error).",
    labelnames=("reason",),
)
bars_series_gaps_total = Counter(
    "bars_series_gaps_total",
    "Live closes that skipped indexes past a held WS series' newest bar (re-read next).",
)
bars_series_resets_total = Counter(
    "bars_series_resets_total",
    "Held WS series reset (reason: restart = index back in one generation, generation_swap).",
    labelnames=("reason",),
)
bars_series_read_waits_total = Counter(
    "bars_series_read_waits_total",
    "WS series store tail reads that found every read slot taken and waited for one.",
)

# --- E12-T05 (#398) `/market/klines` + `/market/bars` endpoint series -----------------------
#: Allow-listed label values (bounded cardinality; never client text).
ENDPOINT_ROUTES: Final = frozenset({"klines", "bars"})
SOURCE_TIERS: Final = frozenset({"questdb", "parquet", "exchange_rest", "tape"})
PARAM_REJECT_REASONS: Final = frozenset({"invalid", "unsupported", "out_of_range"})

bars_endpoint_rows_returned_total = Counter(
    "bars_endpoint_rows_returned_total",
    "Bars returned by successful pages.",
    labelnames=("endpoint_group",),
)
bars_endpoint_422_no_data_recorded_total = Counter(
    "bars_endpoint_422_no_data_recorded_total",
    "Requests refused because the window predates recording.",
)
bars_endpoint_param_rejected_total = Counter(
    "bars_endpoint_param_rejected_total",
    "bar_type/param pairs refused before any read.",
    labelnames=("reason",),
)
bars_endpoint_source_tier_total = Counter(
    "bars_endpoint_source_tier_total",
    "Responses that served rows from a tier (one per tier per response).",
    labelnames=("endpoint_group", "stream"),
)

bars_tape_read_degraded_total = Counter(
    "bars_tape_read_degraded_total",
    "Tape-tier reads for /market/klines that failed and degraded to klines-only.",
    labelnames=("reason",),
)


def record_page(route: str, rows: int, tiers: list[str]) -> None:
    """Count one served page; unknown label values are dropped, never minted."""
    if route not in ENDPOINT_ROUTES:
        return
    bars_endpoint_rows_returned_total.labels(endpoint_group=route).inc(rows)
    for tier in tiers:
        if tier in SOURCE_TIERS:
            bars_endpoint_source_tier_total.labels(endpoint_group=route, stream=tier).inc()


def record_param_rejected(reason: str) -> None:
    if reason in PARAM_REJECT_REASONS:
        bars_endpoint_param_rejected_total.labels(reason=reason).inc()


#: Names served by `export_bars_metrics` (the S01/S02 builder counters plus the above, and the
#: write and read path series of `bars.writer` / `bars.reader`, #1998).
EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "bars_built_total",
        "bars_amended_total",
        "bars_late_trade_dropped_total",
        "bar_volume_splits_total",
        "bars_partial_series_total",
        "bar_builder_specs_in_use",
        "bar_builder_fanout_latency_seconds",
        "bar_state_snapshots_written_total",
        "bar_state_write_failed_total",
        "bars_blob_discarded_total",
        "bar_builder_cold_starts_total",
        "bar_builder_cold_start_seconds",
        "bars_spec_cap_rejected_total",
        "bar_emit_sink_errors_total",
        "bars_series_hydrate_failed_total",  # the WS series store (E12-T06 D3)
        "bars_series_gaps_total",
        "bars_series_resets_total",
        "bars_series_read_waits_total",
        "bar_builder_quarantined_total",
        "bars_restore_gap_total",
        "bars_kline_refused_total",  # bars.kline_rows (#2053)
        "kline_hot_boundary_fallback_total",  # storage.retention.kline_boundary (#2060)
        "bars_endpoint_rows_returned_total",
        "bars_endpoint_422_no_data_recorded_total",
        "bars_endpoint_param_rejected_total",
        "bars_endpoint_source_tier_total",
        "bars_tape_read_degraded_total",
        "bar_renko_multi_brick_total",
        "bar_renko_reversals_total",
        "bar_build_latency_seconds",
        "bars_rows_written_total",  # bars.writer (E12-T02, #1998)
        "bars_write_queue_depth",
        "bars_write_saturation_total",
        "bars_write_failed_total",
        "bars_write_latency_seconds",
        "bars_symbol_cardinality",
        "bars_source_overwrite_refused_total",  # also counted by bars.kline_rows
        "bars_checksum_mismatch_total",  # bars.reader (E12-T02, #1998)
        "bars_rebuild_scheduled_total",
        "bars_stale_build_version_total",
    }
)


def export_bars_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve every bars series on `registry` (the scraped one) with a consistent `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

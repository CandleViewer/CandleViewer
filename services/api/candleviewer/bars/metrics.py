"""Bars-module metrics (E12-T03) and their export onto the scraped `/metrics` registry.

Every name is declared `live` in `observability/metrics_catalogue.py` with `exported=True`:
the series are module-level (builders create children on the hot path, so they cannot use
the facade) and `export_bars_metrics()` re-exports them, with the `env` label, from the
library registry onto the app registry. `register_r0()` skips exported names, so nothing is
registered twice.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability import pgwire_metrics  # noqa: F401 - registers the PG-wire series
from candleviewer.observability.cold_kline_cache_metrics import (  # noqa: F401 - registers them
    bars_cold_read_duplicate_inflight_total,
    cv_cold_kline_page_cache_bytes,
)
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
    "Bar emissions a sink (questdb, series_store, ws, indicators) failed to accept, by sink"
    " or <sink>_timeout; ws also counts generation swaps (ws_generation_swap) and binary"
    " groups sent structured (ws_no_scales, ws_binary_refused); indicators counts each"
    " instance update that raised.",
    labelnames=("reason",),
)
#: The WS series store (E12-T06 D3): failed reads, by the tape tier's degrade reasons
#: (`reader.degrade_reason`); live closes past a gap; series resets, by cause; reads that waited
#: for one of the process-wide read slots (D2-G1, `limits.MAX_CONCURRENT_TAIL_READS`); reads that
#: found a series gapped and left it so (D2-H2).
bars_series_hydrate_failed_total = Counter(
    "bars_series_hydrate_failed_total",
    "WS series store tail reads that failed (reason: timeout, connection, query_error).",
    labelnames=("reason",),
)
bars_series_gaps_total = Counter(
    "bars_series_gaps_total",
    "Live closes that skipped indexes past a held WS series' newest bar, or from index 0 when it"
    " held none after a clean read of its generation whose window the bar opened in (read again).",
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
bars_series_gap_rereads_total = Counter(
    "bars_series_gap_rereads_total",
    "WS series store tail reads that found a series gapped and left it gapped (its re-read"
    " interval doubles, up to a cap).",
)
#: The heal driver's view (#2787 D2-H1): held series that are not complete, counted at scrape
#: time (`SeriesStore.incomplete_count`); repairs not sent as counted, by reason.
bars_series_incomplete_in_use = Gauge(
    "bars_series_incomplete_in_use",
    "Held WS bars series that are not complete: not hydrated (no clean read of their stored tail)"
    " or gapped (a live close skipped past their newest bar); each is read again when due.",
)
bars_series_repair_failed_total = Counter(
    "bars_series_repair_failed_total",
    "WS series store repairs that did not go out as counted (reason: depth = the repair's depth"
    " could not be counted and went out as 1, extra snaps; hook = the repair hook raised, the"
    " read stands and the series' subscribers keep their snapshot).",
    labelnames=("reason",),
)
#: The heal driver's refreshes (#2787 P4b, `bars.heal_driver`), by result.
bars_heal_refresh_total = Counter(
    "bars_heal_refresh_total",
    "Heal driver refreshes of held WS bars series (result: repaired; unchanged = no repair, a"
    " failed read included; timeout = cut by the driver's bound; error = the refresh raised;"
    " tick_error = a tick raised before any refresh).",
    labelnames=("result",),
)

# --- E12-T05 (#398) `/market/klines` + `/market/bars` endpoint series -----------------------
#: Allow-listed label values (bounded cardinality; never client text).
ENDPOINT_ROUTES: Final = frozenset({"klines", "bars"})
SOURCE_TIERS: Final = frozenset({"questdb", "parquet", "exchange_rest", "tape"})
#: Why a bars/klines request was refused (#452 F4a). The first three are the bar_type/param and
#: interval/price_type refusals; the rest are every other refusal of the two routes.
PARAM_REJECT_REASONS: Final = frozenset(
    {
        "invalid",
        "unsupported",
        "out_of_range",
        "unauthenticated",
        "forbidden",
        "bad_window",
        "invalid_cursor",
        "unknown_symbol",
        "window_too_large",
        "no_data_recorded",
        "unavailable",
    }
)

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
    "bars/klines requests refused, by reason (bounded set).",
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

# --- E12-X01 detection signals (#2294; the threat model's section 10) -----------------------
#: BR-11: prints a builder refused under SR-E12-15, by the builder whose cap it is (a renko
#: print completing, or a volume print closing, more than `MAX_BRICKS_PER_TRADE`).
PRINT_REJECT_REASONS: Final = ("renko", "volume")
bars_print_rejected_total = Counter(
    "bars_print_rejected_total",
    "Prints a bar builder refused (SR-E12-15), by the builder whose per-print cap refused them.",
    labelnames=("reason",),
)
for _reason in PRINT_REJECT_REASONS:  # bound now: each series exists at 0 from import
    bars_print_rejected_total.labels(reason=_reason)
#: BR-14: an OHLC price whose binary64 reads back as another decimal (`rows.to_price_double`).
bars_write_roundtrip_mismatch_total = Counter(
    "bars_write_roundtrip_mismatch_total",
    "Bar prices stored as a DOUBLE that reads back as another decimal (precision lost).",
)
#: BR-15: a `spec_hash` already registered for another spec (`spec.SpecRegistry`).
bars_spec_registry_conflict_total = Counter(
    "bars_spec_registry_conflict_total",
    "Spec registrations whose spec_hash already names another spec (the first is kept).",
)
#: BR-37: builder state blobs (`state_store.StateStore.save`), bytes and the atomic write's time.
bars_snapshot_bytes_total = Counter(
    "bars_snapshot_bytes_total",
    "Bytes of builder state blobs written (one blob per series every 60 s, and on stop).",
)
bars_snapshot_write_seconds = Histogram(
    "bars_snapshot_write_seconds",
    "Wall time of one builder state blob write (write, fsync, rename).",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
#: BR-38: bars snapshots built (`ws.bars_source`), by the bucket of the `history` asked for
#: (0..1000, 23 section 6.1): four values, never the raw count.
HISTORY_BUCKETS: Final = ("0", "1-100", "101-500", "501-1000")
bars_subscribe_snapshot_total = Counter(
    "bars_subscribe_snapshot_total",
    "Bars snapshots built (a subscribe's first, a resync's, a repair's), by the bucket of the"
    " history asked for (0, 1-100, 101-500, 501-1000).",
    labelnames=("history",),
)
for _bucket in HISTORY_BUCKETS:
    bars_subscribe_snapshot_total.labels(history=_bucket)
#: BR-13: a client `resync` with `sequence_gap` on a `bars` topic (`ws.sequencing`).
ws_bars_seq_gap_total = Counter(
    "ws_bars_seq_gap_total",
    "Client-reported sequence gaps (resync reason sequence_gap) on bars topics.",
)


def history_bucket(history: int) -> str:
    """The `HISTORY_BUCKETS` value of a validated `history` (0..1000; a larger one is the top)."""
    if history <= 0:
        return "0"
    if history <= 100:
        return "1-100"
    return "101-500" if history <= 500 else "501-1000"


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
        "bars_series_gap_rereads_total",
        "bars_series_incomplete_in_use",
        "bars_series_repair_failed_total",
        "bars_heal_refresh_total",  # bars.heal_driver (#2787 P4b)
        "bar_builder_quarantined_total",
        "bars_restore_gap_total",
        "bars_kline_refused_total",  # bars.kline_rows (#2053)
        "kline_hot_boundary_fallback_total",  # storage.retention.kline_boundary (#2060)
        "cv_cold_kline_page_cache_hits_total",  # storage.cold.kline_reader (#2523 lever 5)
        "cv_cold_kline_page_cache_misses_total",
        "cv_cold_kline_page_cache_evictions_total",
        "cv_cold_kline_page_cache_bytes",
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
        "bars_tail_scan_bounded_total",  # its table-row bound (#2787 D2-M4)
        # The E12-X01 detection signals (#2294).
        "bars_print_rejected_total",
        "bars_write_roundtrip_mismatch_total",
        "bars_spec_registry_conflict_total",
        "bars_snapshot_bytes_total",
        "bars_snapshot_write_seconds",
        "bars_subscribe_snapshot_total",
        "ws_bars_seq_gap_total",
        "bars_cold_read_duplicate_inflight_total",  # storage.cold.kline_reader
        # Every `LazyPgWire`'s, the bars sink's and the store's among them (#2787 D2-G2).
        "questdb_pgwire_discards_total",
        "questdb_pgwire_abandoned_total",
        "questdb_pgwire_lock_wait_seconds",
    }
)


def export_bars_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve every bars series on `registry` (the scraped one) with a consistent `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

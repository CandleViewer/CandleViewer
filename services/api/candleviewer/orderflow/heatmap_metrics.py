"""DOM heatmap metrics (E21-T02, #605; 20-architecture §12.1; 24 §6.3, §6.5).

Every name is declared `live` in `observability/metrics_catalogue.py` with `exported=True`: the
series are module-level, bound at import to their closed label sets where they have one, and
`export_heatmap_metrics()` serves them, with the `env` label, on the scraped registry.

- `heatmap_missing_columns_total{symbol}`: native 100 ms columns whose deadline the engine missed
  (a stall: the column reads `samples = 0`, 24 §6.3); `symbol` is bounded by `symbol_label`;
- `heatmap_columns_emitted_total{state}`: columns published per spec, `state` `live` or
  `estimated` (built while the book was resyncing, 24 §6.3);
- `heatmap_column_publish_latency_ms`: a bucket's end to its column's publish, ms (budget #6);
- `heatmap_subscriptions_active`: live leases held on heatmap specs;
- `heatmap_cell_faults_total`: sizes that are negative or not finite, never written (24 §6.5);
- `heatmap_pinned_symbols`: symbols whose native column is kept without a lease (E21-T04, the
  liquidity tracker's configured symbols; at most `liquidity_pin_max`);
- E21-T03 (#606), `GET /market/heatmap`: `heatmap_backfill_requests_total{tier}` (served
  pages by each segment source, `none` for no recorded history), `heatmap_backfill_duration_ms`,
  `heatmap_backfill_clamped_total` (pages served at a coarser bucket) and
  `heatmap_reconstruct_unverified_total` (snapshots rebuilt from with no stored checksum, BQ-4).
"""

from __future__ import annotations

from typing import Final, Literal, get_args

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)
from candleviewer.orderflow.funding_metrics import symbol_label

State = Literal["live", "estimated"]
BackfillSource = Literal["hot", "cold", "reconstructed", "downsampled", "none"]

STATES: Final[tuple[State, ...]] = ("live", "estimated")
#: Around budget #6's 20 ms and the 100 ms native column (as the book's `_ms` histograms).
LATENCY_BUCKETS: Final = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 50.0, 100.0, 250.0, 1000.0)
BACKFILL_SOURCES: Final[tuple[BackfillSource, ...]] = get_args(BackfillSource)
#: A recorded read, 10 ms to its 30 s deadline (budgets #1 and #14, 06).
BACKFILL_BUCKETS: Final = (10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 30000.0)

heatmap_missing_columns_total = Counter(
    "heatmap_missing_columns_total",
    "Native 100 ms heatmap columns whose deadline the engine missed (a stall; samples=0).",
    labelnames=("symbol",),
)
heatmap_columns_emitted_total = Counter(
    "heatmap_columns_emitted_total",
    "Heatmap columns published per spec, by state: live, or estimated (the book was resyncing).",
    labelnames=("state",),
)
heatmap_column_publish_latency_ms = Histogram(
    "heatmap_column_publish_latency_ms",
    "A heatmap bucket's end to the publish of its column, ms.",
    buckets=LATENCY_BUCKETS,
)
heatmap_subscriptions_active = Gauge(
    "heatmap_subscriptions_active", "Live heatmap WS subscriptions holding a spec lease."
)
heatmap_pinned_symbols = Gauge(
    "heatmap_pinned_symbols",
    "Symbols whose native heatmap column is kept without a lease (the liquidity tracker's).",
)
heatmap_cell_faults_total = Counter(
    "heatmap_cell_faults_total",
    "Heatmap sizes that were negative or not finite: a producer fault, never written.",
)

heatmap_backfill_requests_total = Counter(
    "heatmap_backfill_requests_total",
    "Recorded heatmap pages served, by each segment source (none: no recorded history).",
    labelnames=("tier",),
)
heatmap_backfill_duration_ms = Histogram(
    "heatmap_backfill_duration_ms",
    "A recorded heatmap page's read and build, ms.",
    buckets=BACKFILL_BUCKETS,
)
heatmap_backfill_clamped_total = Counter(
    "heatmap_backfill_clamped_total",
    "Recorded heatmap pages served at a coarser bucket than asked (the column cap).",
)
heatmap_reconstruct_unverified_total = Counter(
    "heatmap_reconstruct_unverified_total",
    "Recorded book snapshots a heatmap was rebuilt from with no stored checksum (estimated).",
)

#: The bound children, one per closed label value (no other value is ever minted).
EMITTED: Final = {s: heatmap_columns_emitted_total.labels(state=s) for s in STATES}
BACKFILLS: Final = {s: heatmap_backfill_requests_total.labels(tier=s) for s in BACKFILL_SOURCES}


def missing(symbol: str, n: int = 1) -> None:
    """Count `n` missed native deadlines of `symbol` (bounded label)."""
    heatmap_missing_columns_total.labels(symbol=symbol_label(symbol)).inc(n)


#: Names served by `export_heatmap_metrics`.
EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "heatmap_missing_columns_total",
        "heatmap_columns_emitted_total",
        "heatmap_column_publish_latency_ms",
        "heatmap_subscriptions_active",
        "heatmap_cell_faults_total",
        "heatmap_pinned_symbols",
        "heatmap_backfill_requests_total",
        "heatmap_backfill_duration_ms",
        "heatmap_backfill_clamped_total",
        "heatmap_reconstruct_unverified_total",
    }
)


def export_heatmap_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the heatmap series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

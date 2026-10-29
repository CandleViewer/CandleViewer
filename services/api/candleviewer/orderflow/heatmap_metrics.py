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
- `heatmap_cell_faults_total`: sizes that are negative or not finite, never written (24 §6.5).
"""

from __future__ import annotations

from typing import Final, Literal

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)
from candleviewer.orderflow.funding_metrics import symbol_label

State = Literal["live", "estimated"]

STATES: Final[tuple[State, ...]] = ("live", "estimated")
#: Around budget #6's 20 ms and the 100 ms native column (as the book's `_ms` histograms).
LATENCY_BUCKETS: Final = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 50.0, 100.0, 250.0, 1000.0)

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
heatmap_cell_faults_total = Counter(
    "heatmap_cell_faults_total",
    "Heatmap sizes that were negative or not finite: a producer fault, never written.",
)

#: The bound children, one per closed label value (no other value is ever minted).
EMITTED: Final = {s: heatmap_columns_emitted_total.labels(state=s) for s in STATES}


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
    }
)


def export_heatmap_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the heatmap series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

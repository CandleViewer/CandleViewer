"""LiquidityTracker metrics (E21-T04, #710; 24 §2.11).

Every name is declared `live` in `observability/metrics_catalogue.py` with `exported=True`;
`export_liquidity_metrics()` serves them, with the `env` label, on the scraped registry.
`symbol` is bounded by the funding `symbol_label` (well-formed and the first 64, else `other`);
`reason` is a closed enum. No trade id or user data in a label.

- `liquidity_reload_events_total{symbol}`, `liquidity_pulled_events_total{symbol}`: events
  published on `{env}.md.{symbol}.liquidity`;
- `liquidity_events_overflow_total{symbol,reason}`: events never published, counted (C-2.18):
  `sample_cap` past `max_events` in one sample, `publish_queue` shed from the full outbound queue
  or past the publish timeout;
- `liquidity_tracker_memory_bytes{symbol}`: the tracker's preallocated ring (24 §2.11 bound);
- `liquidity_band_compute_ms`: one sample's work (quantise, bands, ring, detection), ms.
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

__all__ = [
    "EXPORTED_NAMES",
    "OverflowReason",
    "export_liquidity_metrics",
    "liquidity_band_compute_ms",
    "liquidity_events_overflow_total",
    "liquidity_pulled_events_total",
    "liquidity_reload_events_total",
    "liquidity_tracker_memory_bytes",
    "symbol_label",
]

OverflowReason = Literal["sample_cap", "publish_queue"]
#: Around the 2 ms per-sample budget (ticket) and the 100 ms native cadence.
COMPUTE_BUCKETS: Final = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0)

liquidity_reload_events_total = Counter(
    "liquidity_reload_events_total",
    "LiquidityReload events published (estimated: L2-only inference).",
    labelnames=("symbol",),
)
liquidity_pulled_events_total = Counter(
    "liquidity_pulled_events_total",
    "LiquidityPulled events published (estimated: L2-only inference).",
    labelnames=("symbol",),
)
liquidity_events_overflow_total = Counter(
    "liquidity_events_overflow_total",
    "Liquidity events never published, by reason: sample_cap or publish_queue (C-2.18).",
    labelnames=("symbol", "reason"),
)
liquidity_tracker_memory_bytes = Gauge(
    "liquidity_tracker_memory_bytes",
    "Bytes of a liquidity tracker's preallocated ring.",
    labelnames=("symbol",),
)
liquidity_band_compute_ms = Histogram(
    "liquidity_band_compute_ms",
    "One liquidity sample's work (quantise, bands, ring, detection), ms.",
    buckets=COMPUTE_BUCKETS,
)

#: Names served by `export_liquidity_metrics`.
EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "liquidity_reload_events_total",
        "liquidity_pulled_events_total",
        "liquidity_events_overflow_total",
        "liquidity_tracker_memory_bytes",
        "liquidity_band_compute_ms",
    }
)


def export_liquidity_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the liquidity series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

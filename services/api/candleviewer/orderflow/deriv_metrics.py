"""Derivatives-history metrics (E24-T01 #665, E24-T03 #667; ticket *Observability*).

Labels are bounded: `symbol` goes through `funding_metrics.symbol_label` (validated, capped),
`interval`, `source` and `result` are closed enums. `deriv_range_rejected_total` and
`deriv_upstream_schema_rejected_total` live in `funding_metrics` and are reused, never redeclared.
"""

from __future__ import annotations

from candleviewer.observability.metrics import Counter, Gauge, Histogram

deriv_oi_backfill_pages_total = Counter(
    "deriv_oi_backfill_pages_total",
    "Open-interest history pages fetched by the backfill, by symbol, interval and result.",
    ["symbol", "interval", "result"],
)
deriv_oi_backfill_latency_seconds = Histogram(
    "deriv_oi_backfill_latency_seconds",
    "Wall time of one open-interest backfill job, retries included.",
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
deriv_oi_rows_written_total = Counter(
    "deriv_oi_rows_written_total",
    "Open-interest rows handed to the store, by source (ws_ticker | rest).",
    ["source"],
)
deriv_liquidation_prints_total = Counter(
    "deriv_liquidation_prints_total",
    "Liquidation prints ingested from allLiquidation, by liquidated side (long | short).",
    ["side"],
)
deriv_liquidation_notional_total = Counter(
    "deriv_liquidation_notional_total",
    "Liquidated notional (USD) ingested, by liquidated side.",
    ["side"],
)
deriv_liquidation_burst_rate = Gauge(
    "deriv_liquidation_burst_rate",
    "Liquidation prints per second over the last ingest window.",
)
deriv_liquidation_ingest_lag_seconds = Gauge(
    "deriv_liquidation_ingest_lag_seconds",
    "Ingest time minus exchange time of the last liquidation print.",
)
deriv_liquidation_socket_reconnects_total = Counter(
    "deriv_liquidation_socket_reconnects_total",
    "Resubscriptions of the allLiquidation stream after a drop.",
)
deriv_sub_cap_rejected_total = Counter(
    "deriv_sub_cap_rejected_total",
    "WS derivatives subscriptions refused at the 40-symbol cap.",
)

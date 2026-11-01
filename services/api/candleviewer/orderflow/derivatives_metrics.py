"""Derivatives engine metrics (E24-T04 Observability). Labels are closed enums: `metric` is a
metric family (`open_interest`, `funding`, `basis`, `liquidation_notional`), `reason` why a
bar's OI delta / quadrant is None (`no_oi_sample`, `stale_oi_open`, `flat`). No symbol, no
values, no user data. A closed bar with a None case counts once, so missing OI is visible in
Grafana rather than only on screen."""

from __future__ import annotations

from candleviewer.observability.metrics import Counter, Histogram

__all__ = ["deriv_engine_compute_seconds", "deriv_engine_none_bars_total"]

deriv_engine_compute_seconds = Histogram(
    "deriv_engine_compute_seconds",
    "Derivatives engine compute time per metric family and batch (incremental or full).",
    ["metric"],
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25),  # budgets 5 / 50 ms
)
deriv_engine_none_bars_total = Counter(
    "deriv_engine_none_bars_total",
    "Closed bars whose open_interest_delta / oi_price_quadrant is None, by reason.",
    ["reason"],
)

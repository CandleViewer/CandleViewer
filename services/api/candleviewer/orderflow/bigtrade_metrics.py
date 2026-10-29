"""Big-trade engine metrics (E22-T01 Observability). `symbol` labels reuse the bounded
`symbol_label` of `funding_metrics` (well-formed + capped, else `other`); `mode` is a closed
enum. No trade ids or user data in labels."""

from __future__ import annotations

from candleviewer.observability.metrics import Counter, Histogram
from candleviewer.orderflow.funding_metrics import symbol_label

__all__ = [
    "bigtrade_clusters_emitted_total",
    "bigtrade_eval_latency_seconds",
    "bigtrade_flagged_total",
    "bigtrade_input_rejected_total",
    "bigtrade_prints_evaluated_total",
    "bigtrade_range_rejected_total",
    "bigtrade_replay_mismatch_total",
    "bigtrade_state_truncated_total",
    "bigtrade_threshold_advisory_total",
    "symbol_label",
]

bigtrade_prints_evaluated_total = Counter(
    "bigtrade_prints_evaluated_total", "Prints evaluated by the big-trade engine.", ["symbol"]
)
bigtrade_flagged_total = Counter(
    "bigtrade_flagged_total", "Prints flagged as big trades, by mode.", ["symbol", "mode"]
)
bigtrade_clusters_emitted_total = Counter(
    "bigtrade_clusters_emitted_total", "Trade clusters emitted.", ["symbol"]
)
bigtrade_eval_latency_seconds = Histogram(
    "bigtrade_eval_latency_seconds", "Per-batch big-trade evaluation latency."
)
bigtrade_state_truncated_total = Counter(
    "bigtrade_state_truncated_total",
    "Cluster/buffer state evicted at the SR-E22-05 caps (never silent).",
    ["symbol"],
)
bigtrade_threshold_advisory_total = Counter(
    "bigtrade_threshold_advisory_total", "threshold_too_low advisories emitted.", ["symbol"]
)
bigtrade_input_rejected_total = Counter(
    "bigtrade_input_rejected_total",
    "Engine inputs rejected by the SR-E22-13 assert (non-positive or off-tick).",
    ["symbol"],
)
bigtrade_replay_mismatch_total = Counter(
    "bigtrade_replay_mismatch_total",
    "Replay determinism defects: recomputed threshold/advisory differs from the recording.",
    ["symbol"],
)
bigtrade_range_rejected_total = Counter(
    "bigtrade_range_rejected_total",
    "Trade-tape reads refused by an SR-E22-01..03 bound before any read, by endpoint (E22-T02).",
    ["endpoint"],
)

"""Prometheus metrics for the `exchange.bybit` REST client (E08-T02).

Names, labels and help text are **declared** in the ingestion metric
registry (`candleviewer/ingestion/metrics.py` `SPECS`, E08-T06); this module
only instantiates them because `exchange.bybit` may not import `ingestion`
(`.importlinter` M4). `tests/unit/ingestion/test_metric_registry.py` fails if
anything here drifts from its declaration.

`bybit_rate_limit_remaining` is labelled by `scope` (`public|account`), never
by UID: a UID is an account identifier and must not reach a label (E08-T06
security note). `exchange_errors_total` stays owned by `exchange/base/boundary.py`.
"""

from __future__ import annotations

from candleviewer.observability.metrics import Counter, Gauge, Histogram

bybit_rest_requests_total = Counter(
    "bybit_rest_requests_total",
    "Adapter REST requests, by endpoint and result.",
    ["endpoint", "result"],
)

bybit_rest_latency_seconds = Histogram(
    "bybit_rest_latency_seconds",
    "Adapter REST latency, by endpoint.",
    ["endpoint"],
)

bybit_rate_limit_remaining = Gauge(
    "bybit_rate_limit_remaining",
    "Last-observed remaining rate-limit budget (scope public|account, never a UID).",
    ["scope", "endpoint_class"],
)

bybit_ip_hold_remaining_seconds = Gauge(
    "bybit_ip_hold_remaining_seconds",
    "Seconds left on the IP-wide REST hold after a 10018 (0 when none; no UID label).",
)

bybit_rate_limited_total = Counter(
    "bybit_rate_limited_total",
    "Rate-limited responses, by code.",
    ["code"],
)

bybit_rows_refused_total = Counter(
    "bybit_rows_refused_total",
    "Trading-read rows set aside, by reason (env, account, no fill, unmapped type, not USDT).",
    ["reason"],
)

cv_bybit_unknown_fields_total = Counter(
    "cv_bybit_unknown_fields_total",
    "Reply fields the adapter's strict models do not know, by model (silent drift).",
    ["model"],
)

# G-8b (#3963): the private stream's series (24 §14.2 rule 13). `topic` is a closed set of topic
# names (`order`, `execution`, `execution.fast`, `position`, `wallet`; a subscribe op's topics
# joined by `+`), never a symbol, an id or an account (ruling 7).
bybit_private_rows_refused_total = Counter(
    "bybit_private_rows_refused_total",
    "Private-stream rows dropped, by topic and reason (other env or account, category, symbol, "
    "account type, no settle coin, no fill, unmapped type).",
    ["topic", "reason"],
)

bybit_private_frames_rejected_total = Counter(
    "bybit_private_frames_rejected_total",
    "Private-stream frames rejected whole, by reason (a resync follows; oversize recycles).",
    ["reason"],
)

bybit_private_ws_auth_total = Counter(
    "bybit_private_ws_auth_total",
    "Private-stream auth attempts, by result.",
    ["result"],
)

bybit_private_ws_disconnects_total = Counter(
    "bybit_private_ws_disconnects_total",
    "Private-stream sockets lost or streams closed, by the down or closed status reason.",
    ["reason"],
)

bybit_private_subscribe_refused_total = Counter(
    "bybit_private_subscribe_refused_total",
    "Private-stream subscribe ops refused or unanswered, by the op's topics.",
    ["topic"],
)

bybit_private_reconnect_waited_total = Counter(
    "bybit_private_reconnect_waited_total",
    "Private-stream dials that waited for the consumer to read the last down status.",
)

bybit_private_ws_streams = Gauge(
    "bybit_private_ws_streams",
    "Private streams open now (no account label).",
)

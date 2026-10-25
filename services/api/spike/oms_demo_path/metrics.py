"""The run's metrics, under the production names (#843 Observability; brief item 5).

`order_submit_seconds{transport="rest"}` is registered from its catalogue entry (histogram,
`SUBMIT_BUCKETS`; planned, E29, so `register_r0` does not register it) and observes each
create's call-to-ack latency at the port, our overhead included, as the OMS will measure it: there
is no UI click here. `bybit_clock_drift_ms` (planned, E08) carries the measured offset, exchange
minus host. The adapter's own series are re-exported as cv-api serves them
(`export_ingestion_metrics`). What the catalogue has no name for is `spike_`-prefixed: the venue
RTT and our overhead per call class, the private stream's latency per kind, the parity and
ordering counts and the cycle outcomes. No label holds an identifier (`DISALLOWED_LABEL_NAMES`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from candleviewer.ingestion.metrics import export_ingestion_metrics
from candleviewer.observability.metrics import Metrics, generate_latest
from candleviewer.observability.metrics_catalogue import CATALOGUE, SUBMIT_BUCKETS
from spike.oms_demo_path.measure import StreamMonitor, Timings

OVERHEAD_BUCKETS: Final = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
PRIVATE_BUCKETS: Final = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


def _spec_named(name: str) -> tuple[str, tuple[str, ...], tuple[float, ...] | None, int]:
    spec = next(s for s in CATALOGUE if s.name == name)
    return spec.help, spec.labels, spec.buckets, spec.max_series


def export(
    timings: Timings,
    monitor: StreamMonitor,
    outcomes: Mapping[str, int],
    offset_ms: int | None,
) -> str:
    """The run's Prometheus exposition, filled from what was measured."""
    metrics = Metrics("demo")
    help_text, labels, buckets, max_series = _spec_named("order_submit_seconds")
    submit = metrics.histogram(
        "order_submit_seconds",
        help_text,
        labels,
        buckets=buckets or SUBMIT_BUCKETS,
        max_series=max_series,
    )
    for ms in timings.port_ms.get("create", []):
        submit.labels("rest").observe(ms / 1000)
    drift_help, drift_labels, _, _ = _spec_named("bybit_clock_drift_ms")
    drift = metrics.gauge("bybit_clock_drift_ms", drift_help, drift_labels)
    if offset_ms is not None:
        drift.child().set(offset_ms)
    rtt = metrics.histogram(
        "spike_rest_rtt_seconds",
        "Venue round trip at the rest_transport seam, by call class (E29-K01).",
        ("call",),
        buckets=SUBMIT_BUCKETS,
    )
    for name, values in timings.rtt_ms.items():
        for ms in values:
            rtt.labels(name).observe(ms / 1000)
    overhead = metrics.histogram(
        "spike_backend_overhead_seconds",
        "Port latency minus the venue round trips of its call, by call class (E29-K01).",
        ("call",),
        buckets=OVERHEAD_BUCKETS,
    )
    for name, values in timings.overhead_ms.items():
        for ms in values:
            overhead.labels(name).observe(ms / 1000)
    private = metrics.histogram(
        "spike_private_latency_seconds",
        "Venue time to local receipt, offset-corrected, by private event kind (E29-K01).",
        ("kind",),
        buckets=PRIVATE_BUCKETS,
    )
    for kind, values in monitor.latency_ms.items():
        for ms in values:
            private.labels(kind).observe(max(ms, 0.0) / 1000)
    seen = metrics.gauge(
        "spike_executions", "Executions by where they were seen (E29-K01 parity).", ("seen",)
    )
    for name, count in monitor.parity().items():
        seen.labels(name).set(count)
    metrics.gauge(
        "spike_execution_after_order",
        "Executions that arrived after the order transition they caused (23 S5).",
    ).child().set(monitor.after_order)
    cycles = metrics.gauge("spike_cycle_outcomes", "Cycles by outcome (E29-K01).", ("outcome",))
    for outcome, count in outcomes.items():
        cycles.labels(outcome).set(count)
    export_ingestion_metrics(metrics.registry, env="demo", exchange="bybit")
    return generate_latest(metrics.registry).decode()

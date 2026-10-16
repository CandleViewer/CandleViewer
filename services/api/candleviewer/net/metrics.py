"""Prometheus gauge for the mesh-guard boot self-check."""

from __future__ import annotations

from candleviewer.observability.metrics import CollectorRegistry, Gauge, ReexportCollector

net_binding_safe = Gauge(
    "net_binding_safe",
    "1 if the process's actual listening sockets are all loopback/mesh-only, 0 if a "
    "public wildcard bind (0.0.0.0 / ::) was detected. Set by the mesh-guard self-check.",
)

#: Series re-exported onto the scraped app registry (#2496): the gauge is module-level, so it
#: lands on the library default registry, which no `/metrics` endpoint serves.
NET_EXPORTED_NAMES: frozenset[str] = frozenset({"net_binding_safe"})


def export_net_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve `net_binding_safe` on `registry` (the scraped one) with `env`, so the
    `NetBindingUnsafe` page can read it."""
    return ReexportCollector(registry, names=NET_EXPORTED_NAMES, const_labels={"env": env})

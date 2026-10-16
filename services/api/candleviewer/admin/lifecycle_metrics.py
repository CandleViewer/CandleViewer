"""User lifecycle metrics (E42-T04 S4, #965 Observability, R7), via the facade. Served with `env`
by `export_user_lifecycle_metrics` once slice S6 wires the route; label values are closed sets
fixed in `admin/user_disable.py`."""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import CollectorRegistry, Counter, ReexportCollector

user_lifecycle_total = Counter(
    "cv_user_lifecycle_total",
    "User lifecycle calls by action and result (refusals and failures included).",
    ["action", "result"],
)
user_lifecycle_steps_total = Counter(
    "cv_user_lifecycle_steps_total",
    "User lifecycle cascade steps after the transaction, by outcome (R7).",
    ["step", "outcome"],
)

EXPORTED_NAMES: Final = frozenset({"cv_user_lifecycle_total", "cv_user_lifecycle_steps_total"})


def export_user_lifecycle_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the lifecycle series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

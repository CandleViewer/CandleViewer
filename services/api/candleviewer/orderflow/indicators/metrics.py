"""Indicator engine metrics (E13-T02, #426; 20-architecture §12.1; E13 threat model §10).

Every name is declared `live` in `observability/metrics_catalogue.py` with `exported=True`: the
series are module-level, bound at import to their closed label sets, and
`export_indicator_metrics()` serves them, with the `env` label, on the scraped registry. No label
holds a user id (IR-21): `indicator_subscriptions` counts users by how many instances they hold.

- `indicator` is a server kernel id (`kernels.KERNELS`, 10) and `where` is `server`;
- `reason` (recomputes) is `amended`, `param_change` or `backfill`;
- `bucket` is `1`, `2-4`, `5-7` or `8` (instances held; 8 is the SR-E13-03 per-user cap);
- `cap` is `user`, `symbol` or `process` (SR-E13-03), `window` or `recompute` (SR-E13-04).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final, Literal

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)
from candleviewer.observability.metrics_catalogue import INDICATOR_COMPUTE_BUCKETS
from candleviewer.orderflow.indicators.kernels import KERNELS

RecomputeReason = Literal["amended", "param_change", "backfill"]
Cap = Literal["user", "symbol", "process", "window", "recompute"]

RECOMPUTE_REASONS: Final[tuple[RecomputeReason, ...]] = ("amended", "param_change", "backfill")
CAPS: Final[tuple[Cap, ...]] = ("user", "symbol", "process", "window", "recompute")
#: Users by instances held: the label each count falls in (8 or more is the cap's bucket).
BUCKETS: Final = ("1", "2-4", "5-7", "8")

indicator_compute_seconds = Histogram(
    "indicator_compute_seconds",
    "Indicator kernel time per instance: one closed-bar update, or one full recompute, by "
    "indicator and where it ran (server: the backend kernel).",
    labelnames=("indicator", "where"),
    buckets=INDICATOR_COMPUTE_BUCKETS,
)
indicator_cache_hits_total = Counter(
    "indicator_cache_hits_total",
    "Indicator reads served by an instance already running for that symbol and spec_hash "
    "(memoised, 24 section 7.3).",
)
indicator_cache_misses_total = Counter(
    "indicator_cache_misses_total",
    "Indicator reads that had to start an instance: none ran for that symbol and spec_hash.",
)
indicator_recompute_total = Counter(
    "indicator_recompute_total",
    "Indicator series recomputed from an earlier bar: amended (a late trade changed a "
    "closed bar), param_change, or backfill (re-primed from stored bars).",
    labelnames=("reason",),
)
indicator_subscriptions = Gauge(
    "indicator_subscriptions",
    "Users holding server indicator instances, by how many they hold: 1, 2-4, 5-7 or 8 (the "
    "SR-E13-03 per-user cap). Never a user id (IR-21).",
    labelnames=("bucket",),
)
indicator_cap_rejected_total = Counter(
    "indicator_cap_rejected_total",
    "Server indicator requests refused by a cap: user, symbol or process instances "
    "(SR-E13-03), the window or the recompute slots (SR-E13-04).",
    labelnames=("cap",),
)

#: The bound children, one per closed label value (no other value is ever minted).
COMPUTE: Final = {k: indicator_compute_seconds.labels(indicator=k, where="server") for k in KERNELS}
RECOMPUTES: Final = {r: indicator_recompute_total.labels(reason=r) for r in RECOMPUTE_REASONS}
CAP_REJECTED: Final = {c: indicator_cap_rejected_total.labels(cap=c) for c in CAPS}
SUBSCRIPTIONS: Final = {b: indicator_subscriptions.labels(bucket=b) for b in BUCKETS}


def bucket_of(held: int) -> str:
    """The `indicator_subscriptions` bucket of a user holding `held` (at least 1) instances."""
    if held >= 8:
        return "8"
    if held >= 5:
        return "5-7"
    return "2-4" if held >= 2 else "1"


def set_subscriptions(held_per_user: Iterable[int]) -> None:
    """Set the four buckets from the instances each user holds (users holding none are left out)."""
    counts = dict.fromkeys(BUCKETS, 0)
    for held in held_per_user:
        if held > 0:
            counts[bucket_of(held)] += 1
    for name, gauge in SUBSCRIPTIONS.items():
        gauge.set(counts[name])


#: Names served by `export_indicator_metrics`.
EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "indicator_compute_seconds",
        "indicator_cache_hits_total",
        "indicator_cache_misses_total",
        "indicator_recompute_total",
        "indicator_subscriptions",
        "indicator_cap_rejected_total",
    }
)


def export_indicator_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the indicator series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

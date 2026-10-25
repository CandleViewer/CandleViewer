"""Replay read-path (E26-T02), playback (E26-T03) and loop-budget (#2668) metrics, served on
the scraped registry.

The series are defined beside the code that updates them (`replay.merge`, `replay.source`,
`replay.clock`, `replay.budget`) and register on the library's default registry;
`export_replay_metrics` serves them on the app's scraped registry with the `env` label, as every
other module's exported series are. The retention guard's counter is defined here and updated by
`retention_wiring`, so the exporter serves it whether or not the retention wiring was imported
first (#4468).
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import CollectorRegistry, Counter, ReexportCollector

#: The replay retention guard's failed reads, by site (#2674 G7); `retention_wiring` binds the
#: four sites and counts them. Defined here so the exporter never depends on import order.
replay_retention_guard_errors_total = Counter(
    "replay_retention_guard_errors_total",
    "Replay retention guard reads that failed; the partition was kept this pass.",
    ["where"],
)

#: Names served by `export_replay_metrics`.
EXPORTED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "replay_events_read_total",
        "replay_gap_warnings_total",
        "replay_source_read_seconds",
        "replay_readahead_depth",
        "replay_clock_lag_ms",
        "replay_events_emitted_total",
        "replay_backpressure_seconds_total",
        "replay_achieved_speed_ratio",
        "replay_loop_seconds_total",
        "replay_budget_held_seconds_total",
        "replay_budget_waiters",
        "replay_loop_share_ratio",
        "replay_retention_guard_errors_total",
    }
)


def export_replay_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the replay series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

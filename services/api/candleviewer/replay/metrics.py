"""Replay read-path (E26-T02) and playback (E26-T03) metrics, served on the scraped registry.

The series are defined beside the code that updates them (`replay.merge`, `replay.source`,
`replay.clock`) and register on the library's default registry; `export_replay_metrics` serves
them on the app's scraped registry with the `env` label, as every other module's exported series
are.
"""

from __future__ import annotations

from typing import Final

from candleviewer.observability.metrics import CollectorRegistry, ReexportCollector

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
    }
)


def export_replay_metrics(registry: CollectorRegistry, *, env: str) -> ReexportCollector:
    """Serve the replay series on `registry` (the scraped one) with `env`."""
    return ReexportCollector(registry, names=EXPORTED_NAMES, const_labels={"env": env})

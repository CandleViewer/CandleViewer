"""candleviewer.statechart.plugins — the observability plugin set (E50-T60).

Every `build()` (and, once E50-T49 lands, every restore via
`from_snapshot(plugins=...)`) attaches `[CvErrorHooks(), CvMetricsPlugin(),
CvAuditPlugin()]` (28-statechart-catalogue.md §1.3c). `CvStateFeedPlugin` (E17-T08) is not one of
the three: the module that feeds `machines.{entity}.state` attaches it beside them (`feed_plugins`).

The plugins are *duck-typed*: CV-LINT-IMPORT allows only `factory.py` and
`persistence.py` to import the runtime, and the library's `_SafePlugin`
wrapper resolves hooks by name. Every hook also catches its own exceptions
(log + count) so it can never raise into the interpreter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.statechart.plugins._base import LogPager, Pager
from candleviewer.statechart.plugins.audit import (
    CvAuditPlugin,
    InMemoryMachineEventSink,
    MachineEventRow,
    MachineEventSink,
)
from candleviewer.statechart.plugins.errors import CvErrorHooks
from candleviewer.statechart.plugins.metrics import CvMetricsPlugin
from candleviewer.statechart.plugins.state_feed import (
    CvStateFeedPlugin,
    FeedBinding,
    MachineStateHandle,
    MachineStatePort,
    feed_plugins,
)

if TYPE_CHECKING:
    from candleviewer.observability.metrics import Metrics
    from candleviewer.statechart.config import Lane


def cv_plugins(
    *,
    machine_kind: str,
    lane: Lane,
    entity_id: str,
    env: str,
    metrics: Metrics,
    sink: MachineEventSink,
    pager: Pager | None = None,
    write_ahead: bool | None = None,
) -> tuple[CvErrorHooks, CvMetricsPlugin, CvAuditPlugin]:
    """The mandatory plugin triple, in order, for `factory.build(plugins=...)`
    and (E50-T49) `from_snapshot(plugins=...)`. Write-ahead defaults to the
    order lane (24-internal-schemas.md §17.6)."""
    return (
        CvErrorHooks(machine_kind=machine_kind, lane=lane, pager=pager),
        CvMetricsPlugin(machine_kind=machine_kind, metrics=metrics),
        CvAuditPlugin(
            machine_kind=machine_kind,
            entity_id=entity_id,
            env=env,
            sink=sink,
            write_ahead=(lane == "order") if write_ahead is None else write_ahead,
        ),
    )


__all__ = [
    "CvAuditPlugin",
    "CvErrorHooks",
    "CvMetricsPlugin",
    "CvStateFeedPlugin",
    "FeedBinding",
    "InMemoryMachineEventSink",
    "LogPager",
    "MachineEventRow",
    "MachineEventSink",
    "MachineStateHandle",
    "MachineStatePort",
    "Pager",
    "cv_plugins",
    "feed_plugins",
]

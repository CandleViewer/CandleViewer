"""Admin ops read models (E42-T05): incident grouping, the restore guard, the health mapping."""

from __future__ import annotations

from candleviewer.admin.ops.guards import (
    NOT_DEPLOYED_DETAIL,
    RestoreRefusedError,
    check_restore,
    system_health_frame,
)
from candleviewer.admin.ops.incidents import (
    IncidentState,
    IncidentTransitionError,
    SystemEventRow,
    acknowledge,
    apply_event,
    incident_signature,
    normalise_message,
)

__all__ = [
    "NOT_DEPLOYED_DETAIL",
    "IncidentState",
    "IncidentTransitionError",
    "RestoreRefusedError",
    "SystemEventRow",
    "acknowledge",
    "apply_event",
    "check_restore",
    "incident_signature",
    "normalise_message",
    "system_health_frame",
]

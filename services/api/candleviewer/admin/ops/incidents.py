"""Incident grouping over `system_events` (E42-T05, module M21), pure.

One incident per `(component, signature)`. The signature is a stable hash of the component, the
error class (`system_events.kind`) and the message normalised by `normalise_message`, which
strips ids, timestamps, symbols and numbers so one fault never fragments into thousands of
incidents. `apply_event` is the refresh-on-write step of the materialised read model: the
`system_events` insert path folds each `error`/`critical` event into its incident, so the list
screen never aggregates on request.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal

IncidentStatus = Literal["open", "acknowledged", "resolved"]
Severity = Literal["debug", "info", "warning", "error", "critical"]
INCIDENT_SEVERITIES: Final = frozenset({"error", "critical"})

#: Order matters: whole tokens first (uuid, timestamp, symbol), then hex ids, then numbers.
_RULES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "<id>",
    ),
    (
        re.compile(
            r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
        ),
        "<ts>",
    ),
    (re.compile(r"\b[A-Z0-9]{2,20}USDT\b"), "<symbol>"),
    (re.compile(r"\b(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{8,}\b"), "<id>"),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "<n>"),
)
_SPACE: Final = re.compile(r"\s+")


def normalise_message(message: str) -> str:
    """The message with variable parts replaced by placeholders and whitespace collapsed."""
    for pattern, placeholder in _RULES:
        message = pattern.sub(placeholder, message)
    return _SPACE.sub(" ", message).strip()


def incident_signature(component: str, error_class: str, message: str) -> str:
    """16 hex chars of sha256 over the component, the error class and the normalised message."""
    body = "\x1f".join((component, error_class, normalise_message(message)))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class SystemEventRow:
    """The `system_events` columns the grouping reads."""

    component: str
    kind: str
    severity: Severity
    message: str
    event_ts: datetime


@dataclass(frozen=True, slots=True)
class IncidentState:
    component: str
    signature: str
    severity: Literal["error", "critical"]
    status: IncidentStatus
    title: str
    detail: str
    occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime


def apply_event(incident: IncidentState | None, event: SystemEventRow) -> IncidentState | None:
    """Fold one event into its incident (`None`: the first one). Events below `error` are not
    incidents. A new occurrence reopens a resolved incident; an acknowledged one stays
    acknowledged, because the operator already owns it."""
    if event.severity not in INCIDENT_SEVERITIES:
        return incident
    severity: Literal["error", "critical"] = "critical" if event.severity == "critical" else "error"
    if incident is None:
        return IncidentState(
            component=event.component,
            signature=incident_signature(event.component, event.kind, event.message),
            severity=severity,
            status="open",
            title=normalise_message(event.message),
            detail=event.message,
            occurrences=1,
            first_seen_at=event.event_ts,
            last_seen_at=event.event_ts,
        )
    latest = event.event_ts >= incident.last_seen_at
    return replace(
        incident,
        severity="critical" if "critical" in (incident.severity, severity) else "error",
        status="open" if incident.status == "resolved" else incident.status,
        detail=event.message if latest else incident.detail,
        occurrences=incident.occurrences + 1,
        first_seen_at=min(incident.first_seen_at, event.event_ts),
        last_seen_at=max(incident.last_seen_at, event.event_ts),
    )


class IncidentTransitionError(Exception):
    """The requested status change is not allowed (`409 conflict`)."""


def acknowledge(incident: IncidentState) -> tuple[IncidentState, bool]:
    """`(incident, changed)`. Acknowledging twice is a no-op; a resolved incident refuses."""
    if incident.status == "resolved":
        raise IncidentTransitionError("a resolved incident cannot be acknowledged")
    if incident.status == "acknowledged":
        return incident, False
    return replace(incident, status="acknowledged"), True

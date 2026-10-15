"""E42-T05: incident grouping, the acknowledge transition, the restore guard and the health
mapping onto the `system` topic (pure core; table-driven where the ticket's test plan asks)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest

from candleviewer.admin.ops import (
    IncidentTransitionError,
    RestoreRefusedError,
    SystemEventRow,
    acknowledge,
    apply_event,
    check_restore,
    incident_signature,
    normalise_message,
    system_health_frame,
)
from candleviewer.admin.ops.incidents import Severity
from candleviewer.observability.health_probes import ComponentHealth, ComponentState, HealthSnapshot

_T0 = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)


_WS = Path(__file__).resolve().parents[5] / "packages/protocol/ws-schemas.json"


def _event(message: str, *, minute: int = 0, severity: Severity = "error") -> SystemEventRow:
    at = _T0 + timedelta(minutes=minute)
    return SystemEventRow("recorder", "write_failed", severity, message, at)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "parquet write failed for BTCUSDT segment 41",
            "parquet write failed for <symbol> segment <n>",
        ),
        ("order 0a000000-0000-4000-8000-000000000001 rejected", "order <id> rejected"),
        ("gap at 2026-10-15T08:00:00.123Z on ETHUSDT", "gap at <ts> on <symbol>"),
        ("stale since 2026-10-15 08:00:00+00:00", "stale since <ts>"),
        ("link id 9f1c2b4e0a1d retry 3 after 1.5 s", "link id <id> retry <n> after <n> s"),
        ("  queue   full ", "queue full"),
        ("deadbeef is a word, cafe too", "deadbeef is a word, cafe too"),
    ],
)
def test_normalisation_strips_ids_timestamps_symbols_and_numbers(
    message: str, expected: str
) -> None:
    assert normalise_message(message) == expected


def test_messages_differing_only_by_id_symbol_or_time_share_a_signature() -> None:
    a = incident_signature("recorder", "write_failed", "BTCUSDT 2026-10-15T08:00:00Z id 1a2b3c4d5e")
    b = incident_signature("recorder", "write_failed", "ETHUSDT 2026-10-16T09:30:00Z id 9f8e7d6c5b")
    assert a == b and len(a) == 16
    assert incident_signature("ingestion", "write_failed", "x") != incident_signature(
        "recorder", "write_failed", "x"
    )
    assert incident_signature("recorder", "timeout", "x") != incident_signature(
        "recorder", "write_failed", "x"
    )


def test_forty_events_with_one_signature_are_one_open_incident() -> None:
    incident = None
    for minute in range(40):
        incident = apply_event(
            incident, _event(f"parquet write failed for BTCUSDT segment {minute}", minute=minute)
        )
    assert incident is not None
    assert (incident.occurrences, incident.status) == (40, "open")
    assert (incident.first_seen_at, incident.last_seen_at) == (_T0, _T0 + timedelta(minutes=39))
    assert incident.title == "parquet write failed for <symbol> segment <n>"
    assert incident.detail == "parquet write failed for BTCUSDT segment 39"


def test_events_below_error_are_not_incidents() -> None:
    assert apply_event(None, _event("slow", severity="warning")) is None


def test_fold_keeps_the_worst_severity_and_tolerates_out_of_order_events() -> None:
    incident = apply_event(None, _event("x 1", minute=10))
    incident = apply_event(incident, _event("x 2", minute=5, severity="critical"))
    assert incident is not None
    assert (incident.severity, incident.first_seen_at) == ("critical", _T0 + timedelta(minutes=5))
    assert incident.detail == "x 1"


def test_acknowledge_transitions_once_and_refuses_a_resolved_incident() -> None:
    incident = apply_event(None, _event("x"))
    assert incident is not None
    acked, changed = acknowledge(incident)
    assert (acked.status, changed) == ("acknowledged", True)
    assert acknowledge(acked) == (acked, False)
    reopened_stays_acked = apply_event(acked, _event("x", minute=1))
    assert reopened_stays_acked is not None and reopened_stays_acked.status == "acknowledged"
    resolved = replace(acked, status="resolved")
    with pytest.raises(IncidentTransitionError):
        acknowledge(resolved)
    again = apply_event(resolved, _event("x", minute=2))
    assert again is not None and again.status == "open"


@pytest.mark.parametrize(
    ("maintenance", "positions", "ack", "rule"),
    [
        (False, 0, False, "maintenance_mode_required"),
        (False, 2, True, "maintenance_mode_required"),
        (True, 2, False, "open_positions_unacknowledged"),
        (True, None, False, "open_positions_unacknowledged"),
        (True, 2, True, None),
        (True, None, True, None),
        (True, 0, False, None),
    ],
)
def test_restore_precondition_matrix(
    maintenance: bool, positions: int | None, ack: bool, rule: str | None
) -> None:
    if rule is None:
        check_restore(
            maintenance_mode=maintenance, open_positions=positions, acknowledge_open_positions=ack
        )
        return
    with pytest.raises(RestoreRefusedError) as exc:
        check_restore(
            maintenance_mode=maintenance, open_positions=positions, acknowledge_open_positions=ack
        )
    assert exc.value.rule == rule
    assert str(exc.value) == exc.value.detail
    assert ("2 positions are open" in exc.value.detail) is (
        positions == 2 and rule != "maintenance_mode_required"
    )


def _component(name: str, state: ComponentState, detail: str = "") -> ComponentHealth:
    return ComponentHealth(name, state, 3, detail, None)


def test_health_frame_keeps_unknown_components_and_maps_not_deployed() -> None:
    snapshot = HealthSnapshot(
        ComponentState.NOT_DEPLOYED,
        (
            _component("db", ComponentState.HEALTHY, "ok"),
            _component("quantum_flux", ComponentState.WARNING, "lagging"),
            _component("replay", ComponentState.NOT_DEPLOYED, "module not deployed"),
        ),
        _T0,
    )
    frame = system_health_frame(snapshot)
    assert frame == {
        "kind": "health",
        "health": "healthy",
        "components": [
            {"name": "db", "state": "healthy", "detail": "ok"},
            {"name": "quantum_flux", "state": "warning", "detail": "lagging"},
            {"name": "replay", "state": "healthy", "detail": "not deployed"},
        ],
    }
    system = json.loads(_WS.read_text(encoding="utf-8"))["schemas"]["cv://ws/v1/system.schema.json"]
    jsonschema.Draft202012Validator(system).validate(frame)

"""E42-T05: incident grouping, the acknowledge transition, the restore guard and the health
mapping onto the `system` topic (pure core; one behaviour per test, table-driven where the
ticket's test plan asks)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest

from candleviewer.admin.errors import AdminError
from candleviewer.admin.ops import (
    IncidentState,
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
_MAINTENANCE, _POSITIONS = "maintenance_mode_required", "open_positions_unacknowledged"


def _event(message: str, *, minute: int = 0, severity: Severity = "error") -> SystemEventRow:
    at = _T0 + timedelta(minutes=minute)
    return SystemEventRow("recorder", "write_failed", severity, message, at)


def _incident(message: str = "x") -> IncidentState:
    incident = apply_event(None, _event(message))
    assert incident is not None
    return incident


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


@pytest.mark.parametrize(
    ("component", "error_class", "message", "golden"),
    [
        (
            "recorder",
            "write_failed",
            "parquet write failed for BTCUSDT segment 41",
            "9358bfab779d582a",
        ),
        ("ws", "backpressure", "queue full", "b8ca10ec626bfef6"),
    ],
)
def test_signature_golden_vectors(
    component: str, error_class: str, message: str, golden: str
) -> None:
    assert incident_signature(component, error_class, message) == golden


def test_messages_differing_only_by_id_symbol_or_time_share_a_signature() -> None:
    a = incident_signature("recorder", "write_failed", "BTCUSDT 2026-10-15T08:00:00Z id 1a2b3c4d5e")
    b = incident_signature("recorder", "write_failed", "ETHUSDT 2026-10-16T09:30:00Z id 9f8e7d6c5b")
    assert a == b


def test_the_component_is_part_of_the_signature() -> None:
    assert incident_signature("ws", "write_failed", "x") != incident_signature(
        "recorder", "write_failed", "x"
    )


def test_the_error_class_is_part_of_the_signature() -> None:
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


def test_a_later_critical_raises_the_severity() -> None:
    incident = apply_event(_incident(), _event("x", minute=1, severity="critical"))
    assert incident is not None and incident.severity == "critical"


def test_a_later_error_never_lowers_a_critical_incident() -> None:
    first = apply_event(None, _event("x", severity="critical"))
    incident = apply_event(first, _event("x", minute=1))
    assert incident is not None and incident.severity == "critical"


def test_an_out_of_order_event_moves_first_seen_back_but_keeps_the_latest_detail() -> None:
    incident = apply_event(None, _event("x 1", minute=10))
    incident = apply_event(incident, _event("x 2", minute=5))
    assert incident is not None
    assert (incident.first_seen_at, incident.detail) == (_T0 + timedelta(minutes=5), "x 1")


def test_acknowledge_moves_an_open_incident_to_acknowledged() -> None:
    acked, changed = acknowledge(_incident())
    assert (acked.status, changed) == ("acknowledged", True)


def test_acknowledging_twice_is_a_no_op() -> None:
    acked, _ = acknowledge(_incident())
    assert acknowledge(acked) == (acked, False)


def test_a_resolved_incident_refuses_acknowledge() -> None:
    with pytest.raises(IncidentTransitionError):
        acknowledge(replace(_incident(), status="resolved"))


def test_recurrence_keeps_an_acknowledged_incident_acknowledged() -> None:
    acked, _ = acknowledge(_incident())
    again = apply_event(acked, _event("x", minute=1))
    assert again is not None and again.status == "acknowledged"


def test_recurrence_reopens_a_resolved_incident() -> None:
    again = apply_event(replace(_incident(), status="resolved"), _event("x", minute=2))
    assert again is not None and again.status == "open"


@pytest.mark.parametrize(
    ("maintenance", "positions", "ack", "rule"),
    [
        (False, 0, False, _MAINTENANCE),
        (False, 0, True, _MAINTENANCE),
        (False, 2, False, _MAINTENANCE),
        (False, 2, True, _MAINTENANCE),
        (False, None, False, _MAINTENANCE),
        (False, None, True, _MAINTENANCE),
        (True, 2, False, _POSITIONS),
        (True, None, False, _POSITIONS),
    ],
)
def test_restore_refusal_matrix(
    maintenance: bool, positions: int | None, ack: bool, rule: str
) -> None:
    with pytest.raises(RestoreRefusedError) as exc:
        check_restore(
            maintenance_mode=maintenance, open_positions=positions, acknowledge_open_positions=ack
        )
    assert exc.value.rule == rule


@pytest.mark.parametrize(("positions", "ack"), [(0, False), (0, True), (2, True), (None, True)])
def test_restore_allowed_matrix(positions: int | None, ack: bool) -> None:
    check_restore(maintenance_mode=True, open_positions=positions, acknowledge_open_positions=ack)


def test_open_position_refusal_names_the_count() -> None:
    with pytest.raises(RestoreRefusedError, match="2 positions are open"):
        check_restore(maintenance_mode=True, open_positions=2, acknowledge_open_positions=False)


def test_admin_ops_errors_are_admin_errors() -> None:
    assert issubclass(RestoreRefusedError, AdminError)
    assert issubclass(IncidentTransitionError, AdminError)


def _component(name: str, state: ComponentState, detail: str = "") -> ComponentHealth:
    return ComponentHealth(name, state, 3, detail, None)


def _frame() -> dict[str, object]:
    snapshot = HealthSnapshot(
        ComponentState.NOT_DEPLOYED,
        (
            _component("db", ComponentState.HEALTHY, "ok"),
            _component("quantum_flux", ComponentState.WARNING, "lagging"),
            _component("replay", ComponentState.NOT_DEPLOYED, "module not deployed"),
        ),
        _T0,
    )
    return system_health_frame(snapshot)


def test_health_frame_keeps_unknown_components_and_maps_not_deployed() -> None:
    assert _frame() == {
        "kind": "health",
        "health": "healthy",
        "components": [
            {"name": "db", "state": "healthy", "detail": "ok"},
            {"name": "quantum_flux", "state": "warning", "detail": "lagging"},
            {"name": "replay", "state": "healthy", "detail": "not deployed"},
        ],
    }


def test_health_frame_validates_against_the_system_ws_schema() -> None:
    system = json.loads(_WS.read_text(encoding="utf-8"))["schemas"]["cv://ws/v1/system.schema.json"]
    jsonschema.Draft202012Validator(system).validate(_frame())

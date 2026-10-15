"""Contract (E42-T05, contract slice): incidents grouping and acknowledge, backup verify outcome,
the single-use backup download link and its audited fetch, the restore preconditions the backup
service enforces, and the `backups` step-up class. Additive only (C-6.3): no pre-existing property
changes, nothing new becomes required on an existing schema, the restore body only gains an
optional flag and `Job.kind` (open-ended for readers) only gains a value. Every new operation is
owner-only in the reviewed RBAC matrix and allow-listed as contract-first, and the documented
examples round-trip through the generated models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec

_SPEC = load_openapi_spec()
_PATHS: dict[str, Any] = _SPEC["paths"]
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_ROOT = Path(__file__).resolve().parents[4]
_API = _ROOT / "services/api/tests"
_MATRIX = yaml.safe_load((_API / "contract/rbac/matrix.yaml").read_text(encoding="utf-8"))
_PENDING = json.loads(
    (_API / "unit/architecture/composition_allowlist.json").read_text(encoding="utf-8")
)["openapi_pending"]
_CSRF = {"$ref": "#/components/parameters/CsrfToken"}
_OWNER_ONLY = {
    "owner": "allow",
    "manager_with_grant": "403",
    "manager_without_grant": "403",
    "viewer": "403",
    "unauthenticated": "401",
}
_ACK = _PATHS["/admin/incidents/{incidentId}/acknowledge"]["post"]
_ISSUE = _PATHS["/admin/backups/{backupId}/download"]["post"]
_FETCH = _PATHS["/admin/backups/{backupId}/download/{token}"]["get"]
_RESTORE = _PATHS["/admin/backups/{backupId}/restore"]["post"]
_VERIFY = _PATHS["/admin/backups/{backupId}/verify"]["post"]
_NEW_OPS = {
    "POST /admin/incidents/{incidentId}/acknowledge": (_ACK, "admin:write"),
    "POST /admin/backups/{backupId}/download": (_ISSUE, "backups:write"),
    "GET /admin/backups/{backupId}/download/{token}": (_FETCH, "backups:read"),
}


def _text(description: str) -> str:
    """Whitespace-normalised, so no assertion depends on where the YAML wraps."""
    return " ".join(description.split())


@pytest.mark.parametrize("op", sorted(_NEW_OPS))
def test_new_operations_are_owner_only_and_allow_listed_as_pending(op: str) -> None:
    operation, permission = _NEW_OPS[op]
    assert operation["x-rbac"] == {"permissions": [permission], "scope": "none"}
    assert (_MATRIX["operations"][op]["state"], _MATRIX["operations"][op]["outcomes"]) == (
        "not_mounted",
        _OWNER_ONLY,
    )
    assert _PENDING[op]["ticket"] == "E42-T05"


@pytest.mark.parametrize(
    ("operation", "codes"),
    [
        (_ACK, {"200", "401", "403", "404", "409"}),
        (_ISSUE, {"200", "409", "429"}),
        (_FETCH, {"200", "404", "410", "429"}),
        (_RESTORE, {"202", "403", "409"}),
    ],
)
def test_documented_refusals(operation: dict[str, Any], codes: set[str]) -> None:
    assert codes <= set(operation["responses"])


def test_state_changing_operations_carry_the_csrf_parameter() -> None:
    assert _CSRF in _ACK["parameters"] and _CSRF in _ISSUE["parameters"]
    assert "parameters" not in _FETCH


def test_acknowledge_returns_the_incident_and_names_its_audit_action() -> None:
    schema = _ACK["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/Incident"}
    assert "`incident.acknowledged`" in _ACK["description"]


def test_incident_change_is_additive() -> None:
    incident = _SCHEMAS["Incident"]
    assert {"id", "component", "severity", "status"} <= set(incident["required"])
    assert "acknowledged_at" not in incident["required"]
    assert "signature" not in incident["required"]
    props = incident["properties"]
    assert props["acknowledged_at"] == {"type": ["string", "null"], "format": "date-time"}
    assert set(api.Incident.model_fields) == set(props)


def test_recurrence_reopens_resolved_but_not_acknowledged_incidents() -> None:
    text = _text(_PATHS["/admin/incidents"]["get"]["description"])
    assert "A new occurrence reopens a `resolved` incident" in text
    assert "an `acknowledged` one stays acknowledged" in text


def test_grouped_example_is_one_incident_of_forty_events() -> None:
    content = _PATHS["/admin/incidents"]["get"]["responses"]["200"]["content"]
    (item,) = content["application/json"]["examples"]["grouped"]["value"]["items"]
    model = api.Incident.model_validate(item)
    assert model.model_dump(mode="json", exclude_unset=True) == item
    assert (model.occurrences, model.status) == (40, "open")


def test_restore_body_only_gains_the_optional_acknowledgement() -> None:
    body = _RESTORE["requestBody"]["content"]["application/json"]["schema"]
    assert body["required"] == ["confirm_backup_id", "reason"]
    assert body["additionalProperties"] is False
    flag = body["properties"]["acknowledge_open_positions"]
    assert flag["type"] == "boolean" and "default" not in flag


@pytest.mark.parametrize(
    ("example", "rule"),
    [
        ("maintenanceOff", "maintenance_mode_required"),
        ("positionsOpen", "open_positions_unacknowledged"),
    ],
)
def test_restore_refusals_name_their_precondition(example: str, rule: str) -> None:
    content = _RESTORE["responses"]["409"]["content"]["application/problem+json"]
    value = content["examples"][example]["value"]
    model = api.Problem.model_validate(value)
    assert model.model_dump(mode="json", exclude_unset=True) == value
    assert [e.rule for e in model.errors or []] == [rule]
    assert f"`{rule}`" in _RESTORE["description"]


def test_restore_409_keeps_the_idempotency_conflicts() -> None:
    text = _text(_RESTORE["responses"]["409"]["description"])
    assert "`idempotency_key_reuse`" in text and "`idempotency_in_flight`" in text


@pytest.mark.parametrize("operation", [_RESTORE, _ISSUE])
def test_only_usable_backups_can_be_restored_or_downloaded(operation: dict[str, Any]) -> None:
    text = _text(operation["description"])
    assert "`ok`, `verified` or `restored`" in text
    assert "`backup_not_usable`" in text


@pytest.mark.parametrize("operation", [_RESTORE, _ISSUE, _FETCH])
def test_high_impact_backup_audits_use_severity_error(operation: dict[str, Any]) -> None:
    assert "severity `error`" in _text(operation["description"])


def test_backups_is_a_no_grace_step_up_class_registered_by_the_route_slice() -> None:
    step_up = _PATHS["/auth/step-up"]["post"]
    body = step_up["requestBody"]["content"]["application/json"]["schema"]
    assert "backups" in body["properties"]["action_class"]["enum"]
    assert "`backups` are no-grace classes" in _text(step_up["description"])
    create = _text(_PATHS["/admin/backups"]["post"]["description"])
    assert "fresh `backups` step-up elevation" in create
    assert "(`^/admin/backups`)" in create


def test_verify_failure_is_a_failed_job_recorded_on_the_backup() -> None:
    text = _text(_VERIFY["description"])
    assert "`checksum_mismatch`" in text and "`status: failed`" in text
    assert "`backup.verified`" in text


def test_download_is_single_use_audited_twice_and_never_cached() -> None:
    issued = _ISSUE["responses"]["200"]["content"]["application/json"]
    assert issued["schema"]["required"] == ["download_url", "expires_at"]
    assert "`after_state.stage: issued`" in _text(_ISSUE["description"])
    fetch = _text(_FETCH["description"])
    assert "`after_state.stage: served`" in fetch and "never recorded or logged" in fetch
    headers = _FETCH["responses"]["200"]["headers"]
    assert headers["Cache-Control"]["schema"]["const"] == "no-store"
    assert headers["X-Content-Type-Options"]["schema"]["const"] == "nosniff"
    assert headers["Content-Disposition"]["schema"]["pattern"].startswith("^attachment;")


def test_job_kind_is_open_ended_and_gains_backup_restore() -> None:
    kind = _SCHEMAS["Job"]["properties"]["kind"]
    assert "backup_restore" in kind["enum"]
    assert {"backup", "backup_verify", "audit_export"} <= set(kind["enum"])
    assert "Open-ended for readers" in kind["description"]


def test_health_note_passes_unknown_components_and_hides_detail_below_owner() -> None:
    text = (_ROOT / "docs/plan/23-ws-protocol.md").read_text(encoding="utf-8")
    note = _text(text.split("**Health components (E42-T05).**", 1)[1].split("\n\n", 1)[0])
    assert "passed through, never dropped" in note
    assert "sent to Owner sessions only" in note and "`detail` omitted" in note


def test_security_program_lists_the_new_operations() -> None:
    text = (_ROOT / "docs/plan/04-security-program.md").read_text(encoding="utf-8")
    for operation in ("`acknowledgeIncident`", "`issueBackupDownload`", "`downloadBackup`"):
        assert operation in text

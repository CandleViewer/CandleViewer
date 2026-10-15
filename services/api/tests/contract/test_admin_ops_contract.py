"""Contract (E42-T05, contract slice): incidents grouping and acknowledge, backup verify outcome,
the single-use backup download link, and the restore preconditions the backup service enforces.
Additive only (C-6.3): no pre-existing property changes, nothing new becomes required on an
existing schema, the restore body only gains an optional flag and `Job.kind` only gains a value.
Every new operation is owner-only in the reviewed RBAC matrix, and the documented examples
round-trip through the generated models."""

from __future__ import annotations

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
_MATRIX = yaml.safe_load(
    (_ROOT / "services/api/tests/contract/rbac/matrix.yaml").read_text(encoding="utf-8")
)["operations"]
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


@pytest.mark.parametrize(
    ("operation", "permission", "codes"),
    [
        (_ACK, "admin:write", {"200", "401", "403", "404", "409"}),
        (_ISSUE, "backups:write", {"200", "401", "403", "404", "409"}),
        (_FETCH, "backups:read", {"200", "401", "403", "404"}),
    ],
    ids=["acknowledge", "issue-download", "fetch-download"],
)
def test_new_operations_are_owner_permissions_with_documented_refusals(
    operation: dict[str, Any], permission: str, codes: set[str]
) -> None:
    assert operation["x-rbac"] == {"permissions": [permission], "scope": "none"}
    assert set(operation["responses"]) == codes


@pytest.mark.parametrize(
    "op",
    [
        "POST /admin/incidents/{incidentId}/acknowledge",
        "POST /admin/backups/{backupId}/download",
        "GET /admin/backups/{backupId}/download/{token}",
    ],
)
def test_rbac_matrix_row_denies_every_non_owner(op: str) -> None:
    row = _MATRIX[op]
    assert row["state"] == "not_mounted"
    assert row["outcomes"] == _OWNER_ONLY


def test_state_changing_operations_carry_the_csrf_parameter() -> None:
    assert _CSRF in _ACK["parameters"]
    assert _CSRF in _ISSUE["parameters"]
    assert "parameters" not in _FETCH


def test_acknowledge_returns_the_incident_and_names_its_audit_action() -> None:
    schema = _ACK["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/Incident"}
    assert "`incident.acknowledged`" in _ACK["description"]
    assert "requestBody" not in _ACK


def test_incident_change_is_additive() -> None:
    incident = _SCHEMAS["Incident"]
    assert incident["required"] == [
        "id",
        "component",
        "severity",
        "status",
        "first_seen_at",
        "last_seen_at",
    ]
    props = incident["properties"]
    assert props["status"]["enum"] == ["open", "acknowledged", "resolved"]
    assert props["occurrences"] == {"type": "integer"}
    assert props["acknowledged_at"] == {"type": ["string", "null"], "format": "date-time"}
    assert props["signature"]["type"] == "string"
    assert set(api.Incident.model_fields) == set(props)


def test_grouped_example_is_one_incident_of_forty_events() -> None:
    content = _PATHS["/admin/incidents"]["get"]["responses"]["200"]["content"]
    value = content["application/json"]["examples"]["grouped"]["value"]
    (item,) = value["items"]
    model = api.Incident.model_validate(item)
    assert model.model_dump(mode="json", exclude_unset=True) == item
    assert (model.occurrences, model.status) == (40, "open")
    assert model.first_seen_at < model.last_seen_at


def test_restore_body_only_gains_the_optional_acknowledgement() -> None:
    body = _RESTORE["requestBody"]["content"]["application/json"]["schema"]
    assert body["required"] == ["confirm_backup_id", "reason"]
    assert body["additionalProperties"] is False
    flag = body["properties"]["acknowledge_open_positions"]
    assert flag["type"] == "boolean"
    assert "default" not in flag
    assert set(body["properties"]) == {
        "confirm_backup_id",
        "reason",
        "components",
        "acknowledge_open_positions",
    }


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
    assert (model.status, model.code) == (409, "conflict")
    assert [e.rule for e in model.errors or []] == [rule]
    assert f"`{rule}`" in _RESTORE["description"]
    assert "creates no job" in _RESTORE["description"]


def test_verify_failure_is_a_failed_job_recorded_on_the_backup() -> None:
    text = _VERIFY["description"]
    assert "`checksum_mismatch`" in text
    assert "`status: failed`" in text
    assert "`backup.verified`" in text


def test_download_link_is_single_use_short_lived_and_never_a_credential() -> None:
    issued = _ISSUE["responses"]["200"]["content"]["application/json"]
    assert issued["schema"]["required"] == ["download_url", "expires_at"]
    assert "`backup.downloaded`" in _ISSUE["description"]
    assert "5 minutes" in _ISSUE["description"]
    assert "never logged" in _ISSUE["description"]
    token = next(
        p for p in _PATHS["/admin/backups/{backupId}/download/{token}"]["parameters"] if "name" in p
    )
    assert token["schema"]["pattern"] == "^[A-Za-z0-9_-]{22,64}$"
    url = issued["examples"]["issued"]["value"]["download_url"]
    assert url.rsplit("/", 1)[-1] and url.startswith("/api/v1/admin/backups/")


def test_job_kind_only_gains_backup_restore() -> None:
    kinds = _SCHEMAS["Job"]["properties"]["kind"]["enum"]
    before = "instrument_refresh audit_export backup backup_verify rule_simulation"
    before += " retention_sweep reconciliation archive_import"
    assert [k for k in kinds if k != "backup_restore"] == before.split()
    assert kinds.count("backup_restore") == 1


def test_health_note_passes_unknown_components_through() -> None:
    text = (_ROOT / "docs/plan/23-ws-protocol.md").read_text(encoding="utf-8")
    note = text.split("**Health components (E42-T05).**", 1)[1].split("\n\n", 1)[0]
    assert "passed through, never\ndropped" in note
    assert '`detail: "not deployed"`' in note

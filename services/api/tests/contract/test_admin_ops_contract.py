"""Contract (E42-T05, contract slice): incidents, backup jobs, the one-time download link, restore
preconditions and the no-grace `backups` step-up class. Additive (C-6.3). Every example of every
touched operation validates against its own response schema; 04 §7.2.2 rows are parsed."""

from __future__ import annotations

import json
from typing import Any

import pytest
import yaml

from candleviewer.api._generated import openapi_models as api
from tests.contract._admin_support import (
    OWNER_ONLY,
    ROOT,
    SPEC,
    capability_rows,
    example_cases,
    grants,
    text,
    validate_example,
    x_rbac,
)

_PATHS: dict[str, Any] = SPEC["paths"]
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_TESTS = ROOT / "services/api/tests"
_MATRIX = yaml.safe_load((_TESTS / "contract/rbac/matrix.yaml").read_text(encoding="utf-8"))
_PENDING = json.loads(
    (_TESTS / "unit/architecture/composition_allowlist.json").read_text(encoding="utf-8")
)["openapi_pending"]
_CSRF = {"$ref": "#/components/parameters/CsrfToken"}
_INCIDENTS = _PATHS["/admin/incidents"]["get"]
_ACK = _PATHS["/admin/incidents/{incidentId}/acknowledge"]["post"]
_CREATE = _PATHS["/admin/backups"]["post"]
_DELETE = _PATHS["/admin/backups/{backupId}"]["delete"]
_VERIFY = _PATHS["/admin/backups/{backupId}/verify"]["post"]
_ISSUE = _PATHS["/admin/backups/{backupId}/download"]["post"]
_FETCH = _PATHS["/admin/backups/{backupId}/download/{token}"]["get"]
_RESTORE = _PATHS["/admin/backups/{backupId}/restore"]["post"]
_STEP_UP = _PATHS["/auth/step-up"]["post"]
_NEW_OPS = {
    "POST /admin/incidents/{incidentId}/acknowledge": (_ACK, "admin:write"),
    "POST /admin/backups/{backupId}/download": (_ISSUE, "backups:write"),
    "GET /admin/backups/{backupId}/download/{token}": (_FETCH, "backups:read"),
}
#: Every operation this slice adds or changes.
_TOUCHED = [
    (path, method)
    for path, item in _PATHS.items()
    if path.startswith(("/admin/backups", "/admin/incidents"))
    or path in {"/admin/health", "/admin/jobs/{jobId}", "/auth/step-up"}
    for method in item
    if method in {"get", "post", "delete"}
]
_EXAMPLES = example_cases(_TOUCHED)


def _doc(name: str) -> str:
    return text((ROOT / "docs/plan" / name).read_text(encoding="utf-8"))


def _json_body(operation: dict[str, Any], status: str) -> Any:
    return operation["responses"][status]["content"]["application/json"]["schema"]


@pytest.mark.parametrize("op", sorted(_NEW_OPS))
def test_new_operations_are_owner_only_and_allow_listed_as_pending(op: str) -> None:
    operation, permission = _NEW_OPS[op]
    assert operation["x-rbac"] == {"permissions": [permission], "scope": "none"}
    row = _MATRIX["operations"][op]
    assert (row["state"], row["outcomes"]) == ("not_mounted", OWNER_ONLY)
    assert _PENDING[op]["ticket"] == "E42-T05"


@pytest.mark.parametrize(("case", "pointer", "value"), _EXAMPLES, ids=[c[0] for c in _EXAMPLES])
def test_every_example_validates_against_its_response_schema(
    case: str, pointer: str, value: Any
) -> None:
    validate_example(pointer, value)


@pytest.mark.parametrize(
    ("operation", "codes"),
    [
        (_PATHS["/admin/health"]["get"], {"200", "401", "403"}),
        (_ACK, {"200", "401", "403", "404", "409"}),
        (_DELETE, {"204", "401", "403", "404", "409"}),
        (_VERIFY, {"202", "401", "403", "404"}),
        (_ISSUE, {"200", "401", "403", "404", "409", "429"}),
        (_FETCH, {"200", "401", "403", "404", "410", "429"}),
        (_RESTORE, {"202", "401", "403", "404", "409"}),
    ],
)
def test_documented_responses(operation: dict[str, Any], codes: set[str]) -> None:
    assert codes <= set(operation["responses"])


def test_step_up_and_csrf_refusals_use_the_shared_forbidden_response() -> None:
    for operation in (_DELETE, _VERIFY, _ISSUE, _RESTORE, _ACK):
        assert operation["responses"]["403"] == {"$ref": "#/components/responses/Forbidden"}
        assert _CSRF in operation["parameters"]
    assert "parameters" not in _FETCH


def test_incident_shape() -> None:
    incident = _SCHEMAS["Incident"]
    props = incident["properties"]
    required = {"id", "component", "severity", "status", "first_seen_at", "last_seen_at"}
    assert set(incident["required"]) == required
    assert props["status"]["enum"] == ["open", "acknowledged", "resolved"]
    assert (props["title"]["maxLength"], props["detail"]["maxLength"]) == (200, 2000)
    assert props["detail"]["type"] == ["string", "null"]
    assert props["occurrences"] == {"type": "integer", "minimum": 1}
    assert props["signature"]["pattern"] == "^[0-9a-f]{16}$"
    assert set(api.Incident.model_fields) == set(props)
    page = _json_body(_INCIDENTS, "200")["allOf"][1]["properties"]["items"]
    assert page["items"] == _json_body(_ACK, "200") == {"$ref": "#/components/schemas/Incident"}
    content = _INCIDENTS["responses"]["200"]["content"]["application/json"]
    (item,) = content["examples"]["grouped"]["value"]["items"]
    assert (item["occurrences"], item["status"]) == (40, "open")
    assert api.Incident.model_validate(item).model_dump(mode="json", exclude_unset=True) == item


def test_incident_redaction_and_lifecycle() -> None:
    desc = text(_INCIDENTS["description"])
    for rule in (
        "pass through `candleviewer.observability.redaction.redact_text` before they are stored",
        "when redaction fails, `detail` is `null`",
        "`severity` is the worst of them",
        "once every grouped event is resolved (`system_events.resolved_at`)",
        "clears `resolved_at`, `acknowledged_by` and `acknowledged_at`",
        "a new occurrence at the same severity keeps the status",
        "raises `severity` from `error` to `critical` clears the acknowledgement",
        "there is no resolution text",
        "kept 24 months after `last_seen_at`",
    ):
        assert rule in desc, rule
    assert "`incident.acknowledged`" in _ACK["description"]


def test_backup_jobs_are_pollable_and_job_kind_stays_open_ended() -> None:
    assert _json_body(_CREATE, "202") == {"$ref": "#/components/schemas/Backup"}
    create = text(_CREATE["description"])
    assert "poll `GET /admin/jobs/{Backup.id}`, which reports `kind: backup`" in create
    assert _json_body(_VERIFY, "202")["required"] == _json_body(_RESTORE, "202")["required"]
    assert _json_body(_RESTORE, "202")["required"] == ["job_id"]
    kind = _SCHEMAS["Job"]["properties"]["kind"]
    assert {"backup", "backup_verify", "backup_restore", "audit_export"} <= set(kind["enum"])
    assert "Open-ended for readers" in kind["description"]


def test_backup_error_is_a_stable_code_and_verified_at_survives_a_failed_reverify() -> None:
    error = _SCHEMAS["Backup"]["properties"]["error"]["description"]
    assert "stable code" in error and "`backups.error_message`" in error
    verify = text(_VERIFY["description"])
    assert "`checksum_mismatch`" in verify and "`status: failed`" in verify
    assert "leaves `verified_at` at the last successful verification" in verify


def test_restore_body_gains_two_separate_optional_acknowledgements() -> None:
    body = _RESTORE["requestBody"]["content"]["application/json"]["schema"]
    assert body["required"] == ["confirm_backup_id", "reason"]
    assert body["additionalProperties"] is False
    for name in ("acknowledge_open_positions", "acknowledge_unknown_positions"):
        assert {body["properties"][name][key] for key in ("type", "default")} == {"boolean", False}
    assert "The two flags are separate; neither implies the other" in text(_RESTORE["description"])


def test_restore_preconditions_are_checked_in_the_documented_order() -> None:
    desc = text(_RESTORE["description"])
    order = [
        "`maintenance_mode_required`",
        "`backup_or_restore_running`",
        "`backup_not_usable`",
        "`409 positions_unknown`",
        "`open_positions_unacknowledged`",
    ]
    assert [desc.index(rule) for rule in order] == sorted(desc.index(rule) for rule in order)
    assert "`backup_or_restore_running`" in text(_CREATE["description"])


@pytest.mark.parametrize(
    ("example", "code", "rule"),
    [
        ("maintenanceOff", "conflict", "maintenance_mode_required"),
        ("positionsOpen", "conflict", "open_positions_unacknowledged"),
        ("positionsUnknown", "positions_unknown", None),
    ],
)
def test_restore_refusals_name_their_precondition(
    example: str, code: str, rule: str | None
) -> None:
    content = _RESTORE["responses"]["409"]["content"]["application/problem+json"]
    model = api.Problem.model_validate(content["examples"][example]["value"])
    assert model.code == code
    assert [e.rule for e in model.errors or []] == ([rule] if rule else [])


def test_restore_refusal_is_not_replayed_spends_the_code_and_is_audited() -> None:
    desc = text(_RESTORE["description"])
    assert "is not stored under the `Idempotency-Key`" in desc
    assert "It has already spent the step-up code" in desc
    assert "so the operator steps up again before retrying" in desc
    assert "Every attempt that passes RBAC and the step-up is audited as `backup.restore`" in desc
    assert "`outcome: failure`" in desc and "`outcome: success`" in desc
    assert "is not stored under the key" in text(SPEC["info"]["description"])
    conflicts = text(_RESTORE["responses"]["409"]["description"])
    assert "`idempotency_key_reuse`" in conflicts and "`idempotency_in_flight`" in conflicts


def test_backup_actions_need_a_usable_backup_and_audit_at_severity_error() -> None:
    for operation in (_RESTORE, _ISSUE, _FETCH):
        desc = text(operation["description"])
        assert "severity `error`" in desc
        if operation is not _FETCH:
            assert "`ok`, `verified` or `restored`" in desc and "`backup_not_usable`" in desc
    assert "Audited as `backup.deleted` (actor, backup id," in text(_DELETE["description"])


def test_backups_is_a_no_grace_class_for_restore_download_and_delete_only() -> None:
    classes = _STEP_UP["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert "backups" in classes["action_class"]["enum"]
    step_up = text(_STEP_UP["description"])
    assert "`live_enablement`, `killswitch` and `backups` are no-grace" in step_up
    assert _RESTORE["summary"] == "Restore from a backup (owner, step-up `backups`)"
    gated = "`403 step_up_required` with `action_class` set to `backups`"
    assert all(gated in text(op["description"]) for op in (_RESTORE, _ISSUE, _DELETE))
    sites = (
        "`NO_GRACE_ACTION_CLASSES` in `auth/step_up.py` and `statechart/bindings/b16_session.py`"
    )
    assert sites in text(_ISSUE["description"])
    for operation in (_CREATE, _VERIFY):  # not step-up gated (the dangerous-route registry)
        assert "step-up" not in operation["description"]


def test_download_token_rules_are_normative() -> None:
    desc = text(_FETCH["description"])
    for rule in (
        "access logs, traces, metrics labels and audit fields record the route template "
        "`/admin/backups/{backupId}/download/{token}`, never the token",
        "an unknown token or another user's is `404 not_found`, so a token cannot be probed",
        "`Problem.detail` never echoes the path",
        "sends `Referrer-Policy: no-referrer` and `Cache-Control: no-store`",
        "from a CSPRNG with at least 128 bits of entropy, is stored only as a hash",
        "compared in constant time, and is single-use and short-lived (5 minutes)",
    ):
        assert rule in desc, rule
    for status in ("200", "410"):
        headers = _FETCH["responses"][status]["headers"]
        assert headers["Cache-Control"]["schema"]["const"] == "no-store"
        assert headers["Referrer-Policy"]["schema"]["const"] == "no-referrer"
    nosniff = _FETCH["responses"]["200"]["headers"]["X-Content-Type-Options"]["schema"]
    assert nosniff == {"type": "string", "const": "nosniff"}
    assert "never the link or its token" in text(_ISSUE["description"])
    assert _json_body(_ISSUE, "200")["required"] == ["download_url", "expires_at"]
    (gone,) = [e for e in SPEC["x-error-codes"] if e["code"] == "gone"]
    assert "a one-time link that expired or was used" in gone["title"]
    token = _PATHS["/admin/backups/{backupId}/download/{token}"]["parameters"][1]["schema"]
    assert token["pattern"] == "^[A-Za-z0-9_-]{22,64}$"  # 22 base64url characters = 132 bits
    assert "used" in _FETCH["responses"]["410"]["content"]["application/problem+json"]["examples"]
    assert all("/download/" not in str(v.get("detail")) for c, _, v in _EXAMPLES if "{token}" in c)


def test_health_components_carry_last_good_at_and_hide_detail_below_owner() -> None:
    bundle = json.loads((ROOT / "docs/plan/ws-schema.json").read_text(encoding="utf-8"))
    item = bundle["schemas"]["cv://ws/v1/system.schema.json"]["properties"]["components"]["items"]
    assert item["properties"]["last_good_at"] == {"type": "string", "format": "date-time"}
    assert "required" not in item
    doc = (ROOT / "docs/plan/23-ws-protocol.md").read_text(encoding="utf-8")
    note = text(doc.split("**Health components (E42-T05).**", 1)[1].split("\n\n", 1)[0])
    assert "passed through, never dropped" in note
    assert "get each component's `name`, `state` and `last_good_at`, never `detail`" in note
    manager, viewer = capability_rows()["48"][3:5]
    assert "`last_good_at`; never `detail`" in manager and viewer == "✔(limited, as Manager)"


@pytest.mark.parametrize(
    ("row", "permissions", "operations"),
    [
        ("48b", {"admin:write"}, {"acknowledgeIncident"}),
        ("52", {"backups:write"}, {f"{v}Backup" for v in "create restore verify delete".split()}),
        ("52a", {"backups:write", "backups:read"}, {"issueBackupDownload", "downloadBackup"}),
    ],
)
def test_security_program_rows_match_the_contract(
    row: str, permissions: set[str], operations: set[str]
) -> None:
    cells = capability_rows()[row]
    assert grants(cells[1]) == (permissions, operations)
    assert all(set(x_rbac(operation)) <= permissions for operation in operations)
    assert cells[2].startswith("✔") and cells[3:] == ["✖", "✖"]


def test_docs_share_the_audit_vocabulary_and_the_backups_step_up() -> None:
    sec, internal = _doc("04-security-program.md"), _doc("24-internal-schemas.md")
    names = ("`backup.run`", "`backup.restore`", "`backup.verified`", "`backup.downloaded`")
    for doc in (sec, internal):
        assert all(name in doc for name in names) and "`incident.acknowledged`" in doc
        assert "`backup.created`" not in doc and "`backup.restored`" not in doc
    assert "and restoring, downloading or deleting a backup (one fresh code each)" in sec
    assert "(`live_enablement`/`killswitch`/`backups`: none, fresh code each time)" in internal
    assert "never embeds `str(exc)` or raw probe output" in internal
    assert "There is no resolution text because nobody writes one" in _doc("21-database-schema.md")

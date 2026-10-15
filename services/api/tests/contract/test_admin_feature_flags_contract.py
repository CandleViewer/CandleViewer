"""Contract (E42-T03, contract slice): `PUT /admin/feature-flags/{flagKey}` states the write
rules the flag service enforces (reason, read-version precondition, kind check, step-up, the
live-gate evidence precondition, audit and push) and documents the `401`/`404`/`409` answers.
The `409` carries the current flag (`FeatureFlagConflict`). The change is additive only (C-6.3):
`SetFeatureFlagRequest` still requires only `value`, stays closed, and every pre-existing
property keeps its type. The generated models mirror the schemas and the documented examples
round-trip through them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS

_SPEC = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_LIST = _SPEC["paths"]["/admin/feature-flags"]["get"]
_PUT = _SPEC["paths"]["/admin/feature-flags/{flagKey}"]["put"]
_REQUEST = _SCHEMAS["SetFeatureFlagRequest"]
_CODES = {entry["code"] for entry in _SPEC["x-error-codes"]}
_DOCS = Path(__file__).resolve().parents[4] / "docs" / "plan"


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def test_put_documents_every_refusal_the_service_returns() -> None:
    assert set(_PUT["responses"]) == {"200", "401", "403", "404", "409", "422"}
    assert set(_LIST["responses"]) == {"200", "401", "403"}


def test_conflict_answer_carries_the_current_flag() -> None:
    content = _PUT["responses"]["409"]["content"]["application/problem+json"]
    assert content["schema"] == _ref("FeatureFlagConflict")
    problem, extra = _SCHEMAS["FeatureFlagConflict"]["allOf"]
    assert problem == _ref("Problem")
    assert extra["required"] == ["current"]
    assert extra["properties"]["current"] == _ref("FeatureFlag")


def test_request_change_is_additive_only() -> None:
    props = _REQUEST["properties"]
    assert _REQUEST["required"] == ["value"]
    assert _REQUEST["additionalProperties"] is False
    assert {k: props["reason"][k] for k in ("type", "maxLength")} == {
        "type": "string",
        "maxLength": 280,
    }
    assert props["evidence_url"]["format"] == "uri"
    assert props["expected_updated_at"]["type"] == "string"
    assert props["expected_updated_at"]["format"] == "date-time"
    assert set(props) == {"value", "overrides", "reason", "evidence_url", "expected_updated_at"}


@pytest.mark.parametrize(
    "code", ["validation_failed", "step_up_required", "conflict", "not_found", "trading_disabled"]
)
def test_every_error_code_the_rules_name_is_registered(code: str) -> None:
    assert code in _CODES
    assert f"`{code}`" in _PUT["description"] or f" {code}`" in _PUT["description"]


@pytest.mark.parametrize("rule", ["required", "kind_mismatch", "gate_evidence_required"])
def test_validation_rules_are_named(rule: str) -> None:
    assert f"`{rule}`" in _PUT["description"]


def test_audited_actions_are_named_and_flags_change_is_registered() -> None:
    for action in ("flags.change", "maintenance.enabled", "maintenance.disabled"):
        assert f"`{action}`" in _PUT["description"]
    assert "flags.change" in AUDIT_ACTIONS


def test_generated_models_mirror_the_new_shapes() -> None:
    problem_fields = set(api.Problem.model_fields)
    assert set(api.FeatureFlagConflict.model_fields) == problem_fields | {"current"}
    assert set(api.SetFeatureFlagRequest.model_fields) == set(_REQUEST["properties"])


def test_request_example_round_trips_without_field_loss() -> None:
    body = _PUT["requestBody"]["content"]["application/json"]["examples"]["enableLive"]["value"]
    model = api.SetFeatureFlagRequest.model_validate(body)
    assert model.model_dump(mode="json", exclude_unset=True) == body


def test_conflict_example_round_trips_without_field_loss() -> None:
    content = _PUT["responses"]["409"]["content"]["application/problem+json"]
    example = content["examples"]["staleRead"]["value"]
    model = api.FeatureFlagConflict.model_validate(example)
    assert model.model_dump(mode="json", exclude_unset=True) == example
    assert model.code == "conflict"
    assert model.status == 409


def test_maintenance_flags_are_catalogued_with_safe_defaults() -> None:
    text = (_DOCS / "21-database-schema.md").read_text(encoding="utf-8")
    rows = {
        line.split("|")[1].strip(): [c.strip() for c in line.split("|")[2:5]]
        for line in text.splitlines()
        if line.startswith("| `maintenance.")
    }
    assert rows["`maintenance.mode`"][:2] == ["boolean", "`false`"]
    assert "is_killswitch=true" in rows["`maintenance.mode`"][2]
    assert rows["`maintenance.keep_recorder`"][:2] == ["boolean", "`true`"]


def test_push_note_states_changed_keys_only_and_role_filtering() -> None:
    text = (_DOCS / "23-ws-protocol.md").read_text(encoding="utf-8")
    note = text.split("**Feature-flag and maintenance pushes (E42-T03).**", 1)[1]
    note = note.split("\n\n", 1)[0]
    assert "only the changed keys" in note
    assert "owner-only key" in note
    assert "`maintenance.enabled`" in note and "`maintenance.disabled`" in note

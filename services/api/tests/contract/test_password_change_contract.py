"""`authChangePassword` contract (#2330; ruling on #2110 BQ-219 / 223 / 224 / 228 / 233): the codes
the registry catalogues, the answers the route declares, its examples against `Problem` and the
registry, the `04` Sec.6.3.1 strings the examples quote, and the request body's SR-026 shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.password import ChangePasswordBody
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.auth import password_policy
from candleviewer.auth.password_service import REUSED_DETAIL
from tests.contract._admin_support import ROOT

_CODES = {
    "current_password_invalid": 403,
    "password_breached": 422,
    "password_reused": 422,
    "password_policy": 422,
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _op(spec: dict[str, Any]) -> dict[str, Any]:
    op: dict[str, Any] = spec["paths"]["/auth/password"]["put"]
    return op


def _examples(spec: dict[str, Any], status: str) -> list[dict[str, Any]]:
    content = _op(spec)["responses"][status]["content"]
    media = content.get("application/problem+json") or content["application/json"]
    return [example["value"] for example in media["examples"].values()]


def test_the_registry_catalogues_the_four_codes_at_their_status(spec: dict[str, Any]) -> None:
    registry = {entry["code"]: entry for entry in spec["x-error-codes"]}
    for code, status in _CODES.items():
        assert registry[code]["status"] == status and registry[code]["retryable"] is False


def test_the_route_is_self_scoped_not_step_up_gated_and_ignores_idempotency(
    spec: dict[str, Any],
) -> None:
    """BQ-220 (the #2330 ruling): no step-up; BQ-228: a token-carrying `200` is never stored."""
    op = _op(spec)
    assert op["x-rbac"] == {"permissions": [], "scope": "self"}
    assert op["x-idempotency"] == "ignored"
    assert (
        "Not step-up gated" in op["description"]
        and "step_up_required" not in op["responses"]["403"]["description"]
    )
    assert set(op["responses"]) == {"200", "401", "403", "409", "422", "429", "503"}


def test_the_200_is_a_token_bundle_with_rotated_cookies(spec: dict[str, Any]) -> None:
    ok = _op(spec)["responses"]["200"]
    assert "Set-Cookie" in ok["headers"]
    schema = spec["components"]["schemas"]["ChangePasswordResponse"]
    assert schema["required"] == ["status", "tokens"]
    assert schema["properties"]["tokens"] == {"$ref": "#/components/schemas/TokenBundle"}
    (example,) = _examples(spec, "200")
    assert example["tokens"]["refresh_token"] is None


def test_every_refusal_example_names_a_catalogued_code_at_its_status(spec: dict[str, Any]) -> None:
    registry = {entry["code"]: entry for entry in spec["x-error-codes"]}
    for status in ("403", "422", "429", "503"):
        for example in _examples(spec, status):
            entry = registry[example["code"]]
            assert example["status"] == int(status), example["code"]
            assert example["title"] == entry["title"], example["code"]
            if entry["status"] != 400:  # `validation_failed` is the route's 422 (BQ-224)
                assert entry["status"] == int(status), example["code"]


def test_the_examples_quote_the_04_strings_the_server_sends(spec: dict[str, Any]) -> None:
    """BQ-230: `detail` is `04` Sec.6.3.1's sentence; the route answers the same text."""
    doc = (ROOT / "docs" / "plan" / "04-security-program.md").read_text(encoding="utf-8")
    section = doc.split("#### 6.3.1 ", 1)[1].split("\n### ", 1)[0]
    details = {e["code"]: e["detail"] for e in _examples(spec, "422") + _examples(spec, "403")}
    server = {
        "password_breached": password_policy.DETAILS[password_policy.PolicyRule.BREACHED],
        "password_reused": REUSED_DETAIL,
        "current_password_invalid": "Your current password is incorrect.",
    }
    for code, text in server.items():
        assert details[code] == text and text in section, code
    for rule in (
        password_policy.PolicyRule.MIN_LENGTH,
        password_policy.PolicyRule.CONTAINS_IDENTITY,
    ):
        assert password_policy.DETAILS[rule] in section, rule


def test_the_body_names_no_user_and_matches_the_served_model(spec: dict[str, Any]) -> None:
    """SR-026: no member names a user; the server's model has exactly the schema's members and
    bounds (the policy minimum of 14 is the server's, answered as `password_policy`)."""
    schema = spec["components"]["schemas"]["ChangePasswordRequest"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(ChangePasswordBody.model_fields)
    for name, prop in schema["properties"].items():
        assert (prop["minLength"], prop["maxLength"]) == (1, 512), name
        assert prop["writeOnly"] is True, name
    assert password_policy.MIN_LENGTH == 14 and password_policy.MAX_LENGTH == 512


def test_the_invite_password_schema_carries_the_shared_policy_bounds(spec: dict[str, Any]) -> None:
    """BQ-234: invite redemption applies the same policy, so its schema states the same floor
    (a 12 or 13 code point password is schema-invalid, never schema-valid then `422`)."""
    op = spec["paths"]["/invites/{inviteToken}"]["post"]
    body = op["requestBody"]["content"]["application/json"]["schema"]["properties"]["password"]
    bounds = (password_policy.MIN_LENGTH, password_policy.MAX_LENGTH)
    assert (body["minLength"], body["maxLength"]) == bounds
    assert "password_policy" in op["responses"]["422"]["description"]


def test_the_audit_actions_the_route_writes_are_registered() -> None:
    for action in ("auth.password_change", "auth.session_revoked", "auth.session_created"):
        assert action in AUDIT_ACTIONS

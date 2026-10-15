"""Enrolment-only session contract (#2295, #2344), slice 1/3: contract only (C-6.1).

Pins main-orchestrator's decisions of 2026-10-15, recorded on #2295. A user with `mfa_required`
and no confirmed MFA method gets an enrolment-only session from `POST /auth/login` and from every
recovery sign-in. That session may call five operations, gets `403 mfa_enrollment_required` from
every other one, is refused by the WebSocket, and lives at most 15 minutes; refresh never extends
it. `POST /auth/mfa/enroll/confirm` rotates it to a full session, revokes the user's other TOTP
methods and returns 10 new recovery codes, which move there from the enrol `201`. The routes keep
today's behaviour until the enforcement and endpoint slices land;
`tests/unit/api/test_auth_router.py` pins that runtime and this slice leaves it alone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.ws._generated.error_codes import ERROR_META, WS_ERROR_CODES, ErrorCode

_BASE = "urn:cv:openapi"
_CODE = "mfa_enrollment_required"
_PLAN = Path(__file__).resolve().parents[4] / "docs" / "plan"
#: The only operations an enrolment-only session may call (decision on #2295).
_ALLOWED = {
    ("post", "/auth/mfa/enroll"),
    ("post", "/auth/mfa/enroll/confirm"),
    ("get", "/auth/session"),
    ("post", "/auth/refresh"),
    ("post", "/auth/logout"),
}
_SELF_SERVICE = {"permissions": [], "scope": "self"}
_OPERATION = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`]+)`")


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _op(spec: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    op: dict[str, Any] = spec["paths"][path][method]
    return op


def _ok(spec: dict[str, Any], path: str) -> dict[str, Any]:
    response: dict[str, Any] = _op(spec, "post", path)["responses"]["200"]
    return response


def _conforms(spec: dict[str, Any], value: Any, pointer: str) -> None:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    Draft202012Validator(
        {"$ref": f"{_BASE}#{pointer}"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


def _flat(text: str) -> str:
    """Collapse YAML line wrapping so prose pins survive a re-wrap."""
    return " ".join(text.split())


def _section(spec: dict[str, Any]) -> str:
    text: str = spec["info"]["description"]
    start = text.index("### Enrolment-only session")
    return _flat(text[start : text.index("\n### ", start)])


def _bullet(section: str, title: str) -> str:
    start = section.index(f"**{title}.**")
    end = section.find("* **", start)
    return section[start : end if end != -1 else None]


def _confirm_example(spec: dict[str, Any]) -> dict[str, Any]:
    examples = _ok(spec, "/auth/mfa/enroll/confirm")["content"]["application/json"]["examples"]
    value: dict[str, Any] = examples["rotated"]["value"]
    return value


def test_error_registry_mfa_enrollment_required_is_a_rest_only_403(spec: dict[str, Any]) -> None:
    entry = {e["code"]: e for e in spec["x-error-codes"]}[_CODE]
    assert (entry["status"], entry["retryable"]) == (403, False)
    assert entry.get("surface", ["rest"]) == ["rest"]  # the WS refuses with a `bye`, not an `err`
    assert ERROR_META[ErrorCode(_CODE)].surfaces == ("rest",)
    assert ErrorCode(_CODE) not in WS_ERROR_CODES


def test_forbidden_response_documents_the_code_with_a_conforming_example(
    spec: dict[str, Any],
) -> None:
    forbidden = spec["components"]["responses"]["Forbidden"]
    assert f"`code: {_CODE}`" in forbidden["description"]
    example = forbidden["content"]["application/problem+json"]["examples"]["mfaEnrollmentRequired"]
    _conforms(spec, example["value"], "/components/schemas/Problem")
    title = {e["code"]: e["title"] for e in spec["x-error-codes"]}[_CODE]
    assert (example["value"]["code"], example["value"]["status"]) == (_CODE, 403)
    assert example["value"]["title"] == title


def test_section_allows_exactly_the_five_operations(spec: dict[str, Any]) -> None:
    bullet = _bullet(_section(spec), "Allowed operations")
    named = {(method.lower(), path) for method, path in _OPERATION.findall(bullet)}
    assert named == _ALLOWED
    for method, path in _ALLOWED:
        assert method in spec["paths"][path]
    assert f"answers `403 {_CODE}` and changes nothing" in bullet
    assert "The WebSocket refuses the session at `auth`" in bullet


@pytest.mark.parametrize(
    "rule",
    [
        "The restriction is derived from the user's state on every request; the session carries "
        "no flag.",
        "an owner TOTP reset (which also sets `mfa_required`) or by any recovery sign-in",
        "A session minted enrolment-only lives at most 15 minutes from sign-in.",
        "the successor keeps the same absolute expiry, so refresh never extends it",
        "It then rotates the session (SR-013): the enrolment-only session is revoked",
        "`POST /auth/login` keeps answering `501` to such a user without a confirmed method",
    ],
)
def test_section_states_the_decided_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _section(spec)


def test_login_mints_an_enrolment_only_session_for_a_user_without_a_method(
    spec: dict[str, Any],
) -> None:
    description = _flat(_op(spec, "post", "/auth/login")["description"])
    assert "the session is **enrolment-only**" in description
    assert "keeps getting `501`; C-12.2 makes TOTP mandatory for every user" in description
    examples = _ok(spec, "/auth/login")["content"]["application/json"]["examples"]
    body = examples["enrolmentOnly"]["value"]
    _conforms(spec, body, "/components/schemas/LoginResponse")
    assert (body["user"]["mfa_required"], body["user"]["mfa_enabled"]) == (True, False)
    assert body["tokens"]["refresh_expires_in"] <= 15 * 60


def test_recovery_always_forces_reenrolment_with_an_enrolment_only_session(
    spec: dict[str, Any],
) -> None:
    op = _op(spec, "post", "/auth/mfa/recovery")
    assert op["security"] == []  # pre-session, like `POST /auth/mfa/verify`
    assert _ok(spec, "/auth/mfa/recovery")["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AuthenticatedResponse"
    }
    assert "Set-Cookie" in _ok(spec, "/auth/mfa/recovery")["headers"]
    description = _flat(op["description"])
    assert "Every recovery sign-in forces TOTP re-enrolment, however many codes remain" in (
        description
    )
    assert "mints an **enrolment-only** session" in description
    assert "fewer than three codes" not in description


def test_enroll_needs_no_permission_and_never_returns_recovery_codes(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/mfa/enroll")
    assert op["x-rbac"] == _SELF_SERVICE  # every role enrols its own method
    assert op["responses"]["409"] == {"$ref": "#/components/responses/Conflict"}
    assert "recovery_codes" not in spec["components"]["schemas"]["MfaEnrollResponse"]["properties"]
    for example in op["responses"]["201"]["content"]["application/json"]["examples"].values():
        assert "recovery_codes" not in example["value"]


def test_confirm_returns_the_rotated_session_and_exactly_ten_codes(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/mfa/enroll/confirm")
    assert op["x-rbac"] == _SELF_SERVICE
    assert op["x-idempotency"] == "ignored"  # tokens and codes are never stored for a replay
    assert op["responses"]["409"] == {"$ref": "#/components/responses/Conflict"}
    ok = _ok(spec, "/auth/mfa/enroll/confirm")
    assert ok["headers"] == _ok(spec, "/auth/refresh")["headers"]  # rotated cookies, as refresh
    schema = ok["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/MfaEnrollConfirmResponse"}
    first, extra = spec["components"]["schemas"]["MfaEnrollConfirmResponse"]["allOf"]
    assert first == {"$ref": "#/components/schemas/AuthenticatedResponse"}
    assert set(extra["required"]) == {"mfa_method", "recovery_codes"}
    codes = extra["properties"]["recovery_codes"]
    assert (codes["minItems"], codes["maxItems"]) == (10, 10)


def test_confirm_example_conforms_and_a_short_code_set_does_not(spec: dict[str, Any]) -> None:
    pointer = "/components/schemas/MfaEnrollConfirmResponse"
    body = _confirm_example(spec)
    _conforms(spec, body, pointer)
    assert body["user"]["mfa_enabled"] is True
    with pytest.raises(ValidationError):
        _conforms(spec, {**body, "recovery_codes": body["recovery_codes"][:9]}, pointer)
    with pytest.raises(ValidationError, match="'tokens' is a required property"):
        _conforms(spec, {k: v for k, v in body.items() if k != "tokens"}, pointer)


@pytest.mark.parametrize(
    "rule",
    [
        "revokes every other TOTP method of the user",
        "replaces the user's recovery codes with 10 new ones",
        "the old method and the old codes stop working at the instant the new ones start",
        "It then rotates the session (SR-013)",
        "its access and refresh tokens stop working at once",
        "the 10 recovery codes, which are shown exactly once",
    ],
)
def test_confirm_description_states_the_rotation_rule(spec: dict[str, Any], rule: str) -> None:
    assert rule in _flat(_op(spec, "post", "/auth/mfa/enroll/confirm")["description"])


@pytest.mark.parametrize(
    "action",
    [
        "auth.mfa_enrolled",
        "auth.recovery_codes_regenerated",
        "auth.session_revoked",
        "auth.session_created",
    ],
)
def test_confirm_audit_actions_are_registered(spec: dict[str, Any], action: str) -> None:
    assert f"`{action}`" in _op(spec, "post", "/auth/mfa/enroll/confirm")["description"]
    assert action in AUDIT_ACTIONS


def test_csrf_section_lists_confirm_as_a_token_issue_point(spec: dict[str, Any]) -> None:
    info = _flat(spec["info"]["description"])
    start = info.index("**Issue, rotate and re-issue.**")
    bullet = info[start : info.index("**Multi-tab.**", start)]
    assert "`POST /auth/mfa/enroll/confirm` (which rotates the session)" in bullet


def test_owner_reset_sets_mfa_required(spec: dict[str, Any]) -> None:
    description = _flat(_op(spec, "post", "/users/{userId}/mfa/reset")["description"])
    assert "sets the target's `mfa_required`" in description


def test_user_flags_define_the_enrolment_only_state(spec: dict[str, Any]) -> None:
    user = spec["components"]["schemas"]["User"]["properties"]
    assert "confirmed, unrevoked MFA method" in user["mfa_enabled"]["description"]
    assert "enrolment-only" in user["mfa_required"]["description"]


def test_ws_protocol_refuses_an_enrolment_only_session_at_auth() -> None:
    doc = (_PLAN / "23-ws-protocol.md").read_text(encoding="utf-8")
    auth = doc[doc.index("### 4.3 `auth` → `auth_ok`") : doc.index("### 4.4 Close codes")]
    assert f"`bye` with reason `{_CODE}`, close `4403`" in auth
    assert "It does not count as a failed `auth`." in auth
    bundle = json.loads((_PLAN / "ws-schema.json").read_text(encoding="utf-8"))
    bye = bundle["schemas"]["cv://ws/v1/bye.schema.json"]["properties"]
    assert 4403 in bye["code"]["enum"]
    assert len(_CODE) <= bye["reason"]["maxLength"]

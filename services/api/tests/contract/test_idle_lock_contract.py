"""Idle-lock HTTP contract (#2300; E09-D06 ruling on PR #2290), slice 1/2: contract only (C-6.1).

Pins `POST /auth/unlock`, `POST /auth/session/extend`, the three new 401 codes and the
`SessionInfo.session` deadlines that SCR-005 and CMP-098 build on; routes ship in slice 2/2.
"""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.auth.session_service import MAX_IDLE_TIMEOUT_S, MIN_IDLE_TIMEOUT_S

_BASE = "urn:cv:openapi"
_SESSION_FIELDS = {"id", "issued_at", "expires_at", "idle_deadline", "idle_timeout_s", "locked"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _op(spec: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    op: dict[str, Any] = spec["paths"][path][method]
    return op


def _schema(spec: dict[str, Any], name: str) -> dict[str, Any]:
    schema: dict[str, Any] = spec["components"]["schemas"][name]
    return schema


def _examples(response: dict[str, Any]) -> dict[str, Any]:
    content = response["content"]
    media = content.get("application/json") or content["application/problem+json"]
    return {name: example["value"] for name, example in media["examples"].items()}


def _conforms(spec: dict[str, Any], value: Any, pointer: str) -> None:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    Draft202012Validator(
        {"$ref": f"{_BASE}#{pointer}"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


@pytest.mark.parametrize("code", ["session_idle_locked", "unlock_invalid", "session_revoked"])
def test_error_registry_idle_lock_code_is_rest_only_401_not_retryable(
    spec: dict[str, Any], code: str
) -> None:
    entry = {e["code"]: e for e in spec["x-error-codes"]}[code]
    assert (entry["status"], entry["retryable"]) == (401, False)
    # REST only: no WS change, frames keep flowing while locked (ADR-0020 section 4).
    assert entry.get("surface", ["rest"]) == ["rest"]


def test_unlock_contract_takes_the_password_only(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/unlock")
    assert op["x-rbac"] == {"permissions": [], "scope": "self"}
    assert {"$ref": "#/components/parameters/CsrfToken"} in op["parameters"]
    body = op["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/UnlockRequest"}
    request = _schema(spec, "UnlockRequest")
    # No TOTP field: unlock requires the password only (US-ONB-004, E09-S03).
    assert set(request["properties"]) == {"password"} and request["required"] == ["password"]
    assert request["additionalProperties"] is False
    assert request["properties"]["password"]["writeOnly"] is True


def test_unlock_contract_answers_session_info_or_a_named_refusal(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/unlock")
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/SessionInfo"}
    assert {"401", "403", "422", "429", "503"} <= set(op["responses"])
    assert "x-rate-limit" in op  # throttled like login
    refusals = _examples(op["responses"]["401"])
    assert {e["code"] for e in refusals.values()} >= {"unlock_invalid", "session_revoked"}
    for example in refusals.values():
        _conforms(spec, example, "/components/schemas/Problem")


def test_unlock_contract_session_revoked_carries_the_reason(spec: dict[str, Any]) -> None:
    refusals = _examples(_op(spec, "post", "/auth/unlock")["responses"]["401"])
    reasons = {e["revoked_reason"] for e in refusals.values() if e["code"] == "session_revoked"}
    assert "expired" in reasons  # absolute lifetime elapsed while locked: full sign-in
    enum = set(_schema(spec, "Problem")["properties"]["revoked_reason"]["enum"])
    assert {"expired", "unlock_attempts_exceeded"} <= enum


def test_unlock_contract_audit_actions_are_registered(spec: dict[str, Any]) -> None:
    description = _op(spec, "post", "/auth/unlock")["description"]
    for action in ("auth.session_unlocked", "auth.unlock_failed"):
        assert f"`{action}`" in description
        assert action in AUDIT_ACTIONS


def test_extend_contract_returns_the_server_truth_deadline(spec: dict[str, Any]) -> None:
    op = _op(spec, "post", "/auth/session/extend")
    assert op["x-rbac"] == {"permissions": [], "scope": "self"}
    assert {"$ref": "#/components/parameters/CsrfToken"} in op["parameters"]
    assert "requestBody" not in op
    ok = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/SessionExtendResponse"}
    response = _schema(spec, "SessionExtendResponse")
    assert set(response["required"]) == {"session", "server_time"}
    assert response["properties"]["session"] == {"$ref": "#/components/schemas/SessionState"}


def test_session_info_requires_the_session_state(spec: dict[str, Any]) -> None:
    info = _schema(spec, "SessionInfo")
    assert "session" in info["required"]
    assert info["properties"]["session"] == {"$ref": "#/components/schemas/SessionState"}
    state = _schema(spec, "SessionState")
    assert set(state["required"]) == _SESSION_FIELDS == set(state["properties"])
    assert state["properties"]["locked"]["type"] == "boolean"


def test_session_state_idle_timeout_bounds_match_the_service(spec: dict[str, Any]) -> None:
    timeout = _schema(spec, "SessionState")["properties"]["idle_timeout_s"]
    assert (timeout["minimum"], timeout["maximum"]) == (MIN_IDLE_TIMEOUT_S, MAX_IDLE_TIMEOUT_S)


def test_get_session_examples_conform_and_carry_the_lock_state(spec: dict[str, Any]) -> None:
    examples = _examples(_op(spec, "get", "/auth/session")["responses"]["200"])
    for example in examples.values():
        _conforms(spec, example, "/components/schemas/SessionInfo")
        assert example["session"]["locked"] is False


def test_unauthorized_response_documents_session_idle_locked(spec: dict[str, Any]) -> None:
    examples = _examples(spec["components"]["responses"]["Unauthorized"])
    locked = [e for e in examples.values() if e["code"] == "session_idle_locked"]
    assert len(locked) == 1 and "idle_locked_at" in locked[0]
    _conforms(spec, locked[0], "/components/schemas/Problem")
